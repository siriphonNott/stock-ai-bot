"""CNN Fear & Greed Index — fetch + render gauge card."""
from __future__ import annotations

import io
import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFilter

from card import _font

log = logging.getLogger(__name__)

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Canvas
W, H = 720, 1280

# Palette (dark mode, glossy)
BG = (8, 10, 12, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_DIM = (140, 144, 150, 255)
TEXT_LABEL = (180, 184, 190, 255)
PETAL_DIM = (34, 36, 42, 255)
PETAL_RING = (52, 56, 64, 255)
DIAL_BG = (14, 16, 20, 255)
HUB_BG = (28, 30, 36, 255)
TICK = (110, 114, 120, 255)
DASH = (44, 48, 54, 255)

# Zone palette: (label, vivid color used for active fill / text, dimmed text color)
ZONE_EXTREME_FEAR = ("EXTREME FEAR", (231, 76, 60, 255),   (231, 76, 60, 235))
ZONE_FEAR          = ("FEAR",          (230, 126, 34, 255), (230, 126, 34, 235))
ZONE_NEUTRAL       = ("NEUTRAL",       (200, 200, 205, 255),(190, 190, 196, 235))
ZONE_GREED         = ("GREED",         (98, 220, 122, 255), (98, 220, 122, 235))
ZONE_EXTREME_GREED = ("EXTREME GREED", (40, 200, 130, 255), (40, 200, 130, 235))
ZONES = (ZONE_EXTREME_FEAR, ZONE_FEAR, ZONE_NEUTRAL, ZONE_GREED, ZONE_EXTREME_GREED)


def get_fear_greed_index() -> dict | None:
    try:
        r = requests.get(CNN_URL, headers={"User-Agent": UA}, timeout=10)
        if r.status_code != 200:
            return None
        return r.json().get("fear_and_greed")
    except Exception:
        log.exception("F&G fetch failed")
        return None


def _zone_index(score: float) -> int:
    if score < 25: return 0
    if score < 45: return 1
    if score < 55: return 2
    if score < 75: return 3
    return 4


def _zone(score: float) -> tuple[str, tuple, tuple]:
    return ZONES[_zone_index(score)]


def _paste_rotated_text(
    base: Image.Image,
    *,
    center: tuple[int, int],
    lines,
    font,
    fill: tuple,
    angle: float = 0.0,
) -> None:
    """Render text (single string or list of stacked lines), paste centered at
    `center`, rotated counter-clockwise by `angle`° as one composed block."""
    if isinstance(lines, str):
        lines = [lines]
    tmp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    sizes = []
    for ln in lines:
        bb = tmp_draw.textbbox((0, 0), ln, font=font)
        sizes.append((bb[2] - bb[0], bb[3] - bb[1], bb[0], bb[1]))
    max_w = max(s[0] for s in sizes)
    line_h = max(s[1] for s in sizes)
    gap = 6
    total_h = len(lines) * line_h + (len(lines) - 1) * gap
    pad = 12
    img = Image.new("RGBA", (max_w + pad * 2, total_h + pad * 2), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        tw, th, bx, by = sizes[i]
        x = pad + (max_w - tw) // 2 - bx
        y = pad + i * (line_h + gap) - by
        dr.text((x, y), ln, font=font, fill=fill)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    rw, rh = img.size
    base.alpha_composite(img, (center[0] - rw // 2, center[1] - rh // 2))


def _draw_gauge(base: Image.Image, *, cx: int, cy: int, score: float) -> None:
    score = max(0.0, min(100.0, float(score)))
    active = _zone_index(score)
    active_color = ZONES[active][1]

    # Radii
    r_active = 320
    r_inactive = 290
    r_inner_cut = 215
    r_dial = 198
    r_hub = 58

    d = ImageDraw.Draw(base, "RGBA")

    # 5 pie slices — active is bigger and bright; inactive is dim petal
    for i, (_, vivid, _) in enumerate(ZONES):
        start = 180 + i * 36
        end = 180 + (i + 1) * 36
        if i == active:
            d.pieslice(
                [cx - r_active, cy - r_active, cx + r_active, cy + r_active],
                start, end, fill=vivid,
            )
            # Subtle inner ring on the active segment, for definition
        else:
            d.pieslice(
                [cx - r_inactive, cy - r_inactive, cx + r_inactive, cy + r_inactive],
                start, end, fill=PETAL_DIM,
            )

    # Thin rings between segments — gives a "petal" feel
    for i in range(1, 5):
        ang = math.radians(180 + i * 36)
        r0 = r_inner_cut + 2
        r1 = (r_active if i == active or i - 1 == active else r_inactive) - 2
        x0 = cx + math.cos(ang) * r0
        y0 = cy + math.sin(ang) * r0
        x1 = cx + math.cos(ang) * r1
        y1 = cy + math.sin(ang) * r1
        d.line([(x0, y0), (x1, y1)], fill=BG, width=4)

    # Cut inner half-disk → makes the colored ring into a donut
    d.pieslice([cx - r_inner_cut, cy - r_inner_cut, cx + r_inner_cut, cy + r_inner_cut],
               180, 360, fill=BG)

    # Inner dial — darker disk inside the cut
    d.pieslice([cx - r_dial, cy - r_dial, cx + r_dial, cy + r_dial],
               180, 360, fill=DIAL_BG)
    # Dial rim — subtle outline
    d.arc([cx - r_dial, cy - r_dial, cx + r_dial, cy + r_dial],
          180, 360, fill=PETAL_RING, width=2)

    # Tick dots inside the dial (small dots every ~9°)
    r_ticks = r_dial - 22
    for i in range(21):  # 0..20 over 180°
        ang = math.radians(180 + i * 9)
        tx = cx + math.cos(ang) * r_ticks
        ty = cy + math.sin(ang) * r_ticks
        size = 4 if i % 5 == 0 else 2
        d.ellipse([tx - size / 2, ty - size / 2, tx + size / 2, ty + size / 2], fill=TICK)

    # Numeric labels inside dial at 25 / 50 / 75
    num_font = _font(20)
    for n, frac in ((25, 0.25), (50, 0.5), (75, 0.75)):
        ang = math.radians(180 + frac * 180)
        nx = cx + math.cos(ang) * (r_ticks - 28)
        ny = cy + math.sin(ang) * (r_ticks - 28)
        tw = d.textlength(str(n), font=num_font)
        d.text((nx - tw / 2, ny - 12), str(n), font=num_font, fill=TEXT_DIM)

    # 0 and 100 at the bottom outer ends
    end_font = _font(20)
    d.text((cx - r_active + 8, cy + 14), "0", font=end_font, fill=TEXT_DIM)
    end_w = d.textlength("100", font=end_font)
    d.text((cx + r_active - end_w - 8, cy + 14), "100", font=end_font, fill=TEXT_DIM)

    # Segment labels — inside each segment, rotated for the extreme ones
    label_font_big = _font(26, bold=True)
    label_font_extreme = _font(22, bold=True)
    label_r_mid = (r_inactive + r_inner_cut) / 2
    label_r_active = (r_active + r_inner_cut) / 2
    rotations = [60, 0, 0, 0, -60]  # degrees CCW
    for i, (label, vivid, _) in enumerate(ZONES):
        ang = math.radians(180 + (i + 0.5) * 36)
        is_active = (i == active)
        r = label_r_active if is_active else label_r_mid
        lx = cx + math.cos(ang) * r
        ly = cy + math.sin(ang) * r
        is_extreme = (i == 0 or i == 4)
        fill = TEXT_WHITE if is_active else vivid
        font = label_font_extreme if is_extreme else label_font_big
        lines = label.split() if is_extreme else label
        _paste_rotated_text(
            base, center=(int(lx), int(ly)),
            lines=lines, font=font, fill=fill, angle=rotations[i],
        )

    # Needle (bright, matches active zone)
    ang = math.radians(180 + score * 1.8)
    n_len = r_dial - 30
    nx = cx + math.cos(ang) * n_len
    ny = cy + math.sin(ang) * n_len
    d.line([(cx, cy), (nx, ny)], fill=active_color, width=6)

    # Glow under hub — radial blur
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_d = ImageDraw.Draw(glow_layer)
    glow_d.ellipse(
        [cx - r_hub * 2.2, cy - r_hub * 2.2, cx + r_hub * 2.2, cy + r_hub * 2.2],
        fill=(active_color[0], active_color[1], active_color[2], 90),
    )
    glow_blur = glow_layer.filter(ImageFilter.GaussianBlur(radius=22))
    base.alpha_composite(glow_blur)

    # Hub disk
    d = ImageDraw.Draw(base, "RGBA")
    d.ellipse([cx - r_hub, cy - r_hub, cx + r_hub, cy + r_hub], fill=HUB_BG,
              outline=PETAL_RING, width=2)

    # Score text inside hub
    score_str = f"{score:.0f}"
    score_font = _font(50, bold=True)
    sw = d.textlength(score_str, font=score_font)
    d.text((cx - sw / 2, cy - 35), score_str, font=score_font, fill=TEXT_WHITE)


def _draw_dashed_hline(d: ImageDraw.ImageDraw, x0: int, x1: int, y: int) -> None:
    x = x0
    while x < x1:
        d.line([(x, y), (min(x + 6, x1), y)], fill=DASH, width=1)
        x += 12


def _draw_history(d: ImageDraw.ImageDraw, base: Image.Image, *, y0: int, data: dict) -> int:
    history = [
        ("Previous close", data.get("previous_close")),
        ("1 week ago",     data.get("previous_1_week")),
        ("1 month ago",    data.get("previous_1_month")),
        ("1 year ago",     data.get("previous_1_year")),
    ]
    pad_x = 50
    row_h = 110
    label_font = _font(24)
    zone_font = _font(26, bold=True)
    num_font = _font(30, bold=True)
    circle_r = 36

    for i, (lbl, val) in enumerate(history):
        y = y0 + i * row_h
        # Label (top)
        d.text((pad_x, y + 22), lbl, font=label_font, fill=TEXT_LABEL)
        if val is None:
            continue
        zone_label, vivid, _ = _zone(val)
        # Zone name (below label) in zone color, lowercase capitalized like ref
        zone_disp = zone_label.title()
        d.text((pad_x, y + 56), zone_disp, font=zone_font, fill=vivid)

        # Right side: circle outline with value inside
        cx_r = W - pad_x - circle_r
        cy_r = y + row_h // 2
        d.ellipse(
            [cx_r - circle_r, cy_r - circle_r, cx_r + circle_r, cy_r + circle_r],
            outline=vivid, width=3,
        )
        val_str = f"{val:.0f}"
        vw = d.textlength(val_str, font=num_font)
        d.text((cx_r - vw / 2, cy_r - 22), val_str, font=num_font, fill=TEXT_WHITE)

        # Dashed connector from zone text to circle
        dash_x0 = pad_x + d.textlength(zone_disp, font=zone_font) + 20
        dash_x1 = cx_r - circle_r - 20
        _draw_dashed_hline(d, int(dash_x0), int(dash_x1), y + 70)

        # Bottom divider (except after last row)
        if i < len(history) - 1:
            d.line([(pad_x, y + row_h), (W - pad_x, y + row_h)], fill=DASH, width=1)

    return y0 + len(history) * row_h


def _fmt_et_footer(iso: str) -> str:
    """'Last updated May 18 at 3:11:29 PM ET' from a UTC ISO timestamp."""
    try:
        dt_utc = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return ""
    # %-I works on Linux/macOS; fall back to %I with strip if needed
    try:
        hour = dt_et.strftime("%-I")
    except ValueError:
        hour = dt_et.strftime("%I").lstrip("0") or "12"
    return f"Last updated {dt_et.strftime('%b %d')} at {hour}:{dt_et.strftime('%M:%S %p')} ET"


def render_fear_greed_card(data: dict | None) -> bytes | None:
    if not data:
        return None
    score = data.get("score")
    if score is None:
        return None

    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # Title — left-aligned, large bold
    pad_x = 50
    title_font = _font(56, bold=True)
    d.text((pad_x, 50), "Fear & Greed Index", font=title_font, fill=TEXT_WHITE)

    sub_font = _font(24)
    d.text((pad_x, 125), "What emotion is driving the market now?",
           font=sub_font, fill=TEXT_DIM)

    # Gauge — centered
    cx, cy = W // 2, 560
    _draw_gauge(img, cx=cx, cy=cy, score=score)

    # History rows
    d = ImageDraw.Draw(img, "RGBA")
    y_end = _draw_history(d, img, y0=cy + 220, data=data)

    # Footer
    footer = _fmt_et_footer(data.get("timestamp", ""))
    if footer:
        # tiny clock glyph + footer text
        f_font = _font(20)
        clock = "🕐"
        # PIL won't render emoji on most fonts; fall back to a circle bullet
        bullet = "○"
        d.ellipse([pad_x, H - 50, pad_x + 16, H - 34],
                  outline=TEXT_LABEL, width=2)
        d.text((pad_x + 26, H - 52), footer, font=f_font, fill=TEXT_LABEL)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
