"""Characterisation tests (pass 2): quote row building and bulk-fetch orchestration with Cassandra/network stubbed."""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from db import bulk_fetcher as bf
from db import quote_updater as qu
from golden_util import check
from synth import make_quotes


class _FakeSession:
    def prepare(self, q):
        return ("prepared", q[:20])


@pytest.fixture
def captured(monkeypatch):
    calls = []
    mod = types.ModuleType("cassandra.concurrent")
    mod.execute_concurrent_with_args = lambda s, stmt, rows, concurrency: calls.append((stmt, list(rows), concurrency))
    pkg = types.ModuleType("cassandra")
    pkg.concurrent = mod
    monkeypatch.setitem(sys.modules, "cassandra", pkg)
    monkeypatch.setitem(sys.modules, "cassandra.concurrent", mod)
    monkeypatch.setattr(qu.cass, "session", lambda: _FakeSession())
    monkeypatch.setattr(qu, "_stmts", {})

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(qu, "datetime", _DT)
    return calls


def _live_df():
    df = make_quotes(20, 4, 0.3).rename(columns={})
    df["volume_20d_avg"] = df["volume"] * 0.8
    df["_error"] = False
    df.loc[2, "_error"] = True
    df.loc[3, "ticker"] = "  "
    df.loc[4, "ticker"] = "  PAD  "
    df.loc[5, "sector"] = "  "
    df.loc[6, "rsi_signal"] = None
    return df


def test_upsert_quotes_rows(captured):
    n = qu.upsert_quotes("us", _live_df())
    check("upsert_rows", {"n": n, "calls": captured})
    captured.clear()
    sparse = pd.DataFrame({"ticker": ["A", "B"], "cmp": [1.0, np.nan]})
    check("upsert_rows_sparse", {"n": qu.upsert_quotes("india", sparse), "calls": captured})
    assert qu.upsert_quotes("us", sparse.iloc[0:0]) == 0
    assert qu.upsert_quotes("us", pd.DataFrame({"x": [1]})) == 0


def test_fetch_market_quotes_orchestration(monkeypatch):
    written = []
    monkeypatch.setattr(bf, "_get_tickers", lambda m: [f"T{i}" for i in range(7)] if m != "empty" else [])
    monkeypatch.setattr(bf, "_fetch_ohlcv_batch",
                        lambda b, sfx, inr, m: [{"ticker": t, "cmp": 1.0} for t in b if t != "T3"])
    monkeypatch.setattr(bf, "_fetch_info_one", lambda t, sfx, inr, m: {"pe": 5.0} if t != "T1" else {})
    monkeypatch.setattr(bf, "upsert_quotes", lambda m, df: written.append((m, df.to_dict("records"))) or len(df))
    out = {}
    for market, kw in [("india", {}), ("us", {"with_fundamentals": False}), ("empty", {})]:
        r = bf.fetch_market_quotes(market, batch_size=3, inter_batch_delay=0, **kw)
        r = {k: v for k, v in r.items() if k not in ("elapsed_s", "rate_per_min")}
        out[market] = r
    check("bulk_fetch", {"results": out, "written": written})
