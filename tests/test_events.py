"""Offline tests for backend.events (bus, news enricher, portfolio monitor) and backend.config.providers."""
import asyncio
import importlib
import sys
import types
from collections import deque

import pytest

from config import providers as prov
from events import event_bus as eb
from events import news_enricher as ne
from events import portfolio_monitor as pm


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ event bus
def test_market_event_defaults():
    e = eb.MarketEvent("PRICE_UP", "TCS", "india")
    assert e.data == {} and e.timestamp.endswith("+00:00")
    assert eb.MarketEvent("A", "B", "C").data is not e.data          # no shared default dict


def test_publish_records_history_and_dispatches_to_type_and_wildcard_subscribers():
    bus = eb.EventBus()
    seen = []
    bus.subscribe("PRICE_UP", lambda e: seen.append(("typed", e.ticker)))
    bus.subscribe("*", lambda e: seen.append(("all", e.ticker)))
    bus.subscribe("PRICE_DOWN", lambda e: seen.append(("other", e.ticker)))
    ev = eb.MarketEvent("PRICE_UP", "TCS", "india")
    run(bus.publish(ev))
    assert seen == [("typed", "TCS"), ("all", "TCS")]
    assert bus.history == [ev]


def test_history_is_bounded_and_returns_a_copy():
    bus = eb.EventBus(max_history=2)
    for i in range(3):
        run(bus.publish(eb.MarketEvent("X", str(i), "us")))
    assert [e.ticker for e in bus.history] == ["1", "2"]
    bus.history.clear()
    assert len(bus.history) == 2


def test_failing_callback_does_not_stop_others():
    bus = eb.EventBus()
    seen = []

    def bad(e):
        raise ValueError("x")
    bus.subscribe("X", bad)
    bus.subscribe("X", lambda e: seen.append(e.ticker))
    run(bus.publish(eb.MarketEvent("X", "A", "us")))
    assert seen == ["A"]


def test_coroutine_callbacks_are_scheduled_as_tasks():
    bus = eb.EventBus()
    seen = []

    async def cb(e):
        seen.append(e.ticker)

    async def go():
        bus.subscribe("X", cb)
        await bus.publish(eb.MarketEvent("X", "A", "us"))
        await asyncio.sleep(0)
    run(go())
    assert seen == ["A"]


def test_unsubscribe_removes_callback_and_ignores_unknown():
    bus = eb.EventBus()
    seen = []

    def cb(e):
        seen.append(1)
    bus.subscribe("X", cb)
    bus.unsubscribe("X", cb)
    bus.unsubscribe("X", cb)                  # second removal: no error
    bus.unsubscribe("NEVER", cb)
    run(bus.publish(eb.MarketEvent("X", "A", "us")))
    assert seen == []


def test_global_bus_singleton_exists():
    assert isinstance(eb.bus, eb.EventBus)


# -------------------------------------------------------------- news enricher
@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(ne, "_alert_store", deque(maxlen=3))
    monkeypatch.setattr(ne, "_sse_queues", [])


def _alert(i):
    return ne.Alert(id=str(i), event_type="T", ticker="X", market="us", event_data={}, news=[], timestamp="t")


def test_get_alerts_newest_first_and_limited(store):
    for i in range(3):
        ne._alert_store.append(_alert(i))
    assert [a["id"] for a in ne.get_alerts()] == ["2", "1", "0"]
    assert [a["id"] for a in ne.get_alerts(limit=2)] == ["2", "1"]
    assert ne.get_alerts(limit=1)[0]["event_type"] == "T"


def test_alert_store_is_bounded(store):
    for i in range(5):
        ne._alert_store.append(_alert(i))
    assert [a["id"] for a in ne.get_alerts(10)] == ["4", "3", "2"]


def test_sse_subscribe_unsubscribe(store):
    q = ne.subscribe_sse()
    assert q in ne._sse_queues and q.maxsize == 50
    ne.unsubscribe_sse(q)
    ne.unsubscribe_sse(q)                     # unknown queue ignored
    assert ne._sse_queues == []


def test_setup_subscribes_enricher_to_all_events(monkeypatch):
    bus = eb.EventBus()
    monkeypatch.setattr(eb, "bus", bus)
    ne.setup()
    assert ne._on_event in bus._subscribers["*"]


def test_on_event_builds_alert_and_fans_out_to_queues(store, monkeypatch):
    monkeypatch.setattr(ne, "_fetch_news", lambda t, m: [{"title": f"{t}/{m}"}])
    full = asyncio.Queue(maxsize=1)
    full.put_nowait("occupied")

    async def go():
        q = ne.subscribe_sse()
        ne._sse_queues.append(full)
        await ne._on_event(eb.MarketEvent("PRICE_UP", "TCS", "india", {"pct": 3}, "ts1"))
        return q.get_nowait()
    payload = run(go())
    assert payload["event_type"] == "PRICE_UP" and payload["ticker"] == "TCS"
    assert payload["news"] == [{"title": "TCS/india"}] and payload["timestamp"] == "ts1"
    assert payload["event_data"] == {"pct": 3} and len(payload["id"]) == 8
    assert len(ne._alert_store) == 1            # a full queue is skipped without error


def test_on_event_swallows_errors(store, monkeypatch):
    def boom(t, m):
        raise RuntimeError("x")
    monkeypatch.setattr(ne, "_fetch_news", boom)
    run(ne._on_event(eb.MarketEvent("X", "A", "us")))
    assert len(ne._alert_store) == 0


def test_fetch_news_prefers_newsapi_then_falls_back(monkeypatch):
    calls = []
    monkeypatch.setattr(ne, "NEWSAPI_KEY", "k")
    monkeypatch.setattr(ne, "_fetch_newsapi", lambda t, n: calls.append(("api", t, n)) or [{"a": 1}])
    monkeypatch.setattr(ne, "_fetch_yfinance", lambda t, m, n: calls.append(("yf", t, m, n)) or [{"y": 1}])
    assert ne._fetch_news("TCS.NS", "india") == [{"a": 1}]
    assert calls == [("api", "TCS.NS", 5)]
    monkeypatch.setattr(ne, "_fetch_newsapi", lambda t, n: [])
    assert ne._fetch_news("TCS", "india", limit=2) == [{"y": 1}]
    assert calls[-1] == ("yf", "TCS", "india", 2)
    monkeypatch.setattr(ne, "NEWSAPI_KEY", "")
    calls.clear()
    monkeypatch.setattr(ne, "_fetch_newsapi", lambda t, n: pytest.fail("no key -> no newsapi"))
    assert ne._fetch_news("TCS", "us") == [{"y": 1}]


class FakeResp:
    def __init__(self, payload, status=None):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


def test_fetch_newsapi_maps_articles_and_strips_exchange_suffix(monkeypatch):
    import requests
    seen = {}

    def fake_get(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return FakeResp({"articles": [
            {"title": "T1", "url": "u1", "source": {"name": "Wire"}, "publishedAt": "p", "description": "d"},
            {"title": "", "url": "u2"},                      # no title -> dropped
            {"title": "T3", "url": ""},                      # no url -> dropped
            {"title": "T4", "url": "u4", "source": None},
            {"title": "T5", "url": "u5"},
        ]})
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(ne, "NEWSAPI_KEY", "KEY")
    out = ne._fetch_newsapi("RELIANCE.NS", 3)
    assert "q=RELIANCE&" in seen["url"] and "pageSize=3" in seen["url"] and seen["timeout"] == 8
    assert out[0] == {"title": "T1", "publisher": "Wire", "link": "u1", "published_at": "p",
                      "description": "d", "source": "newsapi"}
    assert [a["title"] for a in out] == ["T1"]               # only the first 3 raw articles are considered
    out = ne._fetch_newsapi("RELIANCE.NS", 5)
    assert [a["title"] for a in out] == ["T1", "T4", "T5"]
    assert out[1]["publisher"] == "" and out[1]["published_at"] == ""


def test_fetch_newsapi_returns_empty_on_error(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResp({}, status=500))
    assert ne._fetch_newsapi("X", 5) == []


def _fake_yf(news, seen=None):
    class T:
        def __init__(self, sym):
            if seen is not None:
                seen.append(sym)
            self.news = news
    return types.SimpleNamespace(Ticker=T)


def test_fetch_yfinance_handles_both_news_shapes_and_india_suffix(monkeypatch):
    seen = []
    news = [
        {"content": {"title": "New", "canonicalUrl": {"url": "n-url"}, "provider": {"displayName": "P"},
                     "pubDate": "2026"}},
        {"content": {"title": "ClickOnly", "clickThroughUrl": {"url": "c-url"}}},
        {"title": "Old", "link": "o-url", "publisher": "Pub", "providerPublishTime": 123},
        {"title": "NoLink", "link": ""},
        {"content": {"title": "", "canonicalUrl": {"url": "x"}}},
    ]
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf(news, seen))
    out = ne._fetch_yfinance("TCS", "india", 10)
    assert seen == ["TCS.NS"]
    assert out == [
        {"title": "New", "publisher": "P", "link": "n-url", "published_at": "2026", "source": "yfinance"},
        {"title": "ClickOnly", "publisher": "", "link": "c-url", "published_at": "", "source": "yfinance"},
        {"title": "Old", "publisher": "Pub", "link": "o-url", "published_at": "123", "source": "yfinance"},
    ]


def test_fetch_yfinance_symbol_rules_limit_and_failure(monkeypatch):
    seen = []
    items = [{"title": f"t{i}", "link": f"l{i}"} for i in range(5)]
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf(items, seen))
    assert len(ne._fetch_yfinance("TCS.NS", "india", 2)) == 2
    ne._fetch_yfinance("AAPL", "us", 1)
    assert seen == ["TCS.NS", "AAPL"]                        # no double suffix; none for US
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf(None))
    assert ne._fetch_yfinance("AAPL", "us", 1) == []

    class Boom:
        @staticmethod
        def Ticker(sym):
            raise RuntimeError("x")
    monkeypatch.setitem(sys.modules, "yfinance", Boom)
    assert ne._fetch_yfinance("AAPL", "us", 1) == []


# ------------------------------------------------------------ portfolio monitor
def test_yf_sym_only_suffixes_india():
    assert pm._yf_sym("TCS", "india") == "TCS.NS"
    assert pm._yf_sym("TCS.NS", "india") == "TCS.NS"
    assert pm._yf_sym("TCS", "us") == "TCS"


def test_compute_rsi_needs_period_plus_one_closes():
    assert pm._compute_rsi([1.0] * 14) is None
    assert pm._compute_rsi([1.0] * 15) == 100.0            # flat: no losses -> 100
    assert pm._compute_rsi([1.0] * 15, period=14) == 100.0


def test_compute_rsi_values():
    up = [float(i) for i in range(1, 17)]
    assert pm._compute_rsi(up) == 100.0
    down = [float(i) for i in range(16, 0, -1)]
    assert pm._compute_rsi(down) == 0.0
    alt = [10.0 + (i % 2) for i in range(30)]               # equal gains and losses over window
    assert pm._compute_rsi(alt) == pytest.approx(50.0, abs=4.0)
    mixed = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 12]
    # last 14 deltas: 7 up(+1) ... computed independently
    d = [mixed[i + 1] - mixed[i] for i in range(len(mixed) - 1)][-14:]
    g, l = sum(x for x in d if x > 0) / 14, sum(-x for x in d if x < 0) / 14
    assert pm._compute_rsi(mixed) == round(100 - 100 / (1 + g / l), 2)


def test_compute_rsi_respects_custom_period():
    closes = [1, 2, 1, 2, 3]
    assert pm._compute_rsi(closes, period=4) == round(100 - 100 / (1 + (3 / 4) / (1 / 4)), 2)
    assert pm._compute_rsi(closes, period=5) is None


def _state(market="india", prev_rsi=None):
    return pm._TickerState(market=market, prev_rsi=prev_rsi)


def types_of(events):
    return [e["type"] for e in events]


@pytest.mark.parametrize("price, expected", [
    (102.0, ["PRICE_UP"]), (101.99, []), (98.0, ["PRICE_DOWN"]), (98.01, []),
])
def test_detect_price_move_threshold_is_two_percent_inclusive(price, expected):
    ev = pm._detect_events("T", _state(), {"price": price, "prev_close": 100.0, "volume": 0, "avg_volume": 1})
    assert types_of(ev) == expected


def test_detect_price_event_payload():
    ev = pm._detect_events("T", _state("us"), {"price": 103.456, "prev_close": 100.0, "volume": 0})[0]
    assert ev == {"type": "PRICE_UP", "ticker": "T", "market": "us",
                  "data": {"price": 103.46, "prev_close": 100.0, "pct_change": 3.46}}


def test_detect_ignores_price_without_valid_previous_close():
    assert pm._detect_events("T", _state(), {"price": 50.0, "prev_close": 0, "volume": 0}) == []
    assert pm._detect_events("T", _state(), {"price": None, "prev_close": 100.0, "volume": 0}) == []


@pytest.mark.parametrize("rsi, prev, expected", [
    (70.0, 69.9, ["RSI_OVERBOUGHT"]), (70.0, None, ["RSI_OVERBOUGHT"]),
    (75.0, 71.0, []),                                            # already overbought: no repeat
    (69.9, 50.0, []),
    (30.0, 30.1, ["RSI_OVERSOLD"]), (30.0, None, ["RSI_OVERSOLD"]),
    (25.0, 29.0, []), (30.1, 50.0, []),
])
def test_detect_rsi_fires_only_on_transitions(rsi, prev, expected):
    ev = pm._detect_events("T", _state(prev_rsi=prev), {"price": 100.0, "prev_close": 100.0,
                                                        "rsi": rsi, "volume": 0})
    assert types_of(ev) == expected


def test_detect_rsi_payload_includes_price_or_none():
    ev = pm._detect_events("T", _state(), {"rsi": 80.0, "price": 12.345, "volume": 0})
    assert ev[0]["data"] == {"rsi": 80.0, "price": 12.35}
    ev = pm._detect_events("T", _state(), {"rsi": 80.0, "volume": 0})
    assert ev[0]["data"] == {"rsi": 80.0, "price": None}


@pytest.mark.parametrize("vol, avg, fires", [(200, 100, True), (199, 100, False), (5, 0, False), (5, None, False)])
def test_detect_volume_surge_is_two_times_average(vol, avg, fires):
    ev = pm._detect_events("T", _state(), {"volume": vol, "avg_volume": avg})
    assert ("VOLUME_SURGE" in types_of(ev)) is fires


def test_detect_volume_surge_payload():
    ev = pm._detect_events("T", _state(), {"volume": 250.7, "avg_volume": 100.2})
    assert ev[0]["data"] == {"volume": 250, "avg_volume": 100, "multiplier": 2.5}


def test_detect_volume_defaults_when_keys_absent():
    assert pm._detect_events("T", _state(), {}) == []


@pytest.mark.parametrize("price, high, low, expected", [
    (98.0, 100.0, 50.0, ["HIGH_52W"]), (97.99, 100.0, 50.0, []),
    (51.0, 100.0, 50.0, ["LOW_52W"]), (51.01, 100.0, 50.0, []),
    (99.0, None, 90.0, []), (49.0, None, 50.0, ["LOW_52W"]),
])
def test_detect_52w_proximity_two_percent(price, high, low, expected):
    ev = pm._detect_events("T", _state(), {"price": price, "high_52w": high, "low_52w": low, "volume": 0})
    assert types_of(ev) == expected


def test_detect_high_takes_precedence_over_low():
    ev = pm._detect_events("T", _state(), {"price": 100.0, "high_52w": 100.0, "low_52w": 100.0, "volume": 0})
    assert types_of(ev) == ["HIGH_52W"]


def test_monitor_ticker_bookkeeping():
    m = pm.PortfolioMonitor()
    m.add_tickers(["A", "B"], "india")
    m.add_tickers(["B", "C"], "us")                    # B already watched: keeps its original market
    assert m.watched() == {"A": "india", "B": "india", "C": "us"}
    m.remove_ticker("A")
    m.remove_ticker("zzz")
    assert m.watched() == {"B": "india", "C": "us"}


def test_monitor_start_is_idempotent_and_stop_cancels():
    async def go():
        m = pm.PortfolioMonitor(poll_interval=3600)
        m.start()
        first = m._task
        m.start()
        assert m._task is first
        m.stop()
        await asyncio.sleep(0)
        return first.cancelled() or first.done()
    assert run(go())
    pm.PortfolioMonitor().stop()                       # stop before start: no error


def test_monitor_run_polls_only_when_tickers_present(monkeypatch):
    m = pm.PortfolioMonitor(poll_interval=0)
    polls = []

    async def fake_poll():
        polls.append(1)
        raise asyncio.CancelledError
    monkeypatch.setattr(m, "_poll", fake_poll)

    async def go_empty():
        t = asyncio.create_task(m._run())
        await asyncio.sleep(0.01)
        t.cancel()
    run(go_empty())
    assert polls == []
    m.add_tickers(["A"], "us")
    with pytest.raises(asyncio.CancelledError):
        run(m._run())
    assert polls == [1]


def test_poll_publishes_detected_events_and_tracks_rsi(monkeypatch):
    bus = eb.EventBus()
    monkeypatch.setattr(eb, "bus", bus)
    data = {"A": {"price": 110.0, "prev_close": 100.0, "rsi": 75.0, "volume": 0},
            "B": None,
            "C": "raise"}

    def fake_fetch(t, market):
        if data[t] == "raise":
            raise RuntimeError("x")
        return data[t]
    monkeypatch.setattr(pm, "_fetch_ticker_data", fake_fetch)
    m = pm.PortfolioMonitor()
    m.add_tickers(["A", "B", "C"], "us")
    run(m._poll())
    assert sorted(types_of([{"type": e.type} for e in bus.history])) == ["PRICE_UP", "RSI_OVERBOUGHT"]
    assert m._tickers["A"].prev_rsi == 75.0 and m._tickers["B"].prev_rsi is None
    run(m._poll())                                        # RSI already overbought -> no second RSI event
    assert [e.type for e in bus.history].count("RSI_OVERBOUGHT") == 1


class FakeHist:
    def __init__(self, closes, volumes):
        self._d = {"Close": closes, "Volume": volumes}
        self.empty = not closes

    def __len__(self):
        return len(self._d["Close"])

    def __getitem__(self, k):
        return types.SimpleNamespace(tolist=lambda: list(self._d[k]))


def _fake_yf_history(hist, fast=None, seen=None):
    class T:
        def __init__(self, sym):
            if seen is not None:
                seen.append(sym)
            self.fast_info = fast or types.SimpleNamespace(year_high=200.0, year_low=50.0)

        def history(self, period, auto_adjust):
            assert (period, auto_adjust) == ("30d", True)
            return hist
    return types.SimpleNamespace(Ticker=T)


def test_fetch_ticker_data_assembles_fields(monkeypatch):
    seen = []
    closes = [float(100 + i) for i in range(20)]
    vols = [10.0] * 19 + [50.0]
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_history(FakeHist(closes, vols), seen=seen))
    out = pm._fetch_ticker_data("TCS", "india")
    assert seen == ["TCS.NS"]
    assert out["price"] == 119.0 and out["prev_close"] == 118.0
    assert out["volume"] == 50.0 and out["avg_volume"] == 10.0
    assert out["rsi"] == 100.0 and out["high_52w"] == 200.0 and out["low_52w"] == 50.0


def test_fetch_ticker_data_none_for_short_empty_or_failing(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_history(FakeHist([], [])))
    assert pm._fetch_ticker_data("X", "us") is None
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_history(FakeHist([1.0], [1.0])))
    assert pm._fetch_ticker_data("X", "us") is None

    class Boom:
        @staticmethod
        def Ticker(s):
            raise RuntimeError("x")
    monkeypatch.setitem(sys.modules, "yfinance", Boom)
    assert pm._fetch_ticker_data("X", "us") is None


def test_fetch_ticker_data_two_bars_is_enough_and_rsi_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yf_history(FakeHist([10.0, 11.0], [5.0, 5.0])))
    out = pm._fetch_ticker_data("X", "us")
    assert out["rsi"] is None and out["avg_volume"] == 5.0


# -------------------------------------------------------------- provider config
def test_configured_providers_always_lists_the_keyless_ones(monkeypatch):
    for k in ("ALPHA_VANTAGE_KEY", "POLYGON_KEY", "IEX_TOKEN", "TRADIER_TOKEN", "QUANDL_KEY", "CURRENCYLAYER_KEY"):
        monkeypatch.setattr(prov.cfg, k, "")
    assert prov.configured_providers() == ["yahoo", "tradingview", "interactive_brokers"]


def test_configured_providers_adds_keyed_ones_in_order(monkeypatch):
    for k in ("ALPHA_VANTAGE_KEY", "POLYGON_KEY", "IEX_TOKEN", "TRADIER_TOKEN", "QUANDL_KEY", "CURRENCYLAYER_KEY"):
        monkeypatch.setattr(prov.cfg, k, "x")
    assert prov.configured_providers() == ["yahoo", "alpha_vantage", "polygon", "iex", "tradier",
                                           "quandl", "currencylayer", "tradingview", "interactive_brokers"]


def test_env_helper_strips_and_defaults(monkeypatch):
    monkeypatch.setenv("SOME_TEST_VAR", "  value ")
    assert prov._env("SOME_TEST_VAR") == "value"
    assert prov._env("SOME_MISSING_VAR_XYZ") == "" and prov._env("SOME_MISSING_VAR_XYZ", "d") == "d"


def test_provider_config_reads_environment_at_import(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", " pk ")
    monkeypatch.setenv("IB_PORT", "7496")
    monkeypatch.delenv("NASDAQ_DATA_LINK_API_KEY", raising=False)
    monkeypatch.setenv("QUANDL_API_KEY", "qk")
    monkeypatch.delenv("IEX_BASE_URL", raising=False)
    try:
        importlib.reload(prov)
        assert prov.cfg.POLYGON_KEY == "pk" and prov.cfg.IB_PORT == 7496 and isinstance(prov.cfg.IB_PORT, int)
        assert prov.cfg.QUANDL_KEY == "qk"
        assert prov.cfg.IEX_BASE == "https://cloud.iexapis.com/stable"
        monkeypatch.setenv("NASDAQ_DATA_LINK_API_KEY", "nk")
        importlib.reload(prov)
        assert prov.cfg.QUANDL_KEY == "nk"                      # NDL key wins over legacy Quandl key
    finally:
        monkeypatch.undo()
        importlib.reload(prov)


def test_rsi_overbought_does_not_refire_when_previous_reading_was_exactly_70():
    ev = pm._detect_events("T", _state(prev_rsi=70.0), {"price": 100.0, "prev_close": 100.0,
                                                        "rsi": 75.0, "volume": 0})
    assert ev == []
