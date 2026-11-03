"""Golden-file helper: ``GOLDEN_WRITE=1`` captures, otherwise compares (pass-2 characterisation tests)."""
from __future__ import annotations

import json
import os
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"


def normalise(obj):
    """JSON round-trip with a stable text form for NaN/numpy/Timestamp values."""
    return json.loads(json.dumps(obj, default=str, sort_keys=False, allow_nan=True))


def check(name: str, obj) -> None:
    got = normalise(obj)
    path = GOLDEN_DIR / f"{name}.golden"
    if os.environ.get("GOLDEN_WRITE") == "1":
        path.write_text(json.dumps(got, indent=1))
        return
    assert got == json.loads(path.read_text())
