"""Unit tests for backend/fetchers/history.py: ticker routing, date parsing, price-on-date
selection and portfolio P&L assembly. yfinance and the Cassandra cache are replaced by fakes;
nothing here touches the network or a database."""
import sys
import types
from datetime import date, datetime

import pandas as pd
import pytest

from fetchers import history


# ── fakes ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_cache(monkeypatch):
    """Stub db.quote_updater so fetch_price_on_date never reaches Cassandra."""
    db = types.ModuleType("db")
    qu = types.ModuleType("db.quote_updater")
    qu.get_cached_price = lambda t, d: None
    qu.cache_price_on_date = lambda *a: None
    qu.get_quotes = lambda market, tickers: {}
    db.quote_updater = qu
    monkeypatch.setitem(sys.modules, "db", db)
    monkeypatch.setitem(sys.modules, "db.quote_updater", qu)
    return qu


def _fake_yf(monkeypatch, frame):
    class _T:
        def __init__(self, sym): pass
        def history(self, start=None, end=None, **kw): return frame
    monkeypatch.setattr(history, "yf", types.SimpleNamespace(Ticker=_T))
    monkeypatch.setattr(history, "HAS_YF", True)


def _daily(dates, closes, tz):
    idx = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize(tz)   # yfinance: exchange-local midnight
    return pd.DataFrame({"Close": closes}, index=idx)


# ── _bare_ticker / _market_from_ticker ───────────────────────────────────────

@pytest.mark.parametrize("t,bare", [
    ("HDFCBANK.NS", "HDFCBANK"), ("RELIANCE.BO", "RELIANCE"), ("tcs.ns", "tcs"),
    ("AAPL", "AAPL"), ("ADS.DE", "ADS.DE"), ("BRK.B", "BRK.B"), ("7203.T", "7203"),
])
def test_bare_ticker(t, bare):
    assert history._bare_ticker(t) == bare


EUROPE = ["DE", "F", "L", "PA", "MI", "MC", "ST", "HE", "CO", "OL", "AS", "BR", "LS", "IR",
          "SW", "WA", "AT", "VI"]


@pytest.mark.parametrize("sfx", EUROPE)
def test_every_european_suffix_routes_to_europe(sfx):
    assert history._market_from_ticker(f"ABC.{sfx}") == "europe"
    assert history._market_from_ticker(f"abc.{sfx.lower()}") == "europe"


@pytest.mark.parametrize("t,market", [
    ("HDFCBANK.NS", "india"), ("500325.BO", "india"), ("7203.T", "japan"),
    ("005930.KS", "korea"), ("035720.KQ", "korea"), ("600519.SS", "china"),
    ("0700.HK", "hong_kong"), ("SHOP.TO", "canada"), ("AAPL", "us"), ("BRK.B", "us"),
])
def test_market_from_ticker(t, market):
    assert history._market_from_ticker(t) == market


# ── parse_date ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2025-01-02", date(2025, 1, 2)),
    ("02/01/2025", date(2025, 1, 2)),          # day-first wins over US order
    ("15-Mar-2024", date(2024, 3, 15)),
    ("March 15, 2024", date(2024, 3, 15)),
    (datetime(2024, 3, 15, 10, 30), date(2024, 3, 15)),
    (date(2024, 3, 15), date(2024, 3, 15)),
    (None, None),
    ("not a date", None),
])
def test_parse_date(raw, expected):
    assert history.parse_date(raw) == expected


# ── fetch_price_on_date ───────────────────────────────────────────────────────

def test_price_on_date_us_ticker_uses_the_target_session(monkeypatch, no_cache):
    """yfinance indexes US bars at New-York midnight; the target day's close must be used,
    not the previous session's."""
    _fake_yf(monkeypatch, _daily(["2026-03-02", "2026-03-03", "2026-03-04"], [10.0, 11.0, 12.0],
                                 "America/New_York"))
    r = history.fetch_price_on_date("AAPL", date(2026, 3, 3))
    assert r["close"] == 11.0
    assert r["actual_date"] == "2026-03-03"


def test_price_on_date_india_ticker_reports_the_session_date(monkeypatch, no_cache):
    _fake_yf(monkeypatch, _daily(["2026-03-02", "2026-03-03", "2026-03-04"], [10.0, 11.0, 12.0],
                                 "Asia/Kolkata"))
    r = history.fetch_price_on_date("TCS.NS", date(2026, 3, 3))
    assert r["close"] == 11.0
    assert r["actual_date"] == "2026-03-03"


def test_price_on_date_weekend_falls_back_to_prior_session(monkeypatch, no_cache):
    _fake_yf(monkeypatch, _daily(["2026-03-05", "2026-03-06", "2026-03-09"], [10.0, 11.0, 12.0],
                                 "Asia/Kolkata"))
    r = history.fetch_price_on_date("TCS.NS", date(2026, 3, 8))   # Sunday
    assert (r["close"], r["actual_date"]) == (11.0, "2026-03-06")


def test_price_on_date_before_first_bar_uses_earliest_available(monkeypatch, no_cache):
    """Comment in the code: 'all rows after target; use earliest available'."""
    _fake_yf(monkeypatch, _daily(["2026-03-02", "2026-03-03"], [10.0, 11.0], "Asia/Kolkata"))
    r = history.fetch_price_on_date("NEWIPO.NS", date(2026, 3, 1))
    assert (r["close"], r["actual_date"]) == (10.0, "2026-03-02")


def test_price_on_date_empty_history_is_an_error(monkeypatch, no_cache):
    _fake_yf(monkeypatch, pd.DataFrame({"Close": []}))
    assert "error" in history.fetch_price_on_date("X", date(2026, 3, 3))


# ── fetch_holdings_history (P&L assembly) ─────────────────────────────────────

@pytest.fixture
def fake_prices(monkeypatch):
    on_date = {("AAPL", date(2025, 1, 2)): 100.0, ("AAPL", date(2025, 6, 2)): 150.0,
               ("MSFT", date(2025, 1, 2)): 50.0}
    divs = {("AAPL", date(2025, 1, 2)): 2.0, ("AAPL", date(2025, 6, 2)): 1.0}
    monkeypatch.setattr(history, "fetch_price_on_date",
                        lambda t, d: {"close": on_date[(t, d)], "actual_date": d.isoformat(),
                                      "source": "fake"})
    monkeypatch.setattr(history, "fetch_current_price",
                        lambda t: {"close": {"AAPL": 200.0, "MSFT": 50.0}[t], "rsi_signal": "HOLD",
                                   "source": "fake"})
    monkeypatch.setattr(history, "fetch_dividends_since",
                        lambda t, d: {"total_per_share": divs.get((t, d), 0.0), "count": 1,
                                      "payouts": []})


def test_single_holding_pnl_and_dividend_total_return(fake_prices):
    out = history.fetch_holdings_history(
        [{"yf_ticker": "AAPL", "purchase_date": "2025-01-02", "quantity": 10}])
    h = out["holdings"][0]
    assert h["price_on_date"] == 100.0
    assert h["cost_basis"] == 1000.0
    assert h["current_value"] == 2000.0
    assert h["unrealised_pnl"] == 1000.0
    assert h["pnl_pct"] == 100.0
    assert h["dividends_received"] == 20.0
    assert h["total_return_pnl"] == 1020.0
    assert h["total_return_pct"] == 102.0
    assert out["summary"]["total_return_pct"] == 102.0


def test_user_purchase_price_beats_price_on_date(fake_prices):
    out = history.fetch_holdings_history(
        [{"yf_ticker": "AAPL", "purchase_date": "2025-01-02", "quantity": 10, "purchase_price": 80}])
    assert out["holdings"][0]["cost_basis"] == 800.0


def test_two_lots_of_one_ticker_are_priced_at_their_own_dates(fake_prices):
    out = history.fetch_holdings_history([
        {"yf_ticker": "AAPL", "purchase_date": "2025-01-02", "quantity": 10},
        {"yf_ticker": "AAPL", "purchase_date": "2025-06-02", "quantity": 5},
    ])
    lot1, lot2 = out["holdings"]
    assert lot1["price_on_date"] == 100.0 and lot1["cost_basis"] == 1000.0
    assert lot2["price_on_date"] == 150.0 and lot2["cost_basis"] == 750.0
    assert lot1["dividends_received"] == 20.0 and lot2["dividends_received"] == 5.0
    assert out["summary"]["total_cost_basis"] == 1750.0


def test_break_even_portfolio_reports_zero_pct_not_none(fake_prices):
    out = history.fetch_holdings_history(
        [{"yf_ticker": "MSFT", "purchase_date": "2025-01-02", "quantity": 10}])
    s = out["summary"]
    assert s["total_unrealised_pnl"] == 0.0
    assert s["total_pnl_pct"] == 0.0


def test_holding_without_quantity_is_not_priced(fake_prices):
    out = history.fetch_holdings_history([{"yf_ticker": "AAPL", "purchase_date": "2025-01-02"}])
    assert out["holdings"][0]["cost_basis"] is None
    assert out["summary"]["priced_count"] == 0
    assert out["summary"]["total_cost_basis"] is None
