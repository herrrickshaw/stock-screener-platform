"""
Historical price retrieval from yfinance.

fetch_price_on_date() — closing price on (or nearest trading day before) a target date
fetch_holdings_history() — parallel fetch for a list of holdings, with P&L computation
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False


# ── date parsing ──────────────────────────────────────────────────────────────

_DATE_FMTS = (
    '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y',
    '%d-%b-%Y', '%d %b %Y', '%d-%B-%Y', '%B %d, %Y',
    '%Y/%m/%d',
)


def parse_date(value) -> Optional[date]:
    """Convert string / datetime / date to datetime.date. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        from dateutil import parser as dp
        return dp.parse(s).date()
    except Exception:
        return None


# ── single-ticker fetchers ────────────────────────────────────────────────────

def fetch_dividends_since(yf_ticker: str, from_date: date) -> dict:
    """
    Sum all dividends per share with ex-date >= from_date up to today.
    Returns {total_per_share, count, payouts:[{date,amount}], source}.
    """
    if not HAS_YF:
        return {'total_per_share': 0.0, 'count': 0, 'payouts': [], 'source': 'unavailable'}
    try:
        divs = yf.Ticker(yf_ticker).dividends
        if divs.empty:
            return {'total_per_share': 0.0, 'count': 0, 'payouts': [], 'source': 'yfinance'}

        idx = divs.index
        if hasattr(idx, 'tz') and idx.tz is not None:
            idx = idx.tz_convert(None).tz_localize(None)
        divs.index = idx

        cutoff = datetime.combine(from_date, datetime.min.time())
        since  = divs[divs.index >= cutoff]

        total   = float(since.sum()) if not since.empty else 0.0
        payouts = [
            {'date': d.date().isoformat(), 'amount': round(float(v), 4)}
            for d, v in since.items()
        ]
        return {
            'total_per_share': round(total, 4),
            'count':           len(payouts),
            'payouts':         payouts,
            'source':          'yfinance',
        }
    except Exception as exc:
        log.debug('fetch_dividends_since %s: %s', yf_ticker, exc)
        return {'total_per_share': 0.0, 'count': 0, 'payouts': [], 'source': 'error'}


def fetch_price_on_date(yf_ticker: str, target: date) -> dict:
    """
    Fetch closing price on (or nearest prior trading day to) target date.
    Returns {'close': float, 'actual_date': str} or {'error': str}.
    """
    if not HAS_YF:
        return {'error': 'yfinance not installed'}

    # Check Cassandra cache first
    from db.quote_updater import get_cached_price
    cached = get_cached_price(yf_ticker, target)
    if cached is not None:
        return {'close': cached, 'actual_date': target.isoformat(), 'source': 'cache'}

    try:
        start = target - timedelta(days=10)
        end   = target + timedelta(days=2)   # +2 so the target date is included
        hist  = yf.Ticker(yf_ticker).history(
            start=start.isoformat(), end=end.isoformat()
        )
        if hist.empty:
            return {'error': 'no data for this ticker/date range'}

        # Normalise timezone-aware index. Daily bars are stamped at exchange-local
        # midnight: drop the tz but keep the wall-clock date. Converting to UTC first
        # (tz_convert(None)) moves US bars to 04:00/05:00 of the same day (so the target
        # session fell after the cutoff) and Asian bars to the previous calendar day.
        idx = hist.index
        if hasattr(idx, 'tz') and idx.tz is not None:
            idx = idx.tz_localize(None)
        hist.index = idx

        cutoff = datetime.combine(target, datetime.min.time())
        before = hist[hist.index <= cutoff]
        if before.empty:
            before = hist.iloc[:1]  # all rows after target; use earliest available

        row        = before.iloc[-1]
        close      = float(row['Close'])
        actual_day = before.index[-1].date()

        if math.isnan(close):
            return {'error': 'close price is NaN'}

        # Write to Cassandra cache
        from db.quote_updater import cache_price_on_date
        cache_price_on_date(yf_ticker, actual_day, close)

        return {'close': round(close, 2), 'actual_date': actual_day.isoformat(), 'source': 'yfinance'}

    except Exception as exc:
        return {'error': str(exc)[:120]}


def fetch_current_price(yf_ticker: str) -> dict:
    """
    Latest price: Cassandra stock_quotes → yfinance fallback.
    Returns {'close': float, 'rsi': float|None, 'rsi_signal': str|None, 'source': str}.
    """
    # Try Cassandra stock_quotes first
    from db.quote_updater import get_quotes
    market = _market_from_ticker(yf_ticker)
    # Cassandra stores India tickers as bare NSE symbols (no .NS/.BO suffix)
    bare = _bare_ticker(yf_ticker)
    cached = get_quotes(market, [bare, yf_ticker])
    hit = cached.get(bare) or cached.get(yf_ticker)
    if hit:
        q = hit
        if q.get('cmp'):
            return {
                'close':      round(q['cmp'], 2),
                'rsi':        q.get('rsi'),
                'rsi_signal': q.get('rsi_signal'),
                'ema_50':     q.get('ema_50'),
                'source':     'cassandra',
            }

    if not HAS_YF:
        return {'error': 'yfinance not installed'}
    try:
        info  = yf.Ticker(yf_ticker).info
        price = info.get('currentPrice') or info.get('regularMarketPrice')
        if price:
            return {'close': round(float(price), 2), 'source': 'yfinance'}
        return {'error': 'no price in yfinance info'}
    except Exception as exc:
        return {'error': str(exc)[:120]}


def _bare_ticker(yf_ticker: str) -> str:
    """Strip known market suffixes for Cassandra lookup."""
    SUFFIXES = {'.NS', '.BO', '.T', '.KS', '.KQ', '.SS', '.SZ', '.HK', '.TO', '.V'}
    upper = yf_ticker.upper()
    for sfx in SUFFIXES:
        if upper.endswith(sfx):
            return yf_ticker[:len(yf_ticker) - len(sfx)]
    return yf_ticker


_EUROPE_SUFFIXES = {
    # Euronext
    'PA', 'AS', 'BR', 'LS', 'MI', 'IR', 'OL',
    # Deutsche Boerse
    'DE', 'F',
    # Nasdaq Nordic & Baltic
    'ST', 'HE', 'CO', 'VS', 'TL', 'RG',
    # BME / others
    'MC', 'WA', 'AT', 'VI', 'L', 'SW', 'PR', 'RO', 'BD',
}


def _market_from_ticker(yf_ticker: str) -> str:
    sfx = yf_ticker.rsplit('.', 1)[-1].upper() if '.' in yf_ticker else ''
    _MAP = {
        'NS': 'india', 'BO': 'india',
        'T':  'japan',
        'KS': 'korea', 'KQ': 'korea',
        'SS': 'china', 'SZ': 'china',
        'HK': 'hong_kong',
        'TO': 'canada', 'V': 'canada',
    }
    if sfx in _MAP:
        return _MAP[sfx]
    if sfx in _EUROPE_SUFFIXES:
        return 'europe'
    return 'us'


# ── batch fetch ───────────────────────────────────────────────────────────────

def fetch_holdings_history(holdings: list[dict], max_workers: int = 8) -> dict:
    """
    For each holding, fetch:
      - price on purchase_date (from yfinance / Cassandra cache)
      - current price + RSI/EMA signal (from Cassandra / yfinance)

    Each holding dict must have:
      yf_ticker     str
      purchase_date date | str   (parsed internally if str)
      purchase_price float | None
      quantity       float | None
      name          str | None

    Returns {
      'holdings': [...enriched dicts...],
      'summary':  {...portfolio-level aggregates...}
    }
    """
    # Normalise dates. Several lots of one ticker bought on different dates are common,
    # so date-dependent lookups are keyed by (ticker, purchase_date), not ticker alone.
    holdings = [dict(h) for h in holdings]
    for h in holdings:
        if isinstance(h.get('purchase_date'), str):
            h['purchase_date'] = parse_date(h['purchase_date'])
    lots = {(h['yf_ticker'], h.get('purchase_date')) for h in holdings}
    tickers = {t for t, _ in lots}

    hist_results: dict[str, dict] = {}
    cur_results:  dict[str, dict] = {}
    div_results:  dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        hist_futs = {
            pool.submit(fetch_price_on_date, ticker, pdate): (ticker, pdate)
            for ticker, pdate in lots
            if pdate
        }
        cur_futs = {
            pool.submit(fetch_current_price, ticker): ticker
            for ticker in tickers
        }
        div_futs = {
            pool.submit(fetch_dividends_since, ticker, pdate): (ticker, pdate)
            for ticker, pdate in lots
            if pdate
        }

        for fut in as_completed(hist_futs, timeout=180):
            ticker = hist_futs[fut]
            try:
                hist_results[ticker] = fut.result()
            except Exception as exc:
                hist_results[ticker] = {'error': str(exc)[:80]}

        for fut in as_completed(cur_futs, timeout=180):
            ticker = cur_futs[fut]
            try:
                cur_results[ticker] = fut.result()
            except Exception as exc:
                cur_results[ticker] = {'error': str(exc)[:80]}

        for fut in as_completed(div_futs, timeout=180):
            ticker = div_futs[fut]
            try:
                div_results[ticker] = fut.result()
            except Exception as exc:
                div_results[ticker] = {'total_per_share': 0.0, 'count': 0, 'payouts': []}

    # Assemble enriched rows (preserve original order)
    enriched: list[dict] = []
    for h in holdings:
        ticker = h['yf_ticker']
        key    = (ticker, h.get('purchase_date'))
        hr     = hist_results.get(key, {})
        cr     = cur_results.get(ticker, {})
        dr     = div_results.get(key, {})

        purchase_date  = h.get('purchase_date')
        purchase_price = _f(h.get('purchase_price'))
        quantity       = _f(h.get('quantity'))
        price_on_date  = _f(hr.get('close'))
        current_price  = _f(cr.get('close'))

        # Effective cost: user-supplied purchase_price beats price_on_date
        effective_buy = purchase_price if purchase_price is not None else price_on_date

        cost_basis    = _round(effective_buy * quantity)   if effective_buy  and quantity else None
        current_value = _round(current_price * quantity)   if current_price  and quantity else None
        pnl           = _round(current_value - cost_basis) if cost_basis and current_value else None
        pnl_pct       = _round((current_price - effective_buy) / effective_buy * 100) \
                        if current_price and effective_buy else None

        # Dividend adjustment
        div_per_share    = _f(dr.get('total_per_share', 0.0)) or 0.0
        div_received     = _round(div_per_share * quantity) if quantity else None
        # Adjusted cost = purchase price net of dividends received
        adjusted_cost    = _round(effective_buy - div_per_share) if effective_buy else None
        # Total return = capital gain + dividends (vs original purchase price)
        total_return_pnl = _round(pnl + div_received) \
                           if pnl is not None and div_received is not None else pnl
        total_return_pct = _round((current_price - effective_buy + div_per_share) / effective_buy * 100) \
                           if current_price and effective_buy else None

        errors = {k: v for k, v in {'hist': hr.get('error'), 'cur': cr.get('error')}.items() if v}

        enriched.append({
            'yf_ticker':          ticker,
            'name':               h.get('name', ''),
            'purchase_date':      purchase_date.isoformat() if isinstance(purchase_date, date) else (purchase_date or ''),
            'actual_date':        hr.get('actual_date'),
            'price_on_date':      price_on_date,
            'purchase_price':     purchase_price,
            'current_price':      current_price,
            'quantity':           quantity,
            'cost_basis':         cost_basis,
            'current_value':      current_value,
            'unrealised_pnl':     pnl,
            'pnl_pct':            pnl_pct,
            # dividend fields
            'dividends_per_share':  round(div_per_share, 4) if div_per_share else 0.0,
            'dividends_received':   div_received,
            'dividend_count':       dr.get('count', 0),
            'dividend_payouts':     dr.get('payouts', []),
            'adjusted_cost':        adjusted_cost,
            'total_return_pnl':     total_return_pnl,
            'total_return_pct':     total_return_pct,
            # signals
            'rsi':             cr.get('rsi'),
            'rsi_signal':      cr.get('rsi_signal'),
            'ema_50':          cr.get('ema_50'),
            'price_source':    hr.get('source', 'unavailable'),
            'quote_source':    cr.get('source', 'unavailable'),
            'errors':          errors if errors else None,
        })

    # Portfolio summary
    valid = [r for r in enriched if r['cost_basis'] is not None and r['current_value'] is not None]
    total_cost    = _round(sum(r['cost_basis']    for r in valid)) if valid else None
    total_value   = _round(sum(r['current_value'] for r in valid)) if valid else None
    total_pnl     = _round(total_value - total_cost)               if total_cost and total_value else None
    total_pnl_pct = _round(total_pnl / total_cost * 100)           if total_cost and total_pnl is not None else None

    total_divs       = _round(sum(r['dividends_received'] or 0 for r in valid)) if valid else None
    total_return_pnl = _round(total_pnl + total_divs) \
                       if total_pnl is not None and total_divs is not None else total_pnl
    total_return_pct = _round(total_return_pnl / total_cost * 100) \
                       if total_return_pnl is not None and total_cost else None

    signals = [r['rsi_signal'] for r in enriched if r.get('rsi_signal')]
    summary = {
        'holdings_count':         len(enriched),
        'priced_count':           len(valid),
        'total_cost_basis':       total_cost,
        'total_current_value':    total_value,
        'total_unrealised_pnl':   total_pnl,
        'total_pnl_pct':          total_pnl_pct,
        'total_dividends_received': total_divs,
        'total_return_pnl':       total_return_pnl,
        'total_return_pct':       total_return_pct,
        'rsi_buy':                signals.count('BUY'),
        'rsi_sell':               signals.count('SELL'),
        'rsi_hold':               signals.count('HOLD'),
    }

    return {'holdings': enriched, 'summary': summary}


def _f(v) -> Optional[float]:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _round(v) -> Optional[float]:
    return round(v, 2) if v is not None else None
