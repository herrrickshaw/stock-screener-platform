"""Golden-file helper: ``GOLDEN_WRITE=1`` captures, otherwise compares (pass-2 characterisation tests)."""
from __future__ import annotations

import difflib
import json
import math
import os
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"


def normalise(obj):
    """JSON round-trip with a stable text form for NaN/numpy/Timestamp values."""
    return json.loads(json.dumps(obj, default=str, sort_keys=False, allow_nan=True))


def _same(want, got, rel_tol: float = 1e-9) -> bool:
    """Structural equality; floats compare to ~9 significant digits (BLAS/libm differ in the last ulp)."""
    if isinstance(want, dict) and isinstance(got, dict):
        return want.keys() == got.keys() and all(_same(want[k], got[k], rel_tol) for k in want)
    if isinstance(want, list) and isinstance(got, list):
        return len(want) == len(got) and all(_same(w, g, rel_tol) for w, g in zip(want, got))
    numeric = (int, float)
    if isinstance(want, numeric) and isinstance(got, numeric) and not isinstance(want, bool):
        if math.isnan(want) or math.isnan(got):
            return math.isnan(want) and math.isnan(got)
        return math.isclose(want, got, rel_tol=rel_tol, abs_tol=1e-12)
    return want == got


def check(name: str, obj) -> None:
    got = normalise(obj)
    path = GOLDEN_DIR / f"{name}.golden"
    if os.environ.get("GOLDEN_WRITE") == "1":
        path.write_text(json.dumps(got, indent=1))
        return
    want = json.loads(path.read_text())
    if not _same(want, got):
        diff = difflib.unified_diff(
            json.dumps(want, indent=1).splitlines(),
            json.dumps(got, indent=1).splitlines(),
            "golden", "actual", lineterm="", n=2,
        )
        raise AssertionError(f"golden {name} differs:\n" + "\n".join(list(diff)[:60]))
