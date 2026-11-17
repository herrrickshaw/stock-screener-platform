"""Regression test: a put-call parity trade must be hedged, not doubled.

Short call + long put is a synthetic short futures position, so the futures leg has to be
a BUY (conversion); long call + short put is a synthetic long, hedged by a futures SELL
(reversal). Held to expiry, the three legs then pay the same amount whatever the
underlying does: sign * (C - P - (F - K)) per unit (r = 0 here).
"""
import itertools

import pytest

from put_call_parity.broker import BrokerBase
from put_call_parity.config import INSTRUMENTS
from put_call_parity.parity_engine import ParitySignal
from put_call_parity.trade_manager import PositionBook, TradeManager

K, F, CALL, PUT = 50_000.0, 50_150.0, 420.0, 200.0   # C - P = 220 > F - K = 150


class FakeBroker(BrokerBase):
    """Fills every market order instantly at a fixed price per symbol and records it."""

    def __init__(self, prices):
        self.prices, self.orders, self._ids = prices, [], itertools.count()

    def login(self): pass
    def get_quote(self, instruments): return {}
    def get_option_chain(self, underlying, expiry, exchange): return []
    def cancel_order(self, order_id): pass
    def get_positions(self): return []

    def place_order(self, tradingsymbol, exchange, transaction_type, quantity, order_type,
                    price=0.0, trigger_price=0.0, product="NRML", tag=""):
        oid = str(next(self._ids))
        self.orders.append({"id": oid, "symbol": tradingsymbol, "side": transaction_type,
                            "qty": quantity, "price": self.prices[tradingsymbol]})
        return oid

    def get_order_status(self, order_id):
        o = next(o for o in self.orders if o["id"] == order_id)
        return {"status": "COMPLETE", "average_price": o["price"]}


def _signal(direction):
    return ParitySignal(
        instrument="BANKNIFTY", expiry="2026-11-27", strike=K, dte=30.0, futures_price=F,
        call_mid=CALL, put_mid=PUT, call_symbol="CE", put_symbol="PE", futures_symbol="FUT",
        theoretical_spread=F - K, observed_spread=CALL - PUT, raw_deviation=(CALL - PUT) - (F - K),
        transaction_cost=0.0, net_deviation=(CALL - PUT) - (F - K), direction=direction, lots=1)


def _expiry_payoff(orders, s):
    value = {"CE": max(s - K, 0.0), "PE": max(K - s, 0.0), "FUT": s}
    return sum((1 if o["side"] == "BUY" else -1) * o["qty"] * (value[o["symbol"]] - o["price"])
               for o in orders)


@pytest.mark.parametrize("direction, sign", [("SHORT_CALL_LONG_PUT", 1), ("LONG_CALL_SHORT_PUT", -1)])
def test_three_legs_lock_in_the_parity_gap(tmp_path, direction, sign):
    broker = FakeBroker({"CE": CALL, "PE": PUT, "FUT": F})
    tm = TradeManager(broker, PositionBook(str(tmp_path / "positions.json")))
    pid = tm.enter_trade(_signal(direction))
    assert pid is not None

    qty = INSTRUMENTS["BANKNIFTY"].lot_size
    locked = sign * ((CALL - PUT) - (F - K)) * qty
    for s in (K - 3_000, K - 150, K, K + 150, K + 3_000):
        assert _expiry_payoff(broker.orders, s) == pytest.approx(locked), s

    # The book-keeping P&L must agree with the order-level payoff.
    position = tm.book.get(pid)
    for s in (K - 3_000, K + 3_000):
        exit_prices = {"call": max(s - K, 0.0), "put": max(K - s, 0.0), "fut": s}
        assert tm._calculate_pnl(position, exit_prices, INSTRUMENTS["BANKNIFTY"]) == pytest.approx(locked)
