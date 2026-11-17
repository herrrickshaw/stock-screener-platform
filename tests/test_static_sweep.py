"""Regression tests for findings of the 2026-10-25 static sweep (ruff/bandit/py_compile).

Every test here first failed on the pre-fix code. No network, no writes outside tmp_path:
``HOME`` is pointed at ``tmp_path`` before the modules under test are imported, because
both ``screener_extended_filters`` and ``market_data_cache`` write under ``Path.home()``."""
import ast
import importlib
import os
import py_compile
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_FILES = os.path.join(ROOT, "Downloads", "code", "python_files")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _fresh_import(name, path):
    sys.modules.pop(name, None)
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(path)


# ── screener_extended_filters.py: Path used before its function-local import (F821) ──

def test_extended_filters_main_writes_index_file(home, capsys):
    mod = _fresh_import("screener_extended_filters", ROOT)
    try:
        mod.main()  # pre-fix: UnboundLocalError on `Path`
    finally:
        sys.modules.pop("screener_extended_filters", None)
    out = home / "screener_filters_index.json"
    assert out.exists()
    assert "Screener index saved" in capsys.readouterr().out


# ── market_data_cache.get_ohlc: parquet present but no meta entry returned None (RET503) ──

def test_get_ohlc_with_parquet_but_no_meta_returns_dataframe(home, monkeypatch):
    mdc = _fresh_import("market_data_cache", PY_FILES)
    try:
        cache = mdc.MarketCache(verbose=False)
        assert cache._meta == {}
        ticker = "TEST.NS"
        # a cached file exists on disk, but the JSON index has no entry for it
        cache._ohlc_path(ticker).write_bytes(b"")
        idx = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
        fresh = pd.DataFrame({"Open": [1.0, 2.0, 3.0], "High": [1.0, 2.0, 3.0],
                              "Low": [1.0, 2.0, 3.0], "Close": [1.0, 2.0, 3.0],
                              "Volume": [10, 20, 30]}, index=idx)
        monkeypatch.setattr(cache, "_yf_download_single", lambda t, start: fresh.copy())
        monkeypatch.setattr(mdc.MarketCache, "_write_parquet", staticmethod(lambda p, d: None))
        monkeypatch.setattr(mdc.pd, "read_parquet", lambda p: fresh.iloc[:2].copy())
        result = cache.get_ohlc(ticker)
    finally:
        sys.modules.pop("market_data_cache", None)
    assert isinstance(result, pd.DataFrame)  # pre-fix: None
    assert len(result) == 3


# ── deoldify.py: Colab `!shell` lines are not Python (py_compile SyntaxError) ──

def test_deoldify_is_valid_python(tmp_path):
    src = os.path.join(PY_FILES, "deoldify.py")
    py_compile.compile(src, cfile=str(tmp_path / "deoldify.pyc"), doraise=True)


# ── DATA_COMPLETENESS_TEST.py: credentials were string literals in source (S105) ──

def test_data_completeness_script_has_no_literal_credentials():
    src = os.path.join(ROOT, "global_expansion_screener_framework", "DATA_COMPLETENESS_TEST.py")
    with open(src, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    literal_assigned = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ("screener_email", "screener_password"):
                    literal_assigned.append(t.id)
    assert literal_assigned == []
