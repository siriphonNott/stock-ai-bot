"""Earnings summary formatter — computed deterministically in Python.

Outputs Telegram HTML <pre> code block for reliable rendering.
"""
from __future__ import annotations

from datetime import date, datetime


LABEL_W = 20
VALUE_W = 13

CURRENCY_SYMBOLS = {"USD": "$", "THB": "฿", "EUR": "€", "GBP": "£", "JPY": "¥"}


def _to_date(s: str) -> date | None:
    try:
        return datetime.fromisoformat(s).date()
    except (TypeError, ValueError):
        return None


def _quarter_label(period: str) -> str:
    d = _to_date(period)
    if d is None:
        return period or ""
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"


def _values(series: list[dict]) -> list[float]:
    return [s["value"] for s in (series or []) if s.get("value") is not None]


def _pct(curr: float | None, prev: float | None) -> float | None:
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100


def _fmt_m(v: float | None, cur: str = "$") -> str | None:
    if v is None:
        return None
    return f"{cur}{v / 1_000_000:,.1f}M"


def _fmt_pct_signed(v: float | None) -> str | None:
    if v is None:
        return None
    return f"{v:+.0f}%"


def _is_record(series: list[float]) -> bool:
    return bool(series) and series[0] == max(series)


def _row(label: str, value: str | None, notes: str = "", hot: bool = False) -> str | None:
    if value is None:
        return None
    line = f"{label:<{LABEL_W}}{value:<{VALUE_W}}{notes}".rstrip()
    if hot:
        line += " 🔥 Record High"
    return line


def _yoy_qoq_notes(vals: list[float]) -> str:
    yoy = _fmt_pct_signed(_pct(vals[0] if vals else None, vals[4] if len(vals) > 4 else None))
    qoq = _fmt_pct_signed(_pct(vals[0] if vals else None, vals[1] if len(vals) > 1 else None))
    parts = []
    if yoy:
        parts.append(f"{yoy} YoY")
    if qoq:
        parts.append(f"{qoq} QoQ")
    return f"({', '.join(parts)})" if parts else ""


def _roic(ni: float | None, debt: float | None, equity: float | None) -> float | None:
    if ni is None or equity is None:
        return None
    invested = (debt or 0) + equity
    if invested <= 0:
        return None
    return ni * 4 / invested * 100  # annualized from quarterly NI


def summarize_earnings(payload: dict) -> str:
    if not payload:
        return ""

    rev = _values(payload.get("quarterly_revenue") or [])
    gp = _values(payload.get("quarterly_gross_profit") or [])
    op = _values(payload.get("quarterly_operating_income") or [])
    ni = _values(payload.get("quarterly_net_income") or [])
    cash = _values(payload.get("quarterly_cash") or [])
    debt = _values(payload.get("quarterly_total_debt") or [])
    eq = _values(payload.get("quarterly_equity") or [])
    eps_s = payload.get("latest_eps_surprise") or {}
    cur = CURRENCY_SYMBOLS.get(payload.get("currency", "USD"), "$")

    if not rev:
        return ""

    period = (payload.get("quarterly_revenue") or [{}])[0].get("period", "")
    header = f"📈 ผลประกอบการ {_quarter_label(period)}"
    lines: list[str] = []

    # Total Revenue
    r = _row("Total Revenue", _fmt_m(rev[0], cur), _yoy_qoq_notes(rev), _is_record(rev))
    if r:
        lines.append(r)

    # Total Income (Gross Profit)
    if gp:
        g = _row("Total Income", _fmt_m(gp[0], cur), _yoy_qoq_notes(gp), _is_record(gp))
        if g:
            lines.append(g)

    # Operating Income
    if op:
        o = _row("Operating Income", _fmt_m(op[0], cur), _yoy_qoq_notes(op), _is_record(op))
        if o:
            lines.append(o)

    # Operating Margin
    margin_now = (op[0] / rev[0] * 100) if op and rev[0] else None
    margin_prev = (op[4] / rev[4] * 100) if len(op) > 4 and len(rev) > 4 and rev[4] else None
    if margin_now is not None:
        notes = f"(vs {margin_prev:.1f}% last year)" if margin_prev is not None else ""
        m = _row("Operating Margin", f"{margin_now:.1f}%", notes)
        if m:
            lines.append(m)

    # Non-GAAP EPS
    eps_reported = eps_s.get("reported")
    eps_est = eps_s.get("estimate")
    eps_pct = eps_s.get("surprise_pct")
    if eps_reported is not None:
        if eps_est is not None and eps_pct is not None:
            eps_notes = (
                f"(Beat Est. {cur}{eps_est:.2f} by {eps_pct:.0f}%)"
                if eps_pct >= 0
                else f"(Miss Est. {cur}{eps_est:.2f} by {abs(eps_pct):.0f}%)"
            )
        elif eps_est is not None:
            eps_notes = f"(Est. {cur}{eps_est:.2f})"
        else:
            eps_notes = ""
        e = _row("Non-GAAP EPS", f"{cur}{eps_reported:.2f}", eps_notes)
        if e:
            lines.append(e)

    # GAAP Net Income
    if ni:
        prev_ni = ni[4] if len(ni) > 4 else None
        notes = f"(vs {_fmt_m(prev_ni, cur)} last year)" if prev_ni is not None else ""
        n = _row("GAAP Net Income", _fmt_m(ni[0], cur), notes, _is_record(ni))
        if n:
            lines.append(n)

    # ROIC
    roic_now = _roic(ni[0] if ni else None, debt[0] if debt else None, eq[0] if eq else None)
    roic_prev = _roic(
        ni[4] if len(ni) > 4 else None,
        debt[4] if len(debt) > 4 else None,
        eq[4] if len(eq) > 4 else None,
    )
    if roic_now is not None:
        notes = f"(vs {roic_prev:.1f}% last year)" if roic_prev is not None else ""
        ro = _row("ROIC", f"{roic_now:.1f}%", notes)
        if ro:
            lines.append(ro)

    # Cash Position
    if cash:
        c = _row("Cash Position", _fmt_m(cash[0], cur))
        if c:
            lines.append(c)

    # Debt
    if debt:
        debt_val = debt[0]
        if debt_val <= 1_000_000:
            d = _row("Debt", "None")
        else:
            d = _row("Debt", _fmt_m(debt_val, cur))
        if d:
            lines.append(d)

    if not lines:
        return ""

    body = "\n".join([header, *lines])
    return f"<pre>{body}</pre>"
