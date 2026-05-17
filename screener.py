"""Top gainers/losers screener for US & Thai markets, plus intraday helpers."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import yfinance as yf

log = logging.getLogger(__name__)

Market = Literal["US", "TH"]
Direction = Literal["gainers", "losers"]


def _yf_screen(market: Market, direction: Direction, count: int):
    if market == "US":
        body = "day_gainers" if direction == "gainers" else "day_losers"
        return yf.screen(body, count=count)
    region = "th"
    op = "gt" if direction == "gainers" else "lt"
    threshold = 3 if direction == "gainers" else -3
    q = yf.EquityQuery("and", [
        yf.EquityQuery("eq", ["region", region]),
        yf.EquityQuery(op, ["percentchange", threshold]),
        yf.EquityQuery("gt", ["intradayprice", 1]),
    ])
    return yf.screen(q, count=count, sortField="percentchange", sortAsc=(direction == "losers"))


def fetch_movers(market: Market, direction: Direction, count: int = 10) -> list[dict]:
    """Return top movers, deduped (drops -R Thai twin shares)."""
    raw = _yf_screen(market, direction, count * 3)
    quotes = (raw or {}).get("quotes", [])

    seen: set[str] = set()
    out: list[dict] = []
    for q in quotes:
        sym = q.get("symbol", "")
        if not sym:
            continue
        if "-R.BK" in sym:
            continue  # skip Thai R-shares; prefer the main listing
        key = sym
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "symbol": sym,
            "name": q.get("shortName") or q.get("longName") or sym,
            "price": q.get("regularMarketPrice"),
            "change": q.get("regularMarketChange"),
            "change_pct": q.get("regularMarketChangePercent"),
            "prev_close": q.get("regularMarketPreviousClose"),
            "currency": q.get("currency", "USD"),
            "market_state": q.get("marketState"),
        })
        if len(out) >= count:
            break
    return out


def fetch_quotes(symbols: list[str]) -> list[dict]:
    """Fetch lightweight quote dicts for a fixed list of symbols (used by Mag 7)."""
    out: list[dict] = []
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
            change = info.get("regularMarketChange")
            if change is None and price is not None and prev is not None:
                change = price - prev
            change_pct = info.get("regularMarketChangePercent")
            if change_pct is None and change is not None and prev:
                change_pct = change / prev * 100
            out.append({
                "symbol": sym,
                "name": info.get("longName") or info.get("shortName") or sym,
                "price": price,
                "change": change,
                "change_pct": change_pct,
                "prev_close": prev,
                "currency": info.get("currency", "USD"),
                "market_state": info.get("marketState"),
            })
        except Exception:
            log.debug("fetch_quotes failed for %s", sym, exc_info=True)
    return out


def fetch_intraday(symbol: str) -> list[float] | None:
    """Return intraday close prices for the sparkline. Falls back to 5-day."""
    try:
        t = yf.Ticker(symbol)
        h = t.history(period="1d", interval="5m")
        if h is None or h.empty:
            h = t.history(period="5d", interval="1h")
        if h is None or h.empty:
            return None
        closes = h["Close"].dropna().tolist()
        return [float(c) for c in closes] or None
    except Exception:
        log.debug("intraday fetch failed for %s", symbol, exc_info=True)
        return None


async def enrich_with_intraday(items: list[dict]) -> list[dict]:
    """Fetch intraday data for each item in parallel."""
    async def one(item):
        item["intraday"] = await asyncio.to_thread(fetch_intraday, item["symbol"])
        return item

    return await asyncio.gather(*(one(i) for i in items))
