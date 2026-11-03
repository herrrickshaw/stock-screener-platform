"""Characterisation test (pass 2): fetch_holdings_history P&L assembly with stubbed price fetchers."""
from __future__ import annotations

from datetime import date

import pytest
from fetchers import history
from golden_util import check

HOLDINGS = [
    {"yf_ticker": "AAA.NS", "name": "Aaa", "purchase_date": "2023-01-02", "purchase_price": 100, "quantity": 10},
    {"yf_ticker": "BBB", "name": "Bbb", "purchase_date": date(2022, 5, 5), "purchase_price": None, "quantity": 5},
    {"yf_ticker": "CCC.DE", "name": "Ccc", "purchase_date": "garbage", "purchase_price": 50, "quantity": None},
    {"yf_ticker": "DDD.L", "purchase_date": "2021-03-04", "purchase_price": float("nan"), "quantity": 3},
    {"yf_ticker": "EEE", "name": "Eee", "purchase_date": "2020-01-01", "purchase_price": 10, "quantity": 2},
    {"yf_ticker": "AAA.NS", "name": "Aaa dup", "purchase_date": "2023-01-02", "purchase_price": 100, "quantity": 10},
]


def _hist(ticker, d):
    if ticker == "EEE":
        return {"error": "no data"}
    return {"close": {"AAA.NS": 90.0, "BBB": 40.5, "DDD.L": 7.0}.get(ticker, 1.0), "actual_date": d.isoformat(), "source": "cache"}


def _cur(ticker):
    if ticker == "DDD.L":
        return {"error": "no price"}
    return {"close": {"AAA.NS": 120.0, "BBB": 38.0, "CCC.DE": 60.0, "EEE": 9.0}[ticker], "rsi": 25.0,
            "rsi_signal": {"AAA.NS": "BUY", "BBB": "SELL"}.get(ticker, "HOLD"), "ema_50": 100.0, "source": "cassandra"}


def _div(ticker, d):
    if ticker == "BBB":
        raise RuntimeError("boom")
    return {"total_per_share": 2.5 if ticker == "AAA.NS" else 0.0, "count": 1, "payouts": [{"date": "2023-06-01", "amount": 2.5}]}


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setattr(history, "fetch_price_on_date", _hist)
    monkeypatch.setattr(history, "fetch_current_price", _cur)
    monkeypatch.setattr(history, "fetch_dividends_since", _div)


def test_holdings_history_golden():
    check("holdings_history", history.fetch_holdings_history(HOLDINGS, max_workers=2))
    check("holdings_history_empty", history.fetch_holdings_history([]))
