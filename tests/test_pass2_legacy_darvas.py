"""Characterisation tests (pass 2): the two legacy compute_darvas_box implementations (current bar excluded)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from golden_util import check
from legacy_loader import load_script


def _ohlc(n, seed, style="yf", breakout=None):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.2, n))
    high = close + rng.uniform(0, 1.5, n)
    low = close - rng.uniform(0, 1.5, n)
    if breakout == "up":
        close[-1] = high[:-1].max() + 5
        high[-1] = close[-1] + 1
    elif breakout == "down":
        close[-1] = low[:-1].min() - 5
        low[-1] = close[-1] - 1
    names = {"yf": ("High", "Low", "Close"), "nse": ("CH_TRADE_HIGH_PRICE", "CH_TRADE_LOW_PRICE", "CH_CLOSING_PRICE")}[style]
    return pd.DataFrame({names[0]: high, names[1]: low, names[2]: close})


def _cases():
    out = {}
    for style in ("yf", "nse"):
        for n in (5, 8, 9, 30, 120):
            for seed in (1, 2):
                out[f"{style}_{n}_{seed}"] = _ohlc(n, seed, style)
        out[f"{style}_up"] = _ohlc(60, 3, style, "up")
        out[f"{style}_down"] = _ohlc(60, 4, style, "down")
    mono = pd.DataFrame({"High": np.arange(1, 41, dtype=float) + 1, "Low": np.arange(1, 41, dtype=float), "Close": np.arange(1, 41, dtype=float)})
    out["monotonic_up"] = mono
    out["monotonic_down"] = mono.iloc[::-1].reset_index(drop=True)
    zeros = mono.copy()
    zeros.loc[10:25, "Low"] = 0
    out["zeros_low"] = zeros
    out["bad_cols"] = pd.DataFrame({"a": range(20), "b": range(20)})
    flat = pd.DataFrame({"High": [10.0] * 30, "Low": [10.0] * 30, "Close": [10.0] * 30})
    out["flat"] = flat
    nan = _ohlc(40, 9)
    nan.loc[7, "High"] = np.nan
    out["nan"] = nan
    return out


@pytest.mark.parametrize("script", ["stock_daily_report_improved", "us_stock_daily_report"])
def test_compute_darvas_box_golden(script, tmp_path, monkeypatch):
    mod = load_script(script, tmp_path, monkeypatch)
    res = {k: mod.compute_darvas_box(df) for k, df in _cases().items()}
    res["confirm2"] = mod.compute_darvas_box(_ohlc(50, 6), confirm=2)
    res["empty"] = mod.compute_darvas_box(pd.DataFrame())
    res["none"] = mod.compute_darvas_box(None) if script == "us_stock_daily_report" else None
    check(f"darvas_legacy_{script}", res)
