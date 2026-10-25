"""Polygon snapshot mapping (fetchers/providers/polygon.py). HTTP and the provider-key
config are stubbed: no network, no credentials file is read."""
import importlib
import sys
import types

import pytest


@pytest.fixture
def polygon(monkeypatch):
    cfgmod = types.ModuleType("config.providers")
    cfgmod.cfg = types.SimpleNamespace(POLYGON_KEY="test-key")
    monkeypatch.setitem(sys.modules, "config.providers", cfgmod)
    monkeypatch.delitem(sys.modules, "fetchers.providers.polygon", raising=False)
    mod = importlib.import_module("fetchers.providers.polygon")
    yield mod
    sys.modules.pop("fetchers.providers.polygon", None)


def test_snapshot_does_not_label_the_day_range_as_52_week_range(polygon, monkeypatch):
    snap = {"tickers": [{"ticker": "AAPL", "lastTrade": {"p": 100.0},
                         "day": {"c": 100.0, "h": 101.0, "l": 99.0, "v": 1000},
                         "prevDay": {"c": 98.0}}]}
    monkeypatch.setattr(polygon, "_get", lambda path, params=None, retries=3: snap)
    q = polygon.PolygonProvider().get_quotes_bulk(["AAPL"], "us")["AAPL"]
    assert q.cmp == 100.0
    assert q.ret_1d == round(2 / 98 * 100, 2)
    # A one-day high/low is not a 52-week high/low: Darvas 'near 52W high' would always pass.
    assert q.high_52w != 101.0 and q.low_52w != 99.0
