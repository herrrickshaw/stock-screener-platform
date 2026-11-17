"""Pure ticker-suffix helpers shared by the Cassandra lookup paths (no I/O)."""
from __future__ import annotations

_STRIPPED_SUFFIXES = {'.NS', '.BO', '.T', '.KS', '.KQ', '.SS', '.SZ', '.HK', '.TO', '.V'}

_SUFFIX_TO_MARKET = {
    'NS': 'india', 'BO': 'india',
    'T':  'japan',
    'KS': 'korea', 'KQ': 'korea',
    'SS': 'china', 'SZ': 'china',
    'HK': 'hong_kong',
    'TO': 'canada', 'V': 'canada',
}


def bare_ticker(yf_ticker: str) -> str:
    """Strip known non-European market suffixes (``.NS`` ...) for the Cassandra lookup."""
    upper = yf_ticker.upper()
    for sfx in _STRIPPED_SUFFIXES:
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


def market_from_ticker(yf_ticker: str) -> str:
    """Map a yfinance ticker's suffix to its Cassandra market partition; no suffix -> 'us'.

    Only ever call this with exchange-qualified tickers: an unqualified symbol
    silently lands in 'us'.
    """
    sfx = yf_ticker.rsplit('.', 1)[-1].upper() if '.' in yf_ticker else ''
    if sfx in _SUFFIX_TO_MARKET:
        return _SUFFIX_TO_MARKET[sfx]
    if sfx in _EUROPE_SUFFIXES:
        return 'europe'
    return 'us'
