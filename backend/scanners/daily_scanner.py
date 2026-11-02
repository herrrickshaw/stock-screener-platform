"""
Daily momentum scanner — vectorized for Cassandra Phase-1 data.
No fundamentals required; uses them when available.

Darvas / Buffett  (0–16 max with all data):
  D1  CMP within 15% of 52W high          → +2   (Darvas box ceiling)
  D2  CMP > EMA-50                         → +2   (uptrend)
  D3  Price in top 40% of 52W range        → +1   (range strength)
  D4  RSI 40–68                            → +1   (healthy momentum)
  D5  ROE > 12%        [if available]      → +1   (Buffett quality)
  D6  PE 5–30          [if available]      → +1   (Buffett value)
  D7  D/E < 1          [if available]      → +1   (Buffett safety)
  D8  CMP > EMA-200    [if available]      → +1   (secular uptrend)
  D9  MACD > signal    [if available]      → +1   (momentum confirmed)
  D10 Volume ratio > 1.5 [if available]    → +1   (volume confirms move)
  D11 EMA-20 > EMA-50  [if available]      → +1   (short MA above long)
  D12 BB %B > 0.5      [if available]      → +1   (price in upper Bollinger zone)
  D13 Stoch %K 20–80 & K > D [if avail]   → +1   (stoch bullish, not extreme)
  BUY ≥ 5 · WATCH ≥ 3 · AVOID < 3

Piotroski (0–11 max with all data):
  F1  ROE > 0          [if available]      → +1
  F5  D/E < 0.5        [if available]      → +1
  F8  OPM > 15%        [if available]      → +1
  F9  Revenue growth > 0 [if available]    → +1
  FX1 CMP > EMA-50                         → +1
  FX2 RSI 40–70                            → +1
  FX3 CMP within 20% of 52W high           → +1
  FX4 Current ratio > 1.5 [if available]   → +1
  FX5 PB < 3           [if available]      → +1   (value screen)
  FX6 EMA-20 > EMA-50  [if available]      → +1   (momentum confirmation)
  FX7 ATR/CMP < 3%     [if available]      → +1   (low volatility / stable)
  BUY ≥ ceil(max×0.65) · WATCH ≥ ceil(max×0.40)
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ── helpers ───────────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Return numeric column or an all-NaN series if missing."""
    return pd.to_numeric(df[name], errors='coerce') if name in df.columns \
        else pd.Series(np.nan, index=df.index)


def _vcrit(passes: pd.Series, valid: pd.Series) -> pd.Series:
    """Boolean criterion: True/False where valid, None elsewhere."""
    out = pd.Series(None, index=passes.index, dtype=object)
    out[valid] = passes[valid]
    return out


def _pts(crit: pd.Series, weight: int = 1) -> pd.Series:
    """Score contribution: ``weight`` where the criterion is True, else 0."""
    return (crit == True).astype(int) * weight   # noqa: E712


def _r(v) -> float | None:
    """Round to 2 dp; None for NaN/inf/non-numeric (JSON-safe)."""
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except (TypeError, ValueError):
        return None


def _b(v) -> bool | None:
    """bool(v) preserving None."""
    if v is None:
        return None
    try:
        return bool(v)
    except Exception:
        return None


def _strs(df: pd.DataFrame, col: str, default: str = '') -> list:
    """Extract a text column as a plain Python list — avoids iloc[i] in the loop."""
    if col in df.columns:
        return df[col].fillna(default).astype(str).tolist()
    return [default] * len(df)


def _int_or_none(v) -> int | None:
    """Volume as int, or None when missing/NaN."""
    return int(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None


def _count_available(*masks: pd.Series) -> pd.Series:
    """Per-row number of criteria whose inputs are present."""
    total = masks[0].astype(int)
    for m in masks[1:]:
        total = total + m.astype(int)
    return total


# Output record layout: (output key, kind, source column).  Kinds: 'text' (string
# list), 'num' (2dp float or None), 'vol' (int or None).  Order is the JSON key
# order the API/front-end has always received.
_COMMON_TAIL = (('sector', 'text', 'sector'), ('industry', 'text', 'industry'))

_DARVAS_FIELDS = (
    ('ticker', 'text', 'ticker'), ('name', 'text', 'name'),
    ('cmp', 'num', 'cmp'), ('high_52w', 'num', 'high_52w'), ('low_52w', 'num', 'low_52w'),
    ('ema_20', 'num', 'ema_20'), ('ema_50', 'num', 'ema_50'), ('ema_200', 'num', 'ema_200'),
    ('rsi', 'num', 'rsi'), ('macd', 'num', 'macd'), ('macd_signal', 'num', 'macd_signal'),
    ('volume_ratio', 'num', 'volume_ratio'),
    ('bb_upper', 'num', 'bb_upper'), ('bb_lower', 'num', 'bb_lower'), ('bb_pct', 'num', 'bb_pct'),
    ('stoch_k', 'num', 'stoch_k'), ('stoch_d', 'num', 'stoch_d'), ('atr_14', 'num', 'atr_14'),
    ('rsi_signal', 'text', 'rsi_signal'),
    ('roe', 'num', 'roe'), ('pe', 'num', 'pe'), ('pb', 'num', 'pb'), ('opm', 'num', 'opm'),
    ('debt_to_equity', 'num', 'debt_to_equity'), ('market_cap', 'num', 'market_cap'),
    ('volume', 'vol', 'volume'), ('beta', 'num', 'beta'), ('current_ratio', 'num', 'current_ratio'),
    ('revenue_growth', 'num', 'revenue_growth'), ('eps', 'num', 'eps'),
    ('dividend_yield', 'num', 'dividend_yield'),
    ('ret_1d', 'num', 'ret_1d'), ('ret_1w', 'num', 'ret_1w'), ('ret_1m', 'num', 'ret_1m'),
    ('ret_3m', 'num', 'ret_3m'), ('ret_6m', 'num', 'ret_6m'), ('ret_1y', 'num', 'ret_1y'),
) + _COMMON_TAIL

_PIOTROSKI_FIELDS = (
    ('ticker', 'text', 'ticker'), ('name', 'text', 'name'),
    ('cmp', 'num', 'cmp'), ('high_52w', 'num', 'high_52w'),
    ('ema_20', 'num', 'ema_20'), ('ema_50', 'num', 'ema_50'), ('ema_200', 'num', 'ema_200'),
    ('rsi', 'num', 'rsi'), ('rsi_signal', 'text', 'rsi_signal'),
    ('macd', 'num', 'macd'), ('macd_signal', 'num', 'macd_signal'),
    ('volume_ratio', 'num', 'volume_ratio'),
    ('bb_upper', 'num', 'bb_upper'), ('bb_lower', 'num', 'bb_lower'), ('bb_pct', 'num', 'bb_pct'),
    ('stoch_k', 'num', 'stoch_k'), ('stoch_d', 'num', 'stoch_d'), ('atr_14', 'num', 'atr_14'),
    ('roe', 'num', 'roe'), ('opm', 'num', 'opm'), ('debt_to_equity', 'num', 'debt_to_equity'),
    ('current_ratio', 'num', 'current_ratio'), ('revenue_growth', 'num', 'revenue_growth'),
    ('pb', 'num', 'pb'), ('market_cap', 'num', 'market_cap'),
    ('volume', 'vol', 'volume'), ('beta', 'num', 'beta'), ('eps', 'num', 'eps'),
    ('dividend_yield', 'num', 'dividend_yield'),
    ('ret_1d', 'num', 'ret_1d'), ('ret_1w', 'num', 'ret_1w'), ('ret_1m', 'num', 'ret_1m'),
    ('ret_3m', 'num', 'ret_3m'), ('ret_6m', 'num', 'ret_6m'), ('ret_1y', 'num', 'ret_1y'),
) + _COMMON_TAIL

_NUMERIC_INPUTS = (
    'cmp', 'high_52w', 'low_52w', 'ema_20', 'ema_50', 'ema_200', 'rsi', 'roe', 'pe', 'pb',
    'debt_to_equity', 'macd', 'macd_signal', 'volume_ratio', 'opm', 'market_cap', 'volume',
    'beta', 'current_ratio', 'revenue_growth', 'eps', 'dividend_yield', 'bb_pct', 'bb_upper',
    'bb_lower', 'stoch_k', 'stoch_d', 'atr_14', 'ret_1d', 'ret_1w', 'ret_1m', 'ret_3m',
    'ret_6m', 'ret_1y',
)
_TEXT_INPUTS = (('ticker', ''), ('name', ''), ('rsi_signal', 'HOLD'), ('sector', ''),
                ('industry', ''), ('_exchange', ''))


def _load_inputs(d: pd.DataFrame) -> tuple[dict, dict]:
    """Pre-compute every numeric Series and text list once (no per-row iloc)."""
    num = {name: _col(d, name) for name in _NUMERIC_INPUTS}
    txt = {name: _strs(d, name, default) for name, default in _TEXT_INPUTS}
    return num, txt


def _base_record(i: int, fields, num: dict, txt: dict) -> dict:
    """Assemble the raw-indicator part of one result row."""
    rec: dict = {}
    for key, kind, src in fields:
        if kind == 'text':
            rec[key] = txt[src][i]
        elif kind == 'vol':
            rec[key] = _int_or_none(num[src].iat[i])
        else:
            rec[key] = _r(num[src].iat[i])
    return rec


def _finish_record(rec: dict, i: int, score, max_score, signal, completeness,
                   criteria: dict, exchange: str) -> dict:
    """Append score/signal/criteria/_exchange (shared tail of both scanners)."""
    rec['score'] = int(score.iat[i])
    rec['max_score'] = int(max_score.iat[i])
    rec['signal'] = str(signal[i])
    rec['completeness'] = int(completeness.iat[i])
    rec['criteria'] = {k: _b(c.iat[i]) for k, c in criteria.items()}
    rec['_exchange'] = exchange
    return rec


# ── Darvas / Buffett ──────────────────────────────────────────────────────────

def scan_darvas(df: pd.DataFrame) -> list[dict]:
    """Score each row 0..max on the Darvas/Buffett criteria; ``df`` has quote columns (see module doc)."""
    if df.empty:
        return []

    d = df.reset_index(drop=True)
    num, txt = _load_inputs(d)
    cmp, h52, l52 = num['cmp'], num['high_52w'], num['low_52w']
    e20, e50, e200 = num['ema_20'], num['ema_50'], num['ema_200']
    rsi, roe, pe, de = num['rsi'], num['roe'], num['pe'], num['debt_to_equity']
    macd, msig, vr = num['macd'], num['macd_signal'], num['volume_ratio']
    bb_pct, stk, std = num['bb_pct'], num['stoch_k'], num['stoch_d']

    # ── Validity masks ────────────────────────────────────────────────────────
    h52s  = h52.where(h52 > 0)
    v_d1  = cmp.notna() & h52.gt(0) & h52.notna()
    v_d2  = cmp.notna() & e50.notna()
    v_d3  = cmp.notna() & h52.notna() & l52.notna() & (h52 - l52).gt(0)
    v_d4  = rsi.notna()
    v_d5  = roe.notna()
    v_d6  = pe.notna()
    v_d7  = de.notna()
    v_d8  = cmp.notna() & e200.notna()
    v_d9  = macd.notna() & msig.notna()
    v_d10 = vr.notna()
    v_d11 = e20.notna() & e50.notna()
    v_d12 = bb_pct.notna()
    v_d13 = stk.notna() & std.notna()

    # ── Criteria (vectorized) ─────────────────────────────────────────────────
    c_near_high   = _vcrit((h52 - cmp) / h52s <= 0.15,               v_d1)
    c_above_e50   = _vcrit(cmp > e50,                                 v_d2)
    c_range_str   = _vcrit((cmp - l52) / (h52 - l52) >= 0.60,        v_d3)
    c_rsi_health  = _vcrit(rsi.between(40, 68),                       v_d4)
    c_roe         = _vcrit(roe > 12,                                  v_d5)
    c_pe          = _vcrit(pe.between(5, 30),                         v_d6)
    c_de          = _vcrit(de < 1.0,                                  v_d7)
    c_above_e200  = _vcrit(cmp > e200,                                v_d8)
    c_macd_bull   = _vcrit(macd > msig,                               v_d9)
    c_vol_surge   = _vcrit(vr > 1.5,                                  v_d10)
    c_ema_cross   = _vcrit(e20 > e50,                                 v_d11)
    c_bb_upper    = _vcrit(bb_pct > 0.5,                              v_d12)
    c_stoch_bull  = _vcrit(stk.between(20, 80) & (stk > std),        v_d13)

    score = (
        _pts(c_near_high, 2) + _pts(c_above_e50, 2) + _pts(c_range_str) +
        _pts(c_rsi_health) + _pts(c_roe) + _pts(c_pe) + _pts(c_de) +
        _pts(c_above_e200) + _pts(c_macd_bull) + _pts(c_vol_surge) +
        _pts(c_ema_cross) + _pts(c_bb_upper) + _pts(c_stoch_bull)
    )

    optional = (v_d5, v_d6, v_d7, v_d8, v_d9, v_d10, v_d11, v_d12, v_d13)
    max_score = 6 + _count_available(*optional)   # D1(2)+D2(2)+D3+D4 always counted
    signal = np.where(score >= 5, 'BUY', np.where(score >= 3, 'WATCH', 'AVOID'))
    n_avail = _count_available(v_d1, v_d2, v_d3, v_d4, *optional)
    completeness = (n_avail / 13 * 100).round().astype(int)

    criteria = {
        'near_52w_high': c_near_high, 'above_ema50': c_above_e50,
        'range_strength': c_range_str, 'rsi_healthy': c_rsi_health,
        'buffett_roe': c_roe, 'buffett_pe': c_pe, 'buffett_de': c_de,
        'above_ema200': c_above_e200, 'macd_bull': c_macd_bull,
        'volume_surge': c_vol_surge, 'ema_cross': c_ema_cross,
        'bb_upper_half': c_bb_upper, 'stoch_bullish': c_stoch_bull,
    }
    return [
        _finish_record(_base_record(i, _DARVAS_FIELDS, num, txt), i, score, max_score,
                       signal, completeness, criteria, txt['_exchange'][i])
        for i in range(len(d))
    ]


# ── Piotroski (simplified) ────────────────────────────────────────────────────

def scan_piotroski(df: pd.DataFrame) -> list[dict]:
    """Simplified Piotroski + momentum proxies; thresholds scale with available fields."""
    if df.empty:
        return []

    d = df.reset_index(drop=True)
    num, txt = _load_inputs(d)
    cmp, h52 = num['cmp'], num['high_52w']
    e20, e50 = num['ema_20'], num['ema_50']
    rsi, roe, opm, pb = num['rsi'], num['roe'], num['opm'], num['pb']
    de, cr, rg, atr = num['debt_to_equity'], num['current_ratio'], num['revenue_growth'], num['atr_14']

    # ── Validity masks ────────────────────────────────────────────────────────
    h52s  = h52.where(h52 > 0)
    v_f1  = roe.notna()
    v_f5  = de.notna()
    v_f8  = opm.notna()
    v_f9  = rg.notna()
    v_fx1 = cmp.notna() & e50.notna()
    v_fx2 = rsi.notna()
    v_fx3 = cmp.notna() & h52.gt(0) & h52.notna()
    v_fx4 = cr.notna()
    v_fx5 = pb.notna()
    v_fx6 = e20.notna() & e50.notna()
    v_fx7 = atr.notna() & cmp.gt(0)

    # ── Criteria ──────────────────────────────────────────────────────────────
    c_f1   = _vcrit(roe > 0,                              v_f1)
    c_f5   = _vcrit(de < 0.5,                             v_f5)
    c_f8   = _vcrit(opm > 15,                             v_f8)
    c_f9   = _vcrit(rg > 0,                               v_f9)
    c_fx1  = _vcrit(cmp > e50,                            v_fx1)
    c_fx2  = _vcrit(rsi.between(40, 70),                  v_fx2)
    c_fx3  = _vcrit((h52 - cmp) / h52s <= 0.20,          v_fx3)
    c_fx4  = _vcrit(cr > 1.5,                             v_fx4)
    c_fx5  = _vcrit(pb < 3,                               v_fx5)
    c_fx6  = _vcrit(e20 > e50,                            v_fx6)
    c_fx7  = _vcrit(atr / cmp.where(cmp > 0) < 0.03,     v_fx7)

    score = (
        _pts(c_f1) + _pts(c_f5) + _pts(c_f8) + _pts(c_f9) +
        _pts(c_fx1) + _pts(c_fx2) + _pts(c_fx3) + _pts(c_fx4) +
        _pts(c_fx5) + _pts(c_fx6) + _pts(c_fx7)
    )

    n_avail = _count_available(v_f1, v_f5, v_f8, v_f9, v_fx1, v_fx2, v_fx3,
                               v_fx4, v_fx5, v_fx6, v_fx7)
    max_score = n_avail.clip(lower=1)

    buy_thresh   = (max_score * 0.65).apply(math.ceil)
    watch_thresh = (max_score * 0.40).apply(math.ceil)
    signal = np.where(score >= buy_thresh, 'BUY',
             np.where(score >= watch_thresh, 'WATCH', 'AVOID'))
    completeness = (n_avail / 11 * 100).round().astype(int)

    criteria = {
        'F1_roe_positive': c_f1, 'F5_low_leverage': c_f5, 'F8_op_margin': c_f8,
        'F9_rev_growth': c_f9, 'FX1_above_ema50': c_fx1, 'FX2_rsi_range': c_fx2,
        'FX3_near_high': c_fx3, 'FX4_current_ratio': c_fx4, 'FX5_pb_value': c_fx5,
        'FX6_ema_cross': c_fx6, 'FX7_low_atr': c_fx7,
    }
    return [
        _finish_record(_base_record(i, _PIOTROSKI_FIELDS, num, txt), i, score, max_score,
                       signal, completeness, criteria, txt['_exchange'][i])
        for i in range(len(d))
    ]
