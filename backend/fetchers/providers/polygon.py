"""
Polygon.io provider — best source for US equities.
REST API v2/vX; free tier: 5 req/min delayed; paid: unlimited real-time.
https://polygon.io/docs/stocks
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests

from fetchers.providers.base import DataProvider, QuoteData, compute_technicals
from config.providers import cfg

log = logging.getLogger(__name__)

_BASE = 'https://api.polygon.io'
_SESSION = requests.Session()
_SESSION.headers['User-Agent'] = 'herrrickshaw/1.0'


def _get(path: str, params: dict | None = None, retries: int = 3) -> dict:
    params = {**(params or {}), 'apiKey': cfg.POLYGON_KEY}
    for attempt in range(retries):
        try:
            r = _SESSION.get(f'{_BASE}{path}', params=params, timeout=15)
            if r.status_code == 429:
                time.sleep(60 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            log.debug('polygon._get(%s) attempt %d: %s', path, attempt, exc)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return {}


def _safe_float(v) -> Optional[float]:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


class PolygonProvider(DataProvider):
    name = 'polygon'

    def is_available(self) -> bool:
        return bool(cfg.POLYGON_KEY)

    def get_ohlcv(self, ticker: str, period_days: int = 365) -> pd.DataFrame:
        end   = date.today()
        start = end - timedelta(days=period_days + 10)
        data  = _get(f'/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}',
                     {'adjusted': 'true', 'sort': 'asc', 'limit': 50000})
        results = data.get('results', [])
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results)
        df['date'] = pd.to_datetime(df['t'], unit='ms')
        df = df.set_index('date').rename(columns={
            'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'
        })[['Open', 'High', 'Low', 'Close', 'Volume']]
        return df

    def get_quotes_bulk(self, tickers: list[str], market: str) -> dict[str, QuoteData]:
        if market != 'us' or not tickers:
            return {}
        result: dict[str, QuoteData] = {}
        # Snapshot endpoint: up to 250 tickers per call
        for i in range(0, len(tickers), 250):
            batch = tickers[i:i + 250]
            data  = _get('/v2/snapshot/locale/us/markets/stocks/tickers',
                         {'tickers': ','.join(batch)})
            for snap in data.get('tickers', []):
                ticker = snap.get('ticker', '')
                try:
                    day  = snap.get('day', {})
                    prev = snap.get('prevDay', {})
                    cmp  = _safe_float(snap.get('lastTrade', {}).get('p')
                                       or day.get('c'))
                    if not cmp:
                        continue

                    ret_1d = None
                    prev_c = _safe_float(prev.get('c'))
                    if cmp and prev_c and prev_c > 0:
                        ret_1d = round((cmp - prev_c) / prev_c * 100, 2)

                    result[ticker] = QuoteData(
                        ticker=ticker, source='polygon',
                        cmp=cmp,
                        volume=int(day.get('v', 0)) or None,
                        # The snapshot only has today's high/low, which is not the
                        # 52-week range; leave high_52w/low_52w for another provider.
                        ret_1d=ret_1d,
                    )
                except Exception as exc:
                    log.debug('polygon snapshot[%s]: %s', ticker, exc)

            time.sleep(0.2)  # respect free-tier rate limit

        # For tickers not in snapshot, fetch OHLCV + technicals
        missing = [t for t in tickers if t not in result]
        for ticker in missing[:50]:   # cap to avoid timeout
            df = self.get_ohlcv(ticker)
            if df.empty:
                continue
            tech = compute_technicals(df['Close'], df.get('Volume'))
            if tech.get('cmp'):
                result[ticker] = QuoteData(ticker=ticker, source='polygon', **tech)

        return result

    def get_fundamentals(self, ticker: str, market: str) -> dict:
        if market != 'us':
            return {}
        # Ticker details (sector, industry, name, market cap)
        details = _get(f'/v3/reference/tickers/{ticker}')
        res     = details.get('results', {})

        # Latest financials
        fins = _get('/vX/reference/financials',
                    {'ticker': ticker, 'limit': 1, 'sort': 'period_of_report_date'})
        fin  = fins.get('results', [{}])[0].get('financials', {}) if fins.get('results') else {}

        def _fin(section: str, key: str) -> Optional[float]:
            return _safe_float(fin.get(section, {}).get(key, {}).get('value'))

        mc = _safe_float(res.get('market_cap'))
        return {
            'name':           res.get('name') or None,
            'sector':         res.get('sic_description') or None,
            'market_cap':     round(mc / 1e6, 2) if mc else None,
            'revenue_growth': None,   # requires two periods; skip here
        }

    def get_quote(self, ticker: str, market: str) -> Optional[QuoteData]:
        if market != 'us':
            return None
        df = self.get_ohlcv(ticker)
        if df.empty:
            return None
        tech = compute_technicals(df['Close'], df.get('Volume'))
        if not tech.get('cmp'):
            return None
        fund = self.get_fundamentals(ticker, market)
        return QuoteData(ticker=ticker, source='polygon', **{**tech, **fund})
