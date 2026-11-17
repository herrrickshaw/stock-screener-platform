"""
Persist yfinance fetch results into Cassandra stock_quotes and read them back.

upsert_quotes() — called fire-and-forget after every /api/live/fetch
get_quotes()    — called during /api/portfolio/parse to enrich matched tickers
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from db import cassandra_client as cass

log = logging.getLogger(__name__)

_stmts: dict[str, Any] = {}
_hist_stmts: dict[str, Any] = {}


def _prepare_hist(s) -> None:
    if _hist_stmts:
        return
    ks = cass.KEYSPACE
    _hist_stmts['insert'] = s.prepare(
        f"INSERT INTO {ks}.price_history (yf_ticker, price_date, close_price) VALUES (?, ?, ?)"
    )
    _hist_stmts['select'] = s.prepare(
        f"SELECT close_price FROM {ks}.price_history WHERE yf_ticker = ? AND price_date = ?"
    )


def cache_price_on_date(yf_ticker: str, price_date, close_price: float) -> None:
    """Store a historical closing price in Cassandra. Silent no-op if offline."""
    s = cass.session()
    if s is None:
        return
    try:
        _prepare_hist(s)
        s.execute(_hist_stmts['insert'], (yf_ticker, price_date, close_price))
    except Exception as exc:
        log.debug('cache_price_on_date failed for %s %s: %s', yf_ticker, price_date, exc)


def get_cached_price(yf_ticker: str, price_date) -> Optional[float]:
    """Return cached closing price for a ticker on a given date, or None."""
    s = cass.session()
    if s is None:
        return None
    try:
        _prepare_hist(s)
        row = s.execute(_hist_stmts['select'], (yf_ticker, price_date)).one()
        return float(row.close_price) if row and row.close_price is not None else None
    except Exception:
        return None


def _prepare(s) -> None:
    if _stmts:
        return
    ks = cass.KEYSPACE
    _stmts['upsert'] = s.prepare(
        f"INSERT INTO {ks}.stock_quotes "
        "(market, yf_ticker, fetched_at, cmp, rsi, ema_20, ema_50, ema_200, rsi_signal, "
        " macd, macd_signal, pe, pb, roe, opm, market_cap, volume, volume_20d_avg, "
        " volume_ratio, high_52w, low_52w, debt_to_equity, beta, current_ratio, "
        " revenue_growth, eps, dividend_yield, "
        " ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, "
        " sector, industry, "
        " bb_upper, bb_lower, bb_pct, atr_14, stoch_k, stoch_d) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    _stmts['select_in'] = s.prepare(
        f"SELECT yf_ticker, fetched_at, cmp, rsi, ema_20, ema_50, ema_200, rsi_signal, "
        f"macd, macd_signal, pe, pb, roe, opm, market_cap, volume, volume_20d_avg, "
        f"volume_ratio, high_52w, low_52w, debt_to_equity, beta, current_ratio, "
        f"revenue_growth, eps, dividend_yield, "
        f"ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, "
        f"sector, industry, "
        f"bb_upper, bb_lower, bb_pct, atr_14, stoch_k, stoch_d "
        f"FROM {ks}.stock_quotes WHERE market = ? AND yf_ticker IN ?"
    )


def _f(row: pd.Series, key: str) -> Optional[float]:
    try:
        v = float(row.get(key))
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _i(row: pd.Series, key: str) -> Optional[int]:
    v = _f(row, key)
    return int(v) if v is not None else None


def _s(row: pd.Series, key: str) -> Optional[str]:
    v = row.get(key)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s if s else None


def _fv(v) -> Optional[float]:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _iv(v) -> Optional[int]:
    f = _fv(v)
    return int(f) if f is not None else None


def _sv(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s if s else None


# Columns read from the live frame (missing ones are added as None), then the
# (column, converter) order of the stock_quotes INSERT after (market, yf_ticker, fetched_at).
_ALL_COLS = [
    'ticker', 'rsi_signal', '_error',
    'cmp', 'rsi', 'ema_20', 'ema_50', 'ema_200', 'macd', 'macd_signal',
    'pe', 'pb', 'roe', 'opm', 'market_cap', 'volume', 'volume_20d_avg',
    'volume_ratio', 'high_52w', 'low_52w', 'debt_to_equity', 'beta',
    'current_ratio', 'revenue_growth', 'eps', 'dividend_yield',
    'ret_1d', 'ret_1w', 'ret_1m', 'ret_3m', 'ret_6m', 'ret_1y',
    'sector', 'industry', 'bb_upper', 'bb_lower', 'bb_pct',
    'atr_14', 'stoch_k', 'stoch_d',
]
_ROW_SPEC = (
    [('cmp', _fv), ('rsi', _fv), ('ema_20', _fv), ('ema_50', _fv), ('ema_200', _fv)]
    + [('rsi_signal', lambda v: str(v or 'HOLD'))]
    + [(c, _fv) for c in ('macd', 'macd_signal', 'pe', 'pb', 'roe', 'opm', 'market_cap')]
    + [('volume', _iv), ('volume_20d_avg', _iv)]
    + [(c, _fv) for c in (
        'volume_ratio', 'high_52w', 'low_52w', 'debt_to_equity', 'beta', 'current_ratio',
        'revenue_growth', 'eps', 'dividend_yield', 'ret_1d', 'ret_1w', 'ret_1m', 'ret_3m',
        'ret_6m', 'ret_1y')]
    + [('sector', _sv), ('industry', _sv)]
    + [(c, _fv) for c in ('bb_upper', 'bb_lower', 'bb_pct', 'atr_14', 'stoch_k', 'stoch_d')]
)


def _valid_quote_rows(live_df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with a blank ticker or an ``_error`` flag, and add any missing quote columns as None."""
    error_mask = live_df.get('_error', pd.Series(False, index=live_df.index)).fillna(False).astype(bool)
    ticker_mask = live_df['ticker'].notna() & (live_df['ticker'].astype(str).str.strip() != '') \
        if 'ticker' in live_df.columns else pd.Series(False, index=live_df.index)
    live_df = live_df[ticker_mask & ~error_mask].reset_index(drop=True)
    for col in _ALL_COLS:
        if col not in live_df.columns:
            live_df[col] = None
    return live_df


def _build_quote_rows(market: str, live_df: pd.DataFrame, now: datetime) -> list[tuple]:
    """Bind-parameter tuples for the stock_quotes upsert, one per valid row."""
    rows: list[tuple] = []
    # itertuples is ~5x faster than iterrows - avoid Series creation per row
    for row in live_df.itertuples(index=False, name='Q'):
        values = [conv(getattr(row, col)) for col, conv in _ROW_SPEC]
        rows.append((market, str(row.ticker).strip(), now, *values))
    return rows


def upsert_quotes(market: str, live_df: pd.DataFrame) -> int:
    """
    Write live fetch results into stock_quotes.
    Blocking — must be dispatched from a background thread.
    Returns the number of rows written.
    """
    s = cass.session()
    if s is None or live_df.empty:
        return 0

    _prepare(s)
    now = datetime.now(timezone.utc)

    live_df = _valid_quote_rows(live_df)
    if live_df.empty:
        return 0

    rows = _build_quote_rows(market, live_df, now)
    if not rows:
        return 0

    try:
        from cassandra.concurrent import execute_concurrent_with_args
        execute_concurrent_with_args(s, _stmts['upsert'], rows, concurrency=50)
        log.info('quote_updater: wrote %d quotes for %s', len(rows), market)
        return len(rows)
    except Exception as exc:
        log.warning('quote_updater: write error for %s: %s', market, exc)
        return 0


def get_market_quotes_df(market: str) -> pd.DataFrame:
    """
    Read ALL cached quotes for a market into a DataFrame ready for scanner input.
    Joins with instruments table for name/exchange. Returns empty DataFrame on failure.
    """
    s = cass.session()
    if s is None:
        return pd.DataFrame()

    _prepare(s)

    # Read all quotes for the market
    try:
        quote_rows = list(s.execute(
            f"SELECT yf_ticker, cmp, rsi, ema_20, ema_50, ema_200, rsi_signal, macd, macd_signal, "
            f"pe, pb, roe, opm, market_cap, volume, volume_20d_avg, volume_ratio, "
            f"high_52w, low_52w, debt_to_equity, beta, current_ratio, "
            f"revenue_growth, eps, dividend_yield, "
            f"ret_1d, ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, "
            f"sector, industry, "
            f"bb_upper, bb_lower, bb_pct, atr_14, stoch_k, stoch_d "
            f"FROM {cass.KEYSPACE}.stock_quotes WHERE market = %s",
            (market,),
        ))
    except Exception as exc:
        log.warning('get_market_quotes_df: read error for %s: %s', market, exc)
        return pd.DataFrame()

    if not quote_rows:
        return pd.DataFrame()

    # Build name + exchange lookup from instruments table
    name_map: dict[str, str] = {}
    exch_map: dict[str, str] = {}
    try:
        inst_rows = s.execute(
            f"SELECT yf_ticker, name, exchange FROM {cass.KEYSPACE}.instruments WHERE market = %s",
            (market,),
        )
        for r in inst_rows:
            if r.yf_ticker:
                name_map[r.yf_ticker] = r.name or ''
                exch_map[r.yf_ticker] = r.exchange or ''
    except Exception as exc:
        log.debug('get_market_quotes_df: instrument lookup failed for %s: %s', market, exc)

    records = []
    for r in quote_rows:
        if r.cmp is None:
            continue
        rec = {
            'ticker':          r.yf_ticker,
            'name':            name_map.get(r.yf_ticker, ''),
            'cmp':             r.cmp,
            'rsi':             r.rsi,
            'ema_20':          getattr(r, 'ema_20', None),
            'ema_50':          r.ema_50,
            'ema_200':         getattr(r, 'ema_200', None),
            'macd':            getattr(r, 'macd', None),
            'macd_signal':     getattr(r, 'macd_signal', None),
            'rsi_signal':      r.rsi_signal or 'HOLD',
            'pe':              r.pe,
            'pb':              r.pb,
            'roe':             r.roe,
            'opm':             r.opm,
            'market_cap':      r.market_cap,
            'volume':          r.volume,
            'volume_20d_avg':  getattr(r, 'volume_20d_avg', None),
            'volume_ratio':    getattr(r, 'volume_ratio', None),
            'high_52w':        r.high_52w,
            'low_52w':         r.low_52w,
            'debt_to_equity':  r.debt_to_equity,
            'beta':            getattr(r, 'beta', None),
            'current_ratio':   getattr(r, 'current_ratio', None),
            'revenue_growth':  getattr(r, 'revenue_growth', None),
            'eps':             getattr(r, 'eps', None),
            'dividend_yield':  getattr(r, 'dividend_yield', None),
            'ret_1d':          getattr(r, 'ret_1d', None),
            'ret_1w':          getattr(r, 'ret_1w', None),
            'ret_1m':          getattr(r, 'ret_1m', None),
            'ret_3m':          getattr(r, 'ret_3m', None),
            'ret_6m':          getattr(r, 'ret_6m', None),
            'ret_1y':          getattr(r, 'ret_1y', None),
            'sector':          getattr(r, 'sector', None) or '',
            'industry':        getattr(r, 'industry', None) or '',
            'bb_upper':        getattr(r, 'bb_upper', None),
            'bb_lower':        getattr(r, 'bb_lower', None),
            'bb_pct':          getattr(r, 'bb_pct', None),
            'atr_14':          getattr(r, 'atr_14', None),
            'stoch_k':         getattr(r, 'stoch_k', None),
            'stoch_d':         getattr(r, 'stoch_d', None),
            '_exchange':       exch_map.get(r.yf_ticker, ''),
        }
        records.append(rec)

    return pd.DataFrame(records) if records else pd.DataFrame()


def get_quotes(market: str, yf_tickers: list[str]) -> dict[str, dict]:
    """
    Fetch cached quote data for a list of yfinance tickers.
    Returns {yf_ticker: {cmp, rsi, ema_50, rsi_signal, fetched_at, ...}}.
    Returns {} if Cassandra is offline or tickers list is empty.
    """
    s = cass.session()
    if s is None or not yf_tickers:
        return {}

    _prepare(s)
    try:
        rows = s.execute(_stmts['select_in'], (market, yf_tickers))
        return {
            row.yf_ticker: {
                'cmp':            row.cmp,
                'rsi':            row.rsi,
                'ema_20':         getattr(row, 'ema_20', None),
                'ema_50':         row.ema_50,
                'ema_200':        getattr(row, 'ema_200', None),
                'macd':           getattr(row, 'macd', None),
                'macd_signal':    getattr(row, 'macd_signal', None),
                'rsi_signal':     row.rsi_signal,
                'pe':             row.pe,
                'pb':             row.pb,
                'roe':            row.roe,
                'opm':            row.opm,
                'market_cap':     row.market_cap,
                'volume':         row.volume,
                'volume_20d_avg': getattr(row, 'volume_20d_avg', None),
                'volume_ratio':   getattr(row, 'volume_ratio', None),
                'high_52w':       row.high_52w,
                'low_52w':        row.low_52w,
                'debt_to_equity': row.debt_to_equity,
                'beta':           getattr(row, 'beta', None),
                'current_ratio':  getattr(row, 'current_ratio', None),
                'revenue_growth': getattr(row, 'revenue_growth', None),
                'eps':            getattr(row, 'eps', None),
                'dividend_yield': getattr(row, 'dividend_yield', None),
                'ret_1d':         getattr(row, 'ret_1d', None),
                'ret_1w':         getattr(row, 'ret_1w', None),
                'ret_1m':         getattr(row, 'ret_1m', None),
                'ret_3m':         getattr(row, 'ret_3m', None),
                'ret_6m':         getattr(row, 'ret_6m', None),
                'ret_1y':         getattr(row, 'ret_1y', None),
                'sector':         getattr(row, 'sector', None) or '',
                'industry':       getattr(row, 'industry', None) or '',
                'bb_upper':       getattr(row, 'bb_upper', None),
                'bb_lower':       getattr(row, 'bb_lower', None),
                'bb_pct':         getattr(row, 'bb_pct', None),
                'atr_14':         getattr(row, 'atr_14', None),
                'stoch_k':        getattr(row, 'stoch_k', None),
                'stoch_d':        getattr(row, 'stoch_d', None),
                'fetched_at':     row.fetched_at.isoformat() if row.fetched_at else None,
            }
            for row in rows
        }
    except Exception as exc:
        log.warning('quote_updater: read error for %s: %s', market, exc)
        return {}
