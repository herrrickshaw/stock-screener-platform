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
    return (crit == True).astype(int) * weight   # noqa: E712


def _r(v) -> float | None:
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
    except (TypeError, ValueError):
        return None


def _b(v) -> bool | None:
    # Unevaluated criteria are NaN (not None) in an object Series under pandas>=3,
    # and bool(nan) is True — so test for missing first.
    if v is None or (isinstance(v, float) and math.isnan(v)):
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


# ── Darvas / Buffett ──────────────────────────────────────────────────────────

def scan_darvas(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    d = df.reset_index(drop=True)

    # ── Pre-compute every column once (eliminates O(n²) reconstruction) ───────
    cmp    = _col(d, 'cmp')
    h52    = _col(d, 'high_52w')
    l52    = _col(d, 'low_52w')
    e20    = _col(d, 'ema_20')
    e50    = _col(d, 'ema_50')
    e200   = _col(d, 'ema_200')
    rsi    = _col(d, 'rsi')
    roe    = _col(d, 'roe')
    pe     = _col(d, 'pe')
    pb     = _col(d, 'pb')
    de     = _col(d, 'debt_to_equity')
    macd   = _col(d, 'macd')
    msig   = _col(d, 'macd_signal')
    vr     = _col(d, 'volume_ratio')
    opm    = _col(d, 'opm')
    mcap   = _col(d, 'market_cap')
    vol    = _col(d, 'volume')
    beta   = _col(d, 'beta')
    cr     = _col(d, 'current_ratio')
    rg     = _col(d, 'revenue_growth')
    eps    = _col(d, 'eps')
    dy     = _col(d, 'dividend_yield')
    bb_pct = _col(d, 'bb_pct')
    bb_u   = _col(d, 'bb_upper')
    bb_l   = _col(d, 'bb_lower')
    stk    = _col(d, 'stoch_k')
    std    = _col(d, 'stoch_d')
    atr    = _col(d, 'atr_14')
    r1d    = _col(d, 'ret_1d')
    r1w    = _col(d, 'ret_1w')
    r1m    = _col(d, 'ret_1m')
    r3m    = _col(d, 'ret_3m')
    r6m    = _col(d, 'ret_6m')
    r1y    = _col(d, 'ret_1y')

    # Pre-extract text columns as lists — avoids d.iloc[i] (Series per row)
    tickers    = _strs(d, 'ticker')
    names      = _strs(d, 'name')
    rsi_sigs   = _strs(d, 'rsi_signal', 'HOLD')
    sectors    = _strs(d, 'sector')
    industries = _strs(d, 'industry')
    exchanges  = _strs(d, '_exchange')

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

    max_score = (
        6  # D1(2)+D2(2)+D3+D4 always available
        + v_d5.astype(int)  + v_d6.astype(int)  + v_d7.astype(int)
        + v_d8.astype(int)  + v_d9.astype(int)  + v_d10.astype(int)
        + v_d11.astype(int) + v_d12.astype(int) + v_d13.astype(int)
    )

    signal = np.where(score >= 5, 'BUY', np.where(score >= 3, 'WATCH', 'AVOID'))

    n_avail = (v_d1.astype(int) + v_d2.astype(int) + v_d3.astype(int) + v_d4.astype(int) +
               v_d5.astype(int) + v_d6.astype(int) + v_d7.astype(int) + v_d8.astype(int) +
               v_d9.astype(int) + v_d10.astype(int) + v_d11.astype(int) +
               v_d12.astype(int) + v_d13.astype(int))
    completeness = (n_avail / 13 * 100).round().astype(int)

    # ── Build output (no iloc, no _col inside loop) ────────────────────────────
    results = []
    for i in range(len(d)):
        vi = vol.iat[i]
        results.append({
            'ticker':         tickers[i],
            'name':           names[i],
            'cmp':            _r(cmp.iat[i]),
            'high_52w':       _r(h52.iat[i]),
            'low_52w':        _r(l52.iat[i]),
            'ema_20':         _r(e20.iat[i]),
            'ema_50':         _r(e50.iat[i]),
            'ema_200':        _r(e200.iat[i]),
            'rsi':            _r(rsi.iat[i]),
            'macd':           _r(macd.iat[i]),
            'macd_signal':    _r(msig.iat[i]),
            'volume_ratio':   _r(vr.iat[i]),
            'bb_upper':       _r(bb_u.iat[i]),
            'bb_lower':       _r(bb_l.iat[i]),
            'bb_pct':         _r(bb_pct.iat[i]),
            'stoch_k':        _r(stk.iat[i]),
            'stoch_d':        _r(std.iat[i]),
            'atr_14':         _r(atr.iat[i]),
            'rsi_signal':     rsi_sigs[i],
            'roe':            _r(roe.iat[i]),
            'pe':             _r(pe.iat[i]),
            'pb':             _r(pb.iat[i]),
            'opm':            _r(opm.iat[i]),
            'debt_to_equity': _r(de.iat[i]),
            'market_cap':     _r(mcap.iat[i]),
            'volume':         int(vi) if vi is not None and not (isinstance(vi, float) and math.isnan(vi)) else None,
            'beta':           _r(beta.iat[i]),
            'current_ratio':  _r(cr.iat[i]),
            'revenue_growth': _r(rg.iat[i]),
            'eps':            _r(eps.iat[i]),
            'dividend_yield': _r(dy.iat[i]),
            'ret_1d':         _r(r1d.iat[i]),
            'ret_1w':         _r(r1w.iat[i]),
            'ret_1m':         _r(r1m.iat[i]),
            'ret_3m':         _r(r3m.iat[i]),
            'ret_6m':         _r(r6m.iat[i]),
            'ret_1y':         _r(r1y.iat[i]),
            'sector':         sectors[i],
            'industry':       industries[i],
            'score':          int(score.iat[i]),
            'max_score':      int(max_score.iat[i]),
            'signal':         str(signal[i]),
            'completeness':   int(completeness.iat[i]),
            'criteria': {
                'near_52w_high':  _b(c_near_high.iat[i]),
                'above_ema50':    _b(c_above_e50.iat[i]),
                'range_strength': _b(c_range_str.iat[i]),
                'rsi_healthy':    _b(c_rsi_health.iat[i]),
                'buffett_roe':    _b(c_roe.iat[i]),
                'buffett_pe':     _b(c_pe.iat[i]),
                'buffett_de':     _b(c_de.iat[i]),
                'above_ema200':   _b(c_above_e200.iat[i]),
                'macd_bull':      _b(c_macd_bull.iat[i]),
                'volume_surge':   _b(c_vol_surge.iat[i]),
                'ema_cross':      _b(c_ema_cross.iat[i]),
                'bb_upper_half':  _b(c_bb_upper.iat[i]),
                'stoch_bullish':  _b(c_stoch_bull.iat[i]),
            },
            '_exchange': exchanges[i],
        })
    return results


# ── Piotroski (simplified) ────────────────────────────────────────────────────

def scan_piotroski(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    d = df.reset_index(drop=True)

    # ── Pre-compute every column once ─────────────────────────────────────────
    cmp    = _col(d, 'cmp')
    h52    = _col(d, 'high_52w')
    e20    = _col(d, 'ema_20')
    e50    = _col(d, 'ema_50')
    e200   = _col(d, 'ema_200')
    rsi    = _col(d, 'rsi')
    roe    = _col(d, 'roe')
    opm    = _col(d, 'opm')
    pb     = _col(d, 'pb')
    de     = _col(d, 'debt_to_equity')
    cr     = _col(d, 'current_ratio')
    rg     = _col(d, 'revenue_growth')
    mcap   = _col(d, 'market_cap')
    vol    = _col(d, 'volume')
    beta   = _col(d, 'beta')
    eps    = _col(d, 'eps')
    dy     = _col(d, 'dividend_yield')
    vr     = _col(d, 'volume_ratio')
    macd   = _col(d, 'macd')
    msig   = _col(d, 'macd_signal')
    bb_u   = _col(d, 'bb_upper')
    bb_l   = _col(d, 'bb_lower')
    bb_pct = _col(d, 'bb_pct')
    stk    = _col(d, 'stoch_k')
    std    = _col(d, 'stoch_d')
    atr    = _col(d, 'atr_14')
    r1d    = _col(d, 'ret_1d')
    r1w    = _col(d, 'ret_1w')
    r1m    = _col(d, 'ret_1m')
    r3m    = _col(d, 'ret_3m')
    r6m    = _col(d, 'ret_6m')
    r1y    = _col(d, 'ret_1y')

    # Pre-extract text columns
    tickers    = _strs(d, 'ticker')
    names      = _strs(d, 'name')
    rsi_sigs   = _strs(d, 'rsi_signal', 'HOLD')
    sectors    = _strs(d, 'sector')
    industries = _strs(d, 'industry')
    exchanges  = _strs(d, '_exchange')

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

    max_score = (
        v_f1.astype(int)  + v_f5.astype(int)  + v_f8.astype(int)  + v_f9.astype(int)  +
        v_fx1.astype(int) + v_fx2.astype(int) + v_fx3.astype(int) + v_fx4.astype(int) +
        v_fx5.astype(int) + v_fx6.astype(int) + v_fx7.astype(int)
    ).clip(lower=1)

    buy_thresh   = (max_score * 0.65).apply(math.ceil)
    watch_thresh = (max_score * 0.40).apply(math.ceil)
    signal = np.where(score >= buy_thresh, 'BUY',
             np.where(score >= watch_thresh, 'WATCH', 'AVOID'))

    n_avail = (v_f1.astype(int) + v_f5.astype(int) + v_f8.astype(int) + v_f9.astype(int) +
               v_fx1.astype(int) + v_fx2.astype(int) + v_fx3.astype(int) + v_fx4.astype(int) +
               v_fx5.astype(int) + v_fx6.astype(int) + v_fx7.astype(int))
    completeness = (n_avail / 11 * 100).round().astype(int)

    # ── Build output ──────────────────────────────────────────────────────────
    results = []
    for i in range(len(d)):
        vi = vol.iat[i]
        results.append({
            'ticker':         tickers[i],
            'name':           names[i],
            'cmp':            _r(cmp.iat[i]),
            'high_52w':       _r(h52.iat[i]),
            'ema_20':         _r(e20.iat[i]),
            'ema_50':         _r(e50.iat[i]),
            'ema_200':        _r(e200.iat[i]),
            'rsi':            _r(rsi.iat[i]),
            'rsi_signal':     rsi_sigs[i],
            'macd':           _r(macd.iat[i]),
            'macd_signal':    _r(msig.iat[i]),
            'volume_ratio':   _r(vr.iat[i]),
            'bb_upper':       _r(bb_u.iat[i]),
            'bb_lower':       _r(bb_l.iat[i]),
            'bb_pct':         _r(bb_pct.iat[i]),
            'stoch_k':        _r(stk.iat[i]),
            'stoch_d':        _r(std.iat[i]),
            'atr_14':         _r(atr.iat[i]),
            'roe':            _r(roe.iat[i]),
            'opm':            _r(opm.iat[i]),
            'debt_to_equity': _r(de.iat[i]),
            'current_ratio':  _r(cr.iat[i]),
            'revenue_growth': _r(rg.iat[i]),
            'pb':             _r(pb.iat[i]),
            'market_cap':     _r(mcap.iat[i]),
            'volume':         int(vi) if vi is not None and not (isinstance(vi, float) and math.isnan(vi)) else None,
            'beta':           _r(beta.iat[i]),
            'eps':            _r(eps.iat[i]),
            'dividend_yield': _r(dy.iat[i]),
            'ret_1d':         _r(r1d.iat[i]),
            'ret_1w':         _r(r1w.iat[i]),
            'ret_1m':         _r(r1m.iat[i]),
            'ret_3m':         _r(r3m.iat[i]),
            'ret_6m':         _r(r6m.iat[i]),
            'ret_1y':         _r(r1y.iat[i]),
            'sector':         sectors[i],
            'industry':       industries[i],
            'score':          int(score.iat[i]),
            'max_score':      int(max_score.iat[i]),
            'signal':         str(signal[i]),
            'completeness':   int(completeness.iat[i]),
            'criteria': {
                'F1_roe_positive':   _b(c_f1.iat[i]),
                'F5_low_leverage':   _b(c_f5.iat[i]),
                'F8_op_margin':      _b(c_f8.iat[i]),
                'F9_rev_growth':     _b(c_f9.iat[i]),
                'FX1_above_ema50':   _b(c_fx1.iat[i]),
                'FX2_rsi_range':     _b(c_fx2.iat[i]),
                'FX3_near_high':     _b(c_fx3.iat[i]),
                'FX4_current_ratio': _b(c_fx4.iat[i]),
                'FX5_pb_value':      _b(c_fx5.iat[i]),
                'FX6_ema_cross':     _b(c_fx6.iat[i]),
                'FX7_low_atr':       _b(c_fx7.iat[i]),
            },
            '_exchange': exchanges[i],
        })
    return results
