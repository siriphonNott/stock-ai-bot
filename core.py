"""Framework-agnostic core — turn a free-text stock query into rendered PNG card(s).

Ported from bot.py's routing/handlers with the Telegram I/O stripped out:
`reply_photo(...)` becomes "append bytes to a list and return", and
`reply_text(<thai error>)` becomes `raise QueryError(<thai>)`. The bot's
"stay silent" paths raise `NoMatch`. Keeping it async preserves the
asyncio.gather/to_thread parallelism the handlers rely on.
"""
from __future__ import annotations

import asyncio
import logging
import re

from dotenv import load_dotenv

from card import _fetch_logo, render_card
from crypto_fear_greed import (
    get_crypto_fng,
    render_crypto_fng_chart,
    render_crypto_fng_gauge,
)
from enrich import enrich_company
from fear_greed import get_fear_greed_index, render_fear_greed_card
from intent import classify_with_llm, looks_like_stock_command
from list_card import render_list_card
from report_card import render_stock_report_card
from screener import enrich_with_intraday, fetch_movers, fetch_quotes
from stock import get_earnings_payload, get_fx_rate, get_intraday_history, get_stock_metrics

load_dotenv()

log = logging.getLogger("stockcore")


class QueryError(Exception):
    """Query was understood but data/render couldn't be produced.

    `thai_message` is the user-facing string the bot used to send;
    `kind` is one of "not_found" | "no_data" | "error".
    """

    def __init__(self, thai_message: str, *, kind: str = "error") -> None:
        self.thai_message = thai_message
        self.kind = kind
        super().__init__(thai_message)


class NoMatch(Exception):
    """Query matched nothing and the LLM fallback returned 'unknown'.

    The original bot stayed silent in this case (handle_message returned None).
    """


TICKER_RE = re.compile(r"^\$?([A-Za-z]{1,8}(?:\.[A-Za-z]{1,3})?)$")
TOP_RE = re.compile(r"top\s*(\d+)", re.IGNORECASE)
MAG7_RE = re.compile(r"(mag\s*7|7\s*mag|7\s*นางฟ้า|7\s*angels)", re.IGNORECASE)

MAG7_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]


def _detect_top_command(text: str) -> tuple[str, str, int] | None:
    """Return (market, direction, n) — 'US'/'TH', 'gainers'/'losers', count — or None."""
    t = (text or "").lower()
    m = TOP_RE.search(t)
    if not m:
        return None
    n = max(1, min(20, int(m.group(1))))
    # Market
    if "อเมริก" in t or "เมกา" in t or " us" in t or t.rstrip().endswith("us"):
        market = "US"
    elif "ไทย" in t or "thai" in t or " th" in t or t.rstrip().endswith("th"):
        market = "TH"
    else:
        return None
    # Direction — defaults to gainers when not specified
    if any(kw in t for kw in ("ลบ", "ร่วง", "losers", "loser", "หนัก", "ดิ่ง")):
        direction = "losers"
    else:
        direction = "gainers"
    return market, direction, n


_FEAR_GREED_RE = re.compile(
    r"\bfear\s*(?:&|and)?\s*greed(?:\s*index)?\b"
    r"|\bfear\s+index\b|\bgreed\s+index\b"
    r"|\bf\s*&\s*g\b|\bfng\b"
    r"|ดัชนีความกลัว|ดัชนีกลัว(?:ความ)?โลภ|ดัชนีกลัวและโลภ|กลัวและโลภ|กลัวโลภ",
    re.IGNORECASE,
)

# Matches: "crypto index", "crypto fear index", "crypto fear & greed index",
# "fear index crypto", "fear crypto", "index crypto" — crypto + any of
# fear/greed/index/fng on either side.
_CRYPTO_FNG_RE = re.compile(
    r"\bcrypto\b[^A-Za-z0-9]*\b(?:fear|greed|index|fng)\b"
    r"|\b(?:fear|greed|index|fng)\b[^A-Za-z0-9]*\bcrypto\b"
    r"|ดัชนี\s*คริปโต|คริปโต\s*ดัชนี|ดัชนี\s*crypto|crypto\s*ดัชนี",
    re.IGNORECASE,
)


def _detect_fear_greed(text: str) -> bool:
    return bool(_FEAR_GREED_RE.search(text))


def _detect_crypto_fear_greed(text: str) -> bool:
    return bool(_CRYPTO_FNG_RE.search(text))


def _detect_mag7(text: str) -> bool:
    return bool(MAG7_RE.search(text or ""))


def _top_title(market: str, direction: str, n: int) -> tuple[str, str]:
    """Return (title, market_tag)."""
    market_name = "หุ้นอเมริกา" if market == "US" else "หุ้นไทย"
    if direction == "gainers":
        title = f"Top {n} {market_name}พุ่งแรงวันนี้ 📈"
    else:
        title = f"Top {n} {market_name}ร่วงหนักวันนี้ 🔻"
    tag = "หุ้นสหรัฐฯ" if market == "US" else "หุ้นไทย"
    return title, tag


async def _enrich_with_logos(items: list[dict]) -> list[dict]:
    async def one(item):
        item["logo"] = await asyncio.to_thread(_fetch_logo, item["symbol"])
        return item
    return await asyncio.gather(*(one(i) for i in items))


def _extract_ticker(text: str) -> str | None:
    text = (text or "").strip()
    m = TICKER_RE.match(text)
    if not m:
        return None
    return m.group(1).upper()


def _candidates(symbol: str) -> list[str]:
    """Return resolution candidates: as-is first, then .BK suffix for Thai fallback."""
    if "." in symbol:
        return [symbol]
    return [symbol, f"{symbol}.BK"]


async def _process_ticker(symbol: str) -> list[bytes]:
    metrics = None
    resolved = symbol
    for candidate in _candidates(symbol):
        try:
            m = await asyncio.to_thread(get_stock_metrics, candidate)
        except Exception:
            log.exception("get_stock_metrics failed for %s", candidate)
            continue
        if m and m.price is not None:
            metrics = m
            resolved = candidate
            break

    if not metrics:
        raise QueryError(f"ไม่พบข้อมูลหุ้น <code>{symbol}</code>", kind="not_found")
    symbol = resolved

    # Fetch chart inputs, earnings payload, logo, and enrichment in parallel
    try:
        intraday, fx, payload, logo, enrichment = await asyncio.gather(
            asyncio.to_thread(get_intraday_history, symbol),
            asyncio.to_thread(get_fx_rate, metrics.currency, "THB"),
            asyncio.to_thread(get_earnings_payload, symbol),
            asyncio.to_thread(_fetch_logo, symbol),
            asyncio.to_thread(
                enrich_company, symbol, metrics.name, metrics.long_summary,
            ),
        )
    except Exception:
        log.exception("fetches failed for %s", symbol)
        intraday = fx = payload = logo = None
        enrichment = {"description_th": "", "tags": []}

    images: list[bytes] = []

    # Chart card
    try:
        card_bytes = await asyncio.to_thread(
            render_card,
            symbol=metrics.symbol,
            name=metrics.name,
            price=metrics.price,
            change=metrics.change,
            change_pct=metrics.change_pct,
            currency=metrics.currency,
            open_price=metrics.open_price,
            day_low=metrics.day_low,
            day_high=metrics.day_high,
            year_low=metrics.year_low,
            year_high=metrics.year_high,
            volume=metrics.volume,
            market_cap=metrics.market_cap,
            eps=metrics.eps,
            pe=metrics.pe,
            exchange_name=metrics.exchange_name,
            market_state=metrics.market_state,
            country=metrics.country,
            fx_to_thb=fx,
            intraday=intraday,
        )
        if card_bytes:
            images.append(card_bytes)
    except Exception:
        log.exception("chart card render failed for %s", symbol)

    # Stock report card — replaces the old text outputs
    try:
        report_bytes = await asyncio.to_thread(
            render_stock_report_card,
            metrics, payload,
            sector=metrics.sector,
            description=enrichment.get("description_th") or None,
            tags=enrichment.get("tags") or None,
            logo=logo,
        )
        if report_bytes:
            images.append(report_bytes)
    except Exception:
        log.exception("report card render failed for %s", symbol)

    return images


async def _handle_top_command(market: str, direction: str, n: int) -> list[bytes]:
    title, tag = _top_title(market, direction, n)
    items = await asyncio.to_thread(fetch_movers, market, direction, n)
    if not items:
        raise QueryError("ไม่มีข้อมูล Top movers ตอนนี้", kind="no_data")
    items = await enrich_with_intraday(items)
    items = await _enrich_with_logos(items)
    img = await asyncio.to_thread(render_list_card, title, tag, items)
    return [img] if img else []


async def _handle_fear_greed_command() -> list[bytes]:
    data = await asyncio.to_thread(get_fear_greed_index)
    if not data:
        raise QueryError("ดึงข้อมูล Fear & Greed Index ไม่สำเร็จ ลองอีกครั้ง", kind="no_data")
    img = await asyncio.to_thread(render_fear_greed_card, data)
    if not img:
        raise QueryError("เรนเดอร์ Fear & Greed Index ไม่สำเร็จ")
    return [img]


async def _handle_crypto_fear_greed_command() -> list[bytes]:
    fng_data = await asyncio.to_thread(get_crypto_fng)
    if not fng_data:
        raise QueryError("ดึงข้อมูล Crypto Fear & Greed Index ไม่สำเร็จ ลองอีกครั้ง", kind="no_data")
    gauge_img, chart_img = await asyncio.gather(
        asyncio.to_thread(render_crypto_fng_gauge, fng_data),
        asyncio.to_thread(render_crypto_fng_chart, fng_data),
    )
    images = [x for x in (gauge_img, chart_img) if x]
    if not images:
        raise QueryError("เรนเดอร์ Crypto Fear & Greed Index ไม่สำเร็จ")
    return images


async def _handle_mag7_command() -> list[bytes]:
    title = "Magnificent 7 (หุ้น 7 นางฟ้า) 🌟"
    tag = "หุ้นสหรัฐฯ"
    items = await asyncio.to_thread(fetch_quotes, MAG7_SYMBOLS)
    if not items:
        raise QueryError("ดึงข้อมูล Mag 7 ไม่สำเร็จ", kind="no_data")
    items = await enrich_with_intraday(items)
    items = await _enrich_with_logos(items)
    img = await asyncio.to_thread(render_list_card, title, tag, items)
    return [img] if img else []


async def render_query(text: str) -> list[bytes]:
    """Mirror of bot.handle_message routing — returns 1..N PNG byte blobs.

    Raises NoMatch (the bot's silent case) or QueryError (understood but failed).
    Routing order is load-bearing: crypto must precede generic F&G so
    "crypto fear & greed index" routes to crypto rather than the CNN equity index.
    """
    if not text:
        raise NoMatch()

    if _detect_crypto_fear_greed(text):
        return await _handle_crypto_fear_greed_command()
    if _detect_fear_greed(text):
        return await _handle_fear_greed_command()
    if _detect_mag7(text):
        return await _handle_mag7_command()
    top = _detect_top_command(text)
    if top:
        return await _handle_top_command(*top)
    symbol = _extract_ticker(text)
    if symbol:
        return await _process_ticker(symbol)

    # Fuzzy fallback — only for stock-related text. Costs ~1 Haiku call.
    if not looks_like_stock_command(text):
        raise NoMatch()
    intent = await asyncio.to_thread(classify_with_llm, text)

    action = intent.get("action")
    if action == "top_movers":
        market = (intent.get("market") or "US").upper()
        direction = intent.get("direction") or "gainers"
        count = max(1, min(20, int(intent.get("count") or 10)))
        return await _handle_top_command(market, direction, count)
    if action == "mag7":
        return await _handle_mag7_command()
    if action == "ticker":
        sym = (intent.get("symbol") or "").upper()
        if sym:
            return await _process_ticker(sym)

    raise NoMatch()
