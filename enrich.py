"""Claude-based stock enrichment — short Thai description + product tags."""
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


SYSTEM_PROMPT = """You enrich stock data with a short Thai company blurb and product/segment tags.

Return JSON only — no prose, no markdown fences. Schema:
{
  "description_th": "<1–2 sentences in plain Thai, max 130 chars total, no emoji>",
  "tags": ["<tag1>", "<tag2>", "<tag3>", "<tag4>"]
}

Rules:
- description_th: what the company does, written naturally in Thai
- tags: 3–4 short keywords for the company's flagship products/brands/segments.
  Keep brand/product names in their native form (e.g. "iPhone" not "ไอโฟน",
  "Azure" not "อะชัวร์"). Use Thai only for generic segments
  (e.g. "ก๊าซธรรมชาติ", "ห้างค้าปลีก", "โรงพยาบาล")."""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def enrich_company(
    symbol: str, name: str | None, business_summary: str | None,
) -> dict:
    """Return {description_th, tags}. Empty dict shape on failure."""
    if not (name or business_summary):
        return {"description_th": "", "tags": []}
    user_msg = (
        f"Ticker: {symbol}\n"
        f"Name: {name or '-'}\n\n"
        f"Business summary:\n{business_summary or '(none)'}"
    )
    try:
        msg = _get_client().messages.create(
            model=MODEL,
            max_tokens=300,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = msg.content[0].text.strip()
        m = _JSON_RE.search(raw)
        if not m:
            return {"description_th": "", "tags": []}
        data = json.loads(m.group(0))
        return {
            "description_th": (data.get("description_th") or "").strip(),
            "tags": [t for t in (data.get("tags") or []) if isinstance(t, str)][:4],
        }
    except Exception:
        log.exception("enrich_company failed for %s", symbol)
        return {"description_th": "", "tags": []}
