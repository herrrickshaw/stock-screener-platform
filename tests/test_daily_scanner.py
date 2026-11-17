"""Characterisation tests: scan output must equal the pre-refactor golden snapshot."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from scanners import daily_scanner as ds
from synth import make_quotes

GOLDEN = json.loads((Path(__file__).parent / "golden" / "daily_scanner.golden").read_text())
FRAMES = {
    "full": lambda: make_quotes(50),
    "sparse": lambda: make_quotes(25, 3, 0.6),
    "minimal": lambda: make_quotes(12, 5, 0.0)[["ticker", "cmp", "high_52w", "low_52w", "ema_50", "rsi"]],
    "empty": lambda: make_quotes(3).iloc[0:0],
}


@pytest.mark.parametrize("case", sorted(FRAMES))
@pytest.mark.parametrize("scan", ["darvas", "piotroski"])
def test_matches_golden(case, scan):
    fn = ds.scan_darvas if scan == "darvas" else ds.scan_piotroski
    got = json.loads(json.dumps(fn(FRAMES[case]()), default=str))
    assert got == GOLDEN[case][scan]


def test_signal_thresholds_darvas():
    rows = ds.scan_darvas(make_quotes(50))
    for r in rows:
        want = "BUY" if r["score"] >= 5 else "WATCH" if r["score"] >= 3 else "AVOID"
        assert r["signal"] == want
        assert 0 <= r["score"] <= r["max_score"]


def test_piotroski_dynamic_threshold_scales_with_available_fields():
    import math
    for r in ds.scan_piotroski(make_quotes(50, 11, 0.5)):
        buy, watch = math.ceil(r["max_score"] * 0.65), math.ceil(r["max_score"] * 0.40)
        want = "BUY" if r["score"] >= buy else "WATCH" if r["score"] >= watch else "AVOID"
        assert r["signal"] == want


def test_helpers():
    assert ds._r(float("nan")) is None
    assert ds._r("x") is None
    assert ds._r(1.2345) == 1.23
    assert ds._b(None) is None
