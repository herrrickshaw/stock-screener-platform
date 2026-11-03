"""Shared Coffee Can helpers (series extraction and the revenue-CAGR / no-loss-year criteria)."""
from __future__ import annotations

import pandas as pd


def series(df, *rows) -> list:
    """Floats for the first matching statement row, most recent year first ([] if none match)."""
    for name in rows:
        if df is not None and name in df.index:
            return [float(v) for v in df.loc[name].dropna() if pd.notna(v)]
    return []


def revenue_cagr_criterion(inc, key: str) -> tuple[dict, dict]:
    """C1: revenue CAGR > 10% over the available history -> (criteria, details)."""
    revs = series(inc, "Total Revenue")
    if len(revs) >= 2:
        years = len(revs) - 1   # revs[0] = most recent, revs[-1] = oldest
        cagr = ((revs[0] / revs[-1]) ** (1 / years) - 1) * 100 if revs[-1] > 0 else None
        return ({key: 1 if (cagr and cagr > 10) else 0},
                {"Revenue_CAGR_%": round(cagr, 2) if cagr else "N/A", "Revenue_years": years})
    return {key: 0}, {"Revenue_CAGR_%": "N/A"}


def no_loss_year_criterion(ni_s: list) -> tuple[dict, dict]:
    """C5: every analysed fiscal year profitable -> (criteria, details)."""
    if ni_s:
        return ({"C5_NoProfitLoss": 1 if all(n > 0 for n in ni_s) else 0},
                {"Loss_years": sum(1 for n in ni_s if n <= 0), "Years_analysed": len(ni_s)})
    return {"C5_NoProfitLoss": 0}, {}


def debt_to_equity_criterion(info: dict, bal, eq_s: list, abs_equity: bool) -> tuple[dict, dict]:
    """C3: D/E < 1 from yfinance info (percent-normalised), else long-term debt over equity."""
    de_raw = info.get("debtToEquity")
    if de_raw is not None:
        de = de_raw / 100 if de_raw > 10 else de_raw
        return {"C3_LowDebt": 1 if de < 1 else 0}, {"Debt_to_Equity": round(de, 2)}
    ltd_s = series(bal, "Long Term Debt")
    if ltd_s and eq_s and eq_s[0] != 0:
        de = ltd_s[0] / (abs(eq_s[0]) if abs_equity else eq_s[0])
        return {"C3_LowDebt": 1 if de < 1 else 0}, {"Debt_to_Equity": round(de, 2)}
    return {"C3_LowDebt": 0}, {"Debt_to_Equity": "N/A"}
