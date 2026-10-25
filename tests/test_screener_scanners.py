"""Unit tests for the Screener.in-CSV scanners: scanners/darvas.py, piotroski.py, coffee_can.py.

Rows come from column_map.normalize_columns, which coerces blank cells to NaN, so a 'missing'
field is NaN, not absent. Expected values are hand-computed from each module's docstring."""
import numpy as np
import pandas as pd
import pytest

import scanners.darvas as darvas
from scanners import coffee_can, piotroski


@pytest.fixture(autouse=True)
def no_damodaran(monkeypatch):
    monkeypatch.setattr(darvas, "get_sector_pe", lambda sector: None)


def _scan(mod, **kw):
    return mod.scan(pd.DataFrame([kw]))[0]


# ── Darvas + Buffett (0-10) ───────────────────────────────────────────────────

GOOD_DARVAS = dict(cmp=99.0, high_52w=100.0, low_52w=50.0, volume=2000, volume_30d_avg=1000,
                   roe=20.0, net_profit_margin=12.0, debt_to_equity=0.2, promoter_holding=60.0,
                   eps_growth_5y=15.0, pe=20.0)


def test_darvas_all_pass_is_ten_and_buy():
    r = _scan(darvas, **GOOD_DARVAS)
    assert r["score"] == 10 and r["signal"] == "BUY"


def test_darvas_bands():
    assert _scan(darvas, **dict(GOOD_DARVAS, roe=1.0, debt_to_equity=2.0, promoter_holding=1.0))["signal"] == "BUY"   # 7
    six = dict(GOOD_DARVAS, roe=1.0, debt_to_equity=2.0, promoter_holding=1.0, pe=80.0)
    assert _scan(darvas, **six)["score"] == 6
    assert _scan(darvas, **six)["signal"] == "WATCH"


def test_darvas_near_high_within_3pct():
    assert _scan(darvas, **dict(GOOD_DARVAS, cmp=97.0))["criteria"]["price_near_52w_high"] is True
    assert _scan(darvas, **dict(GOOD_DARVAS, cmp=96.9))["criteria"]["price_near_52w_high"] is False


def test_darvas_missing_values_are_unevaluated():
    r = _scan(darvas, cmp=99.0, high_52w=np.nan, roe=np.nan)
    assert r["criteria"]["price_near_52w_high"] is None
    assert r["criteria"]["roe_gt_15"] is None


def test_darvas_eps_growth_falls_back_when_5y_is_blank():
    r = _scan(darvas, **dict(GOOD_DARVAS, eps_growth_5y=np.nan, profit_growth_5y=20.0))
    assert r["criteria"]["eps_growth_gt_10"] is True


def test_darvas_zero_eps_growth_is_a_value_not_missing():
    r = _scan(darvas, **dict(GOOD_DARVAS, eps_growth_5y=0.0, profit_growth_5y=20.0))
    assert r["criteria"]["eps_growth_gt_10"] is False


def test_darvas_pe_absolute_fallback_without_sector_pe():
    assert _scan(darvas, **dict(GOOD_DARVAS, pe=34.0))["criteria"]["pe_vs_sector"] is True
    assert _scan(darvas, **dict(GOOD_DARVAS, pe=36.0))["criteria"]["pe_vs_sector"] is False


# ── Piotroski (0-9, F3/F7 not computable from a snapshot) ─────────────────────

GOOD_PIO = dict(roa=10.0, ocf=200.0, total_assets=1000.0, debt_to_equity=0.2, current_ratio=2.0,
                opm=25.0, asset_turnover=1.0)


def test_piotroski_roa_derived_from_profit_and_assets():
    r = _scan(piotroski, net_profit=50.0, total_assets=1000.0, ocf=100.0)
    assert r["criteria"]["F1_roa_positive"] is True
    # OCF/assets = 10% > ROA 5% -> low accruals
    assert r["criteria"]["F4_low_accruals"] is True


def test_piotroski_precomputed_score_wins():
    r = _scan(piotroski, piotroski_score=8, roa=-1.0)
    assert r["score"] == 8 and r["signal"] == "BUY" and r["used_precomputed"] is True


def test_piotroski_margin_falls_back_to_npm_when_opm_blank():
    r = _scan(piotroski, **dict(GOOD_PIO, opm=np.nan, net_profit_margin=25.0))
    assert r["criteria"]["F8_operating_margin"] is True


def test_piotroski_computed_best_case_scores_seven():
    r = _scan(piotroski, **GOOD_PIO)
    assert r["score"] == 7


@pytest.mark.xfail(strict=True, reason="BUY needs >= 8 but only 7 criteria are computable "
                                       "(F3, F7 always None): a computed score can never be BUY")
def test_piotroski_computed_best_case_can_reach_buy():
    assert _scan(piotroski, **GOOD_PIO)["signal"] == "BUY"


# ── Coffee Can ────────────────────────────────────────────────────────────────

GOOD_CC = dict(sales_growth_10y=12.0, profit_growth_10y=15.0, roce=30.0, debt_to_equity=0.2,
               promoter_pledge=0.0, market_cap=5000.0, opm=45.0, roe=25.0)


def test_coffee_can_all_pass_buy_and_moat():
    r = _scan(coffee_can, **GOOD_CC)
    assert r["signal"] == "BUY" and r["passed"] is True
    assert r["moat_score"] == 2 + 1 + 1 + 1


def test_coffee_can_one_failure_of_six_is_watch():
    r = _scan(coffee_can, **dict(GOOD_CC, roce=10.0))
    assert r["signal"] == "WATCH"     # 5/6 = 0.83 >= 0.7


def test_coffee_can_sales_growth_falls_back_when_10y_blank():
    r = _scan(coffee_can, **dict(GOOD_CC, sales_growth_10y=np.nan, sales_growth_5y=5.0))
    assert r["criteria"]["revenue_cagr_gt_10"] is False


def test_coffee_can_profit_growth_falls_back_when_10y_blank():
    r = _scan(coffee_can, **dict(GOOD_CC, profit_growth_10y=np.nan, profit_growth_5y=20.0))
    assert r["criteria"]["profit_cagr_gt_10"] is True


def test_coffee_can_no_data_is_avoid():
    r = _scan(coffee_can, ticker="X")
    assert r["signal"] == "AVOID" and r["passed"] is False
