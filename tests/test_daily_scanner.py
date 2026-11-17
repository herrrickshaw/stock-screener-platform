"""Unit tests for backend/scanners/daily_scanner.py (vectorised Darvas/Buffett + 'Piotroski-simplified').

Expected values are hand-computed from the module docstring's point table.
"""
import math

import numpy as np
import pandas as pd
import pytest

from scanners.daily_scanner import scan_darvas, scan_piotroski


def _row(**kw):
    base = {"ticker": "TEST", "name": "Test Co", "cmp": 100.0, "high_52w": 105.0,
            "low_52w": 60.0, "ema_50": 95.0, "rsi": 55.0}
    base.update(kw)
    return base


def _one(fn, **kw):
    return fn(pd.DataFrame([_row(**kw)]))[0]


# ── Darvas / Buffett ──────────────────────────────────────────────────────────

def test_darvas_empty_frame_returns_empty_list():
    assert scan_darvas(pd.DataFrame()) == []


def test_darvas_core_ohlcv_only_scores_six_and_buys():
    r = _one(scan_darvas)
    # D1 near high (+2), D2 above EMA50 (+2), D3 range 0.889>=0.6 (+1), D4 RSI 55 (+1)
    assert r["score"] == 6
    assert r["max_score"] == 6
    assert r["signal"] == "BUY"
    assert r["criteria"]["near_52w_high"] is True
    assert r["criteria"]["buffett_roe"] is None   # not supplied -> not evaluated


@pytest.mark.parametrize("kw,score,signal", [
    # only D2 (+2) + D4 (+1) = 3 -> WATCH: far from high and bottom of range
    (dict(cmp=70.0, high_52w=105.0, low_52w=60.0, ema_50=65.0, rsi=50.0), 3, "WATCH"),
    # only D2 (+2) -> AVOID (rsi 80 outside 40-68)
    (dict(cmp=70.0, high_52w=105.0, low_52w=60.0, ema_50=65.0, rsi=80.0), 2, "AVOID"),
    # nothing passes
    (dict(cmp=62.0, high_52w=105.0, low_52w=60.0, ema_50=90.0, rsi=20.0), 0, "AVOID"),
])
def test_darvas_signal_bands(kw, score, signal):
    r = _one(scan_darvas, **kw)
    assert (r["score"], r["signal"]) == (score, signal)


def test_darvas_near_high_boundary_is_inclusive_at_15pct():
    assert _one(scan_darvas, cmp=85.0, high_52w=100.0)["criteria"]["near_52w_high"] is True
    assert _one(scan_darvas, cmp=84.9, high_52w=100.0)["criteria"]["near_52w_high"] is False


def test_darvas_rsi_band_inclusive_40_68():
    assert _one(scan_darvas, rsi=40.0)["criteria"]["rsi_healthy"] is True
    assert _one(scan_darvas, rsi=68.0)["criteria"]["rsi_healthy"] is True
    assert _one(scan_darvas, rsi=68.5)["criteria"]["rsi_healthy"] is False


def test_darvas_missing_high_is_not_evaluated_not_failed():
    r = _one(scan_darvas, high_52w=np.nan)
    assert r["criteria"]["near_52w_high"] is None
    assert r["criteria"]["range_strength"] is None
    assert r["score"] == 3   # D2 + D4 only


def test_darvas_zero_range_does_not_divide_by_zero():
    r = _one(scan_darvas, cmp=100.0, high_52w=100.0, low_52w=100.0)
    assert r["criteria"]["range_strength"] is None


def test_darvas_buffett_overlay_scores_fundamentals_when_present():
    """CLAUDE.md / module docstring: 'optional Buffett overlay ROE/PE/DE (+1 each)' when the
    fundamentals are present."""
    r = scan_darvas(pd.DataFrame([_row(roe=20.0, pe=15.0, debt_to_equity=0.5)]))[0]
    assert r["criteria"]["buffett_roe"] is True
    assert r["criteria"]["buffett_pe"] is True
    assert r["criteria"]["buffett_de"] is True
    assert r["score"] == 9
    assert r["roe"] == 20.0


def test_darvas_buffett_overlay_fails_bad_fundamentals():
    r = scan_darvas(pd.DataFrame([_row(roe=5.0, pe=50.0, debt_to_equity=2.0)]))[0]
    assert r["criteria"]["buffett_roe"] is False
    assert r["criteria"]["buffett_pe"] is False
    assert r["criteria"]["buffett_de"] is False
    assert r["score"] == 6


def test_darvas_full_load_scores_optional_technicals():
    r = scan_darvas(pd.DataFrame([_row(ema_200=90.0, macd=1.0, macd_signal=0.5, volume_ratio=2.0,
                                       ema_20=97.0, bb_pct=0.7, stoch_k=60.0, stoch_d=50.0)]))[0]
    assert r["score"] == 6 + 6
    assert r["completeness"] == round(10 / 13 * 100)


def test_darvas_string_numbers_are_coerced():
    r = scan_darvas(pd.DataFrame([_row(cmp="100", rsi="55")]))[0]
    assert r["score"] == 6


# ── 'Piotroski' (simplified, availability-scaled thresholds) ──────────────────

def test_piotroski_empty_frame_returns_empty_list():
    assert scan_piotroski(pd.DataFrame()) == []


def test_piotroski_all_fields_thresholds_8_and_5():
    full = dict(roe=10.0, debt_to_equity=0.2, opm=20.0, revenue_growth=5.0, current_ratio=2.0,
                pb=2.0, ema_20=97.0, atr_14=1.0)
    r = _one(scan_piotroski, **full)
    assert r["max_score"] == 11
    assert r["score"] == 11
    assert r["signal"] == "BUY"
    # 8 of 11 -> BUY (ceil(11*0.65)=8); 7 -> WATCH; 5 -> WATCH (ceil(4.4)=5); 4 -> AVOID
    seven = dict(full, roe=-1.0, debt_to_equity=1.0, opm=1.0, revenue_growth=-1.0)
    assert _one(scan_piotroski, **seven)["score"] == 7
    assert _one(scan_piotroski, **seven)["signal"] == "WATCH"
    eight = dict(seven, roe=1.0)
    assert _one(scan_piotroski, **eight)["signal"] == "BUY"
    four = dict(seven, current_ratio=1.0, pb=5.0, atr_14=10.0)
    assert _one(scan_piotroski, **four)["score"] == 4
    assert _one(scan_piotroski, **four)["signal"] == "AVOID"


def test_piotroski_momentum_only_three_fields():
    r = _one(scan_piotroski)
    assert r["max_score"] == 3
    assert r["score"] == 3 and r["signal"] == "BUY"
    # max 3: BUY >= ceil(1.95)=2, WATCH >= ceil(1.2)=2 -> one pass is AVOID
    r1 = _one(scan_piotroski, ema_50=200.0, high_52w=500.0)
    assert r1["score"] == 1 and r1["signal"] == "AVOID"


def test_piotroski_no_fields_never_divides_by_zero():
    r = scan_piotroski(pd.DataFrame([{"ticker": "X"}]))[0]
    assert r["max_score"] == 1 and r["score"] == 0 and r["signal"] == "AVOID"
    assert r["completeness"] == 0


def test_piotroski_atr_requires_positive_price():
    r = _one(scan_piotroski, cmp=0.0, atr_14=1.0)
    assert r["criteria"]["FX7_low_atr"] is None
