"""Render Top gainers/losers list card matching the dark-stack design."""
from __future__ import annotations

import io
import logging

from PIL import Image, ImageDraw, ImageFont

from card import _font as _card_font  # noqa: F401  re-use same fallback chain
from card import _logo_panel_color

log = logging.getLogger(__name__)

WIDTH = 720
ROW_H = 170
TITLE_H = 80
PADDING_X = 28
PADDING_TOP = 30
PADDING_BOTTOM = 30
DIVIDER_H = 1

BG = (15, 17, 22, 255)
DIVIDER = (38, 41, 50, 255)
TAG_BG = (95, 65, 178, 255)
LOGO_DARK = (40, 44, 52, 255)
LOGO_WHITE = (255, 255, 255, 255)
WHITE = (255, 255, 255, 255)
DIM = (170, 175, 188, 255)
GREEN = (32, 213, 124, 255)
RED = (255, 95, 115, 255)
GREEN_PILL = (28, 64, 48, 255)
RED_PILL = (72, 36, 44, 255)
SPARK_GREEN_FILL = (32, 213, 124, 65)
SPARK_RED_FILL = (255, 95, 115, 65)

CURRENCY_SYMBOLS = {"USD": "$", "THB": "฿", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _font(size: int, bold: bool = False):
    return _card_font(size, bold=bold)


def _strip_bk(sym: str) -> str:
    return sym[:-3] if sym.endswith(".BK") else sym


def _draw_sparkline(img: Image.Image, prices, x, y, w, h, is_up):
    if not prices or len(prices) < 2:
        return
    pmin, pmax = min(prices), max(prices)
    rng = pmax - pmin or 1
    pts = []
    for i, p in enumerate(prices):
        px = x + i * w / (len(prices) - 1)
        py = y + h - (p - pmin) / rng * h
        pts.append((px, py))

    line_color = GREEN if is_up else RED
    fill_color = SPARK_GREEN_FILL if is_up else SPARK_RED_FILL

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    poly = pts + [(x + w, y + h), (x, y + h)]
    od.polygon(poly, fill=fill_color)
    img.alpha_composite(overlay)

    d = ImageDraw.Draw(img)
    d.line(pts, fill=line_color, width=3, joint="curve")


def _paste_logo(card: Image.Image, x: int, y: int, size: int, logo: Image.Image | None):
    """Logo inside a circle. Uses smart panel color so logo stays visible."""
    d = ImageDraw.Draw(card)
    if logo is None:
        d.ellipse([x, y, x + size, y + size], fill=LOGO_DARK)
        return
    bg = _logo_panel_color(logo)
    d.ellipse([x, y, x + size, y + size], fill=bg)
    # Mask logo to circle
    inner = size - 16
    fit = logo.copy()
    fit.thumbnail((inner, inner), Image.LANCZOS)
    lw, lh = fit.size
    cx, cy = x + size // 2 - lw // 2, y + size // 2 - lh // 2
    card.paste(fit, (cx, cy), fit)


def _format_price(price: float | None, currency: str) -> str:
    if price is None:
        return "-"
    return f"{price:,.2f} {currency}"


def _format_prev(prev: float | None) -> str:
    if prev is None:
        return ""
    return f"{prev:,.2f}"


def _market_label(state: str | None, currency: str) -> str:
    if state == "REGULAR":
        return "ตลาดเปิด"
    if state in ("PRE", "PREPRE"):
        return "ก่อนเปิด"
    if state in ("POST", "POSTPOST", "CLOSED"):
        return "หลังตลาดปิด"
    return ""


def _draw_row(card: Image.Image, y: int, *, market_tag: str, item: dict):
    d = ImageDraw.Draw(card)
    is_up = (item.get("change_pct") or 0) >= 0

    # Tag pill
    tag_font = _font(15, bold=True)
    tag_text = market_tag
    tag_w = d.textlength(tag_text, font=tag_font)
    tag_x, tag_y = PADDING_X, y
    pill_w = tag_w + 28
    d.rounded_rectangle([tag_x, tag_y, tag_x + pill_w, tag_y + 28], radius=14, fill=TAG_BG)
    d.text((tag_x + 14, tag_y + 5), tag_text, font=tag_font, fill=WHITE)

    # Logo + symbol (below tag)
    logo_size = 60
    logo_y = y + 50
    _paste_logo(card, PADDING_X, logo_y, logo_size, item.get("logo"))

    symbol = _strip_bk(item["symbol"])
    sym_font = _font(28, bold=True)
    d.text((PADDING_X + logo_size + 18, logo_y + 16), symbol, font=sym_font, fill=WHITE)

    # Sparkline (middle)
    spark_x = 280
    spark_y = logo_y - 5
    spark_w = 160
    spark_h = 70
    _draw_sparkline(card, item.get("intraday"), spark_x, spark_y, spark_w, spark_h, is_up)

    # Right side
    right_edge = WIDTH - PADDING_X
    price = item.get("price")
    prev = item.get("prev_close")
    change_pct = item.get("change_pct") or 0
    currency = item.get("currency", "USD")
    arrow = "+" if change_pct >= 0 else "−"
    color = GREEN if change_pct >= 0 else RED

    # Top line: market label + prev close + arrow + small %
    state = item.get("market_state")
    label = _market_label(state, currency)
    small_font = _font(14)
    pct_color = color
    if prev is not None and label:
        # Format: "หลังตลาดปิด 262.60  ↓ 0.58%"
        top_text = f"{label} {_format_prev(prev)}"
        tw = d.textlength(top_text, font=small_font)
        # arrow + small pct
        delta = abs((price or 0) - (prev or 0))
        pct_text = f"{arrow} {(delta / prev * 100):.2f}%" if prev else f"{arrow} -"
        pct_w = d.textlength(pct_text, font=small_font)
        gap = 12
        total_w = tw + gap + pct_w
        x0 = right_edge - total_w
        d.text((x0, y + 8), top_text, font=small_font, fill=DIM)
        d.text((x0 + tw + gap, y + 8), pct_text, font=small_font, fill=pct_color)

    # Big price
    price_text = _format_price(price, currency)
    price_font = _font(26, bold=True)
    pw = d.textlength(price_text, font=price_font)
    d.text((right_edge - pw, y + 55), price_text, font=price_font, fill=WHITE)

    # Bottom pill: change%
    pill_text = f"{arrow} {abs(change_pct):.2f}%"
    pill_font = _font(18, bold=True)
    pill_tw = d.textlength(pill_text, font=pill_font)
    pill_w_total = pill_tw + 28
    pill_h = 38
    pill_bg = GREEN_PILL if is_up else RED_PILL
    pill_x = right_edge - pill_w_total
    pill_y = y + 105
    d.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w_total, pill_y + pill_h],
        radius=10,
        fill=pill_bg,
    )
    d.text((pill_x + 14, pill_y + 8), pill_text, font=pill_font, fill=color)


def _strip_emoji(s: str) -> str:
    return "".join(c for c in s if ord(c) < 0x1F000).strip()


def render_list_card(title: str, market_tag: str, items: list[dict]) -> bytes:
    n = len(items)
    height = PADDING_TOP + TITLE_H + n * ROW_H + PADDING_BOTTOM
    img = Image.new("RGBA", (WIDTH, height), BG)
    d = ImageDraw.Draw(img)

    d.text((PADDING_X, PADDING_TOP), _strip_emoji(title), font=_font(26, bold=True), fill=WHITE)

    y = PADDING_TOP + TITLE_H
    for i, item in enumerate(items):
        _draw_row(img, y, market_tag=market_tag, item=item)
        y += ROW_H
        if i < n - 1:
            d.line([(PADDING_X, y - 8), (WIDTH - PADDING_X, y - 8)], fill=DIVIDER, width=DIVIDER_H)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
