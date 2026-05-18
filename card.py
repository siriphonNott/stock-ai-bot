"""Stock summary card renderer — dark portrait layout with intraday chart."""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import requests
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# Bundled Sukhumvit Set — works on both Mac dev and Linux/Docker prod.
# Kanit kept as fallback in case the .ttc file is ever missing.
_ASSETS = Path(__file__).parent / "assets" / "fonts"
FONT_PATH = str(_ASSETS / "SukhumvitSet.ttc")
FONT_REG_IDX = 2
FONT_BOLD_IDX = 5

_FALLBACK_PATH = str(_ASSETS / "Kanit-Regular.ttf")
_FALLBACK_PATH_BOLD = str(_ASSETS / "Kanit-Bold.ttf")

# Canvas (chart-dominated portrait; no stats grid below)
W, H = 720, 1100

# Palette
BG = (0, 0, 0, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_DIM = (170, 170, 175, 255)
TEXT_LABEL = (140, 140, 145, 255)
DIVIDER = (45, 45, 50, 255)
GRID_LINE = (50, 50, 55, 255)
PILL_BG = (38, 38, 42, 255)
PILL_PURPLE = (88, 70, 138, 255)
PILL_GRAY = (40, 42, 48, 255)
RED = (255, 75, 90, 255)
GREEN = (98, 220, 122, 255)
TICKER_PURPLE = (162, 145, 255, 255)

# Used by list_card via _logo_panel_color()
WHITE = (255, 255, 255, 255)
DARK_PANEL = (30, 34, 42, 255)

PAD = 36

CURRENCY_SYMBOLS = {"USD": "US$", "THB": "฿", "EUR": "€", "GBP": "£", "JPY": "¥"}

THAI_MONTH_ABBR = {
    1: "ม.ค.", 2: "ก.พ.", 3: "มี.ค.", 4: "เม.ย.", 5: "พ.ค.", 6: "มิ.ย.",
    7: "ก.ค.", 8: "ส.ค.", 9: "ก.ย.", 10: "ต.ค.", 11: "พ.ย.", 12: "ธ.ค.",
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(
            FONT_PATH, size, index=FONT_BOLD_IDX if bold else FONT_REG_IDX
        )
    except Exception:
        try:
            path = _FALLBACK_PATH_BOLD if bold else _FALLBACK_PATH
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()


def _currency_prefix(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency, "")


def _logo_panel_color(logo: Image.Image) -> tuple:
    """Pick a panel background so the logo stays visible.

    Used by list_card for top-movers thumbnails."""
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
        shape = [p for p in pixels if len(p) > 3 and p[3] > 40]
    else:
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
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:
        log.debug("logo fetch failed for %s", symbol, exc_info=True)
        return None


def _fmt_compact(v: float | None) -> str:
    if v is None:
        return "-"
    av = abs(v)
    if av >= 1e12:
        return f"{v / 1e12:,.2f}T"
    if av >= 1e9:
        return f"{v / 1e9:,.2f}B"
    if av >= 1e6:
        return f"{v / 1e6:,.1f}M"
    if av >= 1e3:
        return f"{v / 1e3:,.1f}K"
    return f"{v:,.0f}"


def _fmt_price(v: float | None) -> str:
    return f"{v:,.2f}" if v is not None else "-"


def _fmt_pe(v: float | None) -> str:
    return f"{v:,.1f}" if v is not None else "-"


def _thai_date_time(dt: datetime) -> str:
    """'19 พ.ค. 69 - 02:47:56 น.' (Thai abbr month + Buddhist year, 24h time)."""
    month = THAI_MONTH_ABBR.get(dt.month, "")
    be_year = (dt.year + 543) % 100
    return f"{dt.day} {month} {be_year:02d} - {dt.strftime('%H:%M:%S')} น."


def _normalize_exchange(name: str | None) -> str:
    """Map yfinance exchange names to short, recognizable labels."""
    if not name:
        return ""
    n = name.upper()
    if "NASDAQ" in n or n == "NMS":
        return "NASDAQ"
    if "NYSE" in n or n == "NYQ":
        return "NYSE"
    if "THAILAND" in n or n == "SET":
        return "SET"
    if "TOKYO" in n or n == "JPX":
        return "TSE"
    if "HONG KONG" in n or n == "HKG":
        return "HKEX"
    return n


def _country_badge(country: str | None) -> str:
    if not country:
        return "หุ้น"
    c = country.lower()
    if "united states" in c or c == "us":
        return "หุ้นสหรัฐฯ"
    if "thailand" in c or c == "th":
        return "หุ้นไทย"
    if "japan" in c:
        return "หุ้นญี่ปุ่น"
    if "china" in c or "hong kong" in c:
        return "หุ้นจีน"
    return f"หุ้น{country}"


def _draw_pill(
    d: ImageDraw.ImageDraw,
    text: str,
    x_right: int,
    y: int,
    *,
    fill: tuple,
    text_color: tuple = TEXT_WHITE,
    font: ImageFont.FreeTypeFont | None = None,
    pad_x: int = 22,
    height: int = 50,
) -> int:
    """Right-anchored pill. Returns the pill's left x-coord."""
    font = font or _font(22, bold=True)
    tw = int(d.textlength(text, font=font))
    pill_w = tw + pad_x * 2
    x_left = x_right - pill_w
    d.rounded_rectangle(
        [x_left, y, x_right, y + height], radius=height // 2, fill=fill
    )
    ascent, _ = font.getmetrics()
    d.text((x_left + pad_x, y + (height - ascent) // 2 - 2), text, font=font, fill=text_color)
    return x_left


def _round_logo(logo: Image.Image, size: int) -> Image.Image:
    """Crop logo to a circle on a black panel."""
    logo_fit = logo.copy()
    logo_fit.thumbnail((size - 8, size - 8), Image.LANCZOS)
    panel = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    lw, lh = logo_fit.size
    panel.paste(logo_fit, ((size - lw) // 2, (size - lh) // 2), logo_fit)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(panel, (0, 0), mask)
    return out


def _draw_chart(
    base: Image.Image,
    intraday: Sequence[tuple[Any, float, float | None]],
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    line_color: tuple,
) -> None:
    """Line chart + volume bars at bottom. No Y-axis labels. 24h time labels."""
    if not intraday or len(intraday) < 2:
        return

    raw_prices = [p for _, p, _ in intraday]
    volumes = [v for _, _, v in intraday]
    # 3-point moving average smooths step-function ticks
    prices: list[float] = []
    for i, _ in enumerate(raw_prices):
        window = raw_prices[max(0, i - 1) : i + 2]
        prices.append(sum(window) / len(window))

    p_min, p_max = min(prices), max(prices)
    if p_max == p_min:
        p_max = p_min + 1
    ref_price = raw_prices[0] if raw_prices else (p_min + p_max) / 2
    pad = max((p_max - p_min) * 0.10, abs(ref_price) * 0.005)
    p_lo = p_min - pad
    p_hi = p_max + pad

    # Reserve bottom 18% for volume bars
    vol_h = int(h * 0.18)
    line_h = h - vol_h - 8

    n = len(intraday)

    def line_xy(i: int, price: float) -> tuple[int, int]:
        px = x + int(i * w / (n - 1))
        py = y + int((p_hi - price) / (p_hi - p_lo) * line_h)
        return px, py

    d = ImageDraw.Draw(base, "RGBA")

    # Subtle dashed mid-line for visual reference (no labels)
    mid_y = y + line_h // 2
    dash, gap = 5, 9
    cx = x
    while cx < x + w:
        d.line([(cx, mid_y), (min(cx + dash, x + w), mid_y)], fill=GRID_LINE, width=1)
        cx += dash + gap

    # Line-only style — no opaque area fill, just the curve with a faint glow
    # so the card breathes more (airy / สบายตา).
    poly = [line_xy(i, p) for i, p in enumerate(prices)]
    glow = (line_color[0], line_color[1], line_color[2], 55)
    try:
        d.line(poly, fill=glow, width=8, joint="curve")
        d.line(poly, fill=line_color, width=3, joint="curve")
    except TypeError:
        for i in range(len(poly) - 1):
            d.line([poly[i], poly[i + 1]], fill=glow, width=8)
        for i in range(len(poly) - 1):
            d.line([poly[i], poly[i + 1]], fill=line_color, width=3)

    # Volume bars at the bottom — clip to 90th percentile so a single opening
    # spike doesn't squash the rest of the day into invisible nubs.
    valid_vols = sorted(v for v in volumes if v is not None and v > 0)
    if valid_vols:
        idx_p90 = max(0, int(len(valid_vols) * 0.90) - 1)
        v_scale = valid_vols[idx_p90] or valid_vols[-1]
        if v_scale > 0:
            vol_y0 = y + line_h + 8
            vol_color = (line_color[0], line_color[1], line_color[2], 130)
            # Wider bars: aim for ~3px per bar with 1px gap
            bar_w = max(2, int(w / n) - 1)
            for i, v in enumerate(volumes):
                if v is None or v <= 0:
                    continue
                ratio = min(1.0, v / v_scale)
                bar_h = max(1, int(ratio * vol_h * 0.95))
                bx = x + int(i * w / (n - 1)) - bar_w // 2
                d.rectangle(
                    [bx, vol_y0 + (vol_h - bar_h), bx + bar_w, vol_y0 + vol_h],
                    fill=vol_color,
                )

    # X-axis time labels (24h format), 4 evenly spaced
    label_font = _font(22)
    n_labels = 4
    for j in range(n_labels):
        idx = int(j * (n - 1) / (n_labels - 1))
        ts, _, _ = intraday[idx]
        try:
            label = ts.strftime("%H:%M")
        except Exception:
            label = str(ts)
        lw = d.textlength(label, font=label_font)
        bx, _ = line_xy(idx, prices[idx])
        if j == 0:
            x_text = x
        elif j == n_labels - 1:
            x_text = x + w - int(lw)
        else:
            x_text = bx - int(lw / 2)
        d.text((x_text, y + h + 8), label, font=label_font, fill=TEXT_DIM)


def _draw_top_section(
    img: Image.Image,
    d: ImageDraw.ImageDraw,
    *,
    symbol: str,
    name: str | None,
    logo: Image.Image | None,
    country: str | None,
    exchange_name: str | None,
) -> int:
    """Top row: logo + symbol on left, country/exchange pills on right.
    Returns y-coordinate where the next section can start."""
    top_y = PAD + 10

    # Name (small, above ticker)
    name_text = name or ""
    if name_text:
        # truncate
        name_font = _font(26)
        max_w = W - 2 * PAD - 250  # leave room for badges
        nt = name_text
        while d.textlength(nt, font=name_font) > max_w and len(nt) > 8:
            nt = nt[:-2] + "…"
        d.text((PAD, top_y), nt, font=name_font, fill=TEXT_DIM)

    # Logo + ticker row
    logo_size = 78
    row_y = top_y + 36
    x_cursor = PAD
    if logo is not None:
        rounded = _round_logo(logo, logo_size)
        img.paste(rounded, (x_cursor, row_y), rounded)
        x_cursor += logo_size + 18

    d.text((x_cursor, row_y + 6), symbol, font=_font(60, bold=True), fill=TICKER_PURPLE)

    # Right-side pills (country + exchange)
    pill_y_top = top_y + 6
    pill_y_bot = pill_y_top + 64
    country_label = _country_badge(country)
    _draw_pill(d, country_label, W - PAD, pill_y_top, fill=PILL_PURPLE)
    if exchange_name:
        # Drop suffix like "GS" from "NasdaqGS"
        ex = _normalize_exchange(exchange_name)
        _draw_pill(d, ex, W - PAD, pill_y_bot, fill=PILL_GRAY)

    return row_y + logo_size + 20


def _draw_price_block(
    d: ImageDraw.ImageDraw,
    *,
    y: int,
    price: float,
    currency: str,
    fx_to_thb: float | None,
    is_up: bool,
) -> int:
    """Big price + currency code + Thai baht conversion. Returns next y."""
    color = GREEN if is_up else RED
    price_str = f"{price:,.2f}"
    price_font = _font(82, bold=True)
    cur_font = _font(28)
    baht_font = _font(28, bold=True)

    d.text((PAD, y), price_str, font=price_font, fill=color)
    pw = d.textlength(price_str, font=price_font)

    cx = PAD + int(pw) + 16
    cy = y + 38
    d.text((cx, cy), currency.upper(), font=cur_font, fill=TEXT_DIM)

    if fx_to_thb is not None and currency.upper() != "THB":
        cw = d.textlength(currency.upper(), font=cur_font)
        eq_x = cx + int(cw) + 12
        baht = price * fx_to_thb
        baht_str = f"≈ {baht:,.2f} บาท"
        d.text((eq_x, cy - 2), baht_str, font=baht_font, fill=TEXT_WHITE)

    return y + 95


def _draw_meta_lines(
    d: ImageDraw.ImageDraw,
    *,
    y: int,
    exchange_name: str | None,
    market_state: str | None,
    change_pct: float | None,
    is_up: bool,
) -> int:
    """Three lines: timestamp, market status, change indicator."""
    color = GREEN if is_up else RED
    label_font = _font(24, bold=True)
    body_font = _font(24)

    # Line 1: ราคา ณ: <Thai date time>
    now = datetime.now()
    d.text((PAD, y), "ราคา ณ:", font=label_font, fill=TEXT_WHITE)
    label_w = d.textlength("ราคา ณ: ", font=label_font)
    d.text((PAD + int(label_w), y), _thai_date_time(now), font=body_font, fill=TEXT_DIM)
    y += 38

    # Line 2: Market status
    if exchange_name:
        ex = _normalize_exchange(exchange_name)
        d.text((PAD, y), f"{ex}:", font=label_font, fill=TEXT_WHITE)
        ex_w = d.textlength(f"{ex}: ", font=label_font)
        state_text = {
            "REGULAR": "ตลาดเปิด",
            "PRE": "ก่อนเปิดตลาด",
            "POST": "หลังปิดตลาด",
            "CLOSED": "ตลาดปิด",
        }.get((market_state or "").upper(), "ตลาดปิด")
        d.text((PAD + int(ex_w), y), state_text, font=body_font, fill=TEXT_DIM)
        # green/red dot
        dot_x = PAD + int(ex_w) + int(d.textlength(state_text + "  ", font=body_font))
        dot_color = GREEN if state_text == "ตลาดเปิด" else (180, 180, 185, 255)
        d.ellipse([dot_x, y + 11, dot_x + 14, y + 25], fill=dot_color)
        y += 42

    # Line 3: ↗ X% วันนี้
    if change_pct is not None:
        # Draw triangle arrow
        ax, ay = PAD, y + 18
        arrow_size = 16
        if is_up:
            tri = [(ax, ay + arrow_size), (ax + arrow_size, ay), (ax + arrow_size, ay + arrow_size)]
        else:
            tri = [(ax, ay), (ax + arrow_size, ay + arrow_size), (ax + arrow_size, ay)]
        d.polygon(tri, fill=color)

        text_x = ax + arrow_size + 14
        pct_str = f"{abs(change_pct):.2f}%"
        d.text((text_x, y), pct_str, font=_font(36, bold=True), fill=color)
        pw = d.textlength(pct_str, font=_font(36, bold=True))
        d.text((text_x + int(pw) + 14, y + 8), "วันนี้", font=_font(24), fill=TEXT_DIM)
        y += 56

    return y


def _draw_stats(
    d: ImageDraw.ImageDraw,
    *,
    x0: int,
    y0: int,
    width: int,
    rows: list[tuple[str, str, str, str]],
) -> None:
    label_font = _font(22)
    value_font = _font(24, bold=True)
    col_w = width // 2
    line_h = 48
    for i, (l_lbl, l_val, r_lbl, r_val) in enumerate(rows):
        y = y0 + i * line_h
        d.text((x0, y), l_lbl, font=label_font, fill=TEXT_LABEL)
        lv_w = d.textlength(l_val, font=value_font)
        d.text((x0 + col_w - 40 - lv_w, y - 2), l_val, font=value_font, fill=TEXT_WHITE)
        if r_lbl:
            d.text((x0 + col_w, y), r_lbl, font=label_font, fill=TEXT_LABEL)
        if r_val:
            rv_w = d.textlength(r_val, font=value_font)
            d.text((x0 + width - rv_w, y - 2), r_val, font=value_font, fill=TEXT_WHITE)


def render_card(
    *,
    symbol: str,
    name: str | None,
    price: float | None,
    change: float | None,
    change_pct: float | None,
    currency: str = "USD",
    open_price: float | None = None,
    day_low: float | None = None,
    day_high: float | None = None,
    year_low: float | None = None,
    year_high: float | None = None,
    volume: float | None = None,
    market_cap: float | None = None,
    eps: float | None = None,
    pe: float | None = None,
    exchange_name: str | None = None,
    market_state: str | None = None,
    country: str | None = None,
    fx_to_thb: float | None = None,
    intraday: Sequence[tuple[Any, float, float | None]] | None = None,
) -> bytes | None:
    if price is None:
        return None

    is_up = (change or 0) >= 0
    line_color = GREEN if is_up else RED

    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # 1. Logo + ticker + badges
    logo = _fetch_logo(symbol)
    next_y = _draw_top_section(
        img, d, symbol=symbol, name=name, logo=logo,
        country=country, exchange_name=exchange_name,
    )

    # 2. Price block
    next_y = _draw_price_block(
        d, y=next_y, price=price, currency=currency,
        fx_to_thb=fx_to_thb, is_up=is_up,
    )

    # 3. Timestamp + market status + change
    next_y = _draw_meta_lines(
        d, y=next_y, exchange_name=exchange_name,
        market_state=market_state, change_pct=change_pct, is_up=is_up,
    )

    # 4. Chart — fills the remaining vertical space (stats grid removed)
    next_y += 20
    chart_x = PAD
    chart_w = W - 2 * PAD
    chart_h = H - next_y - 60  # 60px bottom margin reserves room for x-axis labels
    if intraday:
        _draw_chart(img, intraday, x=chart_x, y=next_y, w=chart_w, h=chart_h, line_color=line_color)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
