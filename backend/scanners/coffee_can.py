from __future__ import annotations
"""
Coffee Can Portfolio scan (Saurabh Mukherjea framework).

Hard filters (ALL must pass for BUY):
  H1  Revenue CAGR > 10%   (10Y preferred, 5Y fallback, 3Y last resort)
  H2  Profit CAGR > 10%    (same fallback chain)
  H3  ROCE > 15%
  H4  Debt/Equity < 1
  H5  Promoter pledge < 10%
  H6  Market cap > 100 Cr  (or > $50M for NASDAQ ADRs)

Moat score 0-5 (bonus signals):
  M1  OPM > 40%        (+2) or OPM > 25% (+1)
  M2  ROE > 20%        (+1)
  M3  ROCE > 25%       (+1)
  M4  D/E < 0.3        (+1)

Signal: BUY if all hard filters pass; WATCH if >= 70% pass; AVOID otherwise.
"""
import pandas as pd
from column_map import completeness, first_present, sanitize_result

REQUIRED_FIELDS = [
    'sales_growth_10y', 'sales_growth_5y', 'sales_growth_3y',
    'profit_growth_10y', 'profit_growth_5y', 'profit_growth_3y',
    'roce', 'debt_to_equity', 'promoter_pledge', 'market_cap',
    'opm', 'net_profit_margin', 'roe',
]


def scan(df: pd.DataFrame) -> list[dict]:
    return [sanitize_result(_score(row)) for _, row in df.iterrows()]


def _score(row: pd.Series) -> dict:
    c: dict[str, bool | None] = {}

    # H1: Revenue CAGR > 10%
    rev_g = first_present(row, 'sales_growth_10y', 'sales_growth_5y', 'sales_growth_3y')
    c['revenue_cagr_gt_10'] = (rev_g > 10) if pd.notna(rev_g) else None

    # H2: Profit CAGR > 10%
    pro_g = first_present(row, 'profit_growth_10y', 'profit_growth_5y', 'profit_growth_3y')
    c['profit_cagr_gt_10'] = (pro_g > 10) if pd.notna(pro_g) else None

    # H3: ROCE > 15%
    roce = row.get('roce')
    c['roce_gt_15'] = (roce > 15) if pd.notna(roce) else None

    # H4: D/E < 1
    de = row.get('debt_to_equity')
    c['de_lt_1'] = (de < 1) if pd.notna(de) else None

    # H5: Promoter pledge < 10%
    pledge = row.get('promoter_pledge')
    c['low_promoter_pledge'] = (pledge < 10) if pd.notna(pledge) else None

    # H6: Market cap > 100 Cr
    mcap = row.get('market_cap')
    c['min_market_cap'] = (mcap > 100) if pd.notna(mcap) else None

    evaluated = [v for v in c.values() if v is not None]
    passed_count = sum(1 for v in evaluated if v)
    all_passed = bool(evaluated) and all(evaluated)
    pass_ratio = passed_count / len(evaluated) if evaluated else 0

    # Moat score
    moat = 0
    opm = first_present(row, 'opm', 'net_profit_margin')
    roe = row.get('roe')
    if pd.notna(opm):
        moat += 2 if opm > 40 else (1 if opm > 25 else 0)
    if pd.notna(roe) and roe > 20:
        moat += 1
    if pd.notna(roce) and roce > 25:
        moat += 1
    if pd.notna(de) and de < 0.3:
        moat += 1

    signal = 'BUY' if all_passed else ('WATCH' if pass_ratio >= 0.7 else 'AVOID')

    return {
        'name': row.get('name', ''),
        'ticker': row.get('ticker', ''),
        'sector': row.get('sector', ''),
        'cmp': row.get('cmp'),
        'market_cap': mcap,
        'pe': row.get('pe'),
        'roe': roe,
        'debt_to_equity': de,
        'score': 1 if all_passed else 0,
        'max_score': 1,
        'moat_score': moat,
        'signal': signal,
        'criteria': c,
        'passed': all_passed,
        'completeness': completeness(row, REQUIRED_FIELDS),
        'rsi': row.get('rsi'),
        'ema_50': row.get('ema_50'),
        'rsi_signal': row.get('rsi_signal'),
    }
