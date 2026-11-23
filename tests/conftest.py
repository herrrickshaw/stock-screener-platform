"""Shared pytest setup: put the import roots the code expects on sys.path.

The FastAPI backend is written to run from inside ``backend/`` (modules import
``column_map``, ``parsers.market_db``, ``events.event_bus`` ... as top-level
names) and the DDD package lives under ``Downloads/code``.  Neither is an
installed package, so the roots are added here once.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "backend", ROOT / "Downloads" / "code"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
