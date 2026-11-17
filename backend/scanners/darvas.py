from __future__ import annotations
"""
Darvas Box scan with Warren Buffett quality overlay.

Darvas criteria (price/volume momentum):
  C1  CMP within 3% of 52W high
  C2  Volume >= 1.5x 30-day average (breakout)
  C3  Price above approximate box floor (85% of 52W high)
  C10 Price in upper half of 52W range (strength)

Buffett overlay (quality filter):
  C4  ROE > 15%
  C5  Net profit margin > 10%
  C6  Debt/Equity < 0.5
  C7  Promoter holding > 50%
  C8  EPS / profit growth > 10% (5Y)
  C9  PE < 1.5x sector PE (or PE < 35 absolute)

Score 0-10. Signal: BUY >= 7, WATCH >= 4, AVOID < 4.
"""
import pandas as pd
from column_map import completeness, first_present, sanitize_result
from damodaran import get_sector_pe

REQUIRED_FIELDS = [
    'cmp', 'high_52w', 'low_52w', 'volume', 'volume_30d_avg',
    'roe', 'net_profit_margin', 'opm', 'debt_to_equity',
    'promoter_holding', 'eps_growth_5y', 'profit_growth_5y', 'pe', 'sector_pe',
]


def scan(df: pd.DataFrame) -> list[dict]:
    return [sanitize_result(_score(row)) for _, row in df.iterrows()]


def _score(row: pd.Series) -> dict:
    c: dict[str, bool | None] = {}
    score = 0

    cmp     = row.get('cmp')
    h52     = row.get('high_52w')
    l52     = row.get('low_52w')
    vol     = row.get('volume')
    vol_avg = row.get('volume_30d_avg')

    # C1: CMP within 3% of 52W high
    if pd.notna(cmp) and pd.notna(h52) and h52 > 0:
        c['price_near_52w_high'] = (h52 - cmp) / h52 <= 0.03
    else:
        c['price_near_52w_high'] = None
    if c['price_near_52w_high']:
        score += 1

    # C2: Volume breakout
    if pd.notna(vol) and pd.notna(vol_avg) and vol_avg > 0:
        c['volume_breakout'] = vol >= 1.5 * vol_avg
    else:
        c['volume_breakout'] = None
    if c['volume_breakout']:
        score += 1

    # C3: Above box floor (approx 85% of 52W high)
    if pd.notna(cmp) and pd.notna(h52) and h52 > 0:
        c['above_box_floor'] = cmp >= h52 * 0.85
    else:
        c['above_box_floor'] = None
    if c['above_box_floor']:
        score += 1

    # C4: ROE > 15%
    roe = row.get('roe')
    c['roe_gt_15'] = (roe > 15) if pd.notna(roe) else None
    if c['roe_gt_15']:
        score += 1

    # C5: Net profit margin > 10%
    npm = row.get('net_profit_margin')
    opm = row.get('opm')
    margin = npm if pd.notna(npm) else opm
    c['profit_margin_gt_10'] = (margin > 10) if pd.notna(margin) else None
    if c['profit_margin_gt_10']:
        score += 1

    # C6: D/E < 0.5
    de = row.get('debt_to_equity')
    c['low_debt'] = (de < 0.5) if pd.notna(de) else None
    if c['low_debt']:
        score += 1

    # C7: Promoter holding > 50%
    ph = row.get('promoter_holding')
    c['promoter_holding_gt_50'] = (ph > 50) if pd.notna(ph) else None
    if c['promoter_holding_gt_50']:
        score += 1

    # C8: EPS / profit growth > 10% CAGR
    eg = first_present(row, 'eps_growth_5y', 'profit_growth_5y', 'profit_growth_3y')
    c['eps_growth_gt_10'] = (eg > 10) if pd.notna(eg) else None
    if c['eps_growth_gt_10']:
        score += 1

    # C9: PE < 1.5x sector PE (Damodaran benchmark → screener field → absolute fallback)
    pe = row.get('pe')
    sector = row.get('sector', '') or ''
    spe = get_sector_pe(sector) or row.get('sector_pe')
    if pd.notna(pe) and spe and spe > 0:
        c['pe_vs_sector'] = pe < 1.5 * spe
    elif pd.notna(pe):
        c['pe_vs_sector'] = pe < 35
    else:
        c['pe_vs_sector'] = None
    if c['pe_vs_sector']:
        score += 1

    # C10: Price in upper half of 52W range
    if pd.notna(cmp) and pd.notna(h52) and pd.notna(l52):
        rng = h52 - l52
        c['price_strength'] = ((cmp - l52) / rng > 0.5) if rng > 0 else None
    else:
        c['price_strength'] = None
    if c['price_strength']:
        score += 1

    signal = 'BUY' if score >= 7 else 'WATCH' if score >= 4 else 'AVOID'

    return {
        'name': row.get('name', ''),
        'ticker': row.get('ticker', ''),
        'sector': row.get('sector', ''),
        'cmp': cmp,
        'market_cap': row.get('market_cap'),
        'pe': pe,
        'roe': roe,
        'debt_to_equity': de,
        'score': score,
        'max_score': 10,
        'signal': signal,
        'criteria': c,
        'completeness': completeness(row, REQUIRED_FIELDS),
        'rsi': row.get('rsi'),
        'ema_50': row.get('ema_50'),
        'rsi_signal': row.get('rsi_signal'),
    }
