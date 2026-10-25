from __future__ import annotations
"""
Piotroski F-Score (0-9).

Profitability:
  F1  ROA > 0
  F2  Operating cash flow > 0
  F3  ROA improving YoY          (requires YoY data; skipped if unavailable)
  F4  Accruals < 0  (OCF/Assets > ROA — cash earnings beat reported)

Leverage & Liquidity:
  F5  Long-term debt ratio decreased YoY (proxy: D/E < 0.5)
  F6  Current ratio > 1.5        (improved proxy)
  F7  No new shares issued        (not computable from snapshot; skipped)

Operating Efficiency:
  F8  Operating margin > 20%      (proxy for gross margin improvement)
  F9  Asset turnover > 0.5        (or ROE > 15% if AT unavailable)

If Screener.in pre-computed Piotroski score is present it is used directly.
Signal: BUY >= 8, WATCH >= 6, AVOID <= 5.
"""
import pandas as pd
from column_map import completeness, first_present, sanitize_result

REQUIRED_FIELDS = [
    'roa', 'ocf', 'net_profit', 'total_assets',
    'debt_to_equity', 'current_ratio', 'opm', 'asset_turnover',
    'piotroski_score',
]


def scan(df: pd.DataFrame) -> list[dict]:
    return [sanitize_result(_score(row)) for _, row in df.iterrows()]


def _score(row: pd.Series) -> dict:
    precomputed = row.get('piotroski_score')

    net_profit   = row.get('net_profit')
    total_assets = row.get('total_assets')
    roa          = row.get('roa')
    ocf          = row.get('ocf')

    if pd.isna(roa) and pd.notna(net_profit) and pd.notna(total_assets) and total_assets != 0:
        roa = (net_profit / total_assets) * 100

    f: dict[str, bool | None] = {}

    # F1
    f['F1_roa_positive'] = (roa > 0) if pd.notna(roa) else None

    # F2
    f['F2_ocf_positive'] = (ocf > 0) if pd.notna(ocf) else None

    # F3 — needs two periods; skip
    f['F3_roa_improving'] = None

    # F4: accruals = ROA - OCF/Assets < 0 means OCF/Assets > ROA (quality earnings)
    if pd.notna(ocf) and pd.notna(total_assets) and pd.notna(roa) and total_assets > 0:
        ocf_ratio = (ocf / total_assets) * 100
        f['F4_low_accruals'] = ocf_ratio > roa
    else:
        f['F4_low_accruals'] = None

    # F5: proxy — D/E < 0.5
    de = row.get('debt_to_equity')
    f['F5_low_leverage'] = (de < 0.5) if pd.notna(de) else None

    # F6: current ratio > 1.5
    cr = row.get('current_ratio')
    f['F6_current_ratio'] = (cr > 1.5) if pd.notna(cr) else None

    # F7: no dilution — skip
    f['F7_no_dilution'] = None

    # F8: operating margin > 20%
    opm = first_present(row, 'opm', 'net_profit_margin')
    f['F8_operating_margin'] = (opm > 20) if pd.notna(opm) else None

    # F9: asset turnover
    at = row.get('asset_turnover')
    if pd.notna(at):
        f['F9_asset_turnover'] = at > 0.5
    else:
        roe = row.get('roe')
        f['F9_asset_turnover'] = (roe > 15) if pd.notna(roe) else None

    if pd.notna(precomputed):
        score = int(precomputed)
        f['_note'] = None  # marks that score came from Screener.in
    else:
        # Criteria are numpy.bool_ for DataFrame rows, so `v is True` never matched.
        score = sum(1 for v in f.values() if v is not None and bool(v))

    signal = 'BUY' if score >= 8 else 'WATCH' if score >= 6 else 'AVOID'

    return {
        'name': row.get('name', ''),
        'ticker': row.get('ticker', ''),
        'sector': row.get('sector', ''),
        'cmp': row.get('cmp'),
        'market_cap': row.get('market_cap'),
        'pe': row.get('pe'),
        'roe': row.get('roe'),
        'debt_to_equity': de,
        'score': score,
        'max_score': 9,
        'signal': signal,
        'criteria': f,
        'completeness': completeness(row, REQUIRED_FIELDS),
        'used_precomputed': pd.notna(precomputed),
        'rsi': row.get('rsi'),
        'ema_50': row.get('ema_50'),
        'rsi_signal': row.get('rsi_signal'),
    }
