"""Characterisation test (pass 2): /api/db/geography response with a fake Cassandra session and CSV."""
from __future__ import annotations

import asyncio
import builtins
import io
import os

import pytest
from fastapi import HTTPException
from golden_util import check
from routers import cassandra_router as cr

EU_CSV = "symbol,exchange\n" + "".join(
    f"S{i},{ex}\n" for ex, n in [("London Stock Exchange", 5), ("Euronext Paris", 3), ("Mystery Bourse", 2),
                                  ("SIX Swiss", 3)] for i in range(n)
)


class _Res:
    def __init__(self, v):
        self.v = v

    def one(self):
        return None if self.v is None else (self.v,)


class _Sess:
    COUNTS = {("instruments", "india"): 100, ("stock_quotes", "india"): 40, ("instruments", "us"): 300,
              ("stock_quotes", "us"): 300, ("instruments", "europe"): 13, ("stock_quotes", "europe"): 6,
              ("instruments", "japan"): 50}

    def execute(self, q, params):
        table = "instruments" if ".instruments" in q else "stock_quotes"
        return _Res(self.COUNTS.get((table, params[0])))


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setattr(cr.cass, "is_available", lambda: True)
    monkeypatch.setattr(cr.cass, "session", lambda: _Sess())
    real_exists, real_open = os.path.exists, builtins.open
    monkeypatch.setattr(os.path, "exists", lambda p: True if str(p).endswith("europe_all_list.csv") else real_exists(p))
    monkeypatch.setattr(builtins, "open",
                        lambda p, *a, **k: io.StringIO(EU_CSV) if str(p).endswith("europe_all_list.csv") else real_open(p, *a, **k))


def test_geography_golden(fake_env):
    check("geography", asyncio.run(cr.geography_status()))


def test_geography_offline(monkeypatch):
    monkeypatch.setattr(cr.cass, "is_available", lambda: False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.geography_status())
    assert e.value.status_code == 503
