"""Offline tests for backend.scanners.daily_scanner (vectorised Darvas/Buffett + simplified Piotroski)."""
import math

import numpy as np
import pandas as pd
import pytest

from scanners import daily_scanner as ds

NAN = float("nan")


# ------------------------------------------------------------------ helpers
def test_col_returns_numeric_series_or_all_nan_when_missing():
    df = pd.DataFrame({"a": ["1", "x", None]})
    assert ds._col(df, "a").tolist()[0] == 1.0
    assert math.isnan(ds._col(df, "a").iloc[1]) and math.isnan(ds._col(df, "a").iloc[2])
    missing = ds._col(df, "zzz")
    assert len(missing) == 3 and missing.isna().all() and list(missing.index) == list(df.index)


def test_vcrit_is_none_where_invalid():
    passes = pd.Series([True, False, True])
    valid = pd.Series([True, True, False])
    out = ds._vcrit(passes, valid)
    assert out.tolist()[:2] == [True, False]
    assert bool(valid.iloc[2]) is False          # third slot is the "not evaluated" one (see xfail below)


def test_pts_counts_only_true_with_weight():
    crit = pd.Series([True, False, None], dtype=object)
    assert ds._pts(crit).tolist() == [1, 0, 0]
    assert ds._pts(crit, 2).tolist() == [2, 0, 0]


@pytest.mark.parametrize("v, expected", [
    (1.234, 1.23), (1.235, 1.24), (2, 2.0), ("3.456", 3.46), (NAN, None), (float("inf"), None),
    (-float("inf"), None), (None, None), ("abc", None), (np.float64(1.005), 1.0),
])
def test_r_rounds_to_two_places_and_nulls_non_finite(v, expected):
    got = ds._r(v)
    assert got == expected if expected is None else got == pytest.approx(expected)


def test_b_converts_to_python_bool_or_none():
    assert ds._b(None) is None
    assert ds._b(np.True_) is True and ds._b(np.False_) is False
    assert ds._b(0) is False and ds._b(1) is True

    class Bad:
        def __bool__(self):
            raise RuntimeError

    assert ds._b(Bad()) is None


def test_strs_fills_na_and_defaults_when_column_missing():
    df = pd.DataFrame({"t": ["A", None, "C"]})
    assert ds._strs(df, "t") == ["A", "", "C"]
    assert ds._strs(df, "t", "?") == ["A", "?", "C"]
    assert ds._strs(df, "missing") == ["", "", ""]
    assert ds._strs(df, "missing", "HOLD") == ["HOLD"] * 3


# ------------------------------------------------------------------ darvas
def _darvas_row(**over):
    base = dict(ticker="AAA", name="Alpha", cmp=100.0, high_52w=110.0, low_52w=60.0, ema_50=90.0, rsi=55.0)
    base.update(over)
    return base


def scan_one(fn, **over):
    return fn(pd.DataFrame([_darvas_row(**over)]))[0]


def test_scan_darvas_empty_frame_returns_empty_list():
    assert ds.scan_darvas(pd.DataFrame()) == []
    assert ds.scan_piotroski(pd.DataFrame()) == []


def test_darvas_core_criteria_score_and_signal():
    r = scan_one(ds.scan_darvas)
    # near high (10/110=9 %) +2, above ema50 +2, range (40/50=.8) +1, rsi 55 +1 = 6
    assert r["score"] == 6 and r["max_score"] == 6 and r["signal"] == "BUY"
    c = r["criteria"]
    assert c["near_52w_high"] and c["above_ema50"] and c["range_strength"] and c["rsi_healthy"]
    assert r["ticker"] == "AAA" and r["name"] == "Alpha" and r["rsi_signal"] == "HOLD"
    assert r["completeness"] == round(4 / 13 * 100)


@pytest.mark.parametrize("over, key, expected", [
    (dict(cmp=93.5, high_52w=110.0), "near_52w_high", True),      # (110-93.5)/110 = 0.15 exactly
    (dict(cmp=93.0, high_52w=110.0), "near_52w_high", False),
    (dict(cmp=90.0, ema_50=90.0), "above_ema50", False),          # strictly greater
    (dict(cmp=90.01, ema_50=90.0), "above_ema50", True),
    (dict(cmp=90.0, high_52w=100.0, low_52w=50.0), "range_strength", False),   # (40/50 = .8) -> True actually
    (dict(rsi=40.0), "rsi_healthy", True), (dict(rsi=68.0), "rsi_healthy", True),
    (dict(rsi=39.9), "rsi_healthy", False), (dict(rsi=68.1), "rsi_healthy", False),
    (dict(roe=12.0), "buffett_roe", False), (dict(roe=12.1), "buffett_roe", True),
    (dict(pe=5.0), "buffett_pe", True), (dict(pe=30.0), "buffett_pe", True),
    (dict(pe=4.9), "buffett_pe", False), (dict(pe=30.1), "buffett_pe", False),
    (dict(debt_to_equity=1.0), "buffett_de", False), (dict(debt_to_equity=0.99), "buffett_de", True),
    (dict(ema_200=100.0), "above_ema200", False), (dict(ema_200=99.9), "above_ema200", True),
    (dict(macd=1.0, macd_signal=1.0), "macd_bull", False), (dict(macd=1.1, macd_signal=1.0), "macd_bull", True),
    (dict(volume_ratio=1.5), "volume_surge", False), (dict(volume_ratio=1.51), "volume_surge", True),
    (dict(ema_20=90.0), "ema_cross", False),                      # ema_50 = 90 -> not strictly greater
    (dict(ema_20=91.0), "ema_cross", True),
    (dict(bb_pct=0.5), "bb_upper_half", False), (dict(bb_pct=0.51), "bb_upper_half", True),
    (dict(stoch_k=50.0, stoch_d=40.0), "stoch_bullish", True),
    (dict(stoch_k=50.0, stoch_d=50.0), "stoch_bullish", False),
    (dict(stoch_k=20.0, stoch_d=10.0), "stoch_bullish", True),
    (dict(stoch_k=80.0, stoch_d=10.0), "stoch_bullish", True),
    (dict(stoch_k=19.9, stoch_d=10.0), "stoch_bullish", False),
    (dict(stoch_k=80.1, stoch_d=10.0), "stoch_bullish", False),
])
def test_darvas_criteria_boundaries(over, key, expected):
    if key == "range_strength" and over.get("cmp") == 90.0:
        expected = True
    got = scan_one(ds.scan_darvas, **over)["criteria"][key]
    assert got is expected


def test_darvas_range_strength_threshold_is_60_percent_inclusive():
    # range 50..150 -> cmp 110 is exactly 0.6
    assert scan_one(ds.scan_darvas, cmp=110.0, high_52w=150.0, low_52w=50.0)["criteria"]["range_strength"] is True
    assert scan_one(ds.scan_darvas, cmp=109.0, high_52w=150.0, low_52w=50.0)["criteria"]["range_strength"] is False


def test_darvas_zero_range_or_zero_high_is_not_evaluated_not_a_division_error():
    r = scan_one(ds.scan_darvas, high_52w=100.0, low_52w=100.0)
    assert r["score"] == 2 + 2 + 1 and r["max_score"] == 6    # near-high, ema50 and rsi; range not evaluable
    assert r["completeness"] == round(3 / 13 * 100)
    r = scan_one(ds.scan_darvas, high_52w=0.0)
    assert r["score"] == 2 + 1 and r["completeness"] == round(2 / 13 * 100)


def test_darvas_max_score_grows_with_available_optional_fields():
    r = scan_one(ds.scan_darvas, roe=20.0, pe=15.0, debt_to_equity=0.4, ema_200=80.0, macd=1.0,
                 macd_signal=0.5, volume_ratio=2.0, ema_20=95.0, bb_pct=0.8, stoch_k=50.0, stoch_d=40.0)
    assert r["max_score"] == 6 + 9 and r["score"] == 6 + 9 and r["completeness"] == 100


def test_darvas_signal_thresholds_buy_5_watch_3():
    # near-high (+2) and above-ema50 (+2) only -> 4 -> WATCH ; plus nothing else
    r = scan_one(ds.scan_darvas, rsi=10.0, high_52w=110.0, low_52w=0.0)   # range .91 -> +1 -> 5
    assert r["score"] == 5 and r["signal"] == "BUY"
    r = scan_one(ds.scan_darvas, rsi=10.0, high_52w=1000.0, low_52w=0.0)  # near no, above yes (2), range no
    assert r["score"] == 2 and r["signal"] == "AVOID"
    r = scan_one(ds.scan_darvas, rsi=55.0, high_52w=1000.0, low_52w=0.0)  # 2 + rsi 1 = 3
    assert r["score"] == 3 and r["signal"] == "WATCH"


def test_darvas_output_rounding_and_volume_handling():
    r = scan_one(ds.scan_darvas, cmp=100.456, volume=12345.0, rsi_signal="BUY", sector="IT",
                 industry="Soft", _exchange="NSE", market_cap=1e9)
    assert r["cmp"] == 100.46 and r["volume"] == 12345 and isinstance(r["volume"], int)
    assert r["rsi_signal"] == "BUY" and r["sector"] == "IT" and r["industry"] == "Soft"
    assert r["_exchange"] == "NSE" and r["market_cap"] == 1e9
    assert scan_one(ds.scan_darvas)["volume"] is None            # missing volume -> None, not NaN


def test_darvas_batch_keeps_rows_independent_and_ordered():
    df = pd.DataFrame([_darvas_row(ticker="A"), _darvas_row(ticker="B", cmp=10.0), _darvas_row(ticker="C")],
                      index=[7, 3, 9])
    out = ds.scan_darvas(df)
    assert [r["ticker"] for r in out] == ["A", "B", "C"]
    assert out[0]["score"] == out[2]["score"] and out[1]["score"] != out[0]["score"]


def test_darvas_coerces_numeric_strings():
    r = scan_one(ds.scan_darvas, cmp="100", rsi="55")
    assert r["cmp"] == 100.0 and r["criteria"]["rsi_healthy"] is True


# ---------------------------------------------------------------- piotroski
def _pio(**over):
    base = dict(ticker="PPP", name="Pio")
    base.update(over)
    return pd.DataFrame([base])


def test_piotroski_with_no_data_has_max_score_of_one_and_avoids():
    r = ds.scan_piotroski(_pio())[0]
    assert r["max_score"] == 1 and r["score"] == 0 and r["signal"] == "AVOID" and r["completeness"] == 0


@pytest.mark.parametrize("over, key, expected", [
    (dict(roe=0.0), "F1_roe_positive", False), (dict(roe=0.1), "F1_roe_positive", True),
    (dict(debt_to_equity=0.5), "F5_low_leverage", False), (dict(debt_to_equity=0.49), "F5_low_leverage", True),
    (dict(opm=15.0), "F8_op_margin", False), (dict(opm=15.1), "F8_op_margin", True),
    (dict(revenue_growth=0.0), "F9_rev_growth", False), (dict(revenue_growth=0.1), "F9_rev_growth", True),
    (dict(cmp=100.0, ema_50=100.0), "FX1_above_ema50", False),
    (dict(cmp=100.1, ema_50=100.0), "FX1_above_ema50", True),
    (dict(rsi=40.0), "FX2_rsi_range", True), (dict(rsi=70.0), "FX2_rsi_range", True),
    (dict(rsi=39.9), "FX2_rsi_range", False), (dict(rsi=70.1), "FX2_rsi_range", False),
    (dict(cmp=80.0, high_52w=100.0), "FX3_near_high", True),       # exactly 20 % below
    (dict(cmp=79.9, high_52w=100.0), "FX3_near_high", False),
    (dict(current_ratio=1.5), "FX4_current_ratio", False), (dict(current_ratio=1.6), "FX4_current_ratio", True),
    (dict(pb=3.0), "FX5_pb_value", False), (dict(pb=2.99), "FX5_pb_value", True),
    (dict(ema_20=10.0, ema_50=10.0), "FX6_ema_cross", False),
    (dict(ema_20=10.1, ema_50=10.0), "FX6_ema_cross", True),
    (dict(atr_14=3.0, cmp=100.0), "FX7_low_atr", False),
    (dict(atr_14=2.9, cmp=100.0), "FX7_low_atr", True),
])
def test_piotroski_daily_criteria_boundaries(over, key, expected):
    assert ds.scan_piotroski(_pio(**over))[0]["criteria"][key] is expected


def test_piotroski_atr_with_zero_price_is_not_evaluated():
    r = ds.scan_piotroski(_pio(atr_14=1.0, cmp=0.0))[0]
    assert r["max_score"] == 1 and r["score"] == 0 and r["completeness"] == 0


def test_piotroski_near_high_ignores_non_positive_high():
    r = ds.scan_piotroski(_pio(cmp=10.0, high_52w=0.0))[0]
    assert r["max_score"] == 1 and r["score"] == 0 and r["completeness"] == 0


@pytest.mark.parametrize("n_avail, n_pass, signal", [
    # max_score = n_avail ; BUY >= ceil(.65 n) ; WATCH >= ceil(.40 n)
    (4, 3, "BUY"),      # ceil(2.6)=3
    (4, 2, "WATCH"),    # ceil(1.6)=2
    (4, 1, "AVOID"),
    (2, 2, "BUY"),      # ceil(1.3)=2
    (2, 1, "WATCH"),    # ceil(0.8)=1
    (2, 0, "AVOID"),
    (1, 1, "BUY"), (1, 0, "AVOID"),
])
def test_piotroski_dynamic_thresholds_scale_with_available_fields(n_avail, n_pass, signal):
    # F1 roe>0, F5 de<.5, F8 opm>15, F9 rg>0 are four independent boolean criteria
    good = [("roe", 5.0), ("debt_to_equity", 0.1), ("opm", 20.0), ("revenue_growth", 5.0)]
    bad = [("roe", -5.0), ("debt_to_equity", 2.0), ("opm", 1.0), ("revenue_growth", -5.0)]
    fields = {}
    for i in range(n_avail):
        k, v = (good[i] if i < n_pass else bad[i])
        fields[k] = v
    r = ds.scan_piotroski(_pio(**fields))[0]
    assert r["max_score"] == n_avail and r["score"] == n_pass and r["signal"] == signal


def test_piotroski_full_data_scores_eleven_and_completeness_100():
    r = ds.scan_piotroski(_pio(roe=10.0, debt_to_equity=0.2, opm=20.0, revenue_growth=5.0, cmp=100.0,
                               ema_50=90.0, rsi=50.0, high_52w=110.0, current_ratio=2.0, pb=1.0,
                               ema_20=95.0, atr_14=1.0))[0]
    assert r["score"] == 11 and r["max_score"] == 11 and r["signal"] == "BUY" and r["completeness"] == 100


def test_piotroski_output_fields():
    r = ds.scan_piotroski(_pio(cmp=10.126, volume=500.0, sector="S", industry="I", _exchange="BSE",
                               rsi_signal="SELL"))[0]
    assert r["cmp"] == 10.13 and r["volume"] == 500 and r["sector"] == "S" and r["industry"] == "I"
    assert r["_exchange"] == "BSE" and r["rsi_signal"] == "SELL"
    assert ds.scan_piotroski(_pio())[0]["volume"] is None


# -------------------------------------------------------------- source bug
@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="daily_scanner.py:_vcrit builds an object Series from None, which pandas stores as NaN, "
           "and _b() then reports bool(NaN) == True. Criteria with no data are therefore shown as "
           "passed in the API output (the score is unaffected: _pts compares == True).")
def test_unevaluated_criteria_are_reported_as_none_not_true():
    r = scan_one(ds.scan_darvas)                      # no ROE / MACD / ... columns at all
    assert r["criteria"]["buffett_roe"] is None
    assert r["criteria"]["macd_bull"] is None
