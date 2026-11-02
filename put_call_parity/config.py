"""
config.py
=========
Central configuration for the put-call parity arbitrage strategy.
Covers BankNifty (NSE), Crude Oil Futures (MCX), and Silver Futures (MCX).
"""

from dataclasses import dataclass
from typing import Dict


# ---------------------------------------------------------------------------
# Broker / API credentials  — fill via environment variables or .env file
# ---------------------------------------------------------------------------
BROKER = "kite"          # supported: "kite" | "upstox" | "angel"

KITE_API_KEY    = ""     # set via env KITE_API_KEY
KITE_API_SECRET = ""     # set via env KITE_API_SECRET
KITE_ACCESS_TOKEN = ""   # set after login

UPSTOX_API_KEY    = ""
UPSTOX_API_SECRET = ""
UPSTOX_ACCESS_TOKEN = ""

ANGEL_API_KEY    = ""
ANGEL_CLIENT_ID  = ""
ANGEL_PASSWORD   = ""
ANGEL_TOTP_SECRET = ""


# ---------------------------------------------------------------------------
# Risk-free rate (annualised)
# ---------------------------------------------------------------------------
RISK_FREE_RATE = 0.068   # ~6.8 % (current Indian 91-day T-bill yield)


# ---------------------------------------------------------------------------
# Instrument definitions
# ---------------------------------------------------------------------------
@dataclass
class InstrumentConfig:
    name: str
    exchange: str              # NSE | MCX
    segment: str               # NFO | MCX-FO
    underlying_symbol: str     # e.g. "BANKNIFTY", "CRUDEOIL", "SILVER"
    futures_symbol: str        # root used when searching futures chain
    option_symbol: str         # root used when searching option chain
    lot_size: int
    tick_size: float
    # Maximum lots per leg to stay within exchange position limits
    max_lots: int
    # Minimum parity deviation (in Rs / unit) to trigger a trade
    min_deviation: float
    # Deviation at which to exit (take-profit target as fraction of entry dev)
    exit_fraction: float
    # Stop-loss: close if deviation widens beyond this multiple of entry dev
    stop_loss_multiple: float
    # Currency multiplier for MCX commodities (contract value per lot)
    contract_value_multiplier: float = 1.0


INSTRUMENTS: Dict[str, InstrumentConfig] = {
    "BANKNIFTY": InstrumentConfig(
        name="Bank Nifty",
        exchange="NSE",
        segment="NFO",
        underlying_symbol="BANKNIFTY",
        futures_symbol="BANKNIFTY",
        option_symbol="BANKNIFTY",
        lot_size=15,
        tick_size=0.05,
        max_lots=50,
        min_deviation=30.0,    # Rs 30 per index point minimum edge
        exit_fraction=0.2,     # exit when deviation shrinks to 20 % of entry
        stop_loss_multiple=2.5,
    ),
    "CRUDEOIL": InstrumentConfig(
        name="Crude Oil",
        exchange="MCX",
        segment="MCX-FO",
        underlying_symbol="CRUDEOIL",
        futures_symbol="CRUDEOIL",
        option_symbol="CRUDEOIL",
        lot_size=100,          # 100 barrels per lot
        tick_size=1.0,
        max_lots=20,
        min_deviation=5.0,     # Rs 5 per barrel
        exit_fraction=0.2,
        stop_loss_multiple=2.5,
        contract_value_multiplier=100.0,
    ),
    "SILVER": InstrumentConfig(
        name="Silver",
        exchange="MCX",
        segment="MCX-FO",
        underlying_symbol="SILVER",
        futures_symbol="SILVER",
        option_symbol="SILVER",
        lot_size=30,           # 30 kg per lot
        tick_size=1.0,
        max_lots=20,
        min_deviation=50.0,    # Rs 50 per kg
        exit_fraction=0.2,
        stop_loss_multiple=2.5,
        contract_value_multiplier=30.0,
    ),
}


# ---------------------------------------------------------------------------
# Transaction cost model  (per-lot, per-leg, in Rs)
# ---------------------------------------------------------------------------
@dataclass
class CostModel:
    # Brokerage per order (flat or % — simplified to flat per-lot here)
    brokerage_per_order: float = 20.0
    # STT on sell side (options: 0.0625 % of premium; futures: 0.01 % of value)
    stt_options_sell_rate: float = 0.000625
    stt_futures_rate: float = 0.0001
    # Exchange transaction charges (NSE-FO: 0.05 %, MCX-FO: 0.026 %)
    exchange_charge_nse: float = 0.0005
    exchange_charge_mcx: float = 0.00026
    # GST on brokerage + exchange charges
    gst_rate: float = 0.18
    # SEBI turnover fee
    sebi_rate: float = 0.000001

COST_MODEL = CostModel()


# ---------------------------------------------------------------------------
# Strategy parameters
# ---------------------------------------------------------------------------
SCAN_INTERVAL_SECONDS  = 30    # how often to scan for opportunities
MAX_OPEN_POSITIONS     = 6     # total open arbitrage positions at one time
POSITION_FILE          = "positions.json"   # persisted position book
LOG_FILE               = "parity_trader.log"

# Strike selection: scan this many strikes around ATM on each side
STRIKES_AROUND_ATM = 5

# Minimum open interest to consider a strike liquid enough
MIN_OI_THRESHOLD = 500         # contracts (or lots for MCX)

# Minimum days to expiry to trade (avoid pin-risk near expiry)
MIN_DTE = 2
MAX_DTE = 30
