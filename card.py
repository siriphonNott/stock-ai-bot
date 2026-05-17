"""Stock summary card renderer — green/red card matching the design mockup."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# Bundled Kanit (Thai + Latin) — works on Linux/Docker.
# Sukhumvit Set kept as macOS dev fallback.
_ASSETS = Path(__file__).parent / "assets" / "fonts"
FONT_PATH = str(_ASSETS / "Kanit-Regular.ttf")
FONT_PATH_BOLD = str(_ASSETS / "Kanit-Bold.ttf")
FONT_REG_IDX = 0
FONT_BOLD_IDX = 0

_FALLBACK_PATH = "/System/Library/Fonts/Supplemental/SukhumvitSet.ttc"
_FALLBACK_REG_IDX = 2
_FALLBACK_BOLD_IDX = 5

# Card dimensions
W, H = 640, 480
PADDING = 28
RADIUS = 36

GREEN = (0, 186, 123, 255)      # #00BA7B
RED = (255, 69, 96, 255)        # #FF4560
DARK_BG = (20, 23, 28, 255)
DARK_PANEL = (30, 34, 42, 255)  # used when logo is mostly white
WHITE = (255, 255, 255, 255)
WHITE_DIM = (255, 255, 255, 225)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        path = FONT_PATH_BOLD if bold else FONT_PATH
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(
                _FALLBACK_PATH,
                size,
                index=_FALLBACK_BOLD_IDX if bold else _FALLBACK_REG_IDX,
            )
        except Exception:
            return ImageFont.load_default()


CURRENCY_SYMBOLS = {"USD": "$", "THB": "฿", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency, "")


def _fmt_market_cap(v: float | None, currency: str = "USD") -> str:
    if v is None:
        return "-"
    cur = _currency_symbol(currency)
    if v >= 1e12:
        return f"{cur}{v / 1e12:,.2f}T"
    if v >= 1e9:
        return f"{cur}{v / 1e9:,.2f}B"
    if v >= 1e6:
        return f"{cur}{v / 1e6:,.2f}M"
    return f"{cur}{v:,.0f}"


def _logo_panel_color(logo: Image.Image) -> tuple:
    """Pick a panel background so the logo stays visible.

    Strips background pixels (transparent or matching the 4 corners) and
    averages only the logo's shape pixels. Bright logos → dark panel.
    """
    pixels = list(logo.getdata())
    if not pixels:
        return WHITE

    w, h = logo.size
    corners = [
        logo.getpixel((0, 0)),
        logo.getpixel((w - 1, 0)),
        logo.getpixel((0, h - 1)),
        logo.getpixel((w - 1, h - 1)),
    ]
    transparent_corners = sum(1 for c in corners if len(c) > 3 and c[3] < 40)

    if transparent_corners >= 3:
        # Transparent background — logo = visible pixels only
        shape = [p for p in pixels if len(p) > 3 and p[3] > 40]
    else:
        # Opaque background — drop pixels close to corner brightness
        bg = corners[0]
        bg_brightness = (bg[0] + bg[1] + bg[2]) / 3
        shape = [
            p for p in pixels
            if abs((p[0] + p[1] + p[2]) / 3 - bg_brightness) > 40
            and (len(p) <= 3 or p[3] > 40)
        ]

    if not shape:
        return WHITE
    avg = sum((p[0] + p[1] + p[2]) / 3 for p in shape) / len(shape)
    return DARK_PANEL if avg > 200 else WHITE


def _fetch_logo(symbol: str) -> Image.Image | None:
    """Fetch company logo PNG. Returns None if unavailable."""
    try:
        r = requests.get(
            f"https://financialmodelingprep.com/image-stock/{symbol.upper()}.png",
            timeout=5,
        )
        if r.status_code != 200 or not r.content:
            return None
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        return img
    except Exception:
        log.debug("logo fetch failed for %s", symbol, exc_info=True)
        return None


def render_card(
    *,
    symbol: str,
    name: str | None,
    price: float | None,
    change: float | None,
    change_pct: float | None,
    market_cap: float | None,
    currency: str = "USD",
) -> bytes | None:
    if price is None:
        return None

    is_up = (change or 0) >= 0
    bg_color = GREEN if is_up else RED
    cur = _currency_symbol(currency)

    # Build inner colored card
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([0, 0, W, H], radius=RADIUS, fill=bg_color)

    # Big price
    d.text((40, 38), f"{cur}{price:,.2f}", font=_font(76, bold=True), fill=WHITE)

    # Change line (e.g. "+2.02   +0.68%" / "−4.20   −0.68%")
    if change is not None:
        sign = "+" if change >= 0 else "−"
        parts = [f"{sign}{abs(change):.2f}"]
        if change_pct is not None:
            parts.append(f"{sign}{abs(change_pct):.2f}%")
        d.text((40, 142), "   ".join(parts), font=_font(34, bold=True), fill=WHITE)

    # Logo top-right inside rounded panel (white normally, dark if logo is white)
    logo = _fetch_logo(symbol)
    if logo:
        panel_color = _logo_panel_color(logo)
        box = 110
        cx, cy = W - 90, 95
        d.rounded_rectangle(
            [cx - box // 2, cy - box // 2, cx + box // 2, cy + box // 2],
            radius=20,
            fill=panel_color,
        )
        logo_fit = logo.copy()
        logo_fit.thumbnail((box - 32, box - 32), Image.LANCZOS)
        lw, lh = logo_fit.size
        card.paste(logo_fit, (cx - lw // 2, cy - lh // 2), logo_fit)

    # Bottom-left: symbol + name
    d.text((40, H - 135), symbol, font=_font(48, bold=True), fill=WHITE)
    if name:
        max_chars = 28
        name_disp = name if len(name) <= max_chars else name[: max_chars - 1] + "…"
        d.text((40, H - 70), name_disp, font=_font(24), fill=WHITE_DIM)

    # Bottom-right: Market Cap (label + value)
    mc_label = "Market Cap"
    mc_value = _fmt_market_cap(market_cap, currency)
    label_font = _font(24)
    value_font = _font(44, bold=True)
    lw = d.textlength(mc_label, font=label_font)
    vw = d.textlength(mc_value, font=value_font)
    d.text((W - 40 - lw, H - 135), mc_label, font=label_font, fill=WHITE_DIM)
    d.text((W - 40 - vw, H - 80), mc_value, font=value_font, fill=WHITE)

    # Composite onto dark backdrop (so the rounded corners look right when sent to Telegram)
    bg = Image.new("RGBA", (W + PADDING * 2, H + PADDING * 2), DARK_BG)
    bg.paste(card, (PADDING, PADDING), card)
    out = io.BytesIO()
    bg.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
