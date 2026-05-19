"""Stock report card — dark portrait UI with stacked info sections."""
from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw

from card import _font, _round_logo
from summarizer import _graham_fair_value, _pct, _quarter_label, _roic
from stock import StockMetrics

# ────────────────────────── layout ──────────────────────────

W = 720
TOP_PAD = 20
BOTTOM_PAD = 20
SIDE_PAD = 20
CARD_GAP = 14
CARD_RADIUS = 16
INNER_PAD_X = 24
INNER_PAD_Y = 22

# ────────────────────────── palette ──────────────────────────

BG               = (10, 11, 14, 255)         # main canvas
CARD_BG          = (22, 24, 28, 255)         # card container
CARD_BORDER      = (40, 44, 52, 255)
INNER_BG         = (32, 34, 40, 255)         # stat box / pill bg
DIVIDER          = (40, 42, 48, 255)

TEXT_PRIMARY     = (240, 242, 246, 255)
TEXT_SECONDARY   = (150, 154, 162, 255)
TEXT_LABEL       = (122, 128, 138, 255)

GREEN            = (29, 178, 130, 255)       # +/up
RED              = (235, 78, 78, 255)        # −/down
AMBER            = (210, 140, 40, 255)       # caution

BADGE_OVER_BG    = (252, 235, 235, 255)
BADGE_OVER_TEXT  = (163, 45, 45, 255)
BADGE_UNDER_BG   = (231, 245, 238, 255)
BADGE_UNDER_TEXT = (29, 110, 79, 255)

CURRENCY_SYMBOLS = {"USD": "$", "THB": "฿", "EUR": "€", "GBP": "£", "JPY": "¥"}


# ────────────────────────── format helpers ──────────────────────────

def _values(s: list | None) -> list[float]:
    return [x["value"] for x in (s or []) if x.get("value") is not None]


def _fmt_m(v: float | None, cur: str = "$") -> str | None:
    if v is None:
        return None
    a = abs(v)
    if a >= 1e9:
        body = f"{a / 1e9:,.2f}B"
    elif a >= 1e6:
        body = f"{a / 1e6:,.1f}M"
    elif a >= 1e3:
        body = f"{a / 1e3:,.1f}K"
    else:
        body = f"{a:,.0f}"
    return f"-{cur}{body}" if v < 0 else f"{cur}{body}"


def _fmt_pct_yoy(curr: float | None, prev: float | None) -> str | None:
    p = _pct(curr, prev)
    if p is None:
        return None
    emoji = " 🔥" if p >= 30 else ""
    return f"{p:+.0f}% YoY{emoji}"


def _wrap(text: str, font: Any, max_w: int, d: ImageDraw.ImageDraw) -> list[str]:
    """Greedy wrap. Falls back to char-wrap for long Thai-without-spaces runs."""
    if not text:
        return []
    out: list[str] = []
    cur = ""
    for w in text.split(" "):
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            out.append(cur)
        if d.textlength(w, font=font) > max_w:
            buf = ""
            for ch in w:
                if d.textlength(buf + ch, font=font) > max_w:
                    if buf:
                        out.append(buf)
                    buf = ch
                else:
                    buf += ch
            cur = buf
        else:
            cur = w
    if cur:
        out.append(cur)
    return out


# ────────────────────────── primitive draws ──────────────────────────

def _container(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int) -> None:
    d.rounded_rectangle([x0, y0, x1, y1], radius=CARD_RADIUS, fill=CARD_BG)
    d.rounded_rectangle(
        [x0, y0, x1, y1], radius=CARD_RADIUS, outline=CARD_BORDER, width=1,
    )


def _pill(
    d: ImageDraw.ImageDraw, x: float, y: float, text: str, font: Any, *,
    fill: tuple, text_color: tuple,
    pad_x: int = 10, pad_y: int = 4, radius: int = 4,
) -> tuple[int, int]:
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    w = tw + pad_x * 2
    h = th + pad_y * 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill)
    d.text((x + pad_x - bb[0], y + pad_y - bb[1]), text, font=font, fill=text_color)
    return w, h


def _row(
    d: ImageDraw.ImageDraw, x0: int, x1: int, y: int,
    label: str, value: str, value_color: tuple,
) -> int:
    f_lbl = _font(20)
    f_val = _font(22, bold=True)
    d.text((x0, y), label, font=f_lbl, fill=TEXT_SECONDARY)
    vw = int(d.textlength(value, font=f_val))
    d.text((x1 - vw, y - 2), value, font=f_val, fill=value_color)
    return y + 34


def _hline(d: ImageDraw.ImageDraw, x0: int, x1: int, y: int) -> None:
    d.line([(x0, y), (x1, y)], fill=DIVIDER, width=1)


def _section_title(d: ImageDraw.ImageDraw, x: int, y: int, text: str) -> int:
    f = _font(15, bold=True)
    d.text((x, y), text.upper(), font=f, fill=TEXT_LABEL)
    return y + 30


# ────────────────────────── card heights ──────────────────────────

def _h_company(d, description, tags, inner_w) -> int:
    h = INNER_PAD_Y * 2 + 60 + 20  # padding + logo block
    if description:
        f = _font(20)
        lines = _wrap(description, f, inner_w, d)[:3]
        h += len(lines) * 30 + 6
    if tags:
        h += 40
    return h


def _h_price(payload) -> int:
    h = INNER_PAD_Y * 2 + 32 + 56  # header + price row
    if payload:
        targets = [t for t in (payload.get("target_low"), payload.get("target_mean"),
                               payload.get("target_median")) if t and t > 0]
        if targets or (payload.get("eps") and payload.get("bvps")):
            h += 30
    return h


def _h_valuation(metrics: StockMetrics) -> int:
    h = INNER_PAD_Y * 2 + 30  # padding + title
    if metrics.eps is not None:
        h += 34
    h += 14  # divider + spacing
    for v in (metrics.pe, metrics.pe_fwd, metrics.pb, metrics.ps, metrics.bvps):
        if v is not None:
            h += 34
    return h


def _h_qresults(payload) -> int:
    if not payload:
        return 0
    rev = _values(payload.get("quarterly_revenue"))
    if not rev:
        return 0
    h = INNER_PAD_Y * 2 + 30  # padding + title
    cells = 0
    for k in ("quarterly_revenue", "quarterly_gross_profit",
              "quarterly_operating_income", "quarterly_net_income"):
        if _values(payload.get(k)):
            cells += 1
    rows = (cells + 1) // 2
    h += rows * 102 - 12  # box_h=92 + gap=12, then minus last gap (we add gap)
    h += 12 + 16          # gap + divider+space
    op = _values(payload.get("quarterly_operating_income"))
    ni = _values(payload.get("quarterly_net_income"))
    if op and rev[0]:
        h += 34
    eq = _values(payload.get("quarterly_equity"))
    if ni and eq:
        h += 34
    return h


def _h_balance(payload) -> int:
    if not payload:
        return 0
    cash = _values(payload.get("quarterly_cash"))
    debt = _values(payload.get("quarterly_total_debt"))
    if not (cash or debt):
        return 0
    h = INNER_PAD_Y * 2 + 30  # padding + title
    if cash:
        h += 34
    if debt:
        h += 34
    if cash and debt:
        h += 34
    return h


# ────────────────────────── card content drawers ──────────────────────────

def _draw_company(
    img: Image.Image, d: ImageDraw.ImageDraw,
    x0: int, x1: int, y0: int, *,
    metrics: StockMetrics, sector: str | None,
    description: str | None, tags: list[str] | None, logo: Image.Image | None,
) -> None:
    ix0 = x0 + INNER_PAD_X
    ix1 = x1 - INNER_PAD_X
    y = y0 + INNER_PAD_Y

    ls = 60
    if logo is not None:
        img.alpha_composite(_round_logo(logo, ls), (ix0, y))
    else:
        d.rounded_rectangle(
            [ix0, y, ix0 + ls, y + ls], radius=14, fill=INNER_BG,
        )

    nx = ix0 + ls + 16
    name = metrics.name or metrics.symbol
    d.text((nx, y + 2), name, font=_font(28, bold=True), fill=TEXT_PRIMARY)

    parts = [metrics.symbol]
    if metrics.exchange_name:
        parts.append(metrics.exchange_name)
    if sector or metrics.sector:
        parts.append(sector or metrics.sector)
    d.text(
        (nx, y + 38),
        " · ".join(parts), font=_font(18), fill=TEXT_SECONDARY,
    )

    y += ls + 20

    if description:
        f = _font(20)
        for ln in _wrap(description, f, ix1 - ix0, d)[:3]:
            d.text((ix0, y), ln, font=f, fill=TEXT_SECONDARY)
            y += 30
        y += 6

    if tags:
        f_tag = _font(17)
        tx = ix0
        for t in tags[:4]:
            if tx + 100 > ix1:
                break
            w, _ = _pill(
                d, tx, y, t, f_tag,
                fill=INNER_BG, text_color=TEXT_SECONDARY,
                pad_x=14, pad_y=7, radius=20,
            )
            tx += w + 8


def _draw_price(
    d: ImageDraw.ImageDraw, x0: int, x1: int, y0: int, *,
    metrics: StockMetrics, payload: dict | None, cur: str,
) -> None:
    ix0 = x0 + INNER_PAD_X
    ix1 = x1 - INNER_PAD_X
    y = y0 + INNER_PAD_Y

    f_h = _font(18)
    d.text((ix0, y), "Stock Report", font=f_h, fill=TEXT_SECONDARY)

    if payload and (payload.get("quarterly_revenue") or []):
        period = payload["quarterly_revenue"][0].get("period", "")
        ql = _quarter_label(period)
        qw = d.textlength(ql, font=f_h)
        d.text((ix1 - qw, y), ql, font=f_h, fill=TEXT_SECONDARY)

    y += 32

    price = metrics.price
    f_p = _font(42, bold=True)
    p_str = f"{cur}{price:,.2f}" if price is not None else "-"
    d.text((ix0, y), p_str, font=f_p, fill=TEXT_PRIMARY)
    pw = int(d.textlength(p_str, font=f_p))

    fair = None
    if payload:
        targets = [t for t in (payload.get("target_low"), payload.get("target_mean"),
                               payload.get("target_median")) if t and t > 0]
        if targets:
            fair = sum(targets) / len(targets)
        else:
            fair = _graham_fair_value(metrics.eps, metrics.bvps)

    if fair is not None and price:
        diff = (fair - price) / price * 100
        kind = "under" if diff > 0 else "over"
        pct = abs(diff)
        text = f"{'Undervalued' if kind == 'under' else 'Overvalued'} {pct:.0f}%"
        bg = BADGE_UNDER_BG if kind == "under" else BADGE_OVER_BG
        tc = BADGE_UNDER_TEXT if kind == "under" else BADGE_OVER_TEXT
        _pill(
            d, ix0 + pw + 14, y + 16, text, _font(15, bold=True),
            fill=bg, text_color=tc, pad_x=10, pad_y=4, radius=6,
        )

    y += 56
    if fair is not None:
        d.text(
            (ix0, y), f"Fair price: {cur}{fair:,.2f}",
            font=_font(18), fill=TEXT_SECONDARY,
        )


def _draw_valuation(
    d: ImageDraw.ImageDraw, x0: int, x1: int, y0: int, *,
    metrics: StockMetrics, cur: str,
) -> None:
    ix0 = x0 + INNER_PAD_X
    ix1 = x1 - INNER_PAD_X
    y = _section_title(d, ix0, y0 + INNER_PAD_Y, "Valuation")

    eps = metrics.eps
    if eps is not None:
        if eps < 0:
            eps_str = f"-{cur}{abs(eps):.2f} (ขาดทุน)"
            col = RED
        else:
            eps_str = f"{cur}{eps:.2f}"
            col = TEXT_PRIMARY
        y = _row(d, ix0, ix1, y, "EPS", eps_str, col)

    _hline(d, ix0, ix1, y + 4)
    y += 14

    def col_for(v: float | None, hi: float, hi2: float = 0) -> tuple:
        if v is None:
            return TEXT_PRIMARY
        if hi2 and v >= hi2:
            return RED
        return AMBER if v >= hi else TEXT_PRIMARY

    if metrics.pe is not None:
        y = _row(d, ix0, ix1, y, "P/E (Trailing)",
                 f"{metrics.pe:.0f}x", col_for(metrics.pe, 20))
    if metrics.pe_fwd is not None:
        y = _row(d, ix0, ix1, y, "P/E (Forward)",
                 f"{metrics.pe_fwd:.2f}x", col_for(metrics.pe_fwd, 20))
    if metrics.pb is not None:
        y = _row(d, ix0, ix1, y, "P/B",
                 f"{metrics.pb:.2f}x", col_for(metrics.pb, 3))
    if metrics.ps is not None:
        y = _row(d, ix0, ix1, y, "P/S",
                 f"{metrics.ps:.2f}x", col_for(metrics.ps, 5))
    if metrics.bvps is not None:
        y = _row(d, ix0, ix1, y, "BVPS",
                 f"{cur}{metrics.bvps:.2f}", TEXT_PRIMARY)


def _draw_qresults(
    d: ImageDraw.ImageDraw, x0: int, x1: int, y0: int, *,
    payload: dict | None, cur: str,
) -> None:
    if not payload:
        return
    rev = _values(payload.get("quarterly_revenue"))
    if not rev:
        return
    ix0 = x0 + INNER_PAD_X
    ix1 = x1 - INNER_PAD_X
    y = y0 + INNER_PAD_Y

    period = payload["quarterly_revenue"][0].get("period", "")
    ql = _quarter_label(period)
    y = _section_title(d, ix0, y, f"ผลประกอบการ {ql}")

    gp = _values(payload.get("quarterly_gross_profit"))
    op = _values(payload.get("quarterly_operating_income"))
    ni = _values(payload.get("quarterly_net_income"))

    def cell(arr: list[float], label: str) -> dict | None:
        if not arr:
            return None
        v0 = arr[0]
        return {
            "label": label,
            "value": _fmt_m(v0, cur),
            "color": GREEN if v0 >= 0 else RED,
            "tag": (
                _fmt_pct_yoy(v0, arr[4])
                if len(arr) > 4
                else (
                    f"vs {_fmt_m(arr[4], cur)} ปีก่อน"
                    if False
                    else ""
                )
            ),
        }

    cells = [c for c in (
        cell(rev, "Total Revenue"),
        cell(gp,  "Gross Income"),
        cell(op,  "Operating Income"),
        cell(ni,  "Net Income (GAAP)"),
    ) if c]

    # Special override: Net Income tag shows "vs <prev> ปีก่อน" instead of %
    if ni and len(ni) > 4 and cells:
        for c in cells:
            if c["label"] == "Net Income (GAAP)":
                c["tag"] = f"vs {_fmt_m(ni[4], cur)} ปีก่อน"

    gap = 12
    box_w = (ix1 - ix0 - gap) // 2
    box_h = 92
    for i, c in enumerate(cells):
        row_i = i // 2
        col_i = i % 2
        bx = ix0 + col_i * (box_w + gap)
        by = y + row_i * (box_h + gap)
        d.rounded_rectangle(
            [bx, by, bx + box_w, by + box_h], radius=10, fill=INNER_BG,
        )
        pad = 12
        d.text(
            (bx + pad, by + pad),
            c["label"], font=_font(15), fill=TEXT_LABEL,
        )
        d.text(
            (bx + pad, by + pad + 22),
            c["value"], font=_font(22, bold=True), fill=c["color"],
        )
        if c["tag"]:
            d.text(
                (bx + pad, by + box_h - pad - 18),
                c["tag"], font=_font(14), fill=TEXT_SECONDARY,
            )

    rows = (len(cells) + 1) // 2
    y += rows * (box_h + gap) - gap

    y += 12
    _hline(d, ix0, ix1, y)
    y += 12

    if op and rev[0]:
        margin = op[0] / rev[0] * 100
        col = RED if margin < 0 else GREEN
        y = _row(d, ix0, ix1, y, "Operating Margin", f"{margin:+.1f}%", col)

    debt = _values(payload.get("quarterly_total_debt"))
    eq = _values(payload.get("quarterly_equity"))
    if ni and eq:
        roic = _roic(ni[0], debt[0] if debt else None, eq[0])
        if roic is not None:
            col = RED if roic < 0 else (AMBER if roic < 8 else GREEN)
            y = _row(d, ix0, ix1, y, "ROIC", f"{roic:+.1f}%", col)


def _draw_balance(
    d: ImageDraw.ImageDraw, x0: int, x1: int, y0: int, *,
    payload: dict | None, cur: str,
) -> None:
    if not payload:
        return
    cash = _values(payload.get("quarterly_cash"))
    debt = _values(payload.get("quarterly_total_debt"))
    if not (cash or debt):
        return
    ix0 = x0 + INNER_PAD_X
    ix1 = x1 - INNER_PAD_X
    y = _section_title(d, ix0, y0 + INNER_PAD_Y, "ฐานะการเงิน")

    if cash:
        y = _row(d, ix0, ix1, y, "Cash", _fmt_m(cash[0], cur), GREEN)
    if debt:
        y = _row(d, ix0, ix1, y, "Debt", _fmt_m(debt[0], cur), RED)
    if cash and debt:
        nc = cash[0] - debt[0]
        s = ("+" if nc >= 0 else "") + (_fmt_m(nc, cur) or "")
        y = _row(d, ix0, ix1, y, "Net Cash", s, GREEN if nc >= 0 else RED)


# ────────────────────────── public renderer ──────────────────────────

def render_stock_report_card(
    metrics: StockMetrics, payload: dict | None, *,
    sector: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    logo: Image.Image | None = None,
) -> bytes | None:
    if not metrics:
        return None
    cur = CURRENCY_SYMBOLS.get(metrics.currency, "$")

    # Dummy draw context for measuring text wraps
    dummy = Image.new("RGBA", (W, 100), BG)
    dd = ImageDraw.Draw(dummy, "RGBA")
    inner_w = W - 2 * SIDE_PAD - 2 * INNER_PAD_X

    sections = [
        ("company", _h_company(dd, description, tags, inner_w)),
        ("price",   _h_price(payload)),
        ("val",     _h_valuation(metrics)),
        ("q",       _h_qresults(payload)),
        ("bal",     _h_balance(payload)),
    ]
    sections = [(name, h) for name, h in sections if h > 0]

    total_h = TOP_PAD + BOTTOM_PAD
    for _, h in sections:
        total_h += h + CARD_GAP
    total_h -= CARD_GAP

    img = Image.new("RGBA", (W, total_h), BG)
    d = ImageDraw.Draw(img, "RGBA")
    x0 = SIDE_PAD
    x1 = W - SIDE_PAD

    y = TOP_PAD
    for name, h in sections:
        _container(d, x0, y, x1, y + h)
        if name == "company":
            _draw_company(
                img, d, x0, x1, y,
                metrics=metrics, sector=sector,
                description=description, tags=tags, logo=logo,
            )
        elif name == "price":
            _draw_price(d, x0, x1, y, metrics=metrics, payload=payload, cur=cur)
        elif name == "val":
            _draw_valuation(d, x0, x1, y, metrics=metrics, cur=cur)
        elif name == "q":
            _draw_qresults(d, x0, x1, y, payload=payload, cur=cur)
        elif name == "bal":
            _draw_balance(d, x0, x1, y, payload=payload, cur=cur)
        y += h + CARD_GAP

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
