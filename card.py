"""Stock summary card renderer — dark portrait layout with intraday chart."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Sequence

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

# Canvas
W, H = 720, 1280

# Palette (dark mode, matches reference screenshot)
BG = (0, 0, 0, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_DIM = (170, 170, 175, 255)
TEXT_LABEL = (140, 140, 145, 255)
TEXT_PILL_INACTIVE = (200, 200, 205, 255)
DIVIDER = (45, 45, 50, 255)
GRID_LINE = (50, 50, 55, 255)
PILL_BG = (38, 38, 42, 255)
RED = (255, 69, 96, 255)
GREEN = (0, 200, 110, 255)

PAD = 40

CURRENCY_SYMBOLS = {"USD": "US$", "THB": "฿", "EUR": "€", "GBP": "£", "JPY": "¥"}


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


def _fmt_compact(v: float | None) -> str:
    """Compact number: 4.37T, 20.2M, 1.23K, or plain."""
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


def _draw_dashed_hline(
    d: ImageDraw.ImageDraw, x0: int, x1: int, y: int, color: tuple, dash: int = 6, gap: int = 8
) -> None:
    x = x0
    while x < x1:
        d.line([(x, y), (min(x + dash, x1), y)], fill=color, width=1)
        x += dash + gap


def _draw_chart(
    base: Image.Image,
    intraday: Sequence[tuple[Any, float]],
    *,
    chart_x: int,
    chart_y: int,
    chart_w: int,
    chart_h: int,
    line_color: tuple,
) -> None:
    """Draw line chart with right-side y-axis labels and bottom x-axis labels."""
    if not intraday or len(intraday) < 2:
        return

    raw_prices = [p for _, p in intraday]
    # 3-point moving average smooths step-function ticks (e.g. Thai stocks
    # that trade in fixed 0.25/0.50 increments) without distorting trend.
    prices: list[float] = []
    for i, _ in enumerate(raw_prices):
        window = raw_prices[max(0, i - 1) : i + 2]
        prices.append(sum(window) / len(window))

    p_min, p_max = min(prices), max(prices)
    if p_max == p_min:
        p_max = p_min + 1
    # Pad y-range: 10% of range, but at least 0.5% of price level so narrow
    # trading ranges (PTT-style) don't paint the full chart height.
    ref_price = raw_prices[0] if raw_prices else (p_min + p_max) / 2
    pad = max((p_max - p_min) * 0.10, abs(ref_price) * 0.005)
    p_lo = p_min - pad
    p_hi = p_max + pad

    axis_w = 110  # space reserved on the right for price labels
    plot_x = chart_x
    plot_w = chart_w - axis_w
    plot_y = chart_y
    plot_h = chart_h

    n = len(intraday)

    def to_xy(i: int, price: float) -> tuple[int, int]:
        x = plot_x + int(i * plot_w / (n - 1))
        y = plot_y + int((p_hi - price) / (p_hi - p_lo) * plot_h)
        return x, y

    d = ImageDraw.Draw(base, "RGBA")

    # Dashed horizontal grid lines at 5 nice price levels
    label_font = _font(22)
    n_lines = 5
    step = (p_hi - p_lo) / (n_lines - 1)
    for i in range(n_lines):
        level = p_lo + step * i
        y = plot_y + int((p_hi - level) / (p_hi - p_lo) * plot_h)
        _draw_dashed_hline(d, plot_x, plot_x + plot_w, y, GRID_LINE)
        # Right-side label
        label = f"{level:,.0f}" if level >= 100 else f"{level:,.2f}"
        lw = d.textlength(label, font=label_font)
        d.text((plot_x + plot_w + axis_w - lw, y - 14), label, font=label_font, fill=TEXT_DIM)

    # Filled area below line (translucent — subtle gradient feel)
    fill_color = (line_color[0], line_color[1], line_color[2], 30)
    poly = [to_xy(i, p) for i, p in enumerate(prices)]
    poly_filled = poly + [(plot_x + plot_w, plot_y + plot_h), (plot_x, plot_y + plot_h)]
    d.polygon(poly_filled, fill=fill_color)

    # Main line (thicker, smoothed via multiple passes if needed)
    for i in range(len(poly) - 1):
        d.line([poly[i], poly[i + 1]], fill=line_color, width=3)

    # X-axis time labels — 4 evenly spaced points (5 cause overlap on long times)
    n_labels = 4
    for j in range(n_labels):
        idx = int(j * (n - 1) / (n_labels - 1))
        ts, _ = intraday[idx]
        try:
            label = ts.strftime("%-I:%M %p")
        except Exception:
            label = str(ts)
        lw = d.textlength(label, font=label_font)
        x, _ = to_xy(idx, prices[idx])
        # Center-align under the point, clamp inside plot area
        x_text = max(plot_x, min(plot_x + plot_w - int(lw), x - int(lw / 2)))
        d.text((x_text, plot_y + plot_h + 18), label, font=label_font, fill=TEXT_DIM)


def _draw_tabs(d: ImageDraw.ImageDraw, x0: int, y: int, w: int) -> None:
    labels = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y"]
    font = _font(26, bold=True)
    inner_w = w
    spacing = inner_w // len(labels)
    for i, lbl in enumerate(labels):
        cx = x0 + spacing * i + spacing // 2
        tw = d.textlength(lbl, font=font)
        if i == 0:
            # Active pill
            pill_w, pill_h = 80, 50
            d.rounded_rectangle(
                [cx - pill_w // 2, y - 6, cx + pill_w // 2, y - 6 + pill_h],
                radius=25,
                fill=PILL_BG,
            )
            d.text((cx - tw / 2, y), lbl, font=font, fill=TEXT_WHITE)
        else:
            d.text((cx - tw / 2, y), lbl, font=_font(26), fill=TEXT_PILL_INACTIVE)


def _draw_stats(
    d: ImageDraw.ImageDraw,
    *,
    x0: int,
    y0: int,
    width: int,
    rows: list[tuple[str, str, str, str]],
) -> None:
    """rows: list of (left_label, left_value, right_label, right_value)."""
    label_font = _font(24)
    value_font = _font(26, bold=True)
    col_w = width // 2
    line_h = 56

    for i, (l_lbl, l_val, r_lbl, r_val) in enumerate(rows):
        y = y0 + i * line_h
        # Left column
        d.text((x0, y), l_lbl, font=label_font, fill=TEXT_LABEL)
        lv_w = d.textlength(l_val, font=value_font)
        d.text((x0 + col_w - 40 - lv_w, y - 2), l_val, font=value_font, fill=TEXT_WHITE)
        # Right column
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
    intraday: Sequence[tuple[Any, float]] | None = None,
) -> bytes | None:
    if price is None:
        return None

    is_up = (change or 0) >= 0
    line_color = GREEN if is_up else RED
    cur = _currency_prefix(currency)

    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # --- Header: company name + ticker
    y = PAD + 10
    header = f"{name} ({symbol})" if name else symbol
    # Truncate if too long
    header_font = _font(28)
    max_w = W - 2 * PAD
    while d.textlength(header, font=header_font) > max_w and len(header) > 10:
        header = header[:-2] + "…"
    d.text((PAD, y), header, font=header_font, fill=TEXT_DIM)

    # --- Big price
    y = PAD + 55
    price_str = f"{cur}{price:,.2f}"
    d.text((PAD, y), price_str, font=_font(76, bold=True), fill=TEXT_WHITE)

    # --- Change line
    y_change = y + 110
    if change is not None:
        sign = "-" if change < 0 else "+"
        parts = [f"{sign}{cur}{abs(change):,.2f}"]
        if change_pct is not None:
            parts.append(f"({abs(change_pct):.2f}%)")
        parts.append("• วันนี้")
        d.text((PAD, y_change), " ".join(parts), font=_font(28, bold=True), fill=line_color)

    # --- Horizontal divider
    y_div = y_change + 60
    d.line([(PAD, y_div), (W - PAD, y_div)], fill=DIVIDER, width=1)

    # --- Time period tabs
    y_tabs = y_div + 40
    _draw_tabs(d, PAD, y_tabs, W - 2 * PAD)

    # --- Chart area
    chart_x = PAD
    chart_y = y_tabs + 80
    chart_w = W - 2 * PAD
    chart_h = 360
    if intraday:
        _draw_chart(
            img,
            intraday,
            chart_x=chart_x,
            chart_y=chart_y,
            chart_w=chart_w,
            chart_h=chart_h,
            line_color=line_color,
        )

    # --- Stats grid
    y_stats = chart_y + chart_h + 70
    rows = [
        ("เปิด",         _fmt_price(open_price),      "ปริมาณ",       _fmt_compact(volume)),
        ("มูลค่าตลาด",   _fmt_compact(market_cap),    "ต่ำสุดของวัน", _fmt_price(day_low)),
        ("ต่ำสุดของปี",  _fmt_price(year_low),        "EPS (TTM)",     _fmt_price(eps)),
        ("สูงสุดของวัน", _fmt_price(day_high),        "สูงสุดของปี",  _fmt_price(year_high)),
        ("อัตรา P/E",    _fmt_pe(pe),                 "",              ""),
    ]
    _draw_stats(d, x0=PAD, y0=y_stats, width=W - 2 * PAD, rows=rows)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
