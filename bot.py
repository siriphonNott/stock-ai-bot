"""Optional Telegram adapter — thin wrapper over core.render_query.

Production now runs the HTTP API (app.py) with N8N owning the Telegram side.
This entrypoint is kept as a local smoke test of the core: it drives the same
render_query() over Telegram so behavior can be verified end-to-end without N8N.
Run with: python -u bot.py  (needs TELEGRAM_BOT_TOKEN).
"""
from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core import NoMatch, QueryError, render_query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("stockbot")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    try:
        images = await render_query(update.message.text)
    except NoMatch:
        return
    except QueryError as e:
        await update.message.reply_text(e.thai_message, parse_mode=ParseMode.HTML)
        return
    except Exception:
        log.exception("render_query failed for %r", update.message.text[:80])
        return

    for img in images:
        await update.message.reply_photo(photo=img)


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
