"""Offline tests for put_call_parity.parity_engine: maths, option matrix, scan, exit rules."""
import math
from datetime import date as real_date

import pytest

from put_call_parity import parity_engine as pe
from put_call_parity.config import COST_MODEL, INSTRUMENTS, InstrumentConfig
from put_call_parity.parity_engine import (
    OptionRow,
    ParityEngine,
    ParitySignal,
    discount_factor,
    estimate_transaction_cost,
    observed_cp_spread,
    theoretical_cp_spread,
)


class FrozenDate(real_date):
    """date.today() pinned to 2026-11-01 so DTE is deterministic."""

    @classmethod
    def today(cls):
        return cls(2026, 11, 1)


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(pe, "date", FrozenDate)


def _chain(strike, ce_bid, ce_ask, pe_bid, pe_ask, ce_oi=1000, pe_oi=1000, tag=""):
    return [
        {"strike": strike, "instrument_type": "CE", "bid": ce_bid, "ask": ce_ask,
         "oi": ce_oi, "tradingsymbol": f"CE{tag or int(strike)}"},
        {"strike": strike, "instrument_type": "PE", "bid": pe_bid, "ask": pe_ask,
         "oi": pe_oi, "tradingsymbol": f"PE{tag or int(strike)}"},
    ]


# ---------------------------------------------------------------- core maths
def test_discount_factor_zero_rate_and_zero_time_are_one():
    assert discount_factor(0.0, 100) == 1.0
    assert discount_factor(0.07, 0) == 1.0


def test_discount_factor_uses_calendar_year_of_365_days():
    assert discount_factor(0.1, 365) == pytest.approx(math.exp(-0.1))
    assert discount_factor(0.1, 73) == pytest.approx(math.exp(-0.1 * 73 / 365))


def test_theoretical_spread_sign_and_discounting():
    assert theoretical_cp_spread(150.0, 100.0, 0.0, 30) == 50.0
    assert theoretical_cp_spread(90.0, 100.0, 0.0, 30) == -10.0   # futures below strike
    assert theoretical_cp_spread(150.0, 100.0, 0.1, 365) == pytest.approx(50 * math.exp(-0.1))


def test_observed_spread_uses_the_trading_side_of_the_book():
    args = dict(call_bid=10.0, call_ask=12.0, put_bid=4.0, put_ask=6.0)
    assert observed_cp_spread(**args, direction="LONG_CALL_SHORT_PUT") == 12.0 - 4.0
    assert observed_cp_spread(**args, direction="SHORT_CALL_LONG_PUT") == 10.0 - 6.0
    assert observed_cp_spread(**args, direction="NONE") == 11.0 - 5.0
    assert observed_cp_spread(**args, direction="anything else") == 11.0 - 5.0


# --------------------------------------------------------- transaction costs
def _expected_cost(cfg, lots, call_mid, put_mid, fut):
    cm = COST_MODEL
    mult = cfg.contract_value_multiplier if cfg.contract_value_multiplier > 1 else cfg.lot_size
    notional = fut * mult
    brokerage = cm.brokerage_per_order * 6
    opt_stt = (call_mid + put_mid) * cfg.lot_size * cm.stt_options_sell_rate * 2
    fut_stt = notional * cm.stt_futures_rate * 2
    rate = cm.exchange_charge_nse if cfg.exchange == "NSE" else cm.exchange_charge_mcx
    exch = (call_mid + put_mid) * cfg.lot_size * rate * 2 + notional * rate * 2
    gst = (brokerage + exch) * cm.gst_rate
    sebi = (call_mid + put_mid) * cfg.lot_size * cm.sebi_rate * 2 + notional * cm.sebi_rate * 2
    return (brokerage + opt_stt + fut_stt + exch + gst + sebi) * lots


@pytest.mark.parametrize("key", ["BANKNIFTY", "CRUDEOIL", "SILVER"])
def test_transaction_cost_matches_independent_formula(key):
    cfg = INSTRUMENTS[key]
    got = estimate_transaction_cost(cfg, 1, 420.0, 200.0, 50_000.0)
    assert got == pytest.approx(_expected_cost(cfg, 1, 420.0, 200.0, 50_000.0))


def test_transaction_cost_scales_linearly_with_lots():
    cfg = INSTRUMENTS["BANKNIFTY"]
    one = estimate_transaction_cost(cfg, 1, 100.0, 80.0, 50_000.0)
    assert estimate_transaction_cost(cfg, 7, 100.0, 80.0, 50_000.0) == pytest.approx(7 * one)


def test_exchange_charge_depends_on_exchange():
    base = dict(name="x", segment="s", underlying_symbol="x", futures_symbol="x",
                option_symbol="x", lot_size=10, tick_size=1, max_lots=1,
                min_deviation=1, exit_fraction=0.2, stop_loss_multiple=2)
    nse = InstrumentConfig(exchange="NSE", **base)
    mcx = InstrumentConfig(exchange="MCX", **base)
    assert (estimate_transaction_cost(nse, 1, 50, 50, 1000)
            > estimate_transaction_cost(mcx, 1, 50, 50, 1000))


def test_multiplier_of_exactly_one_falls_back_to_lot_size():
    base = dict(name="x", exchange="MCX", segment="s", underlying_symbol="x", futures_symbol="x",
                option_symbol="x", lot_size=10, tick_size=1, max_lots=1,
                min_deviation=1, exit_fraction=0.2, stop_loss_multiple=2)
    one = InstrumentConfig(contract_value_multiplier=1.0, **base)
    two = InstrumentConfig(contract_value_multiplier=2.0, **base)
    ref_lot = InstrumentConfig(contract_value_multiplier=10.0, **base)
    assert estimate_transaction_cost(one, 1, 0, 0, 1000) == pytest.approx(
        estimate_transaction_cost(ref_lot, 1, 0, 0, 1000))
    assert estimate_transaction_cost(two, 1, 0, 0, 1000) < estimate_transaction_cost(one, 1, 0, 0, 1000)


# ------------------------------------------------------------- option matrix
def test_build_option_matrix_pairs_ce_and_pe_per_strike():
    chain = _chain(100, 5, 6, 3, 4, ce_oi=700, pe_oi=900) + _chain(200, 1, 2, 7, 8)
    m = ParityEngine().build_option_matrix(chain)
    assert sorted(m) == [100.0, 200.0]
    row = m[100.0]
    assert isinstance(row, OptionRow)
    assert (row.call_bid, row.call_ask, row.call_oi, row.call_symbol) == (5.0, 6.0, 700, "CE100")
    assert (row.put_bid, row.put_ask, row.put_oi, row.put_symbol) == (3.0, 4.0, 900, "PE100")


def test_build_option_matrix_drops_strikes_missing_a_leg():
    chain = _chain(100, 5, 6, 3, 4)[:1] + _chain(200, 1, 2, 7, 8)
    assert list(ParityEngine().build_option_matrix(chain)) == [200.0]


def test_build_option_matrix_treats_none_and_missing_quotes_as_zero():
    chain = [
        {"strike": 100, "instrument_type": "CE", "bid": None, "ask": None, "oi": None,
         "tradingsymbol": "C"},
        {"strike": 100, "instrument_type": "PE", "tradingsymbol": "P"},
    ]
    row = ParityEngine().build_option_matrix(chain)[100.0]
    assert (row.call_bid, row.call_ask, row.call_oi) == (0.0, 0.0, 0)
    assert (row.put_bid, row.put_ask, row.put_oi) == (0.0, 0.0, 0)


def test_build_option_matrix_ignores_unknown_instrument_types_and_empty_input():
    chain = [{"strike": 100, "instrument_type": "FUT", "tradingsymbol": "F"}]
    assert ParityEngine().build_option_matrix(chain) == {}
    assert ParityEngine().build_option_matrix([]) == {}


def test_build_option_matrix_accepts_string_strikes():
    chain = _chain("100", 5, 6, 3, 4)
    assert list(ParityEngine().build_option_matrix(chain)) == [100.0]


# ----------------------------------------------------------------------- dte
def test_dte_counts_calendar_days(frozen_today):
    e = ParityEngine()
    assert e._dte("2026-11-29") == 28.0
    assert e._dte("2026-11-02") == 1.0


def test_dte_floors_at_a_millionth_of_nothing_on_or_after_expiry(frozen_today):
    e = ParityEngine()
    assert e._dte("2026-11-01") == 0.001
    assert e._dte("2026-10-01") == 0.001


# ----------------------------------------------------------------- liquidity
def _row(call_oi=1000, put_oi=1000, cb=1, ca=2, pb=1, pa=2):
    return OptionRow(100, cb, ca, call_oi, pb, pa, put_oi, "C", "P")


def test_liquidity_requires_min_oi_on_both_sides_inclusive():
    e, cfg = ParityEngine(), INSTRUMENTS["BANKNIFTY"]
    assert e._liquidity_ok(_row(500, 500), cfg, 500)
    assert not e._liquidity_ok(_row(499, 500), cfg, 500)
    assert not e._liquidity_ok(_row(500, 499), cfg, 500)


@pytest.mark.parametrize("kw", [dict(cb=0), dict(ca=0), dict(pb=0), dict(pa=0)])
def test_liquidity_requires_all_four_quotes_positive(kw):
    assert not ParityEngine()._liquidity_ok(_row(**kw), INSTRUMENTS["BANKNIFTY"], 1)


# ------------------------------------------------------------------ lot size
def test_pick_lots_scales_with_deviation_and_is_capped():
    e, cfg = ParityEngine(), INSTRUMENTS["BANKNIFTY"]   # min_deviation 30, max_lots 50
    assert e._pick_lots(cfg, 30.0) == 1
    assert e._pick_lots(cfg, 29.0) == 1            # floor of 0 still gives one lot
    assert e._pick_lots(cfg, 90.0) == 3
    assert e._pick_lots(cfg, 89.9) == 2
    assert e._pick_lots(cfg, 30.0 * 50) == 50
    assert e._pick_lots(cfg, 30.0 * 500) == 50     # capped at max_lots


# ---------------------------------------------------------------------- scan
def _scan(chain, fut=50_000.0, r=0.0, min_oi=500, key="BANKNIFTY", expiry="2026-11-29"):
    return ParityEngine(r=r).scan(key, chain, fut, "BANKNIFTY-FUT", expiry, min_oi=min_oi)


# BANKNIFTY: min_deviation 30, lot 15.  Round-trip cost is ~Rs 80 per unit (the 0.05 % exchange
# charge on the futures notional dominates), so a signal needs a raw edge well above 80.
RICH_CALLS = _chain(49_850, 500, 500, 150, 150)    # C-P = 350 vs F-K = 150  -> dev +200
RICH_PUTS = _chain(49_850, 150, 150, 500, 500)     # C-P = -350 vs 150       -> dev -500


def test_scan_short_call_long_put_when_calls_are_rich(frozen_today):
    sigs = _scan(RICH_CALLS)
    assert len(sigs) == 1
    s = sigs[0]
    assert isinstance(s, ParitySignal)
    assert s.direction == "SHORT_CALL_LONG_PUT"
    assert s.raw_deviation == pytest.approx(200.0)
    assert s.theoretical_spread == pytest.approx(150.0)
    assert s.observed_spread == pytest.approx(350.0)
    assert (s.call_mid, s.put_mid) == (500.0, 150.0)
    assert s.dte == 28.0 and s.expiry == "2026-11-29" and s.strike == 49_850.0
    assert (s.call_symbol, s.put_symbol, s.futures_symbol) == ("CE49850", "PE49850", "BANKNIFTY-FUT")
    assert s.futures_price == 50_000.0 and s.instrument == "BANKNIFTY"
    assert s.lots == 6                                   # int(200 / 30)
    per_unit = estimate_transaction_cost(INSTRUMENTS["BANKNIFTY"], 6, 500, 150, 50_000.0) / (6 * 15)
    assert s.transaction_cost == pytest.approx(per_unit)
    assert s.net_deviation == pytest.approx(200.0 - per_unit)


def test_scan_long_call_short_put_when_puts_are_rich(frozen_today):
    sigs = _scan(RICH_PUTS)
    assert [s.direction for s in sigs] == ["LONG_CALL_SHORT_PUT"]
    assert sigs[0].raw_deviation == pytest.approx(-500.0)
    assert sigs[0].lots == 16                             # int(500 / 30)
    assert sigs[0].net_deviation == pytest.approx(500.0 - sigs[0].transaction_cost)


def test_scan_discounts_the_futures_spread_by_the_risk_free_rate(frozen_today):
    plain = _scan(RICH_CALLS, r=0.0)[0]
    disc = _scan(RICH_CALLS, r=0.10)[0]
    assert disc.theoretical_spread == pytest.approx(150.0 * math.exp(-0.10 * 28 / 365))
    assert disc.raw_deviation > plain.raw_deviation


def test_scan_returns_nothing_inside_the_min_deviation_band(frozen_today):
    # dev exactly +30 and exactly -30: the comparison is strict, so no trade
    assert _scan(_chain(49_850, 440, 440, 260, 260)) == []
    assert _scan(_chain(49_850, 380, 380, 260, 260)) == []
    assert _scan(_chain(49_850, 410, 410, 260, 260)) == []      # dev 0


def test_scan_drops_signals_whose_edge_does_not_cover_costs(frozen_today):
    # dev +40 clears min_deviation but is below the ~80/unit cost of the 3-leg package
    assert _scan(_chain(49_850, 450, 450, 260, 260)) == []


def test_scan_skips_illiquid_strikes(frozen_today):
    assert _scan(_chain(49_850, 500, 500, 150, 150, ce_oi=499), min_oi=500) == []
    assert len(_scan(_chain(49_850, 500, 500, 150, 150, ce_oi=500), min_oi=500)) == 1
    assert _scan(_chain(49_850, 0, 500, 150, 150)) == []         # no call bid


def test_scan_default_min_oi_is_500(frozen_today):
    chain = _chain(49_850, 500, 500, 150, 150, ce_oi=499)
    assert ParityEngine(r=0.0).scan("BANKNIFTY", chain, 50_000.0, "F", "2026-11-29") == []


def test_scan_sorts_by_net_deviation_descending(frozen_today):
    chain = (_chain(49_850, 500, 500, 150, 150, tag="a")           # dev +200
             + _chain(49_900, 700, 700, 100, 100, tag="b")        # C-P 600 vs 100 -> +500
             + _chain(49_800, 450, 450, 100, 100, tag="c"))       # 350 vs 200 -> +150
    sigs = _scan(chain)
    nets = [s.net_deviation for s in sigs]
    assert nets == sorted(nets, reverse=True)
    assert [s.strike for s in sigs] == [49_900.0, 49_850.0, 49_800.0]


def test_scan_caps_lots_at_instrument_max(frozen_today):
    huge = _chain(49_850, 5_000, 5_000, 100, 100)                 # dev ~4750 -> int(158) lots
    assert _scan(huge)[0].lots == INSTRUMENTS["BANKNIFTY"].max_lots == 50


def test_scan_works_for_mcx_instruments(frozen_today):
    # CRUDEOIL: min_deviation 5, lot 100, multiplier 100, MCX exchange charge
    chain = _chain(6_000, 300, 300, 60, 60)                       # C-P 240 vs F-K 100 -> +140
    sigs = ParityEngine(r=0.0).scan("CRUDEOIL", chain, 6_100.0, "CRUDE-FUT", "2026-11-29")
    assert len(sigs) == 1 and sigs[0].direction == "SHORT_CALL_LONG_PUT"
    assert sigs[0].lots == 20                                     # int(140/5)=28 capped at 20


def test_scan_unknown_instrument_raises_keyerror():
    with pytest.raises(KeyError):
        ParityEngine().scan("NOPE", [], 1.0, "F", "2026-11-29")


def test_engine_default_rate_is_the_configured_rate():
    from put_call_parity.config import RISK_FREE_RATE
    assert ParityEngine().r == RISK_FREE_RATE


# ---------------------------------------------------------------- check_exit
def _sig(strike=100.0, expiry="2026-11-29"):
    return ParitySignal("BANKNIFTY", expiry, strike, 28.0, 150.0, 0, 0, "C", "P", "F",
                        0, 0, 0, 0, 0, "SHORT_CALL_LONG_PUT", 1)


def _exit(engine, c, p, fut, entry_dev=40.0, frac=0.25, sl=2.0, strike=100.0):
    """c, p are (bid, ask).  Theoretical spread is fut - strike (r = 0)."""
    return engine.check_exit(_sig(strike), c[0], c[1], p[0], p[1], fut, entry_dev, frac, sl)


def test_check_exit_takes_profit_at_or_below_target(frozen_today):
    e = ParityEngine(r=0.0)
    # target = 40 * .25 = 10 ; obs 5 ; theo 0 -> dev 5
    ok, why = _exit(e, (10, 10), (5, 5), 100.0)
    assert ok and why == "PROFIT_TARGET (dev=5.00 <= target=10.00)"
    # dev exactly equal to the target still exits (<=)
    ok, why = _exit(e, (15, 15), (5, 5), 100.0)
    assert ok and why.startswith("PROFIT_TARGET")


def test_check_exit_stops_out_at_or_above_stop_loss(frozen_today):
    e = ParityEngine(r=0.0)
    # sl = 40 * 2 = 80
    ok, why = _exit(e, (90, 90), (10, 10), 100.0)           # dev 80 -> equals sl
    assert ok and why == "STOP_LOSS (dev=80.00 >= sl=80.00)"
    ok, why = _exit(e, (200, 200), (10, 10), 100.0)
    assert ok and why.startswith("STOP_LOSS")


def test_check_exit_holds_between_target_and_stop(frozen_today):
    ok, why = _exit(ParityEngine(r=0.0), (40, 40), (5, 5), 100.0)   # dev 35
    assert (ok, why) == (False, "")


def test_check_exit_deviation_is_absolute_and_entry_sign_is_ignored(frozen_today):
    e = ParityEngine(r=0.0)
    ok, _ = _exit(e, (5, 5), (60, 60), 100.0, entry_dev=-40.0)       # obs -55 -> |55| holds
    assert ok is False
    ok, why = _exit(e, (5, 5), (100, 100), 100.0, entry_dev=-40.0)   # obs -95 -> 95 >= 80
    assert ok and why.startswith("STOP_LOSS")


def test_check_exit_uses_mid_prices_not_one_side(frozen_today):
    e = ParityEngine(r=0.0)
    ok, why = _exit(e, (0, 20), (5, 5), 100.0)     # call mid 10 -> obs 5 -> dev 5 -> profit
    assert ok and "dev=5.00" in why


def test_check_exit_theoretical_uses_current_futures_and_signal_strike(frozen_today):
    e = ParityEngine(r=0.0)
    ok, why = _exit(e, (60, 60), (10, 10), 150.0)   # theo 50 ; obs 50 -> dev 0 -> profit
    assert ok and "dev=0.00" in why
    ok, why = _exit(e, (60, 60), (10, 10), 150.0, strike=120.0)   # theo 30 ; dev 20 -> hold
    assert (ok, why) == (False, "")


# --------------------------------------------- min_deviation boundary (cheap instrument)
@pytest.fixture
def cheap_instrument(monkeypatch):
    """A contract whose round-trip cost is ~0.1/unit, so min_deviation (5.0) is the binding gate."""
    cfg = InstrumentConfig(name="T", exchange="MCX", segment="MCX-FO", underlying_symbol="T",
                           futures_symbol="T", option_symbol="T", lot_size=100_000, tick_size=0.01,
                           max_lots=10, min_deviation=5.0, exit_fraction=0.2, stop_loss_multiple=2.0)
    monkeypatch.setitem(INSTRUMENTS, "TEST", cfg)


def _cheap(call_mid, put_mid):
    chain = _chain(100, call_mid, call_mid, put_mid, put_mid)
    return ParityEngine(r=0.0).scan("TEST", chain, 100.0, "F", "2026-11-29")


def test_min_deviation_gate_is_strict_in_both_directions(frozen_today, cheap_instrument):
    assert _cheap(15.0, 10.0) == []                    # dev exactly +5
    assert _cheap(10.0, 15.0) == []                    # dev exactly -5
    up = _cheap(15.01, 10.0)
    down = _cheap(10.0, 15.01)
    assert [s.direction for s in up] == ["SHORT_CALL_LONG_PUT"]
    assert [s.direction for s in down] == ["LONG_CALL_SHORT_PUT"]
    assert up[0].lots == 1 and up[0].net_deviation == pytest.approx(5.01 - up[0].transaction_cost)


def test_scan_uses_mid_of_bid_and_ask_for_both_legs(frozen_today):
    # call 480/520 (mid 500), put 100/200 (mid 150): dev = 350 - 150 = +200 exactly as with 500/150
    sigs = _scan(_chain(49_850, 480, 520, 100, 200))
    assert len(sigs) == 1
    assert (sigs[0].call_mid, sigs[0].put_mid) == (500.0, 150.0)
    assert sigs[0].raw_deviation == pytest.approx(200.0)
