"""Import a legacy ``Downloads/code/python_files`` script with third-party market libraries stubbed out."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

LEGACY_DIR = Path(__file__).resolve().parent.parent / "Downloads" / "code" / "python_files"
_STUBS = ["nse", "bse", "yfinance", "nsepython", "requests_cache", "pandas_datareader", "FinanceDataReader",
          "akshare", "xlsxwriter", "tqdm"]


def _stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__getattr__ = lambda attr: (_ for _ in ()).throw(AttributeError(attr)) if attr.startswith("__") else type(attr, (), {})
    return mod


def load_script(name: str, workdir: Path, monkeypatch):
    """Load ``<name>.py`` fresh (cwd = workdir so its module-level mkdir stays in a temp dir)."""
    monkeypatch.chdir(workdir)
    monkeypatch.syspath_prepend(str(LEGACY_DIR))
    for stub in _STUBS:
        if stub not in sys.modules:
            try:
                __import__(stub)
            except ImportError:
                monkeypatch.setitem(sys.modules, stub, _stub(stub))
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    spec = importlib.util.spec_from_file_location(f"legacy_{name}", LEGACY_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod
