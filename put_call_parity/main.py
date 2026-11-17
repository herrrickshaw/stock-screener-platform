"""
main.py
=======
Entry point for the put-call parity arbitrage strategy.

Usage:
    python -m put_call_parity.main                # live trading
    python -m put_call_parity.main --backtest     # offline parity analysis (no orders)
    python -m put_call_parity.main --broker kite  # broker override

Environment variables (required before running live):
    KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN
  or
    UPSTOX_ACCESS_TOKEN
  or
    ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET
"""

import argparse
import logging


def _parse_args():
    p = argparse.ArgumentParser(description="Put-Call Parity Arbitrage Trader")
    p.add_argument("--broker", choices=["kite", "upstox", "angel"], default="kite")
    p.add_argument("--backtest", action="store_true",
                   help="Run in analysis-only mode (no real orders)")
    p.add_argument("--instrument", nargs="+",
                   choices=["BANKNIFTY", "CRUDEOIL", "SILVER"],
                   help="Restrict to specific instruments (default: all)")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


def main():
    args = _parse_args()
    logging.getLogger().setLevel(args.log_level)

    if args.backtest:
        _run_backtest(args)
        return

    # Live trading
    from .broker import get_broker
    from .strategy import Strategy
    import put_call_parity.config as cfg_module

    if args.instrument:
        # Restrict the INSTRUMENTS dict in place
        keep = {k: v for k, v in cfg_module.INSTRUMENTS.items() if k in args.instrument}
        cfg_module.INSTRUMENTS.clear()
        cfg_module.INSTRUMENTS.update(keep)

    broker = get_broker(args.broker)
    strategy = Strategy(broker=broker)
    strategy.run()


# ---------------------------------------------------------------------------
# Backtest / analysis mode
# ---------------------------------------------------------------------------
def _run_backtest(args):
    """
    Offline analysis: reads a JSON option-chain snapshot and prints
    parity deviations without placing any orders.

    Snapshot format (option_chain_snapshot.json):
    [
      {
        "instrument": "BANKNIFTY",
        "expiry": "2024-01-25",
        "futures_price": 47500.0,
        "futures_symbol": "BANKNIFTY24JAN47500FUT",
        "chain": [
          {"strike": 47000, "instrument_type": "CE", "bid": 600, "ask": 605, "oi": 8000, "tradingsymbol": "BANKNIFTY24JAN47000CE"},
          {"strike": 47000, "instrument_type": "PE", "bid": 95,  "ask": 100, "oi": 7500, "tradingsymbol": "BANKNIFTY24JAN47000PE"},
          ...
        ]
      }
    ]
    """
    import json
    from pathlib import Path
    from .parity_engine import ParityEngine
    from .config import INSTRUMENTS

    snapshot_path = Path("option_chain_snapshot.json")
    if not snapshot_path.exists():
        print("[backtest] option_chain_snapshot.json not found.")
        print("           Create a snapshot file or fetch live data first.")
        _print_sample_snapshot()
        return

    with open(snapshot_path) as f:
        snapshots = json.load(f)

    engine = ParityEngine()
    for snap in snapshots:
        inst_key = snap["instrument"]
        if inst_key not in INSTRUMENTS:
            continue
        if args.instrument and inst_key not in args.instrument:
            continue

        signals = engine.scan(
            instrument_key=inst_key,
            option_chain=snap["chain"],
            futures_price=snap["futures_price"],
            futures_symbol=snap["futures_symbol"],
            expiry=snap["expiry"],
            min_oi=0,   # relax OI filter for backtest
        )

        print(f"\n{'='*70}")
        print(f"  {inst_key}  |  Expiry: {snap['expiry']}  |  Futures: {snap['futures_price']:.2f}")
        print(f"{'='*70}")
        if not signals:
            print("  No actionable deviations found.")
            continue

        print(f"  {'Strike':>10}  {'Direction':<25}  {'RawDev':>8}  {'TxnCost':>8}  {'NetDev':>8}  {'Lots':>5}")
        print(f"  {'-'*10}  {'-'*25}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*5}")
        for s in signals:
            print(
                f"  {s.strike:>10.0f}  {s.direction:<25}  "
                f"{s.raw_deviation:>8.2f}  {s.transaction_cost:>8.2f}  "
                f"{s.net_deviation:>8.2f}  {s.lots:>5}"
            )


def _print_sample_snapshot():
    sample = [
        {
            "instrument": "BANKNIFTY",
            "expiry": "2024-01-25",
            "futures_price": 47500.0,
            "futures_symbol": "BANKNIFTY24JANFUT",
            "chain": [
                {"strike": 47000, "instrument_type": "CE", "bid": 600.0, "ask": 605.0,
                 "oi": 8000, "tradingsymbol": "BANKNIFTY24JAN47000CE", "last_price": 602.5, "volume": 1000},
                {"strike": 47000, "instrument_type": "PE", "bid": 80.0, "ask": 85.0,
                 "oi": 7500, "tradingsymbol": "BANKNIFTY24JAN47000PE", "last_price": 82.5, "volume": 900},
                {"strike": 47500, "instrument_type": "CE", "bid": 300.0, "ask": 305.0,
                 "oi": 12000, "tradingsymbol": "BANKNIFTY24JAN47500CE", "last_price": 302.5, "volume": 2000},
                {"strike": 47500, "instrument_type": "PE", "bid": 295.0, "ask": 300.0,
                 "oi": 11000, "tradingsymbol": "BANKNIFTY24JAN47500PE", "last_price": 297.5, "volume": 1800},
            ]
        }
    ]
    import json
    print("\nSample option_chain_snapshot.json content:")
    print(json.dumps(sample, indent=2))


if __name__ == "__main__":
    main()
