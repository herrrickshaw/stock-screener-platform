"""Make ``backend/`` (flat imports such as ``from column_map import ...``) and the repo root importable."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "backend", ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
