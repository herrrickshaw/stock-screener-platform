"""
Extract stock tickers from uploaded PDF files for any supported market.
"""
from __future__ import annotations

import io
import re
from typing import Optional

from parsers.market_db import lookup, lookup_by_name, extract_from_text

_TICKER_HEADERS = {
    'symbol', 'ticker', 'scrip', 'script', 'nse symbol', 'nse code',
    'trading symbol', 'instrument', 'stock', 'code', 'yf_ticker', 'yf ticker',
    'stock code', 'security code',
}
_NAME_HEADERS = {
    'name', 'company', 'company name', 'scrip name', 'instrument name',
    'security name', 'stock name', 'issuer', 'security', 'description',
}
_ISIN_HEADERS = {'isin', 'isin number', 'isin no', 'isin code'}


def _col_role(header: str) -> Optional[str]:
    h = header.lower().strip().rstrip('.')
    if h in _TICKER_HEADERS: return 'ticker'
    if h in _NAME_HEADERS:   return 'name'
    if h in _ISIN_HEADERS:   return 'isin'
    return None


def _resolve(raw_ticker: str, raw_name: str, raw_isin: str,
             market: str, page: str) -> Optional[dict]:
    info = None
    matched_via = ''

    if raw_ticker:
        # Try the symbol as written first: real NSE symbols contain '-' (BAJAJ-AUTO,
        # MCDOWELL-N). Only then strip series/exchange tails like -EQ, /NSE, spaces.
        full = raw_ticker.upper().strip()
        info = lookup(full, market)
        if not info:
            sym = re.sub(r'[ \t/-].*$', '', full)
            info = lookup(sym, market)
        if info:
            matched_via = 'symbol'

    if not info and raw_isin and raw_isin.startswith('IN') and market == 'india':
        from parsers.symbol_db import lookup_by_isin
        nse = lookup_by_isin(raw_isin)
        if nse:
            info = {'yf_ticker': nse['symbol'] + '.NS', 'name': nse['name']}
            matched_via = 'ISIN'

    if not info and raw_name:
        info = lookup_by_name(raw_name, market)
        if info:
            matched_via = 'name (fuzzy)'

    if not info:
        return None

    return {
        'yf_ticker':   info['yf_ticker'],
        'symbol':      info['yf_ticker'],
        'name':        info.get('name') or raw_name,
        'sheet':       page,
        'matched_via': matched_via,
    }


def _parse_table(table: list[list], page_label: str, market: str) -> list[dict]:
    if not table or len(table) < 2:
        return []
    header = [str(c or '').strip() for c in table[0]]
    role_map: dict[str, int] = {}
    for i, h in enumerate(header):
        role = _col_role(h)
        if role and role not in role_map:
            role_map[role] = i
    if not role_map:
        return []

    results = []
    for row in table[1:]:
        if not row:
            continue
        def cell(key):
            idx = role_map.get(key)
            return str(row[idx] or '').strip() if idx is not None and idx < len(row) else ''
        rec = _resolve(cell('ticker'), cell('name'), cell('isin'), market, page_label)
        if rec:
            results.append(rec)
    return results


def parse_pdf(file_bytes: bytes, market: str = 'india') -> dict:
    import pdfplumber

    stocks: dict[str, dict] = {}
    warnings: list[str] = []
    pages_scanned = 0
    table_hits = 0

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages_scanned = len(pdf.pages)
        for page in pdf.pages:
            label = f'p{page.page_number}'
            for table in page.extract_tables():
                for rec in _parse_table(table, label, market):
                    yf = rec['yf_ticker']
                    if yf not in stocks:
                        stocks[yf] = rec
                        table_hits += 1

            text = page.extract_text() or ''
            for rec in extract_from_text(text, market):
                yf = rec['yf_ticker']
                if yf not in stocks:
                    stocks[yf] = {**rec, 'symbol': yf, 'sheet': label}

    if not stocks:
        warnings.append(
            'No symbols could be extracted. The PDF may be scanned (image-only) '
            'or use a non-standard format.'
        )
    elif table_hits == 0:
        warnings.append(
            'No structured tables detected — symbols matched from raw text. '
            'Review the list carefully for false positives.'
        )

    return {
        'stocks':        list(stocks.values()),
        'warnings':      warnings,
        'pages_scanned': pages_scanned,
    }
