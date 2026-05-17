"""Fuzzy intent classifier — Claude Haiku as fallback when regex doesn't match.

Only invoked for messages that *look like* stock commands; otherwise the bot
stays silent. Keeps cost low while handling typos/synonyms/free-form Thai.
"""
from __future__ import annotations

import json
import logging
import re

from anthropic import Anthropic

log = logging.getLogger(__name__)

_client: Anthropic | None = None
MODEL = "claude-haiku-4-5-20251001"


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()
    return _client


# Cheap pre-filter: only ask Claude if message smells stock-related.
STOCK_HINTS = (
    "top", "หุ้น", "ตลาด", "ราคา", "stock", "ticker", "share",
    "mag", "นางฟ้า", "angels",
    "พุ่ง", "ร่วง", "บวก", "ลบ", "ดิ่ง", "หนัก", "ขึ้น", "ลง",
    "gainers", "losers", "gain", "lose",
    "อเมริก", "เมกา", "ไทย", "thai", " us ", " th ",
    "ขอ", "ดู", "show", "get",
)


def _has_thai(text: str) -> bool:
    return any("฀" <= c <= "๿" for c in text)


def looks_like_stock_command(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if len(t) > 120:
        return False
    tl = t.lower()
    # Short Thai messages — often company name / shorthand query
    if len(t) <= 30 and _has_thai(t):
        return True
    if tl.startswith(("us ", "th ")) or tl.endswith((" us", " th")):
        return True
    return any(kw in tl for kw in STOCK_HINTS)


SYSTEM_PROMPT = """You classify Thai/English messages from a stock chat bot into one structured intent.

Return JSON only — no prose, no markdown fences. Schema:
{
  "action": "top_movers" | "mag7" | "ticker" | "unknown",
  "market": "US" | "TH" | null,
  "direction": "gainers" | "losers" | null,
  "count": <int 1-20> | null,
  "symbol": <uppercase ticker e.g. "AAPL", "PTT.BK"> | null
}

Rules:
- "top_movers" = user wants top N gainers/losers list. Default count=10, direction="gainers" if unclear.
- "mag7" = user wants Magnificent 7 (Apple, Microsoft, Google, Amazon, Meta, Tesla, Nvidia). Triggered by "7 นางฟ้า", "magnificent 7", "mag 7", "หุ้น 7 ตัวยักษ์", etc.
- "ticker" = user wants info on ONE stock. Translate Thai company names to SET ticker with .BK suffix (e.g. ปตท → PTT.BK, กสิกร → KBANK.BK, ซีพี ออลล์ → CPALL.BK, แอดวานซ์ → ADVANC.BK, ปูนใหญ่ → SCC.BK, ปูนซิเมนต์ไทย → SCC.BK, ท่าอากาศยานไทย → AOT.BK, การบินไทย → THAI.BK, เดลต้า → DELTA.BK).
- "unknown" = greetings, small talk, off-topic.
- For "เมกา"/"อเมริกา"/"us" → market="US". For "ไทย"/"thai"/"th" → market="TH".

Examples:
- "top 10 ไทย" → {"action":"top_movers","market":"TH","direction":"gainers","count":10}
- "ขอดูเมกาที่ขึ้นเยอะ" → {"action":"top_movers","market":"US","direction":"gainers","count":10}
- "หุ้นไทยตกหนัก 5 ตัว" → {"action":"top_movers","market":"TH","direction":"losers","count":5}
- "หุ้น 7 นางฟ้า" → {"action":"mag7"}
- "ขอ aapl หน่อย" → {"action":"ticker","symbol":"AAPL"}
- "ปตท ราคาเท่าไหร่" → {"action":"ticker","symbol":"PTT.BK"}
- "สวัสดี" → {"action":"unknown"}"""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def classify_with_llm(text: str) -> dict:
    """Ask Claude to classify. Returns a dict, never raises."""
    try:
        msg = _get_client().messages.create(
            model=MODEL,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": text}],
        )
        raw = msg.content[0].text.strip()
        m = _JSON_RE.search(raw)
        if not m:
            return {"action": "unknown"}
        return json.loads(m.group(0))
    except Exception:
        log.exception("intent classification failed for %r", text[:80])
        return {"action": "unknown"}
