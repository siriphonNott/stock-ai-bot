"""Telegram bot entrypoint — listens for stock tickers and replies with metrics + earnings."""
from __future__ import annotations

import asyncio
import logging
import os
import re

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from card import _fetch_logo, render_card
from intent import classify_with_llm, looks_like_stock_command
from list_card import render_list_card
from screener import enrich_with_intraday, fetch_movers, fetch_quotes
from stock import format_metrics, get_earnings_payload, get_intraday_history, get_stock_metrics
from summarizer import summarize_earnings

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("stockbot")

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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text

    # Fast-path regex
    if _detect_mag7(text):
        await _handle_mag7_command(update, context)
        return
    top = _detect_top_command(text)
    if top:
        await _handle_top_command(update, context, *top)
        return
    symbol = _extract_ticker(text)
    if symbol:
        await _process_ticker(update, context, symbol)
        return

    # Fuzzy fallback — only for stock-related text. Costs ~1 Haiku call.
    if not looks_like_stock_command(text):
        return
    try:
        intent = await asyncio.to_thread(classify_with_llm, text)
    except Exception:
        log.exception("classify_with_llm failed for %r", text[:80])
        return

    action = intent.get("action")
    if action == "top_movers":
        market = (intent.get("market") or "US").upper()
        direction = intent.get("direction") or "gainers"
        count = int(intent.get("count") or 10)
        count = max(1, min(20, count))
        await _handle_top_command(update, context, market, direction, count)
    elif action == "mag7":
        await _handle_mag7_command(update, context)
    elif action == "ticker":
        sym = (intent.get("symbol") or "").upper()
        if sym:
            await _process_ticker(update, context, sym)


async def _process_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

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
        await update.message.reply_text(
            f"ไม่พบข้อมูลหุ้น <code>{symbol}</code>", parse_mode=ParseMode.HTML
        )
        return
    symbol = resolved

    # Card image — dark portrait layout with intraday chart
    try:
        intraday = await asyncio.to_thread(get_intraday_history, symbol)
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
            intraday=intraday,
        )
        if card_bytes:
            await update.message.reply_photo(photo=card_bytes)
    except Exception:
        log.exception("card render failed for %s", symbol)

    reply = format_metrics(metrics)
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML)

    # Earnings summary follow-up
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        payload = await asyncio.to_thread(get_earnings_payload, symbol)
        if not payload:
            return
        summary = await asyncio.to_thread(summarize_earnings, payload)
        if summary:
            await update.message.reply_text(summary, parse_mode=ParseMode.HTML)
    except Exception:
        log.exception("earnings summary failed for %s", symbol)


async def _handle_top_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market: str,
    direction: str,
    n: int,
) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    title, tag = _top_title(market, direction, n)
    try:
        items = await asyncio.to_thread(fetch_movers, market, direction, n)
        if not items:
            await update.message.reply_text("ไม่มีข้อมูล Top movers ตอนนี้")
            return
        items = await enrich_with_intraday(items)
        items = await _enrich_with_logos(items)
        img = await asyncio.to_thread(render_list_card, title, tag, items)
        await update.message.reply_photo(photo=img, caption=title)
    except Exception:
        log.exception("top command failed")
        await update.message.reply_text("ดึงข้อมูล Top movers ไม่สำเร็จ ลองอีกครั้ง")


async def _handle_mag7_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
    title = "Magnificent 7 (หุ้น 7 นางฟ้า) 🌟"
    tag = "หุ้นสหรัฐฯ"
    try:
        items = await asyncio.to_thread(fetch_quotes, MAG7_SYMBOLS)
        if not items:
            await update.message.reply_text("ดึงข้อมูล Mag 7 ไม่สำเร็จ")
            return
        items = await enrich_with_intraday(items)
        items = await _enrich_with_logos(items)
        img = await asyncio.to_thread(render_list_card, title, tag, items)
        await update.message.reply_photo(photo=img, caption=title)
    except Exception:
        log.exception("mag7 command failed")
        await update.message.reply_text("ดึงข้อมูล Mag 7 ไม่สำเร็จ ลองอีกครั้ง")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "สวัสดี 👋\n"
        "พิมพ์ชื่อย่อหุ้น เช่น <code>AAPL</code>, <code>NVDA</code>, <code>$TSLA</code> "
        "เพื่อดูราคา/อัตราส่วน + สรุปผลประกอบการล่าสุด",
        parse_mode=ParseMode.HTML,
    )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot starting (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
