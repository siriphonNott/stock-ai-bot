"""Crypto Fear & Greed Index — fetch + render gauge card + historical chart.

Data source: CoinMarketCap public chart API (same one their dashboard uses).
"""
from __future__ import annotations

import io
import logging
import math
import time
from datetime import datetime, timezone

import requests
from PIL import Image, ImageDraw

from card import _font

log = logging.getLogger(__name__)

CMC_URL = "https://api.coinmarketcap.com/data-api/v3/fear-greed/chart"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Palette
BG = (10, 12, 16, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_DIM = (140, 144, 152, 255)
TEXT_LABEL = (170, 174, 182, 255)
POINTER_GREY = (148, 152, 160, 255)

# Five-stop gradient (Extreme Fear → Extreme Greed)
ZONE_COLORS = [
    (235, 80, 70),    # Extreme Fear
    (240, 140, 50),   # Fear
    (235, 195, 60),   # Neutral
    (140, 210, 90),   # Greed
    (60, 200, 110),   # Extreme Greed
]


def _classify(value: float) -> str:
    if value < 25: return "Extreme Fear"
    if value < 45: return "Fear"
    if value < 55: return "Neutral"
    if value < 75: return "Greed"
    return "Extreme Greed"


def _zone_color(value: float) -> tuple[int, int, int]:
    v = max(0.0, min(100.0, value))
    pos = v / 100.0 * (len(ZONE_COLORS) - 1)
    i = int(pos)
    frac = pos - i
    if i >= len(ZONE_COLORS) - 1:
        return ZONE_COLORS[-1]
    a = ZONE_COLORS[i]
    b = ZONE_COLORS[i + 1]
    return (
        int(a[0] + (b[0] - a[0]) * frac),
        int(a[1] + (b[1] - a[1]) * frac),
        int(a[2] + (b[2] - a[2]) * frac),
    )


# ────────────────────────── data fetcher ──────────────────────────

def get_crypto_fng(days: int = 1100) -> dict | None:
    """Fetch crypto F&G + BTC history from CMC. Returns dict with:
       - current/yesterday/last_week/last_month: {score, name}
       - history: list of {date, score, btc_price, btc_volume} (oldest→newest)
    """
    end = int(time.time())
    start = end - days * 86400
    try:
        r = requests.get(
            CMC_URL,
            params={"start": start, "end": end},
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        body = r.json().get("data") or {}
        data_list = body.get("dataList") or []
        hv = body.get("historicalValues") or {}
        if not data_list or not hv.get("now"):
            return None
        history = []
        for item in data_list:
            try:
                ts = int(item["timestamp"])
                history.append({
                    "date":       datetime.fromtimestamp(ts, tz=timezone.utc),
                    "score":      float(item["score"]),
                    "btc_price":  float(item.get("btcPrice")  or 0.0),
                    "btc_volume": float(item.get("btcVolume") or 0.0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        if not history:
            return None
        history.sort(key=lambda p: p["date"])
        return {
            "current":    hv.get("now"),
            "yesterday":  hv.get("yesterday"),
            "last_week":  hv.get("lastWeek"),
            "last_month": hv.get("lastMonth"),
            "history":    history,
        }
    except Exception:
        log.exception("CMC crypto F&G fetch failed")
        return None


# ────────────────────────── gauge card ──────────────────────────

GAUGE_W, GAUGE_H = 1200, 580


def render_crypto_fng_gauge(data: dict | None) -> bytes | None:
    if not data or not data.get("current"):
        return None
    try:
        value = float(data["current"]["score"])
        name = data["current"].get("name") or _classify(value)
    except (KeyError, TypeError, ValueError):
        return None

    img = Image.new("RGBA", (GAUGE_W, GAUGE_H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    title_font = _font(42, bold=True)
    d.text((50, 38), "Crypto Fear & Greed Index", font=title_font, fill=TEXT_WHITE)

    # Semi-circle gauge — opens upward, sits in left half
    cx, cy = 420, 430
    r_outer = 230
    r_inner = 202

    # Rainbow arc — many small pieslices for a smooth gradient
    n_seg = 180
    for i in range(n_seg):
        a0 = 180 + i * (180 / n_seg)
        a1 = 180 + (i + 1) * (180 / n_seg)
        v = (i + 0.5) / n_seg * 100
        col = _zone_color(v)
        d.pieslice(
            [cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
            a0, a1, fill=(col[0], col[1], col[2], 255),
        )
    d.pieslice(
        [cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
        180, 360, fill=BG,
    )
    d.rectangle([cx - r_outer - 4, cy, cx + r_outer + 4, cy + r_outer + 4], fill=BG)

    # Triangle pointer — bigger, tip sits just below the arc inner edge
    ang = math.radians(180 + value * 1.8)
    nx, ny = math.cos(ang), math.sin(ang)
    tx_a, ty_a = -math.sin(ang), math.cos(ang)
    pin_gap = 8                        # small gap so the pin nearly touches the arc
    tri_len = 30
    tri_w = 18
    tip_r = r_inner - pin_gap          # tip sits this far inside the inner edge
    base_r = tip_r - tri_len
    tip_x = cx + nx * tip_r
    tip_y = cy + ny * tip_r
    base_cx = cx + nx * base_r
    base_cy = cy + ny * base_r
    b1x = base_cx + tx_a * tri_w
    b1y = base_cy + ty_a * tri_w
    b2x = base_cx - tx_a * tri_w
    b2y = base_cy - ty_a * tri_w
    d.polygon([(tip_x, tip_y), (b1x, b1y), (b2x, b2y)], fill=POINTER_GREY)

    # Big value + classification under the arc — more breathing room
    val_str = f"{int(round(value))}"
    val_font = _font(124, bold=True)
    vw = d.textlength(val_str, font=val_font)
    val_y = cy - 170                   # nudged up
    d.text((cx - vw / 2, val_y), val_str, font=val_font, fill=TEXT_WHITE)

    cls_font = _font(48)               # bigger classification
    cw = d.textlength(name, font=cls_font)
    cls_y = val_y + 140
    d.text((cx - cw / 2, cls_y), name, font=cls_font, fill=TEXT_WHITE)

    # Right column: yesterday / last week / last month — tighter font sizes
    right_col_x = 790
    right_num_x = GAUGE_W - 60
    label_font = _font(26)
    cls_font_small = _font(26, bold=True)
    num_font = _font(62, bold=True)    # reduced from 76
    row_y0 = 140
    row_gap = 130
    rows = [
        ("Yesterday",  data.get("yesterday")),
        ("Last Week",  data.get("last_week")),
        ("Last Month", data.get("last_month")),
    ]
    for i, (lbl, item) in enumerate(rows):
        y = row_y0 + i * row_gap
        d.text((right_col_x, y), lbl, font=label_font, fill=TEXT_DIM)
        if not item:
            continue
        try:
            v = float(item["score"])
        except (KeyError, TypeError, ValueError):
            continue
        cls_text = item.get("name") or _classify(v)
        d.text((right_col_x, y + 34), cls_text, font=cls_font_small, fill=TEXT_WHITE)
        v_str = f"{int(round(v))}"
        nw = d.textlength(v_str, font=num_font)
        d.text((right_num_x - nw, y + 2), v_str, font=num_font, fill=TEXT_WHITE)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


# ────────────────────────── historical chart ──────────────────────────

CHART_W, CHART_H = 1600, 800
# Muted band colors — softer on the eyes
BAND_GREED = (28, 54, 48, 255)   # muted teal
BAND_FEAR  = (56, 32, 46, 255)   # muted plum
BTC_LINE   = (160, 164, 178, 255)
VOL_FILL   = (115, 100, 140, 200)
ZONE_LABEL = (190, 194, 202, 235)  # light grey — readable on band
GRID_DASH  = (110, 114, 122, 180)  # grey horizontal grid


def _dashed_hline(
    d: ImageDraw.ImageDraw, x0: float, x1: float, y: float,
    *, fill: tuple, dash: int = 3, gap: int = 4, width: int = 1,
) -> None:
    x = x0
    while x < x1:
        d.line([(x, y), (min(x + dash, x1), y)], fill=fill, width=width)
        x += dash + gap


def render_crypto_fng_chart(data: dict | None) -> bytes | None:
    if not data or not data.get("history"):
        return None
    history = data["history"]
    if len(history) < 2:
        return None

    img = Image.new("RGBA", (CHART_W, CHART_H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    pad_l, pad_r, pad_t, pad_b = 80, 130, 80, 90
    x0, x1 = pad_l, CHART_W - pad_r
    y0, y1 = pad_t, CHART_H - pad_b
    pw, ph = x1 - x0, y1 - y0

    # Legend — evenly spaced, slightly larger dots for clarity
    leg_font = _font(24)
    legend = [
        ((235, 195, 60),  "Crypto Fear and Greed Index"),
        ((175, 180, 195), "Bitcoin Price"),
        ((150, 138, 178), "Bitcoin Volume"),
    ]
    dot_d = 16
    dot_y = 30
    leg_y = 24
    lx = 60
    for col, lbl in legend:
        d.ellipse(
            [lx, dot_y, lx + dot_d, dot_y + dot_d],
            fill=(col[0], col[1], col[2], 255),
        )
        d.text((lx + dot_d + 10, leg_y), lbl, font=leg_font, fill=TEXT_LABEL)
        lx += dot_d + 10 + d.textlength(lbl, font=leg_font) + 50

    # Build time axis from history
    start_date = history[0]["date"]
    end_date   = history[-1]["date"]
    total_secs = (end_date - start_date).total_seconds()
    if total_secs <= 0:
        return None

    def x_for(dt) -> float:
        return x0 + pw * (dt - start_date).total_seconds() / total_secs

    btc_prices = [p["btc_price"] for p in history if p["btc_price"] > 0]
    if not btc_prices:
        return None
    btc_max = max(btc_prices)
    btc_min = min(btc_prices)
    btc_y_max = max(150_000, int(math.ceil(btc_max / 30_000)) * 30_000)
    btc_y_min = 30_000 if btc_min >= 25_000 else 0

    def y_btc(price) -> float:
        return y1 - ph * (price - btc_y_min) / max(1, btc_y_max - btc_y_min)

    def y_fng(value) -> float:
        return y1 - ph * value / 100.0

    # Background bands
    d.rectangle([x0, y_fng(100), x1, y_fng(75)], fill=BAND_GREED)
    d.rectangle([x0, y_fng(25),  x1, y_fng(0)],  fill=BAND_FEAR)

    # Fine dashed horizontal grid at every USD tick — drawn before the lines
    # so the price/F&G plot reads above the grid.
    for p_val in range(btc_y_min, btc_y_max + 1, 30_000):
        _dashed_hline(d, x0, x1, y_btc(p_val), fill=GRID_DASH)

    # Volume bars (bottom 20%, faint)
    vol_h_max = ph * 0.20
    vol_max = max((p["btc_volume"] for p in history), default=0)
    if vol_max > 0:
        for p in history:
            xx = x_for(p["date"])
            vh = (p["btc_volume"] / vol_max) * vol_h_max
            if vh < 1:
                continue
            d.line([(xx, y1), (xx, y1 - vh)], fill=VOL_FILL, width=2)

    # BTC price line
    btc_pts = [(x_for(p["date"]), y_btc(p["btc_price"])) for p in history if p["btc_price"] > 0]
    if len(btc_pts) >= 2:
        d.line(btc_pts, fill=BTC_LINE, width=2)

    # F&G line — coloured by zone, segment by segment
    prev_xy = None
    prev_v = None
    for p in history:
        xy = (x_for(p["date"]), y_fng(p["score"]))
        if prev_xy is not None:
            avg = (prev_v + p["score"]) / 2
            col = _zone_color(avg)
            d.line([prev_xy, xy], fill=(col[0], col[1], col[2], 255), width=2)
        prev_xy, prev_v = xy, p["score"]

    # Left axis ticks (BTC USD)
    tick_font = _font(20)
    for p_val in range(btc_y_min, btc_y_max + 1, 30_000):
        ty = y_btc(p_val)
        d.text((22, ty - 12), f"{p_val // 1000}K", font=tick_font, fill=TEXT_DIM)

    # Right axis ticks (F&G)
    for v in (20, 40, 60, 80, 100):
        ty = y_fng(v)
        d.text((x1 + 10, ty - 12), str(v), font=tick_font, fill=TEXT_DIM)

    # Zone labels — light grey on the right, inside their bands
    zone_font = _font(22)
    zone_labels = [
        ("Extreme Greed", 87),
        ("Greed",         65),
        ("Neutral",       50),
        ("Fear",          35),
        ("Extreme Fear",  12),
    ]
    for lbl, vy in zone_labels:
        tw = d.textlength(lbl, font=zone_font)
        d.text((x1 - tw - 20, y_fng(vy) - 12), lbl, font=zone_font, fill=ZONE_LABEL)

    # Axis corner labels
    d.text((22, y1 + 32), "USD", font=tick_font, fill=TEXT_DIM)
    d.text((x1 + 10, y1 + 32), "F&G", font=tick_font, fill=TEXT_DIM)

    # X-axis: Jan/Jul markers
    month_font = _font(20)
    cur_year, cur_month = start_date.year, start_date.month
    while cur_month not in (1, 7):
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1
    while True:
        try:
            tick_dt = datetime(cur_year, cur_month, 1, tzinfo=timezone.utc)
        except ValueError:
            break
        if tick_dt > end_date:
            break
        if tick_dt >= start_date:
            tx = x_for(tick_dt)
            label = tick_dt.strftime("%b %Y")
            tw = d.textlength(label, font=month_font)
            d.text((tx - tw / 2, y1 + 16), label, font=month_font, fill=TEXT_DIM)
        cur_month += 6
        if cur_month > 12:
            cur_month -= 12
            cur_year += 1

    # Current value tag on right edge
    last = history[-1]
    last_v = last["score"]
    col = _zone_color(last_v)
    last_y = y_fng(last_v)
    box_w, box_h = 70, 42
    bx = x1 + 4
    by = last_y - box_h / 2
    d.rectangle([bx, by, bx + box_w, by + box_h], fill=(col[0], col[1], col[2], 255))
    v_str = f"{int(round(last_v))}"
    cur_font = _font(26, bold=True)
    vw = d.textlength(v_str, font=cur_font)
    d.text((bx + (box_w - vw) / 2, by + 5), v_str, font=cur_font, fill=TEXT_WHITE)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
