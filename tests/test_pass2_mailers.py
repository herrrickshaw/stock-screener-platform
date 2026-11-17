"""Characterisation tests (pass 2): daily mailer HTML reports (report generation only; nothing is sent)."""
from __future__ import annotations

import importlib
import sys
from datetime import datetime

from golden_util import check

ROOT_MODULES = ["daily_mailer", "daily_mailer_enhanced"]


class _FixedDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 5, 6, 7, 8, 9)


def _load(name, monkeypatch):
    sys.modules.pop(name, None)
    mod = importlib.import_module(name)
    monkeypatch.setattr(mod, "datetime", _FixedDT)
    return mod


def test_enhanced_report_golden(monkeypatch):
    mod = _load("daily_mailer_enhanced", monkeypatch)
    check("mailer_enhanced_html", {"html": mod.EnhancedDailyMailer().generate_html_report()})


def _stocks(n, base):
    return [{"symbol": f"S{i}", "price": 10.5 + i, "score": base + i, "market": "NSE",
             "signal": ["BUY", "WATCH", "HOLD"][i % 3]} for i in range(n)]


def test_daily_mailer_report_golden(monkeypatch):
    mod = _load("daily_mailer", monkeypatch)
    m = mod.DailyMailer()
    picks = {"title": "T1", "description": "D1", "stocks": _stocks(14, 3), "summary": "sum1"}
    quality = {"title": "T2", "description": "D2", "stocks": [], "summary": ""}
    german = {"title": "T3", "description": "D3", "summary": "sum3",
              "tiers": {"tier_1": {"label": "L1", "allocation": "50%", "stocks": _stocks(3, 1)},
                        "tier_2": {"label": "L2", "allocation": "30%", "stocks": []}}}
    monkeypatch.setattr(m, "get_darvas_picks", lambda: picks)
    monkeypatch.setattr(m, "get_piotroski_picks", lambda: quality)
    monkeypatch.setattr(m, "get_german_ccc_analysis", lambda: german)
    check("mailer_daily_html", {"html": m.generate_html_report(), "summary": m.get_global_summary()})
