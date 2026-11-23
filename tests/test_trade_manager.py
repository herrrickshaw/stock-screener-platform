"""Offline tests for put_call_parity.trade_manager (position book, fill polling, entry/exit/unwind/P&L)."""
import json

import pytest

from put_call_parity import trade_manager as tm
from put_call_parity.broker import BrokerBase
from put_call_parity.config import INSTRUMENTS
from put_call_parity.parity_engine import ParitySignal
from put_call_parity.trade_manager import PositionBook, TradeManager, _wait_for_fill


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    """_log_closed writes closed_positions.json relative to the CWD; keep it in tmp_path."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(tm.time, "sleep", lambda s: None)


class FakeBroker(BrokerBase):
    """Records every order; per-symbol status/price/failure scripted by the test."""

    def __init__(self, prices=None, statuses=None, place_fail=()):
        self.prices = prices or {}
        self.statuses = statuses or {}      # symbol -> final status string
        self.place_fail = set(place_fail)   # symbols whose place_order raises
        self.orders = []

    def login(self): pass
    def get_quote(self, instruments): return {}
    def get_option_chain(self, underlying, expiry, exchange): return []
    def cancel_order(self, order_id): pass
    def get_positions(self): return []

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity, order_type,
                    price=0.0, trigger_price=0.0, product="NRML", tag=""):
        if tradingsymbol in self.place_fail and not tag.startswith("UNWIND"):
            raise RuntimeError("exchange down")
        self.orders.append(dict(symbol=tradingsymbol, exchange=exchange, side=transaction_type,
                                qty=quantity, type=order_type, product=product, tag=tag))
        return f"O{len(self.orders) - 1}"

    def get_order_status(self, order_id):
        o = self.orders[int(order_id[1:])]
        status = self.statuses.get(o["symbol"], "COMPLETE")
        return {"status": status, "average_price": self.prices.get(o["symbol"], 100.0),
                "status_message": "because"}


def _signal(direction="SHORT_CALL_LONG_PUT", instrument="BANKNIFTY", lots=2, strike=50_000.0):
    return ParitySignal(
        instrument=instrument, expiry="2026-11-27", strike=strike, dte=30.0, futures_price=50_150.0,
        call_mid=420.0, put_mid=200.0, call_symbol="CE", put_symbol="PE", futures_symbol="FUT",
        theoretical_spread=150.0, observed_spread=220.0, raw_deviation=70.0, transaction_cost=0.0,
        net_deviation=70.0, direction=direction, lots=lots)


# ------------------------------------------------------------- PositionBook
def test_position_book_starts_empty_without_a_file(tmp_path):
    book = PositionBook(str(tmp_path / "p.json"))
    assert len(book) == 0 and book.get_all() == {} and book.get("x") is None


def test_position_book_add_persists_and_reloads(tmp_path):
    path = tmp_path / "p.json"
    book = PositionBook(str(path))
    book.add("a", {"qty": 15})
    assert json.loads(path.read_text()) == {"a": {"qty": 15}}
    again = PositionBook(str(path))
    assert len(again) == 1 and again.get("a") == {"qty": 15}


def test_position_book_remove_persists_and_ignores_unknown_ids(tmp_path):
    path = tmp_path / "p.json"
    book = PositionBook(str(path))
    book.add("a", {"qty": 1})
    book.add("b", {"qty": 2})
    book.remove("a")
    book.remove("nope")                      # silently ignored
    assert json.loads(path.read_text()) == {"b": {"qty": 2}}
    assert len(book) == 1


def test_position_book_get_all_returns_a_copy(tmp_path):
    book = PositionBook(str(tmp_path / "p.json"))
    book.add("a", {"qty": 1})
    snap = book.get_all()
    snap["zzz"] = {}
    assert "zzz" not in book.get_all()


def test_position_book_serialises_non_json_values_as_strings(tmp_path):
    from datetime import date
    path = tmp_path / "p.json"
    PositionBook(str(path)).add("a", {"when": date(2026, 11, 1)})
    assert json.loads(path.read_text())["a"]["when"] == "2026-11-01"


# ----------------------------------------------------------- _wait_for_fill
@pytest.mark.parametrize("state", ["COMPLETE", "FILLED", "complete", "filled"])
def test_wait_for_fill_returns_on_complete_or_filled_any_case(state, no_sleep):
    class B:
        def get_order_status(self, oid): return {"status": state, "average_price": 5}
    assert _wait_for_fill(B(), "1")["average_price"] == 5


@pytest.mark.parametrize("state", ["CANCELLED", "REJECTED", "rejected"])
def test_wait_for_fill_raises_on_cancel_or_reject(state, no_sleep):
    class B:
        def get_order_status(self, oid): return {"status": state, "status_message": "no margin"}
    with pytest.raises(RuntimeError, match=r"Order 7 .*: no margin"):
        _wait_for_fill(B(), "7")


def test_wait_for_fill_polls_until_filled(no_sleep):
    seq = iter(["OPEN", "PENDING", "COMPLETE"])
    calls = []

    class B:
        def get_order_status(self, oid):
            calls.append(oid)
            return {"status": next(seq)}
    assert _wait_for_fill(B(), "9")["status"] == "COMPLETE"
    assert len(calls) == 3


def test_wait_for_fill_times_out(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(tm.time, "time", lambda: clock["t"])

    def fake_sleep(s):
        clock["t"] += s
    monkeypatch.setattr(tm.time, "sleep", fake_sleep)

    class B:
        def get_order_status(self, oid): return {"status": "OPEN"}
    with pytest.raises(TimeoutError, match="not filled within 5.0s"):
        _wait_for_fill(B(), "1", timeout=5.0, poll=0.5)
    assert clock["t"] == pytest.approx(1005.0)      # slept exactly up to the deadline


def test_wait_for_fill_tolerates_missing_status_key(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(tm.time, "time", lambda: clock["t"])
    monkeypatch.setattr(tm.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))

    class B:
        def get_order_status(self, oid): return {}
    with pytest.raises(TimeoutError):
        _wait_for_fill(B(), "1", timeout=1.0, poll=0.5)


# ------------------------------------------------------------- enter_trade
def _manager(tmp_path, **broker_kw):
    broker = FakeBroker(**broker_kw)
    book = PositionBook(str(tmp_path / "book.json"))
    return TradeManager(broker, book), broker, book


@pytest.mark.parametrize("direction, sides", [
    ("SHORT_CALL_LONG_PUT", ("SELL", "BUY", "BUY")),
    ("LONG_CALL_SHORT_PUT", ("BUY", "SELL", "SELL")),
])
def test_enter_trade_places_three_hedged_market_orders(tmp_path, no_sleep, direction, sides):
    mgr, broker, book = _manager(tmp_path, prices={"CE": 420.0, "PE": 200.0, "FUT": 50_150.0})
    pid = mgr.enter_trade(_signal(direction, lots=2))
    assert pid and pid.startswith("BANKNIFTY_2026-11-27_50000_")
    assert [(o["symbol"], o["side"]) for o in broker.orders] == list(zip(["CE", "PE", "FUT"], sides))
    cfg = INSTRUMENTS["BANKNIFTY"]
    for o in broker.orders:
        assert o["qty"] == 2 * cfg.lot_size
        assert o["exchange"] == cfg.segment            # NFO, not the NSE cash segment
        assert (o["type"], o["product"]) == ("MARKET", "NRML")
        assert o["tag"] == "PCP_BANKNIFTY_50000"
    pos = book.get(pid)
    assert pos["entry_call_price"] == 420.0 and pos["entry_put_price"] == 200.0
    assert pos["entry_futures_price"] == 50_150.0
    assert pos["direction"] == direction and pos["lots"] == 2 and pos["qty"] == 30
    assert pos["entry_deviation"] == 70.0
    assert pos["exchange"] == "NSE" and pos["segment"] == "NFO"
    assert set(pos["order_ids"]) == {"call", "put", "fut"}


def test_enter_trade_custom_tag_prefix(tmp_path, no_sleep):
    mgr, broker, _ = _manager(tmp_path)
    mgr.enter_trade(_signal(), tag_prefix="XYZ")
    assert broker.orders[0]["tag"] == "XYZ_BANKNIFTY_50000"


def test_enter_trade_mcx_uses_mcx_segment(tmp_path, no_sleep):
    mgr, broker, book = _manager(tmp_path)
    pid = mgr.enter_trade(_signal(instrument="CRUDEOIL", lots=3, strike=6000.0))
    assert {o["exchange"] for o in broker.orders} == {"MCX-FO"}
    assert {o["qty"] for o in broker.orders} == {300}
    assert book.get(pid)["exchange"] == "MCX"


def test_enter_trade_on_place_failure_unwinds_earlier_legs_and_returns_none(tmp_path, no_sleep):
    mgr, broker, book = _manager(tmp_path, place_fail={"FUT"})
    assert mgr.enter_trade(_signal("SHORT_CALL_LONG_PUT")) is None
    assert len(book) == 0
    unwind = [o for o in broker.orders if o["tag"].startswith("UNWIND_")]
    # entry was SELL call / BUY put, so the unwind is BUY call / SELL put
    assert [(o["symbol"], o["side"]) for o in unwind] == [("CE", "BUY"), ("PE", "SELL")]
    assert all(o["tag"] == "UNWIND_PCP_BANKNIFTY_50000" for o in unwind)
    assert all(o["qty"] == 30 and o["exchange"] == "NFO" for o in unwind)


def test_enter_trade_first_leg_failure_has_nothing_to_unwind(tmp_path, no_sleep):
    mgr, broker, book = _manager(tmp_path, place_fail={"CE"})
    assert mgr.enter_trade(_signal()) is None
    assert broker.orders == [] and len(book) == 0


def test_enter_trade_unwind_for_long_call_short_put_direction(tmp_path, no_sleep):
    mgr, broker, _ = _manager(tmp_path, place_fail={"FUT"})
    assert mgr.enter_trade(_signal("LONG_CALL_SHORT_PUT")) is None
    unwind = [(o["symbol"], o["side"]) for o in broker.orders if o["tag"].startswith("UNWIND_")]
    assert unwind == [("CE", "SELL"), ("PE", "BUY")]


def test_enter_trade_survives_a_failing_unwind_order(tmp_path, no_sleep, monkeypatch):
    mgr, broker, _ = _manager(tmp_path, place_fail={"FUT"})
    real = broker.place_order

    def flaky(**kw):
        if kw["tag"].startswith("UNWIND"):
            raise RuntimeError("cannot unwind")
        return real(**kw)
    monkeypatch.setattr(broker, "place_order", flaky)
    assert mgr.enter_trade(_signal()) is None          # error is logged, not raised


def test_emergency_unwind_unknown_direction_places_nothing(tmp_path):
    mgr, broker, _ = _manager(tmp_path)
    sig = _signal("NONE")
    mgr._emergency_unwind({"call": "O1"}, {}, sig, INSTRUMENTS["BANKNIFTY"], 15, "t")
    assert broker.orders == []


def test_missing_fill_price_is_recorded_as_zero(tmp_path, no_sleep, monkeypatch):
    mgr, broker, book = _manager(tmp_path)
    monkeypatch.setattr(broker, "get_order_status", lambda oid: {"status": "COMPLETE"})
    pid = mgr.enter_trade(_signal())
    pos = book.get(pid)
    assert (pos["entry_call_price"], pos["entry_put_price"], pos["entry_futures_price"]) == (0, 0, 0)


# -------------------------------------------------------------- exit_trade
def _open_position(mgr, direction="SHORT_CALL_LONG_PUT"):
    pid = mgr.enter_trade(_signal(direction))
    mgr.broker.orders.clear()
    return pid


def test_exit_trade_unknown_position_returns_false(tmp_path):
    mgr, broker, _ = _manager(tmp_path)
    assert mgr.exit_trade("ghost") is False
    assert broker.orders == []


@pytest.mark.parametrize("direction, sides", [
    ("SHORT_CALL_LONG_PUT", ("BUY", "SELL", "SELL")),
    ("LONG_CALL_SHORT_PUT", ("SELL", "BUY", "BUY")),
])
def test_exit_trade_reverses_every_leg_and_clears_the_book(tmp_path, no_sleep, direction, sides):
    mgr, broker, book = _manager(tmp_path, prices={"CE": 420.0, "PE": 200.0, "FUT": 50_150.0})
    pid = _open_position(mgr, direction)
    assert mgr.exit_trade(pid, reason="PROFIT_TARGET") is True
    assert [(o["symbol"], o["side"]) for o in broker.orders] == list(zip(["CE", "PE", "FUT"], sides))
    assert all(o["tag"] == f"EXIT_{pid[:20]}" and o["qty"] == 30 for o in broker.orders)
    assert pid not in book.get_all()


def test_exit_trade_logs_closed_position_with_pnl_and_reason(tmp_path, no_sleep):
    mgr, broker, book = _manager(tmp_path, prices={"CE": 420.0, "PE": 200.0, "FUT": 50_150.0})
    pid = _open_position(mgr)
    broker.prices.update({"CE": 400.0, "PE": 210.0, "FUT": 50_160.0})
    assert mgr.exit_trade(pid, "STOP_LOSS")
    history = json.loads((tmp_path / "closed_positions.json").read_text())
    assert len(history) == 1
    rec = history[0]
    assert rec["position_id"] == pid and rec["exit_reason"] == "STOP_LOSS"
    assert rec["exit_prices"] == {"call": 400.0, "put": 210.0, "fut": 50_160.0}
    # short call +20, long put +10, long fut +10 per unit, 30 units
    assert rec["pnl"] == pytest.approx((20 + 10 + 10) * 30)
    assert "exit_time" in rec


def test_exit_trade_appends_to_existing_closed_log(tmp_path, no_sleep):
    mgr, broker, book = _manager(tmp_path)
    (tmp_path / "closed_positions.json").write_text(json.dumps([{"old": 1}]))
    pid = _open_position(mgr)
    assert mgr.exit_trade(pid)
    history = json.loads((tmp_path / "closed_positions.json").read_text())
    assert history[0] == {"old": 1} and len(history) == 2
    assert history[1]["exit_reason"] == ""


def test_exit_trade_failure_keeps_position_and_attempts_every_leg(tmp_path, no_sleep):
    mgr, broker, book = _manager(tmp_path)
    pid = _open_position(mgr)
    broker.statuses["PE"] = "REJECTED"
    assert mgr.exit_trade(pid) is False
    assert pid in book.get_all()                                     # still tracked
    assert [o["symbol"] for o in broker.orders] == ["CE", "PE", "FUT"]   # kept going
    assert not (tmp_path / "closed_positions.json").exists()


# --------------------------------------------------------------------- pnl
def _pos(direction, **kw):
    base = dict(direction=direction, lots=2, qty=30, entry_call_price=100.0,
                entry_put_price=50.0, entry_futures_price=1000.0)
    base.update(kw)
    return base


def test_pnl_for_conversion_and_reversal_are_mirror_images():
    mgr = TradeManager(None, None)
    cfg = INSTRUMENTS["BANKNIFTY"]
    exit_prices = {"call": 90.0, "put": 70.0, "fut": 1005.0}
    short = mgr._calculate_pnl(_pos("SHORT_CALL_LONG_PUT"), exit_prices, cfg)
    long_ = mgr._calculate_pnl(_pos("LONG_CALL_SHORT_PUT"), exit_prices, cfg)
    assert short == pytest.approx(((100 - 90) + (70 - 50) + (1005 - 1000)) * 30)
    assert long_ == pytest.approx(-short)


def test_pnl_uses_quantity_not_lots_and_defaults_missing_exit_prices_to_zero():
    mgr = TradeManager(None, None)
    cfg = INSTRUMENTS["BANKNIFTY"]
    p = mgr._calculate_pnl(_pos("SHORT_CALL_LONG_PUT"), {}, cfg)
    assert p == pytest.approx(((100 - 0) + (0 - 50) + (0 - 1000)) * 30)
    p2 = mgr._calculate_pnl(_pos("LONG_CALL_SHORT_PUT", qty=60), {}, cfg)
    assert p2 == pytest.approx(((0 - 100) + (50 - 0) + (1000 - 0)) * 60)


# ------------------------------------------------------------- source bug
@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="trade_manager.py:136-137 records order_ids[leg] before the fill is confirmed, so a "
           "REJECTED leg is 'unwound' by sending the opposite order, which opens a naked position "
           "in that leg instead of flattening one.")
def test_rejected_leg_is_not_unwound(tmp_path, no_sleep):
    mgr, broker, book = _manager(tmp_path, statuses={"PE": "REJECTED"})
    assert mgr.enter_trade(_signal("SHORT_CALL_LONG_PUT")) is None
    unwound = [o["symbol"] for o in broker.orders if o["tag"].startswith("UNWIND_")]
    assert unwound == ["CE"]            # only the leg that actually filled needs reversing


@pytest.mark.parametrize("direction, expected", [
    ("SHORT_CALL_LONG_PUT", {"CE": "BUY", "PE": "SELL", "FUT": "SELL"}),
    ("LONG_CALL_SHORT_PUT", {"CE": "SELL", "PE": "BUY", "FUT": "BUY"}),
])
def test_emergency_unwind_reverses_each_listed_leg(tmp_path, direction, expected):
    mgr, broker, _ = _manager(tmp_path)
    mgr._emergency_unwind({"call": "1", "put": "2", "fut": "3"}, {}, _signal(direction),
                          INSTRUMENTS["BANKNIFTY"], 30, "tag")
    assert {o["symbol"]: o["side"] for o in broker.orders} == expected
    assert [o["symbol"] for o in broker.orders] == ["CE", "PE", "FUT"]
