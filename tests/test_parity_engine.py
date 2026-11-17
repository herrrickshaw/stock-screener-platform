"""Characterisation tests for put-call parity maths (no broker, no network)."""
from __future__ import annotations

import json
import math
from pathlib import Path

from put_call_parity import parity_engine as pe
from put_call_parity.config import INSTRUMENTS

GOLDEN = json.loads((Path(__file__).parent / "golden" / "parity.golden").read_text())


def _chain():
    quotes = {50000: (1200, 1210, 150, 156), 50100: (1130, 1140, 190, 200), 49900: (1300, 1312, 120, 125)}
    rows = []
    for k, (cb, ca, pb, pa) in quotes.items():
        rows.append(dict(strike=k, instrument_type="CE", bid=cb, ask=ca, oi=900, tradingsymbol=f"C{k}"))
        rows.append(dict(strike=k, instrument_type="PE", bid=pb, ask=pa, oi=800, tradingsymbol=f"P{k}"))
    return rows


def test_scan_matches_golden():
    eng = pe.ParityEngine(r=0.065)
    eng._dte = lambda expiry: 12.0
    sigs = eng.scan(GOLDEN["key"], _chain(), 51000.0, "FUT", "2099-01-01", min_oi=500)
    assert [s.__dict__ for s in sigs] == GOLDEN["sigs"]


def test_scalar_maths_match_golden():
    cfg = INSTRUMENTS[GOLDEN["key"]]
    assert pe.estimate_transaction_cost(cfg, 2, 1200.0, 150.0, 51000.0) == GOLDEN["cost"]
    assert pe.theoretical_cp_spread(51000, 50000, 0.065, 12) == GOLDEN["th"]
    assert pe.discount_factor(0.065, 30) == GOLDEN["df"]


def test_discount_factor_zero_rate_is_one():
    assert pe.discount_factor(0.0, 100) == 1.0
    assert math.isclose(pe.discount_factor(0.1, 365), math.exp(-0.1))


def test_illiquid_strikes_filtered():
    eng = pe.ParityEngine()
    eng._dte = lambda expiry: 10.0
    chain = [dict(r, oi=1) for r in _chain()]
    assert eng.scan(GOLDEN["key"], chain, 51000.0, "FUT", "2099-01-01", min_oi=500) == []


def test_observed_spread_directions():
    assert pe.observed_cp_spread(10, 12, 3, 4, "LONG_CALL_SHORT_PUT") == 12 - 3
    assert pe.observed_cp_spread(10, 12, 3, 4, "SHORT_CALL_LONG_PUT") == 10 - 4
    assert pe.observed_cp_spread(10, 12, 3, 4, "NONE") == 11 - 3.5


def test_check_exit_profit_target_and_stop_loss():
    eng = pe.ParityEngine(r=0.0)
    eng._dte = lambda expiry: 10.0
    sig = pe.ParitySignal("X", "2099-01-01", 100.0, 10.0, 100.0, 5, 5, "c", "p", "f",
                          0, 0, 0, 0, 0, "NONE", 1)
    args = dict(entry_deviation=10.0, exit_fraction=0.2, stop_loss_multiple=2.0)
    assert eng.check_exit(sig, 5, 5, 5, 5, 100.0, **args)[0] is True      # dev 0 -> profit
    stop = eng.check_exit(sig, 30, 30, 5, 5, 100.0, **args)               # dev 25 -> stop
    assert stop[0] and stop[1].startswith("STOP_LOSS")
    assert eng.check_exit(sig, 15, 15, 5, 5, 100.0, **args) == (False, "")  # dev 10


def test_dte_is_calendar_days_floored_for_expiry_day():
    from datetime import date
    eng = pe.ParityEngine()
    assert eng._dte("2026-01-31", today=date(2026, 1, 1)) == 30.0
    assert eng._dte("2026-01-01", today=date(2026, 1, 1)) == 0.001
    assert eng._dte("2025-12-01", today=date(2026, 1, 1)) == 0.001
