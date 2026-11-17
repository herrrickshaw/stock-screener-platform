"""
trade_manager.py
================
Handles order execution for the three-leg put-call parity trade package:
    Leg 1: Call option   (buy or sell)
    Leg 2: Put option    (buy or sell)
    Leg 3: Futures       (buy or sell)

Also manages the open position book (persisted to JSON so a restart
can resume monitoring existing positions).
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .broker import BrokerBase
from .config import INSTRUMENTS, POSITION_FILE
from .parity_engine import ParitySignal

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position book
# ---------------------------------------------------------------------------
class PositionBook:
    def __init__(self, filepath: str = POSITION_FILE):
        self._path = Path(filepath)
        self._positions: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            with open(self._path) as f:
                self._positions = json.load(f)
        else:
            self._positions = {}

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._positions, f, indent=2, default=str)

    def add(self, position_id: str, position: Dict):
        self._positions[position_id] = position
        self._save()
        log.info("Position added: %s", position_id)

    def remove(self, position_id: str):
        if position_id in self._positions:
            del self._positions[position_id]
            self._save()
            log.info("Position removed: %s", position_id)

    def get_all(self) -> Dict[str, Dict]:
        return dict(self._positions)

    def __len__(self):
        return len(self._positions)

    def get(self, position_id: str) -> Optional[Dict]:
        return self._positions.get(position_id)


# ---------------------------------------------------------------------------
# Utility: wait for fill or timeout
# ---------------------------------------------------------------------------
def _wait_for_fill(broker: BrokerBase, order_id: str,
                   timeout: float = 30.0, poll: float = 0.5) -> Dict:
    """Poll order status until filled or timeout. Returns final order dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = broker.get_order_status(order_id)
        state = status.get("status", "").upper()
        if state in ("COMPLETE", "FILLED"):
            return status
        if state in ("CANCELLED", "REJECTED"):
            raise RuntimeError(f"Order {order_id} {state}: {status.get('status_message')}")
        time.sleep(poll)
    raise TimeoutError(f"Order {order_id} not filled within {timeout}s")


# ---------------------------------------------------------------------------
# Trade executor
# ---------------------------------------------------------------------------
class TradeManager:
    def __init__(self, broker: BrokerBase, book: PositionBook):
        self.broker = broker
        self.book = book

    # -----------------------------------------------------------------------
    # Entry
    # -----------------------------------------------------------------------
    def enter_trade(self, signal: ParitySignal, tag_prefix: str = "PCP") -> Optional[str]:
        """
        Places all three legs simultaneously (market orders for speed).
        Returns a position_id on success, None on failure.

        Direction: SHORT_CALL_LONG_PUT  → sell call, buy put, buy futures  (conversion)
        Direction: LONG_CALL_SHORT_PUT  → buy call, sell put, sell futures (reversal)

        The option pair is a synthetic futures position (short call + long put is a
        synthetic short), so the futures leg must take the OPPOSITE side to hedge it.
        Locked-in value at expiry: conversion = (C - P)e^(rT) + K - F, reversal = its negative.
        """
        cfg = INSTRUMENTS[signal.instrument]
        qty = signal.lots * cfg.lot_size
        exchange = cfg.exchange
        segment  = cfg.segment

        if signal.direction == "SHORT_CALL_LONG_PUT":
            call_side = "SELL"
            put_side  = "BUY"
            fut_side  = "BUY"
        else:
            call_side = "BUY"
            put_side  = "SELL"
            fut_side  = "SELL"

        tag = f"{tag_prefix}_{signal.instrument}_{int(signal.strike)}"

        log.info(
            "ENTERING trade | %s | %s | Strike %s | %s call / %s put / %s futures | Lots %d",
            signal.instrument, signal.expiry, signal.strike,
            call_side, put_side, fut_side, signal.lots,
        )

        order_ids: Dict[str, str] = {}
        fill_prices: Dict[str, float] = {}

        legs = [
            ("call", signal.call_symbol,    exchange if exchange == "NSE" else exchange, call_side),
            ("put",  signal.put_symbol,     exchange if exchange == "NSE" else exchange, put_side),
            ("fut",  signal.futures_symbol, exchange,                                   fut_side),
        ]

        for leg_name, symbol, exch, side in legs:
            try:
                oid = self.broker.place_order(
                    tradingsymbol=symbol,
                    exchange=segment,
                    transaction_type=side,
                    quantity=qty,
                    order_type="MARKET",
                    product="NRML",
                    tag=tag,
                )
                order_ids[leg_name] = oid
                filled = _wait_for_fill(self.broker, oid)
                fill_prices[leg_name] = float(filled.get("average_price", 0))
                log.info("  Leg %-4s filled: %s @ %.2f", leg_name, symbol, fill_prices[leg_name])
            except Exception as exc:
                log.error("  Leg %s FAILED: %s — attempting to unwind %s", leg_name, exc, list(order_ids))
                self._emergency_unwind(order_ids, fill_prices, signal, cfg, qty, tag)
                return None

        position_id = f"{signal.instrument}_{signal.expiry}_{int(signal.strike)}_{int(time.time())}"
        position = {
            "position_id": position_id,
            "instrument": signal.instrument,
            "expiry": signal.expiry,
            "strike": signal.strike,
            "direction": signal.direction,
            "lots": signal.lots,
            "qty": qty,
            "call_symbol": signal.call_symbol,
            "put_symbol": signal.put_symbol,
            "futures_symbol": signal.futures_symbol,
            "entry_call_price": fill_prices.get("call", 0),
            "entry_put_price": fill_prices.get("put", 0),
            "entry_futures_price": fill_prices.get("fut", 0),
            "entry_deviation": signal.raw_deviation,
            "entry_time": datetime.now().isoformat(),
            "order_ids": order_ids,
            "exchange": cfg.exchange,
            "segment": cfg.segment,
        }
        self.book.add(position_id, position)
        return position_id

    # -----------------------------------------------------------------------
    # Exit
    # -----------------------------------------------------------------------
    def exit_trade(self, position_id: str, reason: str = "") -> bool:
        """
        Closes all three legs of an existing position.
        Returns True if all legs exited successfully.
        """
        position = self.book.get(position_id)
        if not position:
            log.warning("exit_trade: position %s not found", position_id)
            return False

        cfg = INSTRUMENTS[position["instrument"]]
        qty = position["qty"]
        segment = position["segment"]

        # Reverse the original direction
        if position["direction"] == "SHORT_CALL_LONG_PUT":
            call_exit = "BUY"
            put_exit  = "SELL"
            fut_exit  = "SELL"
        else:
            call_exit = "SELL"
            put_exit  = "BUY"
            fut_exit  = "BUY"

        tag = f"EXIT_{position_id[:20]}"

        log.info(
            "EXITING position %s | reason: %s",
            position_id, reason or "manual",
        )

        success = True
        exit_prices: Dict[str, float] = {}

        legs = [
            ("call", position["call_symbol"],    segment, call_exit),
            ("put",  position["put_symbol"],     segment, put_exit),
            ("fut",  position["futures_symbol"], segment, fut_exit),
        ]

        for leg_name, symbol, exch, side in legs:
            try:
                oid = self.broker.place_order(
                    tradingsymbol=symbol,
                    exchange=exch,
                    transaction_type=side,
                    quantity=qty,
                    order_type="MARKET",
                    product="NRML",
                    tag=tag,
                )
                filled = _wait_for_fill(self.broker, oid)
                exit_prices[leg_name] = float(filled.get("average_price", 0))
                log.info("  Exit leg %-4s: %s @ %.2f", leg_name, symbol, exit_prices[leg_name])
            except Exception as exc:
                log.error("  Exit leg %s FAILED: %s — manual intervention required!", leg_name, exc)
                success = False

        if success:
            pnl = self._calculate_pnl(position, exit_prices, cfg)
            log.info("Position %s closed | P&L: %.2f", position_id, pnl)
            # Store closed position details in log before removing
            self._log_closed(position, exit_prices, pnl, reason)
            self.book.remove(position_id)

        return success

    # -----------------------------------------------------------------------
    # Emergency unwind (called when leg placement fails mid-entry)
    # -----------------------------------------------------------------------
    def _emergency_unwind(self, order_ids: Dict[str, str],
                           fill_prices: Dict[str, float],
                           signal: ParitySignal,
                           cfg,
                           qty: int,
                           tag: str):
        """Attempt to reverse any legs that were already filled."""
        reversal_map = {
            "SHORT_CALL_LONG_PUT": {"call": "BUY", "put": "SELL", "fut": "SELL"},
            "LONG_CALL_SHORT_PUT": {"call": "SELL", "put": "BUY", "fut": "BUY"},
        }
        reversal = reversal_map.get(signal.direction, {})
        symbols  = {
            "call": signal.call_symbol,
            "put":  signal.put_symbol,
            "fut":  signal.futures_symbol,
        }
        for leg_name, oid in order_ids.items():
            side = reversal.get(leg_name)
            if not side:
                continue
            try:
                self.broker.place_order(
                    tradingsymbol=symbols[leg_name],
                    exchange=cfg.segment,
                    transaction_type=side,
                    quantity=qty,
                    order_type="MARKET",
                    product="NRML",
                    tag=f"UNWIND_{tag}",
                )
                log.info("  Emergency unwind leg %s: %s", leg_name, side)
            except Exception as ex:
                log.error("  UNWIND FAILED for leg %s: %s — check manually!", leg_name, ex)

    # -----------------------------------------------------------------------
    # P&L
    # -----------------------------------------------------------------------
    def _calculate_pnl(self, position: Dict, exit_prices: Dict[str, float], cfg) -> float:
        lot_size = cfg.lot_size
        lots = position["lots"]
        qty = position["qty"]

        if position["direction"] == "SHORT_CALL_LONG_PUT":
            # Sold call, bought put, bought futures
            call_pnl = (position["entry_call_price"] - exit_prices.get("call", 0)) * qty
            put_pnl  = (exit_prices.get("put", 0) - position["entry_put_price"]) * qty
            fut_pnl  = (exit_prices.get("fut", 0) - position["entry_futures_price"]) * qty
        else:
            # Bought call, sold put, sold futures
            call_pnl = (exit_prices.get("call", 0) - position["entry_call_price"]) * qty
            put_pnl  = (position["entry_put_price"] - exit_prices.get("put", 0)) * qty
            fut_pnl  = (position["entry_futures_price"] - exit_prices.get("fut", 0)) * qty

        return call_pnl + put_pnl + fut_pnl

    def _log_closed(self, position: Dict, exit_prices: Dict, pnl: float, reason: str):
        record = {
            **position,
            "exit_prices": exit_prices,
            "pnl": pnl,
            "exit_reason": reason,
            "exit_time": datetime.now().isoformat(),
        }
        closed_log = Path("closed_positions.json")
        history: List[Dict] = []
        if closed_log.exists():
            with open(closed_log) as f:
                history = json.load(f)
        history.append(record)
        with open(closed_log, "w") as f:
            json.dump(history, f, indent=2, default=str)
