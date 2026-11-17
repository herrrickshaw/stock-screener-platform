"""
Abstract base class and shared data types for all data providers.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd


@dataclass
class QuoteData:
    """Canonical quote + fundamentals record returned by every provider."""
    ticker:          str
    source:          str

    # Price / technicals
    cmp:             Optional[float] = None
    rsi:             Optional[float] = None
    ema_20:          Optional[float] = None
    ema_50:          Optional[float] = None
    ema_200:         Optional[float] = None
    macd:            Optional[float] = None
    macd_signal:     Optional[float] = None
    rsi_signal:      str             = 'HOLD'
    high_52w:        Optional[float] = None
    low_52w:         Optional[float] = None
    volume:          Optional[int]   = None
    volume_20d_avg:  Optional[int]   = None
    volume_ratio:    Optional[float] = None

    # Bollinger Bands (20-day SMA ± 2σ)
    bb_upper:        Optional[float] = None
    bb_lower:        Optional[float] = None
    bb_pct:          Optional[float] = None   # 0 = at lower band, 1 = at upper band

    # Volatility / momentum oscillators
    atr_14:          Optional[float] = None   # Average True Range (14-day Wilder's)
    stoch_k:         Optional[float] = None   # Stochastic %K (14-day)
    stoch_d:         Optional[float] = None   # Stochastic %D (3-day SMA of %K)

    # Period returns (%)
    ret_1d:  Optional[float] = None
    ret_1w:  Optional[float] = None
    ret_1m:  Optional[float] = None
    ret_3m:  Optional[float] = None
    ret_6m:  Optional[float] = None
    ret_1y:  Optional[float] = None

    # Fundamentals
    pe:             Optional[float] = None
    pb:             Optional[float] = None
    roe:            Optional[float] = None   # %
    opm:            Optional[float] = None   # %
    market_cap:     Optional[float] = None   # USD M or INR Cr
    debt_to_equity: Optional[float] = None
    beta:           Optional[float] = None
    current_ratio:  Optional[float] = None
    revenue_growth: Optional[float] = None   # %
    eps:            Optional[float] = None
    dividend_yield: Optional[float] = None   # %

    # Meta
    sector:   Optional[str] = None
    industry: Optional[str] = None
    name:     Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def merge(self, other: 'QuoteData') -> 'QuoteData':
        """Fill None fields from another QuoteData (self takes priority)."""
        d = asdict(self)
        for k, v in asdict(other).items():
            if d.get(k) is None and v is not None:
                d[k] = v
        d['source'] = f'{self.source}+{other.source}'
        return QuoteData(**d)


def _rsi14(closes: pd.Series) -> Optional[float]:
    """Wilder's smoothed RSI-14; None below 15 bars."""
    if len(closes) < 15:
        return None
    delta = closes.diff().dropna()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    ag = float(gains.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
    al = float(losses.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
    return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)


def _emas(closes: pd.Series) -> tuple:
    n = len(closes)
    ema20 = round(float(closes.ewm(span=20, adjust=False).mean().iloc[-1]), 2)
    ema50 = round(float(closes.ewm(span=50, adjust=False).mean().iloc[-1]), 2)
    ema200 = round(float(closes.ewm(span=200, adjust=False).mean().iloc[-1]), 2) if n >= 50 else None
    return ema20, ema50, ema200


def _macd(closes: pd.Series) -> tuple:
    """MACD (12/26/9) line and signal; each None until enough bars."""
    n = len(closes)
    if n < 26:
        return None, None
    ml = closes.ewm(span=12, adjust=False).mean() - closes.ewm(span=26, adjust=False).mean()
    macd_val = round(float(ml.iloc[-1]), 4)
    macd_sig = round(float(ml.ewm(span=9, adjust=False).mean().iloc[-1]), 4) if n >= 35 else None
    return macd_val, macd_sig


def _bollinger(closes: pd.Series, cmp: float) -> tuple:
    """20-day SMA +/- 2 sigma bands and %B position."""
    if len(closes) < 20:
        return None, None, None
    tail20 = closes.iloc[-20:]
    sma20 = float(tail20.mean())
    std20 = float(tail20.std(ddof=1))
    bb_upper = round(sma20 + 2 * std20, 2)
    bb_lower = round(sma20 - 2 * std20, 2)
    bb_range = bb_upper - bb_lower
    bb_pct = round((cmp - bb_lower) / bb_range, 3) if bb_range > 0 else None
    return bb_upper, bb_lower, bb_pct


def _atr14(closes: pd.Series, highs, lows) -> Optional[float]:
    """Wilder's ATR-14; needs highs and lows."""
    if highs is None or lows is None:
        return None
    h_s = highs.dropna()
    l_s = lows.dropna()
    min_len = min(len(h_s), len(l_s), len(closes))
    if min_len < 15:
        return None
    h_a = h_s.iloc[-min_len:].values
    l_a = l_s.iloc[-min_len:].values
    c_a = closes.iloc[-min_len:].values
    # True Range vectors (skip first bar - no previous close)
    tr_hl = h_a[1:] - l_a[1:]
    tr_hpc = abs(h_a[1:] - c_a[:-1])
    tr_lpc = abs(l_a[1:] - c_a[:-1])
    tr = pd.Series([max(a, b, c) for a, b, c in zip(tr_hl, tr_hpc, tr_lpc)])
    return round(float(tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1]), 4)


def _stochastic(closes: pd.Series, highs, lows) -> tuple:
    """Stochastic %K/%D (14/3); needs highs and lows."""
    if highs is None or lows is None:
        return None, None
    h_s = highs.dropna()
    l_s = lows.dropna()
    min_len = min(len(h_s), len(l_s), len(closes))
    if min_len < 17:  # 14 for %K + 3 for %D
        return None, None
    c_s = closes.iloc[-min_len:]
    h_14 = h_s.iloc[-min_len:].rolling(14).max()
    l_14 = l_s.iloc[-min_len:].rolling(14).min()
    denom = (h_14 - l_14).replace(0, float('nan'))
    k_series = pd.Series(100 * (c_s.values - l_14.values) / denom.values).dropna()
    if len(k_series) >= 3:
        return round(float(k_series.iloc[-1]), 2), round(float(k_series.iloc[-3:].mean()), 2)
    return None, None


def _period_return(closes: pd.Series, cmp: float, nb: int) -> Optional[float]:
    if len(closes) <= nb:
        return None
    prev = float(closes.iloc[-(nb + 1)])
    return round((cmp - prev) / prev * 100, 2) if prev > 0 and not math.isnan(prev) else None


def _return_since_first(closes: pd.Series, cmp: float) -> Optional[float]:
    first = float(closes.iloc[0])
    return round((cmp - first) / first * 100, 2) if first > 0 and not math.isnan(first) else None


def _volume_metrics(volumes: Optional[pd.Series]) -> tuple:
    """(latest volume, 20d average, ratio)."""
    vol = vol_avg = vol_ratio = None
    if volumes is not None:
        vs = volumes.dropna()
        if not vs.empty:
            vol = int(vs.iloc[-1])
            if len(vs) >= 5:
                vw = min(20, len(vs))
                vol_avg = int(vs.iloc[-vw:].mean())
                vol_ratio = round(vol / vol_avg, 2) if vol_avg > 0 else None
    return vol, vol_avg, vol_ratio


def _rsi_signal(rsi: Optional[float], cmp: float, ema50: float) -> str:
    if rsi is None:
        return 'HOLD'
    if rsi < 30 and cmp > ema50:
        return 'BUY'
    if rsi > 70 and cmp < ema50:
        return 'SELL'
    return 'HOLD'


def compute_technicals(
    closes: pd.Series,
    volumes: Optional[pd.Series] = None,
    highs:   Optional[pd.Series] = None,
    lows:    Optional[pd.Series] = None,
) -> dict:
    """
    Compute technical indicators from daily OHLCV series.

    Requires only `closes` (+ optional `volumes`, `highs`, `lows`).
    Returns a dict compatible with QuoteData field names.

    Indicators computed:
      Always (from closes): RSI-14, EMA-20/50/200, MACD+signal, 52W hi/lo,
                            Bollinger Bands (20-day), period returns, volume ratio
      With highs+lows:      ATR-14 (Wilder's), Stochastic %K/%D
    """
    if closes is None or len(closes) < 2:
        return {}

    closes = closes.dropna()
    n = len(closes)
    if n < 2:
        return {}

    cmp = float(closes.iloc[-1])
    rsi = _rsi14(closes)
    ema20, ema50, ema200 = _emas(closes)
    macd_val, macd_sig = _macd(closes)
    # 52-week high / low (slice last 252 bars, no rolling)
    w = min(252, n)
    h52 = round(float(closes.iloc[-w:].max()), 2)
    l52 = round(float(closes.iloc[-w:].min()), 2)
    bb_upper, bb_lower, bb_pct = _bollinger(closes, cmp)
    stoch_k, stoch_d = _stochastic(closes, highs, lows)
    vol, vol_avg, vol_ratio = _volume_metrics(volumes)

    return {
        'cmp': round(cmp, 2),
        'rsi': rsi,
        'ema_20': ema20, 'ema_50': ema50, 'ema_200': ema200,
        'macd': macd_val, 'macd_signal': macd_sig, 'rsi_signal': _rsi_signal(rsi, cmp, ema50),
        'high_52w': h52, 'low_52w': l52,
        'bb_upper': bb_upper, 'bb_lower': bb_lower, 'bb_pct': bb_pct,
        'atr_14': _atr14(closes, highs, lows), 'stoch_k': stoch_k, 'stoch_d': stoch_d,
        'volume': vol, 'volume_20d_avg': vol_avg, 'volume_ratio': vol_ratio,
        'ret_1d': _period_return(closes, cmp, 1), 'ret_1w': _period_return(closes, cmp, 5),
        'ret_1m': _period_return(closes, cmp, 21), 'ret_3m': _period_return(closes, cmp, 63),
        'ret_6m': _period_return(closes, cmp, 126), 'ret_1y': _return_since_first(closes, cmp),
    }


class DataProvider(ABC):
    """Abstract base for all data providers."""

    name: str = 'base'

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is configured and reachable."""
        ...

    def get_quote(self, ticker: str, market: str) -> Optional[QuoteData]:
        """Fetch a single quote.  Override for providers with live quote endpoints."""
        return None

    def get_quotes_bulk(self, tickers: list[str], market: str) -> dict[str, QuoteData]:
        """
        Fetch multiple quotes in one call (batch endpoint).
        Default: calls get_quote() sequentially.  Override for true batch APIs.
        """
        result: dict[str, QuoteData] = {}
        for t in tickers:
            q = self.get_quote(t, market)
            if q:
                result[t] = q
        return result

    def get_ohlcv(self, ticker: str, period_days: int = 365) -> pd.DataFrame:
        """
        Return daily OHLCV DataFrame with columns: Open High Low Close Volume.
        Index: DatetimeIndex.  Empty DataFrame on failure.
        """
        return pd.DataFrame()

    def get_fundamentals(self, ticker: str, market: str) -> dict:
        """
        Return fundamentals dict with keys matching QuoteData field names.
        Empty dict if not available.
        """
        return {}

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} enabled={self.is_available()}>'
