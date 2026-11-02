"""Ticker/market routing helpers (pure string functions)."""
from __future__ import annotations

import pytest
from fetchers.history import _bare_ticker, _market_from_ticker


@pytest.mark.parametrize("raw,bare", [
    ("HDFCBANK.NS", "HDFCBANK"), ("500325.BO", "500325"), ("7203.T", "7203"),
    ("005930.KS", "005930"), ("AAPL", "AAPL"), ("ADS.DE", "ADS.DE"), ("rio.l", "rio.l"),
])
def test_bare_ticker(raw, bare):
    assert _bare_ticker(raw) == bare


@pytest.mark.parametrize("ticker,market", [
    ("HDFCBANK.NS", "india"), ("7203.T", "japan"), ("005930.KS", "korea"),
    ("600519.SS", "china"), ("ADS.DE", "europe"), ("RIO.L", "europe"),
    ("NESN.SW", "europe"), ("AAPL", "us"), ("RY.TO", "canada"), ("0700.HK", "hong_kong"),
])
def test_market_from_ticker(ticker, market):
    assert _market_from_ticker(ticker) == market
