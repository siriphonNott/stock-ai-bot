"""Crypto Fear & Greed Index — fetch + render gauge card + historical chart."""
from __future__ import annotations

import io
import logging
import math
from datetime import datetime, timezone

import requests
from PIL import Image, ImageDraw

from card import _font

log = logging.getLogger(__name__)

ALT_URL = "https://api.alternative.me/fng/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Palette — matches existing F&G card vibe
BG = (10, 12, 16, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_DIM = (140, 144, 152, 255)
TEXT_LABEL = (170, 174, 182, 255)
POINTER_GREY = (130, 134, 142, 255)

# Five-stop gradient colors (Extreme Fear → Extreme Greed)
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


# ────────────────────────── data fetchers ──────────────────────────

def get_crypto_fng(limit: int = 1100) -> dict | None:
    """Fetch crypto Fear & Greed from alternative.me. Newest is data[0]."""
    try:
        r = requests.get(
            ALT_URL, params={"limit": limit},
            headers={"User-Agent": UA}, timeout=10,
        )
        if r.status_code != 200:
            return None
        items = r.json().get("data", [])
        if not items:
            return None
        return {
            "current":    items[0],
            "yesterday":  items[1]  if len(items) > 1  else None,
            "last_week":  items[7]  if len(items) > 7  else None,
            "last_month": items[30] if len(items) > 30 else None,
            "history":    list(reversed(items)),  # oldest → newest
        }
    except Exception:
        log.exception("Crypto F&G fetch failed")
        return None


def get_btc_history(days: int = 1100) -> list[dict] | None:
    """BTC-USD daily history via yfinance — returns [{date, close, volume}, …]."""
    try:
        import yfinance as yf
        years = max(1, days // 365 + 1)
        hist = yf.Ticker("BTC-USD").history(period=f"{years}y", interval="1d")
        if hist is None or hist.empty:
            return None
        out = []
        for idx, row in hist.iterrows():
            close = row.get("Close")
            vol = row.get("Volume")
            if close is None or (isinstance(close, float) and math.isnan(close)):
                continue
            out.append({
                "date":   idx.to_pydatetime(),
                "close":  float(close),
                "volume": float(vol) if vol is not None and not math.isnan(vol) else 0.0,
            })
        return out
    except Exception:
        log.exception("BTC history fetch failed")
        return None


# ────────────────────────── gauge card ──────────────────────────

GAUGE_W, GAUGE_H = 1200, 540


def render_crypto_fng_gauge(data: dict | None) -> bytes | None:
    if not data or not data.get("current"):
        return None
    try:
        value = float(data["current"]["value"])
    except (KeyError, TypeError, ValueError):
        return None

    img = Image.new("RGBA", (GAUGE_W, GAUGE_H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    title_font = _font(40, bold=True)
    d.text((50, 35), "Crypto Fear & Greed Index", font=title_font, fill=TEXT_WHITE)

    # Semi-circle: opens upward, sits in left half
    cx, cy = 420, 440
    r_outer = 230
    r_inner = 204

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
    # Cut inner half-disk to leave a ring
    d.pieslice(
        [cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
        180, 360, fill=BG,
    )
    # Hide the lower half (we only want top semi-circle)
    d.rectangle([cx - r_outer - 4, cy, cx + r_outer + 4, cy + r_outer + 4], fill=BG)

    # Triangle pointer — sits just below the inner edge, pointing toward the arc
    ang = math.radians(180 + value * 1.8)
    nx, ny = math.cos(ang), math.sin(ang)
    tx_a, ty_a = -math.sin(ang), math.cos(ang)
    p_anchor_r = r_inner - 6
    px = cx + nx * p_anchor_r
    py = cy + ny * p_anchor_r
    tri_len = 22
    tri_w = 14
    tip_x = px + nx * tri_len
    tip_y = py + ny * tri_len
    b1x = px + tx_a * tri_w
    b1y = py + ty_a * tri_w
    b2x = px - tx_a * tri_w
    b2y = py - ty_a * tri_w
    d.polygon([(tip_x, tip_y), (b1x, b1y), (b2x, b2y)], fill=POINTER_GREY)

    # Big value + classification under the arc
    val_str = f"{int(round(value))}"
    val_font = _font(96, bold=True)
    vw = d.textlength(val_str, font=val_font)
    d.text((cx - vw / 2, cy - 110), val_str, font=val_font, fill=TEXT_WHITE)

    cls = _classify(value)
    cls_font = _font(32)
    cw = d.textlength(cls, font=cls_font)
    d.text((cx - cw / 2, cy - 10), cls, font=cls_font, fill=TEXT_WHITE)

    # Right column: yesterday / last week / last month
    right_col_x = 800
    right_num_x = GAUGE_W - 70
    label_font = _font(24)
    cls_font_small = _font(24, bold=True)
    num_font = _font(60, bold=True)
    row_y0 = 130
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
            v = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
        cls_text = item.get("value_classification") or _classify(v)
        d.text((right_col_x, y + 32), cls_text, font=cls_font_small, fill=TEXT_WHITE)
        v_str = f"{int(round(v))}"
        nw = d.textlength(v_str, font=num_font)
        d.text((right_num_x - nw, y + 4), v_str, font=num_font, fill=TEXT_WHITE)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


# ────────────────────────── historical chart ──────────────────────────

CHART_W, CHART_H = 1600, 800
BAND_GREED = (24, 56, 42, 255)
BAND_FEAR  = (62, 28, 34, 255)
BTC_LINE   = (160, 164, 178, 255)
VOL_FILL   = (90, 80, 110, 200)
ZONE_LABEL = (210, 214, 220, 220)


def render_crypto_fng_chart(
    fng_data: dict | None, btc_history: list[dict] | None,
) -> bytes | None:
    if not fng_data or not fng_data.get("history") or not btc_history:
        return None

    img = Image.new("RGBA", (CHART_W, CHART_H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # ── plot box
    pad_l, pad_r, pad_t, pad_b = 80, 130, 80, 90
    x0, x1 = pad_l, CHART_W - pad_r
    y0, y1 = pad_t, CHART_H - pad_b
    pw, ph = x1 - x0, y1 - y0

    # ── legend (top)
    leg_font = _font(22)
    legend = [
        ((235, 195, 60),  "Crypto Fear and Greed Index"),
        ((170, 174, 188), "Bitcoin Price"),
        ((120, 110, 140), "Bitcoin Volume"),
    ]
    lx = 60
    for col, lbl in legend:
        d.ellipse([lx, 32, lx + 14, 46], fill=(col[0], col[1], col[2], 255))
        d.text((lx + 22, 26), lbl, font=leg_font, fill=TEXT_DIM)
        lx += 36 + d.textlength(lbl, font=leg_font) + 30

    # ── build F&G by date
    fng_by_date: dict = {}
    for entry in fng_data["history"]:
        try:
            ts = int(entry["timestamp"])
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            fng_by_date[dt] = float(entry["value"])
        except (KeyError, TypeError, ValueError):
            continue
    if not fng_by_date:
        return None

    btc_points = [
        {"date": p["date"].date(), "close": p["close"], "volume": p["volume"]}
        for p in btc_history
    ]
    if not btc_points:
        return None

    start_date = max(btc_points[0]["date"], min(fng_by_date.keys()))
    end_date   = min(btc_points[-1]["date"], max(fng_by_date.keys()))
    total_days = (end_date - start_date).days
    if total_days <= 0:
        return None

    def x_for(date) -> float:
        return x0 + pw * (date - start_date).days / total_days

    # BTC price scale — round to nearest 30K
    in_range = [p["close"] for p in btc_points if start_date <= p["date"] <= end_date]
    if not in_range:
        return None
    btc_max = max(in_range)
    btc_y_max = max(150_000, int(math.ceil(btc_max / 30_000)) * 30_000)
    btc_y_min = 30_000 if min(in_range) >= 25_000 else 0

    def y_btc(price) -> float:
        return y1 - ph * (price - btc_y_min) / max(1, btc_y_max - btc_y_min)

    def y_fng(value) -> float:
        return y1 - ph * value / 100.0

    # ── background bands: Extreme Greed (top) + Extreme Fear (bottom)
    d.rectangle([x0, y_fng(100), x1, y_fng(75)], fill=BAND_GREED)
    d.rectangle([x0, y_fng(25),  x1, y_fng(0)],  fill=BAND_FEAR)

    # ── volume bars (bottom 20%)
    vol_h_max = ph * 0.20
    vol_max = max((p["volume"] for p in btc_points), default=0)
    if vol_max > 0:
        for p in btc_points:
            if not (start_date <= p["date"] <= end_date):
                continue
            xx = x_for(p["date"])
            vh = (p["volume"] / vol_max) * vol_h_max
            if vh < 1:
                continue
            d.line([(xx, y1), (xx, y1 - vh)], fill=VOL_FILL, width=2)

    # ── BTC price line
    btc_pts = [
        (x_for(p["date"]), y_btc(p["close"]))
        for p in btc_points if start_date <= p["date"] <= end_date
    ]
    if len(btc_pts) >= 2:
        d.line(btc_pts, fill=BTC_LINE, width=2)

    # ── F&G line — coloured by zone, segment by segment
    fng_pts = sorted(
        (date, v) for date, v in fng_by_date.items()
        if start_date <= date <= end_date
    )
    prev_xy = None
    prev_v = None
    for date, v in fng_pts:
        xy = (x_for(date), y_fng(v))
        if prev_xy is not None:
            avg = (prev_v + v) / 2
            col = _zone_color(avg)
            d.line([prev_xy, xy], fill=(col[0], col[1], col[2], 255), width=2)
        prev_xy, prev_v = xy, v

    # ── left axis ticks (BTC USD)
    tick_font = _font(20)
    for p in range(btc_y_min, btc_y_max + 1, 30_000):
        ty = y_btc(p)
        d.text((22, ty - 12), f"{p // 1000}K", font=tick_font, fill=TEXT_DIM)

    # ── right axis ticks (F&G 20/40/60/80/100)
    for v in (20, 40, 60, 80, 100):
        ty = y_fng(v)
        d.text((x1 + 10, ty - 12), str(v), font=tick_font, fill=TEXT_DIM)

    # ── zone labels on the right side (within the band)
    zone_font = _font(22)
    zone_labels = [
        ("Extreme Greed", 87, (90, 200, 130, 230)),
        ("Greed",         65, ZONE_LABEL),
        ("Neutral",       50, ZONE_LABEL),
        ("Fear",          35, ZONE_LABEL),
        ("Extreme Fear",  12, (220, 110, 110, 230)),
    ]
    for lbl, vy, col in zone_labels:
        tw = d.textlength(lbl, font=zone_font)
        d.text((x1 - tw - 20, y_fng(vy) - 12), lbl, font=zone_font, fill=col)

    # ── axis corner labels
    d.text((22, y1 + 32), "USD", font=tick_font, fill=TEXT_DIM)
    d.text((x1 + 10, y1 + 32), "F&G", font=tick_font, fill=TEXT_DIM)

    # ── x-axis date labels every 6 months on Jan/Jul
    month_font = _font(20)
    cur_year = start_date.year
    cur_month = start_date.month
    # advance to nearest Jan or Jul
    while cur_month not in (1, 7):
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1
    while True:
        try:
            tick_date = datetime(cur_year, cur_month, 1).date()
        except ValueError:
            break
        if tick_date > end_date:
            break
        if tick_date >= start_date:
            tx = x_for(tick_date)
            label = tick_date.strftime("%b %Y")
            tw = d.textlength(label, font=month_font)
            d.text((tx - tw / 2, y1 + 16), label, font=month_font, fill=TEXT_DIM)
        cur_month += 6
        if cur_month > 12:
            cur_month -= 12
            cur_year += 1

    # ── current value tag on right edge
    if fng_pts:
        last_date, last_v = fng_pts[-1]
        col = _zone_color(last_v)
        last_y = y_fng(last_v)
        box_w, box_h = 70, 42
        bx = x1 + 4
        by = last_y - box_h / 2
        d.rectangle(
            [bx, by, bx + box_w, by + box_h],
            fill=(col[0], col[1], col[2], 255),
        )
        v_str = f"{int(round(last_v))}"
        cur_font = _font(26, bold=True)
        vw = d.textlength(v_str, font=cur_font)
        d.text(
            (bx + (box_w - vw) / 2, by + 5),
            v_str, font=cur_font, fill=TEXT_WHITE,
        )

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
