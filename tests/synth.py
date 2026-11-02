"""Deterministic synthetic quote frames for scanner tests (no network, no DB)."""
from __future__ import annotations

import numpy as np
import pandas as pd

NUMERIC_COLS = [
    'cmp', 'high_52w', 'low_52w', 'ema_20', 'ema_50', 'ema_200', 'rsi', 'roe',
    'pe', 'pb', 'debt_to_equity', 'macd', 'macd_signal', 'volume_ratio', 'opm',
    'market_cap', 'volume', 'beta', 'current_ratio', 'revenue_growth', 'eps',
    'dividend_yield', 'bb_pct', 'bb_upper', 'bb_lower', 'stoch_k', 'stoch_d',
    'atr_14', 'ret_1d', 'ret_1w', 'ret_1m', 'ret_3m', 'ret_6m', 'ret_1y',
]


def make_quotes(n: int = 80, seed: int = 7, nan_frac: float = 0.25) -> pd.DataFrame:
    """Return an n-row frame shaped like Cassandra ``stock_quotes`` with random gaps."""
    rng = np.random.default_rng(seed)
    cmp_ = rng.uniform(20, 500, n)
    data = {
        'ticker': [f'SYM{i:03d}' for i in range(n)],
        'name': [f'Company {i}' for i in range(n)],
        'cmp': cmp_,
        'high_52w': cmp_ * rng.uniform(1.0, 1.6, n),
        'low_52w': cmp_ * rng.uniform(0.4, 1.0, n),
        'ema_20': cmp_ * rng.uniform(0.9, 1.1, n),
        'ema_50': cmp_ * rng.uniform(0.85, 1.15, n),
        'ema_200': cmp_ * rng.uniform(0.7, 1.3, n),
        'rsi': rng.uniform(15, 90, n),
        'roe': rng.uniform(-5, 35, n),
        'pe': rng.uniform(2, 60, n),
        'pb': rng.uniform(0.3, 8, n),
        'debt_to_equity': rng.uniform(0, 3, n),
        'macd': rng.normal(0, 2, n),
        'macd_signal': rng.normal(0, 2, n),
        'volume_ratio': rng.uniform(0.3, 3, n),
        'opm': rng.uniform(-5, 40, n),
        'market_cap': rng.uniform(1e8, 1e11, n),
        'volume': rng.integers(1_000, 5_000_000, n).astype(float),
        'beta': rng.uniform(0.3, 2, n),
        'current_ratio': rng.uniform(0.4, 4, n),
        'revenue_growth': rng.normal(8, 15, n),
        'eps': rng.normal(5, 8, n),
        'dividend_yield': rng.uniform(0, 6, n),
        'bb_pct': rng.uniform(-0.2, 1.2, n),
        'bb_upper': cmp_ * 1.05,
        'bb_lower': cmp_ * 0.95,
        'stoch_k': rng.uniform(0, 100, n),
        'stoch_d': rng.uniform(0, 100, n),
        'atr_14': cmp_ * rng.uniform(0.005, 0.06, n),
        'ret_1d': rng.normal(0, 2, n), 'ret_1w': rng.normal(0, 4, n),
        'ret_1m': rng.normal(0, 8, n), 'ret_3m': rng.normal(0, 14, n),
        'ret_6m': rng.normal(0, 20, n), 'ret_1y': rng.normal(0, 30, n),
        'rsi_signal': rng.choice(['BUY', 'HOLD', 'SELL'], n),
        'sector': rng.choice(['Tech', 'Banks', 'Energy'], n),
        'industry': rng.choice(['A', 'B'], n),
        '_exchange': rng.choice(['NSE', 'NYSE', 'XETRA'], n),
    }
    df = pd.DataFrame(data)
    mask = rng.random((n, len(NUMERIC_COLS))) < nan_frac
    for j, col in enumerate(NUMERIC_COLS):
        df.loc[mask[:, j], col] = np.nan
    df.loc[0, 'high_52w'] = 0.0          # non-positive 52W high edge case
    df.loc[1, 'ticker'] = None           # missing text
    return df
