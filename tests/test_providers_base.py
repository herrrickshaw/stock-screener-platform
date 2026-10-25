"""Unit tests for fetchers/providers/base.py: compute_technicals and QuoteData.merge.
Inputs are synthetic linear/constant series whose indicators can be worked out by hand."""
import numpy as np
import pandas as pd
import pytest

from fetchers.providers.base import QuoteData, compute_technicals


def _linear(n=30, start=100.0):
    idx = pd.bdate_range("2026-01-01", periods=n)
    c = pd.Series(start + np.arange(n, dtype=float), index=idx)
    return c, c + 1.0, c - 1.0


def _wilder(values):
    return float(pd.Series(values).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])


def test_too_short_returns_empty():
    assert compute_technicals(pd.Series([1.0])) == {}
    assert compute_technicals(pd.Series([np.nan, 5.0])) == {}


def test_rising_series_basics():
    c, h, l = _linear()
    t = compute_technicals(c, pd.Series(1000.0, index=c.index), h, l)
    assert t["cmp"] == 129.0
    assert t["rsi"] == 100.0                     # no down days
    assert t["high_52w"] == 129.0 and t["low_52w"] == 100.0
    assert t["ret_1d"] == round(1 / 128 * 100, 2)
    assert t["ret_1y"] == 29.0
    assert t["volume_ratio"] == 1.0
    assert t["atr_14"] == 2.0                    # every true range is high-low = 2
    # %K over last 14 bars: (129 - 115) / (130 - 115) = 93.33
    assert t["stoch_k"] == pytest.approx(93.33, abs=0.01)
    assert t["rsi_signal"] == "HOLD"


def test_constant_series_has_no_bollinger_pct():
    c = pd.Series([50.0] * 25)
    t = compute_technicals(c)
    assert t["bb_upper"] == t["bb_lower"] == 50.0
    assert t["bb_pct"] is None
    assert t["ema_20"] == t["ema_50"] == 50.0


def test_atr_aligns_high_low_close_by_date_when_a_close_is_missing():
    """A NaN close must drop that bar for H/L too; closes/highs/lows were dropna'd
    independently and then zipped by position, pairing each high with the wrong close."""
    c, h, l = _linear()
    c.iloc[10] = np.nan
    t = compute_technicals(c, None, h, l)
    # Joint rows: bars 0-9, 11-29 (29 bars -> 28 true ranges). TR is 2 everywhere except the
    # gap bar 11 vs close 109: max(112-110, |112-109|, |110-109|) = 3.
    trs = [2.0] * 9 + [3.0] + [2.0] * 18
    assert t["atr_14"] == round(_wilder(trs), 4)


def test_merge_fills_only_missing_fields():
    a = QuoteData(ticker="X", source="a", cmp=10.0)
    b = QuoteData(ticker="X", source="b", cmp=99.0, pe=12.0)
    m = a.merge(b)
    assert (m.cmp, m.pe, m.source) == (10.0, 12.0, "a+b")
