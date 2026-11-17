"""Characterisation tests (pass 2): darvas scanner and compute_technicals pinned to pre-refactor output."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fetchers.providers.base import compute_technicals
from golden_util import check
from scanners import darvas
from synth import make_quotes


def _darvas_frame() -> pd.DataFrame:
    df = make_quotes(60, 3, 0.2)
    rng = np.random.default_rng(5)
    n = len(df)
    df["volume_30d_avg"] = df["volume"] * rng.uniform(0.3, 1.2, n)
    df["net_profit_margin"] = rng.uniform(-5, 25, n)
    df["promoter_holding"] = rng.uniform(10, 80, n)
    df["eps_growth_5y"] = rng.normal(8, 15, n)
    df["profit_growth_5y"] = rng.normal(8, 15, n)
    df["profit_growth_3y"] = rng.normal(8, 15, n)
    df["sector_pe"] = rng.uniform(10, 40, n)
    df.loc[df.index % 7 == 0, "eps_growth_5y"] = np.nan
    df.loc[df.index % 11 == 0, "net_profit_margin"] = np.nan
    df.loc[df.index % 5 == 0, "sector"] = None
    df.loc[3, "low_52w"] = df.loc[3, "high_52w"]  # zero-range edge
    return df


@pytest.fixture(autouse=True)
def _no_damodaran(monkeypatch):
    table = {"Tech": 20.0, "Banks": 0.0}
    monkeypatch.setattr(darvas, "get_sector_pe", lambda s: table.get(s))


def test_darvas_scan_golden():
    check("darvas_scan", darvas.scan(_darvas_frame()))
    check("darvas_scan_minimal", darvas.scan(make_quotes(10, 9, 0.0)[["ticker", "cmp", "high_52w", "low_52w", "pe"]]))


def _series(n, seed, base=100.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series(base + np.cumsum(rng.normal(0, 1.5, n)), index=idx).abs() + 1
    high = close + rng.uniform(0, 2, n)
    low = (close - rng.uniform(0, 2, n)).clip(lower=0.5)
    vol = pd.Series(rng.integers(1000, 90000, n).astype(float), index=idx)
    return close, vol, high, low


@pytest.mark.parametrize("n", [1, 2, 10, 15, 20, 26, 35, 60, 130, 300])
def test_compute_technicals_golden(n):
    c, v, h, l = _series(max(n, 1), n)
    check(f"technicals_{n}_full", compute_technicals(c, v, h, l))
    check(f"technicals_{n}_close_only", compute_technicals(c))


def test_compute_technicals_edge_cases():
    c, v, h, l = _series(40, 1)
    c2 = c.copy()
    c2.iloc[5] = np.nan
    check("technicals_nan", compute_technicals(c2, v, h, l))
    check("technicals_none", compute_technicals(None))
    flat = pd.Series([5.0] * 30)
    check("technicals_flat", compute_technicals(flat, pd.Series([0.0] * 30), flat, flat))
