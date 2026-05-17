"""Stock data fetcher using yfinance."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any

import yfinance as yf


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


@dataclass
class StockMetrics:
    symbol: str
    name: str | None
    currency: str
    price: float | None
    change: float | None
    change_pct: float | None
    market_cap: float | None
    eps: float | None
    pe: float | None
    pe_fwd: float | None
    bvps: float | None
    pb: float | None
    ps: float | None


def get_stock_metrics(symbol: str) -> StockMetrics | None:
    ticker = yf.Ticker(symbol)
    info = ticker.info or {}
    if not info.get("symbol") and not info.get("shortName"):
        return None
    price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    prev_close = _safe_float(info.get("regularMarketPreviousClose") or info.get("previousClose"))
    change = _safe_float(info.get("regularMarketChange"))
    if change is None and price is not None and prev_close is not None:
        change = price - prev_close
    change_pct = _safe_float(info.get("regularMarketChangePercent"))
    if change_pct is None and change is not None and prev_close:
        change_pct = change / prev_close * 100
    return StockMetrics(
        symbol=symbol.upper(),
        name=info.get("longName") or info.get("shortName"),
        currency=info.get("currency", "USD"),
        price=price,
        change=change,
        change_pct=change_pct,
        market_cap=_safe_float(info.get("marketCap")),
        eps=_safe_float(info.get("trailingEps")),
        pe=_safe_float(info.get("trailingPE")),
        pe_fwd=_safe_float(info.get("forwardPE")),
        bvps=_safe_float(info.get("bookValue")),
        pb=_safe_float(info.get("priceToBook")),
        ps=_safe_float(info.get("priceToSalesTrailing12Months")),
    )


def _row(df, row_name):
    if df is None or df.empty or row_name not in df.index:
        return None
    return df.loc[row_name]


def get_earnings_payload(symbol: str) -> dict | None:
    """Return a dict of raw earnings data for Claude to summarize.

    Includes all available quarters so Claude can detect record highs/trends."""
    ticker = yf.Ticker(symbol)

    income = ticker.quarterly_income_stmt
    if income is None or income.empty:
        return None

    revenue = _row(income, "Total Revenue")
    gross_profit = _row(income, "Gross Profit")
    op_income = _row(income, "Operating Income")
    net_income = _row(income, "Net Income")

    def series_to_list(s):
        if s is None:
            return []
        return [
            {"period": str(p.date()) if hasattr(p, "date") else str(p), "value": _safe_float(v)}
            for p, v in s.items()
        ]

    balance = ticker.quarterly_balance_sheet
    cash_series = _row(balance, "Cash And Cash Equivalents")
    debt_series = _row(balance, "Total Debt")
    equity_series = _row(balance, "Stockholders Equity")

    # Earnings surprise (latest reported quarter)
    eps_surprise = None
    try:
        ed = ticker.earnings_dates
        if ed is not None and not ed.empty and "Reported EPS" in ed.columns:
            past = ed.dropna(subset=["Reported EPS"])
            if not past.empty:
                row = past.iloc[0]
                eps_surprise = {
                    "date": str(row.name.date()) if hasattr(row.name, "date") else str(row.name),
                    "estimate": _safe_float(row.get("EPS Estimate")),
                    "reported": _safe_float(row.get("Reported EPS")),
                    "surprise_pct": _safe_float(row.get("Surprise(%)")),
                }
    except Exception:
        pass

    return {
        "symbol": symbol.upper(),
        "currency": (ticker.info or {}).get("currency", "USD"),
        "quarterly_revenue": series_to_list(revenue),
        "quarterly_gross_profit": series_to_list(gross_profit),
        "quarterly_operating_income": series_to_list(op_income),
        "quarterly_net_income": series_to_list(net_income),
        "quarterly_cash": series_to_list(cash_series),
        "quarterly_total_debt": series_to_list(debt_series),
        "quarterly_equity": series_to_list(equity_series),
        "latest_eps_surprise": eps_surprise,
    }


LABEL_W = 11
VALUE_W = 11


CURRENCY_SYMBOLS = {"USD": "$", "THB": "฿", "EUR": "€", "GBP": "£", "JPY": "¥"}


def format_metrics(m: StockMetrics) -> str:
    import html

    cur = CURRENCY_SYMBOLS.get(m.currency, "")

    def money(v):
        return f"{cur}{v:,.2f}" if v is not None else "-"

    def num(v):
        return f"{v:,.2f}" if v is not None else "-"

    rows: list[tuple[str, str, str]] = [
        ("Price", money(m.price), "ราคาปัจจุบัน"),
        ("EPS", money(m.eps), "บริษัททำเงินได้จริงไหม"),
        ("P/E", num(m.pe), "หุ้นแพง/ถูกเทียบกำไร"),
        ("P/E (FWD)", num(m.pe_fwd), "ตลาดคาดหวังอนาคต"),
        ("BVPS", money(m.bvps), "มูลค่าทรัพย์สินจริง"),
        ("P/B", num(m.pb), "แพงกว่าทรัพย์สินกี่เท่า"),
        ("P/S", num(m.ps), "แพงเมื่อเทียบรายได้"),
    ]
    body = "\n".join(f"{lbl:<{LABEL_W}}{val:<{VALUE_W}}{desc}" for lbl, val, desc in rows)
    name = html.escape(m.name) if m.name else ""
    name_line = f" — {name}" if name else ""
    return f"📊 <b>{m.symbol}</b>{name_line}\n<pre>{body}</pre>"
