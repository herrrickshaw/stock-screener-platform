"""Test path setup: the backend is imported as top-level modules (``scanners``, ``fetchers``...)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "backend"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
