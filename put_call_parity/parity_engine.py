"""
parity_engine.py
================
Put-Call Parity calculations, deviation detection, and cost-adjusted
signal generation for BankNifty, Crude Oil, and Silver.

Put-Call Parity (for European options on a futures contract):
    C - P = (F - K) * e^(-r*T)          [futures-based]

Put-Call Parity (for European options on a cash index, e.g. BankNifty):
    C - P = S * e^((r-d)*T) - K * e^(-r*T)
          ≈ F - K * e^(-r*T)  when futures price F = S * e^((r-d)*T)

In practice we use the observed futures price F to avoid needing dividend yield,
which simplifies to:
    Theoretical: C - P = (F - K) * e^(-r*T)
    Observed:    C_obs - P_obs  (mid prices from the market)
    Deviation:   δ = (C_obs - P_obs) - (F - K) * e^(-r*T)

Trading signals:
    δ > +threshold  → call is expensive / put is cheap
        Action: SELL call, BUY put, BUY futures   (conversion: synthetic short hedged by real long)
    δ < -threshold  → put is expensive / call is cheap
        Action: BUY call, SELL put, SELL futures  (reversal: synthetic long hedged by real short)
"""

import math
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from .config import COST_MODEL, INSTRUMENTS, RISK_FREE_RATE, InstrumentConfig

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class OptionRow:
    strike: float
    call_bid: float
    call_ask: float
    call_oi: int
    put_bid: float
    put_ask: float
    put_oi: int
    call_symbol: str
    put_symbol: str


@dataclass
class ParitySignal:
    instrument: str
    expiry: str
    strike: float
    dte: float                  # days to expiry (fractional)
    futures_price: float
    call_mid: float
    put_mid: float
    call_symbol: str
    put_symbol: str
    futures_symbol: str
    theoretical_spread: float   # (F - K) * e^(-rT)
    observed_spread: float      # call_mid - put_mid
    raw_deviation: float        # observed - theoretical
    transaction_cost: float     # total round-trip cost estimate
    net_deviation: float        # raw_deviation - transaction_cost
    direction: str              # "LONG_CALL_SHORT_PUT" | "SHORT_CALL_LONG_PUT" | "NONE"
    lots: int


# ---------------------------------------------------------------------------
# Core maths
# ---------------------------------------------------------------------------
def discount_factor(r: float, dte: float) -> float:
    """e^(-r * T) where T is in calendar years."""
    T = dte / 365.0
    return math.exp(-r * T)


def theoretical_cp_spread(futures_price: float, strike: float,
                           r: float, dte: float) -> float:
    """
    Theoretical call-put spread under put-call parity using observed futures:
        (F - K) * e^(-rT)
    """
    df = discount_factor(r, dte)
    return (futures_price - strike) * df


def observed_cp_spread(call_bid: float, call_ask: float,
                       put_bid: float, put_ask: float,
                       direction: str) -> float:
    """
    Conservative mid-price approach.
    For LONG_CALL_SHORT_PUT: we pay ask for call, receive bid for put.
    For SHORT_CALL_LONG_PUT: we receive bid for call, pay ask for put.
    Returns observed C - P from the trading perspective.
    """
    if direction == "LONG_CALL_SHORT_PUT":
        # Buy call at ask, sell put at bid
        return call_ask - put_bid
    elif direction == "SHORT_CALL_LONG_PUT":
        # Sell call at bid, buy put at ask
        return call_bid - put_ask
    else:
        # Neutral estimate using mids
        call_mid = (call_bid + call_ask) / 2
        put_mid = (put_bid + put_ask) / 2
        return call_mid - put_mid


def estimate_transaction_cost(cfg: InstrumentConfig, lots: int,
                               call_mid: float, put_mid: float,
                               futures_price: float) -> float:
    """
    Estimate total round-trip transaction cost for the full arb package:
        2 option legs (call + put) + 1 futures leg, entry AND exit.
    All amounts in Rs per lot.
    """
    cm = COST_MODEL
    lot = cfg.lot_size
    multiplier = cfg.contract_value_multiplier if cfg.contract_value_multiplier > 1 else lot
    futures_notional = futures_price * multiplier

    # --- brokerage (flat per order; 4 orders per leg pair for round-trip) ---
    brokerage = cm.brokerage_per_order * 6   # 3 legs × 2 (entry+exit)

    # --- STT (only on sell side for options, both sides for futures) ---
    option_stt = (call_mid * lot * cm.stt_options_sell_rate +
                  put_mid * lot * cm.stt_options_sell_rate) * 2
    futures_stt = futures_notional * cm.stt_futures_rate * 2

    # --- Exchange charges ---
    exc_rate = cm.exchange_charge_nse if cfg.exchange == "NSE" else cm.exchange_charge_mcx
    exchange_charges = (
        (call_mid + put_mid) * lot * exc_rate * 2 +
        futures_notional * exc_rate * 2
    )

    # --- GST on brokerage + exchange charges ---
    gst = (brokerage + exchange_charges) * cm.gst_rate

    # --- SEBI charges ---
    sebi = (call_mid + put_mid) * lot * cm.sebi_rate * 2 + futures_notional * cm.sebi_rate * 2

    total_per_lot = brokerage + option_stt + futures_stt + exchange_charges + gst + sebi
    return total_per_lot * lots


# ---------------------------------------------------------------------------
# Signal generator
# ---------------------------------------------------------------------------
class ParityEngine:
    def __init__(self, r: float = RISK_FREE_RATE):
        self.r = r

    def build_option_matrix(self, option_chain: List[Dict]) -> Dict[float, OptionRow]:
        """
        Group raw option chain records by strike into paired CE/PE rows.
        Input: list of dicts from broker.get_option_chain()
        """
        matrix: Dict[float, dict] = {}
        for row in option_chain:
            strike = float(row["strike"])
            if strike not in matrix:
                matrix[strike] = {
                    "call_bid": 0.0, "call_ask": 0.0, "call_oi": 0,
                    "put_bid": 0.0, "put_ask": 0.0, "put_oi": 0,
                    "call_symbol": "", "put_symbol": "",
                }
            opt_type = row["instrument_type"]
            if opt_type == "CE":
                matrix[strike]["call_bid"] = float(row.get("bid", 0) or 0)
                matrix[strike]["call_ask"] = float(row.get("ask", 0) or 0)
                matrix[strike]["call_oi"]  = int(row.get("oi", 0) or 0)
                matrix[strike]["call_symbol"] = row["tradingsymbol"]
            elif opt_type == "PE":
                matrix[strike]["put_bid"] = float(row.get("bid", 0) or 0)
                matrix[strike]["put_ask"] = float(row.get("ask", 0) or 0)
                matrix[strike]["put_oi"]  = int(row.get("oi", 0) or 0)
                matrix[strike]["put_symbol"] = row["tradingsymbol"]

        result = {}
        for strike, d in matrix.items():
            if d["call_symbol"] and d["put_symbol"]:
                result[strike] = OptionRow(
                    strike=strike,
                    call_bid=d["call_bid"], call_ask=d["call_ask"], call_oi=d["call_oi"],
                    put_bid=d["put_bid"],   put_ask=d["put_ask"],   put_oi=d["put_oi"],
                    call_symbol=d["call_symbol"], put_symbol=d["put_symbol"],
                )
        return result

    def _dte(self, expiry: str) -> float:
        """Days to expiry from today (using calendar days)."""
        exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        today = date.today()
        delta = (exp_date - today).days
        return max(float(delta), 0.001)   # avoid div-by-zero on expiry day

    def _liquidity_ok(self, row: OptionRow, cfg: InstrumentConfig,
                       min_oi: int) -> bool:
        return (row.call_oi >= min_oi and row.put_oi >= min_oi and
                row.call_bid > 0 and row.put_bid > 0 and
                row.call_ask > 0 and row.put_ask > 0)

    def _pick_lots(self, cfg: InstrumentConfig, net_dev: float) -> int:
        """
        Simple lot sizing: 1 lot minimum; scale up proportionally to deviation,
        capped at cfg.max_lots.
        """
        base_lots = max(1, int(net_dev / cfg.min_deviation))
        return min(base_lots, cfg.max_lots)

    def scan(
        self,
        instrument_key: str,
        option_chain: List[Dict],
        futures_price: float,
        futures_symbol: str,
        expiry: str,
        min_oi: int = 500,
    ) -> List[ParitySignal]:
        """
        Scan all strikes in the option chain for put-call parity deviations.
        Returns actionable ParitySignal objects sorted by net_deviation descending.
        """
        cfg = INSTRUMENTS[instrument_key]
        dte = self._dte(expiry)
        matrix = self.build_option_matrix(option_chain)

        signals: List[ParitySignal] = []

        for strike, row in matrix.items():
            if not self._liquidity_ok(row, cfg, min_oi):
                continue

            theoretical = theoretical_cp_spread(futures_price, strike, self.r, dte)
            call_mid = (row.call_bid + row.call_ask) / 2
            put_mid  = (row.put_bid  + row.put_ask)  / 2
            obs_neutral = call_mid - put_mid
            raw_dev = obs_neutral - theoretical

            # Determine if deviation is exploitable in either direction
            # raw_dev > 0 → call relatively expensive → sell call, buy put, buy futures (conversion)
            # raw_dev < 0 → put relatively expensive → buy call, sell put, sell futures (reversal)
            abs_dev = abs(raw_dev)
            direction = "NONE"
            if raw_dev > cfg.min_deviation:
                direction = "SHORT_CALL_LONG_PUT"
            elif raw_dev < -cfg.min_deviation:
                direction = "LONG_CALL_SHORT_PUT"
            else:
                continue

            lots = self._pick_lots(cfg, abs_dev)
            txn_cost = estimate_transaction_cost(cfg, lots, call_mid, put_mid, futures_price)
            cost_per_unit = txn_cost / (lots * cfg.lot_size)
            net_dev = abs_dev - cost_per_unit

            if net_dev <= 0:
                continue

            signals.append(ParitySignal(
                instrument=instrument_key,
                expiry=expiry,
                strike=strike,
                dte=dte,
                futures_price=futures_price,
                call_mid=call_mid,
                put_mid=put_mid,
                call_symbol=row.call_symbol,
                put_symbol=row.put_symbol,
                futures_symbol=futures_symbol,
                theoretical_spread=theoretical,
                observed_spread=obs_neutral,
                raw_deviation=raw_dev,
                transaction_cost=cost_per_unit,
                net_deviation=net_dev,
                direction=direction,
                lots=lots,
            ))

        signals.sort(key=lambda s: s.net_deviation, reverse=True)
        return signals

    def check_exit(
        self,
        signal: ParitySignal,
        current_call_bid: float,
        current_call_ask: float,
        current_put_bid: float,
        current_put_ask: float,
        current_futures: float,
        entry_deviation: float,
        exit_fraction: float,
        stop_loss_multiple: float,
    ) -> Tuple[bool, str]:
        """
        Returns (should_exit, reason).
        Exit when:
          - deviation has reverted to exit_fraction * entry_deviation (profit target)
          - deviation has expanded to stop_loss_multiple * entry_deviation (stop-loss)
        """
        dte = self._dte(signal.expiry)
        theoretical = theoretical_cp_spread(current_futures, signal.strike, self.r, dte)
        obs_now = ((current_call_bid + current_call_ask) / 2 -
                   (current_put_bid  + current_put_ask)  / 2)
        current_dev = abs(obs_now - theoretical)

        profit_target = abs(entry_deviation) * exit_fraction
        stop_loss     = abs(entry_deviation) * stop_loss_multiple

        if current_dev <= profit_target:
            return True, f"PROFIT_TARGET (dev={current_dev:.2f} <= target={profit_target:.2f})"
        if current_dev >= stop_loss:
            return True, f"STOP_LOSS (dev={current_dev:.2f} >= sl={stop_loss:.2f})"
        return False, ""
