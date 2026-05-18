"""CNN Fear & Greed Index — fetch + render gauge card."""
from __future__ import annotations

import io
import logging
import math
from datetime import datetime

import requests
from PIL import Image, ImageDraw

from card import _font

log = logging.getLogger(__name__)

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Canvas
W, H = 720, 1280

# Palette
BG = (0, 0, 0, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_DIM = (170, 170, 175, 255)
TEXT_LABEL = (130, 130, 138, 255)
HUB_BG = (30, 30, 35, 255)

# 5 zones — label and arc color (left → right on the gauge)
ZONE_EXTREME_FEAR = ("EXTREME FEAR", (231, 76, 60, 255))
ZONE_FEAR = ("FEAR", (230, 126, 34, 255))
ZONE_NEUTRAL = ("NEUTRAL", (241, 196, 15, 255))
ZONE_GREED = ("GREED", (39, 174, 96, 255))
ZONE_EXTREME_GREED = ("EXTREME GREED", (22, 160, 133, 255))
ZONES = (ZONE_EXTREME_FEAR, ZONE_FEAR, ZONE_NEUTRAL, ZONE_GREED, ZONE_EXTREME_GREED)


def get_fear_greed_index() -> dict | None:
    """Fetch CNN's current F&G snapshot. None on failure."""
    try:
        r = requests.get(CNN_URL, headers={"User-Agent": UA}, timeout=10)
        if r.status_code != 200:
            return None
        return r.json().get("fear_and_greed")
    except Exception:
        log.exception("F&G fetch failed")
        return None


def _classify(score: float) -> tuple[str, tuple]:
    """Map 0–100 score to (label, color)."""
    if score < 25:
        return ZONE_EXTREME_FEAR
    if score < 45:
        return ZONE_FEAR
    if score < 55:
        return ZONE_NEUTRAL
    if score < 75:
        return ZONE_GREED
    return ZONE_EXTREME_GREED


def _draw_gauge(d: ImageDraw.ImageDraw, *, cx: int, cy: int, radius: int, arc_w: int, score: float) -> None:
    """Draw a 180° semi-circular gauge with 5 colored zones and a needle."""
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]

    # 5 segments of 36° each, drawn as thick arcs (180° → 360° = top half in PIL)
    # Pad by 0.4° on each side per segment so adjacent segments visually connect.
    for i, (_, color) in enumerate(ZONES):
        start = 180 + i * 36 - 0.4
        end = 180 + (i + 1) * 36 + 0.4
        d.arc(bbox, start, end, fill=color, width=arc_w)

    # Tick marks at the 6 segment boundaries
    tick_color = (60, 60, 65, 255)
    for i in range(6):
        angle = math.radians(180 + i * 36)
        r_outer = radius + 4
        r_inner = radius - arc_w - 6
        x1 = cx + math.cos(angle) * r_outer
        y1 = cy + math.sin(angle) * r_outer
        x2 = cx + math.cos(angle) * r_inner
        y2 = cy + math.sin(angle) * r_inner
        d.line([(x1, y1), (x2, y2)], fill=tick_color, width=2)

    # Needle — line from hub to inside edge of the arc band
    s = max(0.0, min(100.0, float(score)))
    angle = math.radians(180 + s * 1.8)
    needle_len = radius - arc_w + 10
    nx = cx + math.cos(angle) * needle_len
    ny = cy + math.sin(angle) * needle_len
    d.line([(cx, cy), (nx, ny)], fill=TEXT_WHITE, width=6)

    # Hub disk
    d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=HUB_BG, outline=TEXT_WHITE, width=3)


def _fmt_thai_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return iso or ""
    return f"ข้อมูล ณ {dt.strftime('%d %b %Y %H:%M UTC')}"


def render_fear_greed_card(data: dict | None) -> bytes | None:
    if not data:
        return None
    score = data.get("score")
    if score is None:
        return None

    label, current_color = _classify(score)
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # Title
    title = "Fear & Greed Index"
    title_font = _font(48, bold=True)
    tw = d.textlength(title, font=title_font)
    d.text(((W - tw) // 2, 70), title, font=title_font, fill=TEXT_WHITE)

    subtitle = "อารมณ์ที่ขับเคลื่อนตลาด"
    sub_font = _font(26)
    sw = d.textlength(subtitle, font=sub_font)
    d.text(((W - sw) // 2, 138), subtitle, font=sub_font, fill=TEXT_DIM)

    # Gauge
    cx, cy = W // 2, 510
    radius = 280
    arc_w = 56
    _draw_gauge(d, cx=cx, cy=cy, radius=radius, arc_w=arc_w, score=score)

    # Zone label markers under arc ends
    end_font = _font(18, bold=True)
    d.text((cx - radius - 4, cy + 14), "0", font=end_font, fill=TEXT_DIM)
    end_w = d.textlength("100", font=end_font)
    d.text((cx + radius - end_w + 4, cy + 14), "100", font=end_font, fill=TEXT_DIM)

    # Big score number below gauge
    score_str = f"{score:.0f}"
    score_font = _font(140, bold=True)
    sw2 = d.textlength(score_str, font=score_font)
    score_y = cy + 50
    d.text(((W - sw2) // 2, score_y), score_str, font=score_font, fill=current_color)

    # Status label
    status_font = _font(42, bold=True)
    lw = d.textlength(label, font=status_font)
    d.text(((W - lw) // 2, score_y + 165), label, font=status_font, fill=current_color)

    # Historical comparison
    history = [
        ("เมื่อวาน",    data.get("previous_close")),
        ("1 สัปดาห์",  data.get("previous_1_week")),
        ("1 เดือน",    data.get("previous_1_month")),
        ("1 ปี",       data.get("previous_1_year")),
    ]
    h_y0 = score_y + 250
    line_h = 56
    h_label_font = _font(26)
    h_value_font = _font(30, bold=True)
    h_status_font = _font(20, bold=True)
    pad_x = 60

    # Divider above
    d.line([(pad_x, h_y0 - 24), (W - pad_x, h_y0 - 24)], fill=(45, 45, 50, 255), width=1)

    for i, (lbl, val) in enumerate(history):
        y_row = h_y0 + i * line_h
        d.text((pad_x, y_row), lbl, font=h_label_font, fill=TEXT_DIM)
        if val is None:
            continue
        zone_label, zone_color = _classify(val)
        # right side: value then status
        st_w = d.textlength(zone_label, font=h_status_font)
        st_x = W - pad_x - st_w
        d.text((st_x, y_row + 6), zone_label, font=h_status_font, fill=zone_color)
        val_str = f"{val:.0f}"
        val_w = d.textlength(val_str, font=h_value_font)
        d.text((st_x - val_w - 20, y_row - 2), val_str, font=h_value_font, fill=TEXT_WHITE)

    # Timestamp footer
    ts_text = _fmt_thai_dt(data.get("timestamp", ""))
    if ts_text:
        ts_font = _font(20)
        tw3 = d.textlength(ts_text, font=ts_font)
        d.text(((W - tw3) // 2, H - 50), ts_text, font=ts_font, fill=TEXT_LABEL)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
