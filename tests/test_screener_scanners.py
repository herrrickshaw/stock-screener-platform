"""Offline tests for backend.column_map and the Screener.in-CSV scanners (darvas, piotroski, coffee_can)."""
import math

import numpy as np
import pandas as pd
import pytest

import column_map
from column_map import COLUMN_ALIASES, completeness, normalize_columns, sanitize_result
from scanners import coffee_can, darvas, piotroski

NAN = float("nan")


def S(**kw):
    return pd.Series(kw, dtype=object)


# ------------------------------------------------------------- column_map
def test_normalize_columns_maps_aliases_case_and_space_insensitively():
    df = pd.DataFrame({" nse code ": ["TCS"], "CMP Rs.": ["3,500.50"], "roe %": ["25 %"],
                       "Junk": ["x"]})
    out = normalize_columns(df)
    assert list(out.columns) == ["ticker", "cmp", "roe", "Junk"]
    assert out.loc[0, "cmp"] == 3500.50
    assert out.loc[0, "roe"] == 25.0
    assert out.loc[0, "ticker"] == "TCS"            # text columns stay strings


def test_normalize_columns_does_not_mutate_input():
    df = pd.DataFrame({"Price": ["1"]})
    normalize_columns(df)
    assert list(df.columns) == ["Price"] and df.loc[0, "Price"] == "1"


def test_normalize_columns_first_matching_alias_wins_and_each_source_used_once():
    # 'NSE Code' is listed before 'Symbol' for ticker, so it is the one renamed
    df = pd.DataFrame({"Symbol": ["B"], "NSE Code": ["A"]})
    out = normalize_columns(df)
    assert out.loc[0, "ticker"] == "A"
    assert "Symbol" in out.columns


def test_normalize_columns_coerces_garbage_to_nan_and_keeps_name_sector_text():
    df = pd.DataFrame({"Name": ["Acme"], "Sector": ["IT"], "P/E": ["n/a"], "Market Cap": ["1,00,000"]})
    out = normalize_columns(df)
    assert math.isnan(out.loc[0, "pe"])
    assert out.loc[0, "market_cap"] == 100000.0
    assert out.loc[0, "name"] == "Acme" and out.loc[0, "sector"] == "IT"


def test_normalize_columns_leaves_unknown_columns_untouched():
    df = pd.DataFrame({"Whatever": ["1,5"]})
    assert normalize_columns(df).loc[0, "Whatever"] == "1,5"


def test_no_header_alias_is_claimed_by_two_canonical_fields():
    owner = {}
    for canon, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            key = a.strip().lower()
            assert owner.setdefault(key, canon) == canon, (key, owner[key], canon)


def test_completeness_counts_non_nan_fields():
    row = S(a=1.0, b=NAN, c=0.0)
    assert completeness(row, ["a", "b", "c", "missing"]) == 50.0
    assert completeness(row, ["a"]) == 100.0
    assert completeness(row, ["b"]) == 0.0
    assert completeness(row, []) == 100.0
    assert completeness(S(a=1, b=2, c=3), ["a", "b", "z"]) == 66.7        # rounded to 1 dp


def test_sanitize_result_replaces_nan_inf_and_unwraps_numpy_scalars_recursively():
    out = sanitize_result({
        "a": NAN, "b": float("inf"), "c": -float("inf"), "d": 1.5,
        "e": np.float64(2.5), "f": np.True_, "g": np.int64(7),
        "h": {"x": NAN, "y": np.bool_(False), "z": {"deep": np.float64("nan")}},
        "i": "text", "j": None,
    })
    assert out["a"] is None and out["b"] is None and out["c"] is None
    assert out["d"] == 1.5
    assert out["e"] == 2.5 and type(out["e"]) is float
    assert out["f"] is True and out["g"] == 7 and type(out["g"]) is int
    assert out["h"] == {"x": None, "y": False, "z": {"deep": None}}
    assert out["i"] == "text" and out["j"] is None


def test_sanitize_result_does_not_mutate_input():
    src = {"a": NAN, "n": {"b": NAN}}
    sanitize_result(src)
    assert math.isnan(src["a"]) and math.isnan(src["n"]["b"])


# ----------------------------------------------------------------- darvas
@pytest.fixture(autouse=True)
def _no_damodaran(monkeypatch):
    monkeypatch.setattr(darvas, "get_sector_pe", lambda sector: None)


GOOD_DARVAS = dict(cmp=100.0, high_52w=102.0, low_52w=50.0, volume=300, volume_30d_avg=100,
                   roe=20.0, net_profit_margin=12.0, debt_to_equity=0.2, promoter_holding=60.0,
                   eps_growth_5y=15.0, pe=20.0, name="Acme", ticker="ACME", sector="IT")


def D(**over):
    d = dict(GOOD_DARVAS)
    d.update(over)
    return S(**d)


def test_darvas_all_ten_criteria_pass_gives_buy():
    r = darvas._score(D())
    assert r["score"] == 10 and r["max_score"] == 10 and r["signal"] == "BUY"
    assert all(v is True for v in r["criteria"].values()) and len(r["criteria"]) == 10
    assert (r["name"], r["ticker"], r["sector"]) == ("Acme", "ACME", "IT")


@pytest.mark.parametrize("over, key, expected", [
    # C1: within 3 % of the high (inclusive)
    (dict(cmp=97.0, high_52w=100.0), "price_near_52w_high", True),
    (dict(cmp=96.9, high_52w=100.0), "price_near_52w_high", False),
    (dict(high_52w=0.0), "price_near_52w_high", None),
    (dict(cmp=NAN), "price_near_52w_high", None),
    # C2: volume >= 1.5x average (inclusive)
    (dict(volume=150, volume_30d_avg=100), "volume_breakout", True),
    (dict(volume=149, volume_30d_avg=100), "volume_breakout", False),
    (dict(volume_30d_avg=0), "volume_breakout", None),
    (dict(volume=NAN), "volume_breakout", None),
    # C3: above 85 % of 52w high (inclusive)
    (dict(cmp=85.0, high_52w=100.0), "above_box_floor", True),
    (dict(cmp=84.9, high_52w=100.0), "above_box_floor", False),
    # C4: ROE strictly > 15
    (dict(roe=15.0), "roe_gt_15", False),
    (dict(roe=15.1), "roe_gt_15", True),
    (dict(roe=NAN), "roe_gt_15", None),
    # C5: margin strictly > 10, falls back from net margin to OPM only when NPM is NaN
    (dict(net_profit_margin=10.0), "profit_margin_gt_10", False),
    (dict(net_profit_margin=NAN, opm=11.0), "profit_margin_gt_10", True),
    (dict(net_profit_margin=NAN, opm=NAN), "profit_margin_gt_10", None),
    (dict(net_profit_margin=5.0, opm=50.0), "profit_margin_gt_10", False),      # NPM wins over OPM
    # C6: D/E strictly < 0.5
    (dict(debt_to_equity=0.5), "low_debt", False),
    (dict(debt_to_equity=0.49), "low_debt", True),
    # C7: promoter holding strictly > 50
    (dict(promoter_holding=50.0), "promoter_holding_gt_50", False),
    (dict(promoter_holding=50.1), "promoter_holding_gt_50", True),
    # C8: growth strictly > 10
    (dict(eps_growth_5y=10.0), "eps_growth_gt_10", False),
    (dict(eps_growth_5y=10.5), "eps_growth_gt_10", True),
    (dict(eps_growth_5y=NAN), "eps_growth_gt_10", None),
])
def test_darvas_criterion_boundaries(over, key, expected):
    got = darvas._score(D(**over))["criteria"][key]
    assert got is expected


def test_darvas_price_strength_is_upper_half_of_52w_range():
    assert darvas._score(D(cmp=76.0, high_52w=100.0, low_52w=50.0))["criteria"]["price_strength"] is True
    assert darvas._score(D(cmp=75.0, high_52w=100.0, low_52w=50.0))["criteria"]["price_strength"] is False
    assert darvas._score(D(high_52w=50.0, low_52w=50.0))["criteria"]["price_strength"] is None   # zero range
    assert darvas._score(D(low_52w=NAN))["criteria"]["price_strength"] is None


def test_darvas_pe_absolute_fallback_is_below_35():
    assert darvas._score(D(pe=34.9))["criteria"]["pe_vs_sector"] is True
    assert darvas._score(D(pe=35.0))["criteria"]["pe_vs_sector"] is False
    assert darvas._score(D(pe=NAN))["criteria"]["pe_vs_sector"] is None


def test_darvas_pe_uses_screener_sector_pe_when_damodaran_has_none():
    # 1.5 x sector_pe 30 = 45: pe 44 passes (absolute rule would fail it), pe 45 does not
    assert darvas._score(D(pe=44.0, sector_pe=30.0))["criteria"]["pe_vs_sector"] is True
    assert darvas._score(D(pe=45.0, sector_pe=30.0))["criteria"]["pe_vs_sector"] is False


def test_darvas_damodaran_sector_pe_takes_precedence(monkeypatch):
    seen = []
    monkeypatch.setattr(darvas, "get_sector_pe", lambda s: seen.append(s) or 10.0)
    r = darvas._score(D(pe=14.0, sector_pe=100.0, sector="Pharma"))
    assert seen == ["Pharma"]
    assert r["criteria"]["pe_vs_sector"] is True            # 14 < 15
    assert darvas._score(D(pe=15.0, sector_pe=100.0))["criteria"]["pe_vs_sector"] is False


def test_darvas_missing_sector_is_passed_as_empty_string(monkeypatch):
    seen = []
    monkeypatch.setattr(darvas, "get_sector_pe", lambda s: seen.append(s) or None)
    darvas._score(S(cmp=1.0, pe=10.0))
    darvas._score(S(cmp=1.0, pe=10.0, sector=None))
    assert seen == ["", ""]


@pytest.mark.parametrize("score_target, signal", [(7, "BUY"), (6, "WATCH"), (4, "WATCH"), (3, "AVOID")])
def test_darvas_signal_thresholds(score_target, signal):
    # start from a row where nothing passes and then enable criteria one by one
    row = S(cmp=50.0, high_52w=100.0, low_52w=10.0, volume=1, volume_30d_avg=100, roe=1.0,
            net_profit_margin=1.0, debt_to_equity=9.0, promoter_holding=1.0, eps_growth_5y=1.0, pe=99.0)
    enable = [("roe", 20.0), ("net_profit_margin", 20.0), ("debt_to_equity", 0.1),
              ("promoter_holding", 90.0), ("eps_growth_5y", 50.0), ("pe", 10.0), ("volume", 500)]
    base = darvas._score(row)["score"]
    # base: cmp 50 vs high 100 -> C1 no, C2 no, C3 no ; range (50-10)/90 = .44 -> C10 no
    assert base == 0
    for k, v in enable[:score_target]:
        row[k] = v
    r = darvas._score(row)
    assert r["score"] == score_target and r["signal"] == signal


def test_darvas_scan_returns_one_sanitised_result_per_row():
    df = pd.DataFrame([GOOD_DARVAS, {**GOOD_DARVAS, "roe": NAN, "name": "B"}])
    out = darvas.scan(df)
    assert [r["name"] for r in out] == ["Acme", "B"]
    assert out[1]["roe"] is None                       # NaN sanitised for JSON
    assert out[0]["completeness"] > out[1]["completeness"]
    assert darvas.scan(df.iloc[0:0]) == []


# -------------------------------------------------------------- piotroski
def P(**kw):
    return S(**kw)


def test_piotroski_derives_roa_from_profit_over_assets_in_percent():
    r = piotroski._score(P(net_profit=10.0, total_assets=200.0))
    assert r["criteria"]["F1_roa_positive"] is True
    r = piotroski._score(P(net_profit=-10.0, total_assets=200.0))
    assert r["criteria"]["F1_roa_positive"] is False
    assert piotroski._score(P(net_profit=10.0, total_assets=0.0))["criteria"]["F1_roa_positive"] is None
    assert piotroski._score(P())["criteria"]["F1_roa_positive"] is None


def test_piotroski_explicit_roa_is_not_overridden():
    r = piotroski._score(P(roa=-1.0, net_profit=100.0, total_assets=100.0))
    assert r["criteria"]["F1_roa_positive"] is False


def test_piotroski_accrual_test_compares_ocf_yield_with_roa():
    # roa 5 %, ocf/assets 10 % -> low accruals
    assert piotroski._score(P(roa=5.0, ocf=10.0, total_assets=100.0))["criteria"]["F4_low_accruals"] is True
    assert piotroski._score(P(roa=10.0, ocf=10.0, total_assets=100.0))["criteria"]["F4_low_accruals"] is False
    assert piotroski._score(P(roa=5.0, ocf=10.0, total_assets=0.0))["criteria"]["F4_low_accruals"] is None
    assert piotroski._score(P(roa=5.0, ocf=NAN, total_assets=100.0))["criteria"]["F4_low_accruals"] is None


@pytest.mark.parametrize("field, crit, fails_at, passes_at", [
    ("ocf", "F2_ocf_positive", 0.0, 0.1),
    ("current_ratio", "F6_current_ratio", 1.5, 1.51),
    ("opm", "F8_operating_margin", 20.0, 20.1),
])
def test_piotroski_threshold_boundaries(field, crit, fails_at, passes_at):
    assert piotroski._score(P(**{field: fails_at}))["criteria"][crit] is False
    assert piotroski._score(P(**{field: passes_at}))["criteria"][crit] is True
    assert piotroski._score(P(**{field: NAN}))["criteria"][crit] is None


def test_piotroski_leverage_is_strictly_below_half():
    assert piotroski._score(P(debt_to_equity=0.49))["criteria"]["F5_low_leverage"] is True
    assert piotroski._score(P(debt_to_equity=0.5))["criteria"]["F5_low_leverage"] is False


def test_piotroski_f3_and_f7_are_never_evaluated():
    c = piotroski._score(P(roa=5, ocf=5, total_assets=10))["criteria"]
    assert c["F3_roa_improving"] is None and c["F7_no_dilution"] is None


def test_piotroski_asset_turnover_falls_back_to_roe_when_missing():
    assert piotroski._score(P(asset_turnover=0.51))["criteria"]["F9_asset_turnover"] is True
    assert piotroski._score(P(asset_turnover=0.5))["criteria"]["F9_asset_turnover"] is False
    assert piotroski._score(P(roe=15.1))["criteria"]["F9_asset_turnover"] is True
    assert piotroski._score(P(roe=15.0))["criteria"]["F9_asset_turnover"] is False
    assert piotroski._score(P())["criteria"]["F9_asset_turnover"] is None
    # a real turnover value wins over a high ROE
    assert piotroski._score(P(asset_turnover=0.1, roe=99.0))["criteria"]["F9_asset_turnover"] is False


def test_piotroski_opm_falls_back_to_net_margin_when_opm_missing_or_zero():
    assert piotroski._score(P(net_profit_margin=25.0))["criteria"]["F8_operating_margin"] is True
    assert piotroski._score(P(opm=0.0, net_profit_margin=25.0))["criteria"]["F8_operating_margin"] is True


def test_piotroski_score_counts_true_criteria_only():
    full = P(roa=5.0, ocf=10.0, total_assets=100.0, debt_to_equity=0.1, current_ratio=2.0,
             opm=30.0, asset_turnover=1.0)
    r = piotroski._score(full)
    assert r["score"] == 7 and r["max_score"] == 9 and r["signal"] == "WATCH"
    assert r["used_precomputed"] is False


@pytest.mark.parametrize("pre, signal", [(9, "BUY"), (8, "BUY"), (7, "WATCH"), (6, "WATCH"), (5, "AVOID"), (0, "AVOID")])
def test_piotroski_precomputed_score_is_used_with_thresholds(pre, signal):
    r = piotroski._score(P(piotroski_score=pre, roa=-5.0))
    assert r["score"] == pre and r["signal"] == signal and r["used_precomputed"] is True
    assert r["criteria"]["_note"] is None


def test_piotroski_precomputed_float_is_truncated_to_int():
    assert piotroski._score(P(piotroski_score=7.9))["score"] == 7


def test_piotroski_scan_maps_every_row():
    df = pd.DataFrame([{"name": "A", "piotroski_score": 9}, {"name": "B", "roa": 1.0}])
    out = piotroski.scan(df)
    assert [(r["name"], r["signal"]) for r in out] == [("A", "BUY"), ("B", "AVOID")]
    assert out[0]["completeness"] == round(100 / 9, 1)


# -------------------------------------------------------------- coffee can
GOOD_CC = dict(sales_growth_10y=15.0, profit_growth_10y=15.0, roce=20.0, debt_to_equity=0.5,
               promoter_pledge=0.0, market_cap=500.0)


def C(**over):
    d = dict(GOOD_CC)
    d.update(over)
    return S(**d)


def test_coffee_can_buy_requires_all_hard_filters():
    r = coffee_can._score(C())
    assert r["signal"] == "BUY" and r["passed"] is True and r["score"] == 1 and r["max_score"] == 1
    assert set(r["criteria"]) == {"revenue_cagr_gt_10", "profit_cagr_gt_10", "roce_gt_15", "de_lt_1",
                                  "low_promoter_pledge", "min_market_cap"}


@pytest.mark.parametrize("over, key, passes", [
    (dict(sales_growth_10y=10.0), "revenue_cagr_gt_10", False),
    (dict(sales_growth_10y=10.1), "revenue_cagr_gt_10", True),
    (dict(profit_growth_10y=10.0), "profit_cagr_gt_10", False),
    (dict(roce=15.0), "roce_gt_15", False),
    (dict(roce=15.1), "roce_gt_15", True),
    (dict(debt_to_equity=1.0), "de_lt_1", False),
    (dict(debt_to_equity=0.99), "de_lt_1", True),
    (dict(promoter_pledge=10.0), "low_promoter_pledge", False),
    (dict(promoter_pledge=9.9), "low_promoter_pledge", True),
    (dict(market_cap=100.0), "min_market_cap", False),
    (dict(market_cap=100.1), "min_market_cap", True),
])
def test_coffee_can_hard_filter_boundaries(over, key, passes):
    r = coffee_can._score(C(**over))
    assert r["criteria"][key] is passes
    assert (r["signal"] == "BUY") is passes


def test_coffee_can_growth_falls_back_from_10y_to_5y_to_3y_when_zero_or_missing_key():
    # an absent key (not NaN) or a falsy 0 drops through to the next horizon
    assert coffee_can._score(S(sales_growth_5y=12.0))["criteria"]["revenue_cagr_gt_10"] is True
    assert coffee_can._score(S(sales_growth_10y=0.0, sales_growth_3y=12.0))["criteria"]["revenue_cagr_gt_10"] is True
    assert coffee_can._score(S(profit_growth_3y=12.0))["criteria"]["profit_cagr_gt_10"] is True


def test_coffee_can_watch_needs_70_percent_of_evaluated_filters():
    # 4 of 6 pass = 66.7 % -> AVOID ; 5 of 6 = 83 % -> WATCH
    four = coffee_can._score(C(roce=1.0, debt_to_equity=5.0))
    assert four["signal"] == "AVOID" and four["passed"] is False
    five = coffee_can._score(C(roce=1.0))
    assert five["signal"] == "WATCH"


def test_coffee_can_only_evaluated_filters_count():
    # 7 of 10 evaluated is not reachable with 6 filters; use 2 of 2 evaluated -> all passed -> BUY
    r = coffee_can._score(S(roce=20.0, debt_to_equity=0.5))
    assert r["signal"] == "BUY" and r["passed"] is True
    # 1 of 2 evaluated = 50 % -> AVOID
    assert coffee_can._score(S(roce=20.0, debt_to_equity=5.0))["signal"] == "AVOID"


def test_coffee_can_nothing_evaluated_is_avoid_not_buy():
    r = coffee_can._score(S())
    assert r["signal"] == "AVOID" and r["passed"] is False and r["score"] == 0


def test_coffee_can_exact_70_percent_boundary():
    # 7/10 cannot occur with six filters, but 70 % of evaluated >= 0.7 uses >=; 3 of 4 = 75 % WATCH
    r = coffee_can._score(S(roce=20.0, debt_to_equity=0.5, promoter_pledge=0.0, market_cap=5.0))
    assert r["signal"] == "WATCH"


@pytest.mark.parametrize("over, moat", [
    (dict(opm=41.0), 2 + 0), (dict(opm=40.0), 1), (dict(opm=26.0), 1), (dict(opm=25.0), 0),
])
def test_coffee_can_moat_opm_tiers(over, moat):
    row = C(roce=10.0, debt_to_equity=5.0, **over)           # isolate the OPM component
    assert coffee_can._score(row)["moat_score"] == moat


def test_coffee_can_moat_adds_roe_roce_and_low_leverage_points():
    r = coffee_can._score(C(opm=50.0, roe=21.0, roce=26.0, debt_to_equity=0.29))
    assert r["moat_score"] == 2 + 1 + 1 + 1
    r = coffee_can._score(C(opm=50.0, roe=20.0, roce=25.0, debt_to_equity=0.3))     # all on the boundary
    assert r["moat_score"] == 2


def test_coffee_can_moat_opm_falls_back_to_net_margin():
    assert coffee_can._score(S(net_profit_margin=45.0))["moat_score"] == 2


def test_coffee_can_scan_sanitises_and_preserves_order():
    df = pd.DataFrame([{**GOOD_CC, "name": "A", "pe": NAN}, {**GOOD_CC, "name": "B", "roce": 1.0}])
    out = coffee_can.scan(df)
    assert [(r["name"], r["signal"]) for r in out] == [("A", "BUY"), ("B", "WATCH")]
    assert out[0]["pe"] is None


# -------------------------------------------------------------- source bugs
@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="coffee_can.py:H1/H2 use `row.get('sales_growth_10y') or row.get('sales_growth_5y') ...`; "
           "a NaN 10Y value is truthy, so the documented 10Y -> 5Y -> 3Y fallback never happens for "
           "the NaN that normalize_columns() produces for blank Screener cells.")
def test_coffee_can_growth_fallback_works_for_nan_cells():
    row = C(sales_growth_10y=NAN, sales_growth_5y=20.0, profit_growth_10y=NAN, profit_growth_5y=20.0)
    c = coffee_can._score(row)["criteria"]
    assert c["revenue_cagr_gt_10"] is True and c["profit_cagr_gt_10"] is True


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="darvas.py:C8 chains `eps_growth_5y or profit_growth_5y or profit_growth_3y`; NaN is "
           "truthy so a blank EPS-growth cell blocks the profit-growth fallback.")
def test_darvas_eps_growth_falls_back_to_profit_growth_for_nan_cells():
    row = D(eps_growth_5y=NAN, profit_growth_5y=20.0)
    assert darvas._score(row)["criteria"]["eps_growth_gt_10"] is True
