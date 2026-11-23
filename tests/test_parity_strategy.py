"""Offline tests for put_call_parity.strategy: expiry/quote helpers, scan, monitor and run loop.

strategy.py configures logging and opens ``parity_trader.log`` in the CWD at import time, so it is
imported fresh from a tmp_path CWD and sys.modules / root logging are restored afterwards.
"""
import importlib
import logging
import sys
from datetime import date as real_date
from datetime import datetime

import pytest

from put_call_parity.config import INSTRUMENTS
from put_call_parity.parity_engine import ParitySignal


class FrozenDate(real_date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 1)


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    saved_mod = sys.modules.pop("put_call_parity.strategy", None)
    mod = importlib.import_module("put_call_parity.strategy")
    monkeypatch.setattr(mod, "date", FrozenDate)
    yield mod
    for h in list(root.handlers):
        if h not in saved_handlers:
            root.removeHandler(h)
            h.close()
    root.setLevel(saved_level)
    sys.modules.pop("put_call_parity.strategy", None)
    if saved_mod is not None:
        sys.modules["put_call_parity.strategy"] = saved_mod


class FakeKite:
    def __init__(self, instruments):
        self._i = instruments
        self.segments = []

    def instruments(self, segment):
        self.segments.append(segment)
        return self._i


class FakeBroker:
    def __init__(self, instruments=(), quotes=None, chain=None, chain_exc=None, quote_exc=None):
        self.kite = FakeKite(list(instruments))
        self.quotes = quotes or {}
        self.chain = chain or []
        self.chain_exc = chain_exc
        self.quote_exc = quote_exc
        self.quote_calls = []
        self.chain_calls = []

    def get_quote(self, syms):
        self.quote_calls.append(list(syms))
        if self.quote_exc:
            raise self.quote_exc
        return self.quotes

    def get_option_chain(self, underlying, expiry, exchange):
        self.chain_calls.append((underlying, expiry, exchange))
        if self.chain_exc:
            raise self.chain_exc
        return self.chain

    def place_order(self, **kw):
        raise AssertionError("not expected")


def _opt(name, expiry):
    return {"name": name, "expiry": expiry, "instrument_type": "CE"}


def _fut(name, expiry, ts="FUTSYM"):
    return {"name": name, "expiry": expiry, "instrument_type": "FUT", "tradingsymbol": ts}


# ------------------------------------------------------------- expiries
def test_nearest_expiries_filters_by_dte_window_dedups_and_sorts(st):
    # today 2026-11-01 ; MIN_DTE 2, MAX_DTE 30
    insts = [
        _opt("BANKNIFTY", datetime(2026, 11, 20)),     # dte 19 ok (datetime has strftime)
        _opt("BANKNIFTY", datetime(2026, 11, 20)),     # duplicate
        _opt("BANKNIFTY", "2026-11-03"),               # dte 2 -> inclusive lower bound
        _opt("BANKNIFTY", "2026-11-02"),               # dte 1 -> too close
        _opt("BANKNIFTY", "2026-12-01"),               # dte 30 -> inclusive upper bound
        _opt("BANKNIFTY", "2026-12-02"),               # dte 31 -> too far
        _opt("NIFTY", "2026-11-10"),                   # other underlying
    ]
    got = st._nearest_expiries(FakeBroker(insts), "BANKNIFTY")
    assert got == ["2026-11-03", "2026-11-20", "2026-12-01"]


def test_nearest_expiries_queries_the_instrument_segment(st):
    b = FakeBroker([])
    st._nearest_expiries(b, "CRUDEOIL")
    assert b.kite.segments == ["MCX-FO"]


def test_nearest_expiries_broker_without_kite_returns_empty(st):
    class NoKite:
        pass
    assert st._nearest_expiries(NoKite(), "BANKNIFTY") == []


# -------------------------------------------------------------- futures
def _fut_broker(quote, expiry="2026-11-26"):
    sym = "NFO:FUTSYM"
    return FakeBroker([_fut("BANKNIFTY", expiry), _fut("BANKNIFTY", "2026-12-31", "OTHER")],
                      quotes={sym: quote})


def test_futures_quote_is_mid_of_best_bid_and_ask(st):
    q = {"depth": {"buy": [{"price": 100.0}], "sell": [{"price": 102.0}]}, "last_price": 50.0}
    b = _fut_broker(q)
    assert st._get_futures_quote(b, "BANKNIFTY", "2026-11-26") == 101.0
    assert b.quote_calls == [["NFO:FUTSYM"]]


def test_futures_quote_falls_back_to_last_price_when_a_side_is_empty(st):
    q = {"depth": {"buy": [{"price": 0}], "sell": [{"price": 102.0}]}, "last_price": 99.5}
    assert st._get_futures_quote(_fut_broker(q), "BANKNIFTY", "2026-11-26") == 99.5
    assert st._get_futures_quote(_fut_broker({"last_price": 77.0}), "BANKNIFTY", "2026-11-26") == 77.0


def test_futures_quote_none_when_no_contract_for_expiry(st):
    assert st._get_futures_quote(_fut_broker({}), "BANKNIFTY", "2027-01-01") is None


def test_futures_quote_ignores_non_futures_and_other_names(st):
    insts = [{"name": "BANKNIFTY", "expiry": "2026-11-26", "instrument_type": "CE", "tradingsymbol": "X"},
             _fut("NIFTY", "2026-11-26")]
    assert st._get_futures_quote(FakeBroker(insts), "BANKNIFTY", "2026-11-26") is None


def test_futures_quote_returns_none_instead_of_raising_on_broker_error(st):
    b = _fut_broker({}, )
    b.quote_exc = RuntimeError("boom")
    assert st._get_futures_quote(b, "BANKNIFTY", "2026-11-26") is None


def test_futures_quote_accepts_datetime_expiries(st):
    q = {"last_price": 12.0}
    b = FakeBroker([_fut("BANKNIFTY", datetime(2026, 11, 26))], quotes={"NFO:FUTSYM": q})
    assert st._get_futures_quote(b, "BANKNIFTY", "2026-11-26") == 12.0


def test_futures_symbol_resolves_tradingsymbol_or_falls_back_to_root(st):
    b = _fut_broker({})
    assert st._get_futures_symbol(b, "BANKNIFTY", "2026-11-26") == "FUTSYM"
    assert st._get_futures_symbol(b, "BANKNIFTY", "2027-01-01") == "BANKNIFTY"
    assert st._get_futures_symbol(object(), "SILVER", "2026-11-26") == "SILVER"


def test_futures_symbol_falls_back_when_instrument_lookup_raises(st):
    class Bad:
        class kite:
            @staticmethod
            def instruments(seg):
                raise RuntimeError("x")
    assert st._get_futures_symbol(Bad(), "CRUDEOIL", "2026-11-26") == "CRUDEOIL"


# ------------------------------------------------------ option refresh
POS = {"segment": "NFO", "call_symbol": "CE1", "put_symbol": "PE1"}


def test_refresh_option_prices_reads_depth_best_prices(st):
    quotes = {
        "NFO:CE1": {"depth": {"buy": [{"price": 10.0}], "sell": [{"price": 12.0}]}, "last_price": 11.0},
        "NFO:PE1": {"depth": {"buy": [{"price": 4.0}], "sell": [{"price": 6.0}]}, "last_price": 5.0},
    }
    b = FakeBroker(quotes=quotes)
    assert st._refresh_option_prices(b, POS) == {
        "call_bid": 10.0, "call_ask": 12.0, "put_bid": 4.0, "put_ask": 6.0}
    assert b.quote_calls == [["NFO:CE1", "NFO:PE1"]]


def test_refresh_option_prices_uses_last_price_when_depth_is_empty_or_zero(st):
    quotes = {"NFO:CE1": {"depth": {"buy": [{"price": 0}], "sell": [{}]}, "last_price": 11.0},
              "NFO:PE1": {"last_price": 5.0}}
    got = st._refresh_option_prices(FakeBroker(quotes=quotes), POS)
    assert got == {"call_bid": 11.0, "call_ask": 11.0, "put_bid": 5.0, "put_ask": 5.0}


def test_refresh_option_prices_missing_symbol_gives_zeros(st):
    got = st._refresh_option_prices(FakeBroker(quotes={}), POS)
    assert got == {"call_bid": 0, "call_ask": 0, "put_bid": 0, "put_ask": 0}


def test_refresh_option_prices_returns_empty_dict_on_error(st):
    assert st._refresh_option_prices(FakeBroker(quote_exc=RuntimeError("x")), POS) == {}


# -------------------------------------------------------- Strategy class
def _strategy(st, tmp_path, broker):
    return st.Strategy(broker=broker)


@pytest.fixture
def pos_file(tmp_path, monkeypatch, st):
    """Point the Strategy's PositionBook at tmp_path."""
    real = st.PositionBook
    monkeypatch.setattr(st, "PositionBook", lambda: real(str(tmp_path / "pos.json")))


def _signal(net, strike=100.0, inst="BANKNIFTY", expiry="2026-11-26"):
    return ParitySignal(inst, expiry, strike, 25.0, 150.0, 0, 0, "C", "P", "F", 0, 0, 0, 0, net,
                        "SHORT_CALL_LONG_PUT", 1)


def test_scan_instrument_no_expiries_returns_empty(st, pos_file):
    s = st.Strategy(broker=FakeBroker([]))
    assert s._scan_instrument("BANKNIFTY") == []


def test_scan_instrument_collects_and_sorts_signals_across_expiries(st, pos_file, monkeypatch):
    insts = [_opt("BANKNIFTY", "2026-11-10"), _opt("BANKNIFTY", "2026-11-20"),
             _fut("BANKNIFTY", "2026-11-10", "F1"), _fut("BANKNIFTY", "2026-11-20", "F2")]
    b = FakeBroker(insts, quotes={"NFO:F1": {"last_price": 50_000.0}, "NFO:F2": {"last_price": 50_100.0}},
                   chain=[{"x": 1}])
    s = st.Strategy(broker=b)
    seen = []

    def fake_scan(**kw):
        seen.append(kw)
        net = 5.0 if kw["expiry"] == "2026-11-10" else 9.0
        return [_signal(net, expiry=kw["expiry"])]
    monkeypatch.setattr(s.engine, "scan", fake_scan)
    out = s._scan_instrument("BANKNIFTY")
    assert [x.net_deviation for x in out] == [9.0, 5.0]
    assert [k["futures_price"] for k in seen] == [50_000.0, 50_100.0]
    assert [k["futures_symbol"] for k in seen] == ["F1", "F2"]
    assert all(k["min_oi"] == st.MIN_OI_THRESHOLD and k["instrument_key"] == "BANKNIFTY" for k in seen)
    assert b.chain_calls == [("BANKNIFTY", "2026-11-10", "NFO"), ("BANKNIFTY", "2026-11-20", "NFO")]


def test_scan_instrument_skips_expiry_without_futures_price(st, pos_file, monkeypatch):
    insts = [_opt("BANKNIFTY", "2026-11-10")]
    b = FakeBroker(insts, chain=[{"x": 1}])
    s = st.Strategy(broker=b)
    monkeypatch.setattr(s.engine, "scan", lambda **kw: pytest.fail("must not scan"))
    assert s._scan_instrument("BANKNIFTY") == []
    assert b.chain_calls == []


def test_scan_instrument_survives_chain_errors_and_empty_chains(st, pos_file, monkeypatch):
    insts = [_opt("BANKNIFTY", "2026-11-10"), _fut("BANKNIFTY", "2026-11-10", "F1")]
    quotes = {"NFO:F1": {"last_price": 50_000.0}}
    s = st.Strategy(broker=FakeBroker(insts, quotes=quotes, chain_exc=RuntimeError("down")))
    monkeypatch.setattr(s.engine, "scan", lambda **kw: pytest.fail("must not scan"))
    assert s._scan_instrument("BANKNIFTY") == []
    s2 = st.Strategy(broker=FakeBroker(insts, quotes=quotes, chain=[]))
    monkeypatch.setattr(s2.engine, "scan", lambda **kw: pytest.fail("must not scan"))
    assert s2._scan_instrument("BANKNIFTY") == []


def _position(**kw):
    p = {"instrument": "BANKNIFTY", "expiry": "2026-11-26", "strike": 100.0, "direction": "SHORT_CALL_LONG_PUT",
         "lots": 1, "segment": "NFO", "call_symbol": "CE1", "put_symbol": "PE1",
         "futures_symbol": "FUTSYM", "entry_deviation": 40.0}
    p.update(kw)
    return p


def _monitor_setup(st, tmp_path, quotes, insts=None):
    insts = insts if insts is not None else [_fut("BANKNIFTY", "2026-11-26")]
    b = FakeBroker(insts, quotes=quotes)
    s = st.Strategy(broker=b)
    exits = []
    s.tm.exit_trade = lambda pid, reason: exits.append((pid, reason))
    s.book.add("p1", _position())
    return s, exits


def test_monitor_positions_exits_when_engine_says_so(st, pos_file, tmp_path):
    # BANKNIFTY: exit_fraction .2, stop 2.5 ; entry dev 40 -> target 8, stop 100.
    # futures 100 (theo 0 at strike 100) ; call mid 5, put mid 5 -> dev 0 -> profit target
    quotes = {"NFO:FUTSYM": {"last_price": 100.0},
              "NFO:CE1": {"depth": {"buy": [{"price": 5.0}], "sell": [{"price": 5.0}]}},
              "NFO:PE1": {"depth": {"buy": [{"price": 5.0}], "sell": [{"price": 5.0}]}}}
    s, exits = _monitor_setup(st, tmp_path, quotes)
    s._monitor_positions()
    assert len(exits) == 1 and exits[0][0] == "p1" and exits[0][1].startswith("PROFIT_TARGET")


def test_monitor_positions_holds_when_deviation_is_between_target_and_stop(st, pos_file, tmp_path):
    quotes = {"NFO:FUTSYM": {"last_price": 100.0},
              "NFO:CE1": {"depth": {"buy": [{"price": 40.0}], "sell": [{"price": 40.0}]}},
              "NFO:PE1": {"depth": {"buy": [{"price": 5.0}], "sell": [{"price": 5.0}]}}}
    s, exits = _monitor_setup(st, tmp_path, quotes)       # dev 35 : 8 < 35 < 100
    s._monitor_positions()
    assert exits == []


def test_monitor_positions_skips_when_option_quotes_fail(st, pos_file, tmp_path):
    s, exits = _monitor_setup(st, tmp_path, {})
    s.broker.quote_exc = RuntimeError("x")
    s._monitor_positions()
    assert exits == []


def test_monitor_positions_skips_when_futures_price_unavailable(st, pos_file, tmp_path):
    quotes = {"NFO:CE1": {"last_price": 5.0}, "NFO:PE1": {"last_price": 5.0}}
    s, exits = _monitor_setup(st, tmp_path, quotes, insts=[])
    s._monitor_positions()
    assert exits == []


def test_monitor_positions_with_empty_book_does_nothing(st, pos_file):
    b = FakeBroker([])
    s = st.Strategy(broker=b)
    s._monitor_positions()
    assert b.quote_calls == []


# ------------------------------------------------------------- run loop
def _run_once(st, s, monkeypatch, sleeps):
    """Run one iteration of Strategy.run(); the sleep call ends the loop via KeyboardInterrupt."""
    def fake_sleep(sec):
        sleeps.append(sec)
        raise KeyboardInterrupt
    monkeypatch.setattr(st.time, "sleep", fake_sleep)
    try:
        s.run()
    except KeyboardInterrupt:       # raised from the error-path sleep, outside the loop's own handler
        pass


def test_run_enters_best_signals_up_to_free_slots_and_skips_duplicates(st, pos_file, monkeypatch):
    s = st.Strategy(broker=FakeBroker([]))
    monkeypatch.setattr(st, "MAX_OPEN_POSITIONS", 2)
    s.book.add("held", _position(strike=300.0))             # one slot used -> one slot free
    sigs = [_signal(9.0, strike=300.0), _signal(8.0, strike=200.0), _signal(7.0, strike=100.0)]
    monkeypatch.setattr(s, "_scan_instrument",
                        lambda key: sigs if key == "BANKNIFTY" else [])
    monkeypatch.setattr(s, "_monitor_positions", lambda: None)
    entered = []
    monkeypatch.setattr(s.tm, "enter_trade", lambda sig: entered.append(sig.strike) or "pid")
    sleeps = []
    _run_once(st, s, monkeypatch, sleeps)
    # slots=1 -> only the top signal (strike 300) is considered, and it duplicates the held position
    assert entered == []
    assert 0 <= sleeps[0] <= st.SCAN_INTERVAL_SECONDS


def test_run_enters_new_strike_when_slot_free(st, pos_file, monkeypatch):
    s = st.Strategy(broker=FakeBroker([]))
    sigs = [_signal(9.0, strike=300.0), _signal(8.0, strike=200.0)]
    monkeypatch.setattr(s, "_scan_instrument", lambda key: sigs if key == "BANKNIFTY" else [])
    monkeypatch.setattr(s, "_monitor_positions", lambda: None)
    entered = []
    monkeypatch.setattr(s.tm, "enter_trade", lambda sig: entered.append(sig.strike) or "pid")
    _run_once(st, s, monkeypatch, [])
    assert entered == [300.0, 200.0]


def test_run_skips_scan_when_book_is_full(st, pos_file, monkeypatch):
    s = st.Strategy(broker=FakeBroker([]))
    monkeypatch.setattr(st, "MAX_OPEN_POSITIONS", 1)
    s.book.add("held", _position())
    monkeypatch.setattr(s, "_scan_instrument", lambda key: pytest.fail("must not scan"))
    monkeypatch.setattr(s, "_monitor_positions", lambda: None)
    _run_once(st, s, monkeypatch, [])


def test_run_sleep_never_negative_when_iteration_overruns(st, pos_file, monkeypatch):
    s = st.Strategy(broker=FakeBroker([]))
    monkeypatch.setattr(s, "_scan_instrument", lambda key: [])
    monkeypatch.setattr(s, "_monitor_positions", lambda: None)
    monkeypatch.setattr(st, "SCAN_INTERVAL_SECONDS", -100)
    sleeps = []
    _run_once(st, s, monkeypatch, sleeps)
    assert sleeps == [0]


def test_run_logs_unhandled_errors_then_pauses_five_seconds(st, pos_file, monkeypatch):
    s = st.Strategy(broker=FakeBroker([]))

    def boom():
        raise ValueError("kaput")
    monkeypatch.setattr(s, "_monitor_positions", boom)
    sleeps = []
    _run_once(st, s, monkeypatch, sleeps)
    assert sleeps == [5]


def test_strategy_wires_default_broker_through_get_broker(st, pos_file, monkeypatch):
    marker = FakeBroker([])
    seen = []
    monkeypatch.setattr(st, "get_broker", lambda name: seen.append(name) or marker)
    s = st.Strategy()
    assert s.broker is marker and seen == [st.BROKER]
    assert s.tm.broker is marker and s.tm.book is s.book
    assert s.engine.r == st.RISK_FREE_RATE
