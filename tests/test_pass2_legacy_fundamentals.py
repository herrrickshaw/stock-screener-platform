"""Characterisation tests (pass 2): legacy Piotroski / Coffee Can scorers with fake yfinance tickers."""
from __future__ import annotations

import types

import numpy as np
import pandas as pd
import pytest
from golden_util import check
from legacy_loader import load_script

INC = ["Net Income", "Total Revenue", "Gross Profit", "EBIT"]
BAL = ["Total Assets", "Long Term Debt", "Current Assets", "Current Liabilities", "Share Issued", "Stockholders Equity"]
CF = ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"]


def _frame(rows, rng, ncols, scale, drop=()):
    data = {r: rng.uniform(0.5, 2.0, ncols) * scale for r in rows if r not in drop}
    cols = pd.to_datetime([f"{2025 - i}-03-31" for i in range(ncols)])
    return pd.DataFrame(data, index=cols).T


def _ticker(seed, ncols=4, drop_inc=(), drop_bal=(), drop_cf=(), info=None, losses=False, fast_cap=None):
    rng = np.random.default_rng(seed)
    inc = _frame(INC, rng, ncols, 1e9, drop_inc)
    if losses and "Net Income" in inc.index:
        inc.loc["Net Income"] = inc.loc["Net Income"] * [1, -1, 1, 1][:ncols]
    bal = _frame(BAL, rng, ncols, 1e9, drop_bal)
    cf = _frame(CF, rng, ncols, 1e8, drop_cf)
    ns = types.SimpleNamespace(income_stmt=None, financials=inc, balance_sheet=bal, cash_flow=None, cashflow=cf,
                               info=info if info is not None else {"debtToEquity": 45.0, "marketCap": 2e9,
                                                                     "sharesOutstanding": 1e8})
    ns.fast_info = types.SimpleNamespace(market_cap=fast_cap)
    return ns


def _cases():
    return {
        "full": _ticker(1), "full2": _ticker(2), "full3": _ticker(3), "two_cols": _ticker(4, ncols=2),
        "one_col": _ticker(5, ncols=1), "no_gross": _ticker(6, drop_inc=("Gross Profit",)),
        "no_bal": _ticker(7, drop_bal=("Total Assets", "Share Issued")), "no_cf": _ticker(8, drop_cf=CF),
        "no_fcf": _ticker(9, drop_cf=("Free Cash Flow",)), "losses": _ticker(10, losses=True),
        "no_info": _ticker(11, info={}), "de_small": _ticker(12, info={"debtToEquity": 0.4, "marketCap": 8e8}),
        "fast_cap": _ticker(13, info={}, fast_cap=5e9), "no_inc": _ticker(14, drop_inc=INC),
        "no_ltd": _ticker(15, drop_bal=("Long Term Debt",), info={}),
    }


@pytest.fixture
def india(tmp_path, monkeypatch):
    mod = load_script("stock_daily_report_improved", tmp_path, monkeypatch)
    return mod


@pytest.fixture
def us(tmp_path, monkeypatch):
    return load_script("us_stock_daily_report", tmp_path, monkeypatch)


def _india_run(mod, fn, ticker, monkeypatch):
    monkeypatch.setattr(mod, "YFINANCE_OK", True, raising=False)
    monkeypatch.setattr(mod, "yf", types.SimpleNamespace(Ticker=lambda sym: ticker), raising=False)
    return fn("SYM")


@pytest.mark.parametrize("kind", ["piotroski", "coffee_can"])
def test_india_scorers(india, kind, monkeypatch):
    fn = getattr(india, f"compute_{kind}" + ("_score" if kind == "piotroski" else ""))
    check(f"legacy_india_{kind}", {k: _india_run(india, fn, t, monkeypatch) for k, t in _cases().items()})


@pytest.mark.parametrize("kind", ["piotroski", "coffee_can"])
def test_us_scorers(us, kind):
    fn = getattr(us, f"compute_{kind}" + ("_score" if kind == "piotroski" else ""))
    check(f"legacy_us_{kind}", {k: fn(t, "SYM") for k, t in _cases().items()})


def test_india_yf_financials_accepts_dataframes(india):
    """Bug fix: `df or df` raised ValueError for real yfinance DataFrames, so every scorer returned an error."""
    t = _ticker(1)
    t.income_stmt, t.cash_flow = t.financials, t.cashflow
    inc, bal, cf = india._yf_financials(t)
    assert not inc.empty and not bal.empty and not cf.empty
