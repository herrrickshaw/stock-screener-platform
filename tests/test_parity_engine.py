"""Unit tests for put_call_parity/parity_engine.py (pure maths + signal scan).

put_call_parity/config.py holds broker credentials, so it is never imported here: a stub
module with a synthetic instrument and cost model is injected in its place. The futures-leg
side (conversion vs reversal) is covered by open PR #22 and not tested here."""
import importlib
import math
import sys
import types
from dataclasses import dataclass
from datetime import date, timedelta

import pytest


@dataclass
class _Instr:
    lot_size: int = 15
    contract_value_multiplier: int = 1
    exchange: str = "NSE"
    min_deviation: float = 10.0
    max_lots: int = 5


@dataclass
class _Costs:
    brokerage_per_order: float = 20.0
    stt_options_sell_rate: float = 0.0
    stt_futures_rate: float = 0.0
    exchange_charge_nse: float = 0.0
    exchange_charge_mcx: float = 0.0
    gst_rate: float = 0.0
    sebi_rate: float = 0.0


@pytest.fixture
def pe(monkeypatch):
    cfg = types.ModuleType("put_call_parity.config")
    cfg.InstrumentConfig = _Instr
    cfg.COST_MODEL = _Costs()
    cfg.INSTRUMENTS = {"TEST": _Instr()}
    cfg.RISK_FREE_RATE = 0.0
    monkeypatch.setitem(sys.modules, "put_call_parity.config", cfg)
    monkeypatch.delitem(sys.modules, "put_call_parity.parity_engine", raising=False)
    mod = importlib.import_module("put_call_parity.parity_engine")
    yield mod
    sys.modules.pop("put_call_parity.parity_engine", None)


def _chain(strike, cb, ca, pb, pa, oi=1000):
    return [
        {"strike": strike, "instrument_type": "CE", "bid": cb, "ask": ca, "oi": oi,
         "tradingsymbol": f"X{int(strike)}CE"},
        {"strike": strike, "instrument_type": "PE", "bid": pb, "ask": pa, "oi": oi,
         "tradingsymbol": f"X{int(strike)}PE"},
    ]


def _expiry(days=10):
    return (date.today() + timedelta(days=days)).isoformat()


def test_discount_factor(pe):
    assert pe.discount_factor(0.0, 30) == 1.0
    assert pe.discount_factor(0.073, 365) == pytest.approx(math.exp(-0.073))


def test_theoretical_spread_is_discounted_f_minus_k(pe):
    assert pe.theoretical_cp_spread(50150, 50000, 0.0, 10) == pytest.approx(150.0)
    assert pe.theoretical_cp_spread(50150, 50000, 0.073, 365) == pytest.approx(150 * math.exp(-0.073))


def test_observed_spread_uses_the_trading_side(pe):
    assert pe.observed_cp_spread(419, 421, 199, 201, "LONG_CALL_SHORT_PUT") == 421 - 199
    assert pe.observed_cp_spread(419, 421, 199, 201, "SHORT_CALL_LONG_PUT") == 419 - 201
    assert pe.observed_cp_spread(419, 421, 199, 201, "NONE") == 220


def test_option_matrix_drops_strikes_without_both_legs(pe):
    chain = _chain(50000, 1, 2, 1, 2) + [{"strike": 50100, "instrument_type": "CE", "bid": 1,
                                          "ask": 2, "oi": 9, "tradingsymbol": "ONLYCE"}]
    m = pe.ParityEngine(r=0.0).build_option_matrix(chain)
    assert list(m) == [50000.0]


def test_scan_flags_expensive_call(pe):
    # C - P = 220 vs F - K = 150 -> raw deviation +70 (> 10) -> short call / long put
    sig = pe.ParityEngine(r=0.0).scan("TEST", _chain(50000, 419, 421, 199, 201), 50150, "XFUT",
                                      _expiry())
    assert len(sig) == 1
    s = sig[0]
    assert s.direction == "SHORT_CALL_LONG_PUT"
    assert s.raw_deviation == pytest.approx(70.0)
    assert s.lots == 5                              # min(int(70/10), max_lots=5)
    assert s.net_deviation == pytest.approx(70.0 - s.transaction_cost)


def test_scan_flags_expensive_put(pe):
    sig = pe.ParityEngine(r=0.0).scan("TEST", _chain(50000, 279, 281, 199, 201), 50150, "XFUT",
                                      _expiry())
    assert sig[0].direction == "LONG_CALL_SHORT_PUT"
    assert sig[0].raw_deviation == pytest.approx(-70.0)


def test_scan_ignores_small_deviation_and_illiquid_strikes(pe):
    eng = pe.ParityEngine(r=0.0)
    assert eng.scan("TEST", _chain(50000, 154, 156, 0.5, 1.5), 50150, "F", _expiry()) == []   # dev 4
    assert eng.scan("TEST", _chain(50000, 419, 421, 199, 201, oi=10), 50150, "F", _expiry()) == []
    assert eng.scan("TEST", _chain(50000, 0, 421, 199, 201), 50150, "F", _expiry()) == []      # no bid


def test_brokerage_is_flat_per_order_not_per_lot(pe):
    """'brokerage (flat per order ...)': 3 legs x entry+exit = 6 orders whatever the lot count.
    With every other cost rate zero, 1 lot and 5 lots must cost the same 6 x 20."""
    cfg = _Instr()
    one = pe.estimate_transaction_cost(cfg, 1, 420, 200, 50150)
    five = pe.estimate_transaction_cost(cfg, 5, 420, 200, 50150)
    assert one == pytest.approx(120.0)
    assert five == pytest.approx(120.0)


def test_variable_costs_scale_with_lots(pe, monkeypatch):
    pe.COST_MODEL.brokerage_per_order = 0.0
    pe.COST_MODEL.stt_futures_rate = 0.0001
    cfg = _Instr()
    one = pe.estimate_transaction_cost(cfg, 1, 420, 200, 50000)
    # futures notional 50000*15 = 750000; STT both sides = 750000 * 0.0001 * 2 = 150
    assert one == pytest.approx(150.0)
    assert pe.estimate_transaction_cost(cfg, 4, 420, 200, 50000) == pytest.approx(600.0)


def test_check_exit_profit_target_and_stop(pe):
    eng = pe.ParityEngine(r=0.0)
    s = eng.scan("TEST", _chain(50000, 419, 421, 199, 201), 50150, "F", _expiry())[0]
    # deviation back to 0 -> profit target (0.25 x 70)
    ok, why = eng.check_exit(s, 154, 156, 4, 6, 50150, 70.0, 0.25, 3.0)
    assert ok and why.startswith("PROFIT_TARGET")
    # deviation 250 >= 3 x 70 -> stop loss
    ok, why = eng.check_exit(s, 399, 401, 0, 0, 50150, 70.0, 0.25, 3.0)
    assert ok and why.startswith("STOP_LOSS")
    ok, _ = eng.check_exit(s, 219, 221, 19, 21, 50150, 70.0, 0.25, 3.0)   # dev 50: hold
    assert not ok
