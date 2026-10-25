import math
import pandas as pd

# Maps canonical field names to all known Screener.in export header variations
COLUMN_ALIASES: dict[str, list[str]] = {
    'name':              ['Name', 'Company', 'Stock Name', 'Company Name'],
    'ticker':            ['NSE Code', 'BSE Code', 'Ticker', 'Symbol', 'NSE Symbol', 'BSE Symbol'],
    'cmp':               ['CMP Rs.', 'Price', 'Current Price', 'CMP', 'LTP', 'Close Price',
                          'Price (USD)', 'Price (GBP)', 'Price (EUR)', 'Last Price'],
    'market_cap':        ['Market Cap Rs.Cr.', 'Market Capitalization', 'Market Cap', 'Mcap Rs.Cr.',
                          'Market Cap (USD M)', 'Market Cap (USD B)', 'Mkt Cap (USD M)', 'Market Capitalisation',
                          'Market Cap (EUR B)', 'Market Cap (EUR M)', 'Mkt Cap (EUR B)'],
    'pe':                ['P/E', 'PE Ratio', 'Price to Earning', 'PE', 'Price/Earnings', 'P/E Ratio',
                          'Price to Earnings', 'Trailing P/E'],
    'pb':                ['P/B', 'PB Ratio', 'Price to Book', 'PB', 'Price/Book', 'P/B Ratio'],
    'roe':               ['ROE %', 'Return on equity %', 'Return on Equity', 'ROE', 'Return on Equity %'],
    'roce':              ['ROCE %', 'Return on capital employed %', 'ROCE', 'Return on Capital %',
                          'Return on Invested Capital %', 'ROIC %'],
    'roa':               ['ROA %', 'Return on Assets %', 'ROA', 'Return on Assets'],
    'debt_to_equity':    ['Debt to equity', 'D/E Ratio', 'Debt/Equity', 'Debt to Equity',
                          'Debt/Equity Ratio', 'Total Debt/Equity'],
    'current_ratio':     ['Current ratio', 'Current Ratio'],
    'eps':               ['EPS Rs.', 'EPS TTM', 'Basic EPS Rs.', 'EPS'],
    'eps_growth_5y':     ['EPS 5Y Avg', 'EPS Growth 5Y', 'Earning per share 5Years %'],
    'sales_growth_3y':   ['Sales growth 3Years %', 'Revenue growth 3Y', 'Sales Growth 3Yr', 'Revenue 3Yr CAGR %'],
    'sales_growth_5y':   ['Sales growth 5Years %', 'Revenue growth 5Y', 'Sales Growth 5Yr', 'Revenue 5Yr CAGR %',
                          'Revenue Growth 5Y %'],
    'sales_growth_10y':  ['Sales growth 10Years %', 'Revenue growth 10Y', 'Sales Growth 10Yr', 'Revenue 10Yr CAGR %',
                          'Revenue Growth 10Y %'],
    'profit_growth_3y':  ['Profit growth 3Years %', 'PAT growth 3Y', 'Net Profit growth 3Yr %'],
    'profit_growth_5y':  ['Profit growth 5Years %', 'PAT growth 5Y', 'Net Profit growth 5Yr %',
                          'Profit Growth 5Y %', 'EPS Growth 5Y %'],
    'profit_growth_10y': ['Profit growth 10Years %', 'PAT growth 10Y', 'Net Profit growth 10Yr %',
                          'Profit Growth 10Y %'],
    'ocf':               ['Cash from Operations Rs.Cr.', 'Operating cash flow', 'Cash from operating activity Rs.Cr.',
                          'OCF Rs.Cr.', 'Cash from Operations (USD M)', 'Operating Cash Flow (USD M)',
                          'Cash from Operations'],
    'net_profit':        ['Net profit Rs.Cr.', 'Net Profit TTM', 'PAT Rs.Cr.', 'Net Profit',
                          'Profit after tax Rs.Cr.', 'Net Income (USD M)', 'Net Income', 'Net Earnings (USD M)'],
    'total_assets':      ['Total assets Rs.Cr.', 'Total Assets Rs.Cr.', 'Total Assets',
                          'Total Assets (USD M)', 'Total Assets (USD B)'],
    'revenue':           ['Revenue Rs.Cr.', 'Sales Rs.Cr.', 'Net Sales', 'Total Revenue', 'Turnover Rs.Cr.',
                          'Revenue (USD M)', 'Net Revenue (USD M)'],
    'promoter_holding':  ['Promoter holding %', 'Promoter Holding', 'Promoter %', 'Promoter Holdings %',
                          'Insider Holding %', 'Insider Ownership %', 'Institutional Ownership %'],
    'promoter_pledge':   ['Promoter pledge %', 'Pledged percentage', 'Promoter Pledge %', '% Pledged'],
    'high_52w':          ['52 Week High Rs.', '52W High', '52 Week High', '52Wk High', '52W High Rs.',
                          '52 Week High (USD)', '52 Week High (GBP)', '52-Week High'],
    'low_52w':           ['52 Week Low Rs.', '52W Low', '52 Week Low', '52Wk Low', '52W Low Rs.',
                          '52 Week Low (USD)', '52 Week Low (GBP)', '52-Week Low'],
    'volume':            ['Volume', 'Volume Today', 'Vol', 'Traded Volume'],
    'volume_30d_avg':    ['30D Avg Volume', 'Volume 30D Avg', 'Avg Volume 30D', '30 Day Avg Vol'],
    'net_profit_margin': ['Net profit margin %', 'Net Margin %', 'NPM %', 'Net Profit Margin', 'Net Margin'],
    'opm':               ['OPM %', 'Operating Profit Margin %', 'Operating Margin %', 'EBITDA Margin %',
                          'Operating Margin'],
    'piotroski_score':   ['Piotroski score', 'F-Score', 'Piotroski F-Score', 'Piotroski Score'],
    'asset_turnover':    ['Asset Turnover', 'Asset Turnover Ratio'],
    'sector':            ['Sector', 'Industry', 'Sector Name', 'Industry Name'],
    'sector_pe':         ['Sector PE', 'Industry PE', 'Sector P/E'],
    'dividend_yield':    ['Dividend yield %', 'Div Yield %', 'Dividend Yield'],
    'long_term_debt':    ['Borrowings Rs.Cr.', 'Long term borrowings', 'LT Debt Rs.Cr.'],
}

_SKIP_NUMERIC = {'name', 'ticker', 'sector'}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df_cols_lower = {c.strip().lower(): c for c in df.columns}
    col_map: dict[str, str] = {}

    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = alias.strip().lower()
            if key in df_cols_lower and df_cols_lower[key] not in col_map:
                col_map[df_cols_lower[key]] = canonical
                break

    df = df.rename(columns=col_map)

    for col in df.columns:
        if col in _SKIP_NUMERIC or col not in COLUMN_ALIASES:
            continue
        df[col] = pd.to_numeric(
            df[col].astype(str)
                   .str.replace(',', '', regex=False)
                   .str.replace('%', '', regex=False)
                   .str.strip(),
            errors='coerce',
        )

    return df


def first_present(row, *keys):
    """First of ``keys`` whose value is present (not None/NaN), else None.

    ``a or b`` is wrong for these rows: NaN is truthy (so a blank cell never falls back)
    and 0 is falsy (so a genuine zero is skipped)."""
    for k in keys:
        v = row.get(k)
        if v is not None and pd.notna(v):
            return v
    return None


def completeness(row: pd.Series, required_fields: list[str]) -> float:
    if not required_fields:
        return 100.0
    available = sum(1 for f in required_fields if pd.notna(row.get(f)))
    return round(100.0 * available / len(required_fields), 1)


def sanitize_result(result: dict) -> dict:
    out: dict = {}
    for k, v in result.items():
        if isinstance(v, dict):
            out[k] = sanitize_result(v)
        elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            out[k] = None
        elif hasattr(v, 'item'):
            out[k] = v.item()
        else:
            out[k] = v
    return out
