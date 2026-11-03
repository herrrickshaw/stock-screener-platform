"""
Bulk live-quote fetcher for all instruments in Cassandra.

Uses the multi-source provider system (fetchers/multi_source.py) which
routes requests to the best available provider per market with fallback:
  US:     Polygon → IEX → Tradier → TradingView → Alpha Vantage → Yahoo
  India:  IB → Yahoo → TradingView → Alpha Vantage
  Europe: IB → Yahoo → TradingView → Alpha Vantage
  Others: Yahoo → TradingView

Phase 1 — bulk OHLCV via get_quotes_bulk() (provider-specific batch endpoints)
Phase 2 — per-ticker fundamentals via get_fundamentals() (merged across providers)

Suffix strategy (per Cassandra instruments):
  india  — bare NSE symbols (20MICRONS) → appends .NS for yfinance
  us     — bare symbols (AAPL)          → no suffix
  europe — pre-suffixed (1COV.DE …)     → no suffix
  japan  — pre-suffixed (1301.T …)      → no suffix
  korea  — pre-suffixed (000020.KS …)   → no suffix
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd

from db import cassandra_client as cass
from db.quote_updater import upsert_quotes

log = logging.getLogger(__name__)

MARKETS = ['india', 'us', 'europe', 'japan', 'korea', 'china', 'hong_kong', 'canada']

_MARKET_CFG: dict[str, dict] = {
    'india':     {'suffix': '.NS', 'is_inr': True},
    'us':        {'suffix': '',    'is_inr': False},
    'europe':    {'suffix': '',    'is_inr': False},
    'japan':     {'suffix': '',    'is_inr': False},
    'korea':     {'suffix': '',    'is_inr': False},
    'china':     {'suffix': '',    'is_inr': False},
    'hong_kong': {'suffix': '',    'is_inr': False},
    'canada':    {'suffix': '',    'is_inr': False},
}

_progress: dict[str, dict] = {}
_lock     = threading.Lock()
_cancel   = threading.Event()


# ── progress helpers ──────────────────────────────────────────────────────────

def get_progress() -> dict:
    with _lock:
        return dict(_progress)


def cancel():
    _cancel.set()


# ── Cassandra helpers ─────────────────────────────────────────────────────────

def _get_tickers(market: str) -> list[str]:
    s = cass.session()
    if s is None:
        return []
    try:
        rows = s.execute(
            f"SELECT yf_ticker FROM {cass.KEYSPACE}.instruments WHERE market = %s",
            (market,),
        )
        return [r.yf_ticker for r in rows if r.yf_ticker]
    except Exception as exc:
        log.error('bulk_fetcher._get_tickers(%s): %s', market, exc)
        return []


def _yf_sym(ticker: str, suffix: str) -> str:
    """Add suffix only when the ticker doesn't already carry one."""
    if not suffix:
        return ticker
    return ticker if ticker.upper().endswith(suffix.upper()) else f'{ticker}{suffix}'


# ── Phase 1: bulk OHLCV via multi-source provider ────────────────────────────

def _fetch_ohlcv_batch(
    tickers: list[str],
    suffix: str,
    is_inr: bool,
    market: str = 'us',
) -> list[dict]:
    """
    Fetch 1-year OHLCV for a batch of tickers via the best available provider.
    Returns a list of row dicts (without fundamentals).
    """
    from fetchers.multi_source import get_quotes_bulk

    # Build yf-style ticker symbols (India needs .NS suffix added)
    yf_tickers = [_yf_sym(t, suffix) for t in tickers]
    sym_back   = dict(zip(yf_tickers, tickers))   # yf_ticker → original DB key

    batch_results = get_quotes_bulk(yf_tickers, market)

    rows: list[dict] = []
    for yf_sym, quote in batch_results.items():
        orig = sym_back.get(yf_sym, yf_sym)
        d    = quote.to_dict()
        d['ticker']  = orig
        d['_source'] = quote.source
        rows.append(d)

    return rows


# ── Phase 2: per-ticker fundamentals via multi-source ────────────────────────

def _fetch_info_one(ticker: str, suffix: str, is_inr: bool, market: str = 'us') -> dict:
    """Fetch and merge fundamentals for one ticker from the best available providers."""
    from fetchers.multi_source import get_fundamentals
    yf_sym = _yf_sym(ticker, suffix)
    try:
        return get_fundamentals(yf_sym, market)
    except Exception as exc:
        log.debug('_fetch_info_one(%s): %s', ticker, exc)
        return {}


# ── Main fetch functions ──────────────────────────────────────────────────────

def _set_progress(market: str, value: dict) -> None:
    with _lock:
        _progress[market] = value


def _update_progress(market: str, **fields) -> None:
    with _lock:
        _progress[market].update(fields)


def _run_phase1(market: str, tickers: list[str], suffix: str, is_inr: bool,
                batch_size: int, inter_batch_delay: float, started: float) -> tuple[dict, int, int]:
    """Phase 1: OHLCV batches. Returns (rows by ticker, done count, error count)."""
    total = len(tickers)
    done = errors = 0
    phase1_rows: dict[str, dict] = {}  # ticker -> partial row

    for i in range(0, total, batch_size):
        if _cancel.is_set():
            break
        batch = tickers[i:i + batch_size]
        batch_rows = _fetch_ohlcv_batch(batch, suffix, is_inr, market)

        for row in batch_rows:
            phase1_rows[row['ticker']] = row

        batch_done = len(batch_rows)
        done   += batch_done
        errors += len(batch) - batch_done

        elapsed = time.time() - started
        rate    = round((done + errors) / elapsed * 60, 1) if elapsed > 0 else 0
        _update_progress(market, done=done + errors, errors=errors,
                         elapsed_s=round(elapsed, 1), rate_per_min=rate)

        if inter_batch_delay > 0:
            time.sleep(inter_batch_delay)
    return phase1_rows, done, errors


def _run_phase2(market: str, phase1_rows: dict[str, dict], suffix: str, is_inr: bool,
                max_workers: int, started: float) -> None:
    """Phase 2: throttled per-ticker fundamentals merged into ``phase1_rows``."""
    _update_progress(market, phase=2)
    log.info('bulk_fetcher: [%s] phase 2 (fundamentals) — %d tickers', market, len(phase1_rows))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {
            pool.submit(_fetch_info_one, t, suffix, is_inr, market): t
            for t in list(phase1_rows.keys())
        }
        for fut in as_completed(futs, timeout=600):
            t = futs[fut]
            try:
                extras = fut.result()
                if extras:
                    phase1_rows[t].update(extras)
            except Exception as exc:
                log.debug('bulk_fetcher: [%s] fundamentals for %s failed: %s', market, t, exc)

    _update_progress(market, elapsed_s=round(time.time() - started, 1))


def fetch_market_quotes(
    market: str,
    batch_size: int = 100,
    max_workers: int = 6,
    with_fundamentals: bool = True,
    inter_batch_delay: float = 0.5,
) -> dict:
    """
    Fetch live quotes for every instrument in one market and persist to Cassandra.
    Blocking — must be called from a background thread.
    """
    cfg    = _MARKET_CFG.get(market, {'suffix': '', 'is_inr': False})
    suffix = cfg['suffix']
    is_inr = cfg['is_inr']

    tickers = _get_tickers(market)
    if not tickers:
        result = {'market': market, 'total': 0, 'done': 0, 'errors': 0,
                  'written': 0, 'status': 'no_instruments', 'elapsed_s': 0}
        _set_progress(market, result)
        return result

    total   = len(tickers)
    written = 0
    started = time.time()

    _set_progress(market, {
        'status': 'running', 'total': total,
        'done': 0, 'errors': 0, 'written': 0,
        'elapsed_s': 0, 'rate_per_min': 0, 'phase': 1,
    })

    log.info('bulk_fetcher: [%s] phase 1 (OHLCV) — %d tickers, batch=%d', market, total, batch_size)
    phase1_rows, done, errors = _run_phase1(market, tickers, suffix, is_inr,
                                            batch_size, inter_batch_delay, started)

    if with_fundamentals and phase1_rows and not _cancel.is_set():
        _run_phase2(market, phase1_rows, suffix, is_inr, max_workers, started)

    if phase1_rows:
        written = upsert_quotes(market, pd.DataFrame(list(phase1_rows.values())))

    elapsed = time.time() - started
    result = {
        'market': market, 'total': total, 'done': done, 'errors': errors,
        'written': written, 'elapsed_s': round(elapsed, 1),
        'status': 'cancelled' if _cancel.is_set() else 'done',
        'rate_per_min': round(total / elapsed * 60, 1) if elapsed > 0 else 0,
    }
    _set_progress(market, result)

    log.info('bulk_fetcher: [%s] %s — %d written in %.0fs',
             market, result['status'], written, elapsed)
    return result


def fetch_all_quotes(
    markets: Optional[list[str]] = None,
    batch_size: int = 100,
    max_workers: int = 6,
    with_fundamentals: bool = True,
) -> list[dict]:
    """Fetch quotes for all markets sequentially to respect rate limits."""
    _cancel.clear()
    targets = [m for m in (markets or MARKETS) if m in _MARKET_CFG]
    results = []
    for m in targets:
        if _cancel.is_set():
            break
        results.append(fetch_market_quotes(
            m,
            batch_size=batch_size,
            max_workers=max_workers,
            with_fundamentals=with_fundamentals,
        ))
    return results
