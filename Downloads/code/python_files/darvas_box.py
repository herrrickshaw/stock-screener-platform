"""
Shared Darvas Box building blocks used by the daily-report scripts.

Design rule: box formation uses ONLY historical bars - the caller passes
``highs``/``lows`` that already exclude the current bar, so today's bar cannot
contaminate the box boundaries.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """First column whose name contains any candidate (case-insensitive, candidate order wins)."""
    for c in candidates:
        match = next((col for col in df.columns if c.upper() in col.upper()), None)
        if match:
            return match
    return None


def numeric_list(df: pd.DataFrame, col: str) -> list:
    """Column as floats, non-numeric / missing coerced to 0."""
    return pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()


def confirmed_top(highs: list, confirm: int) -> tuple:
    """Most recent high not exceeded by the next ``confirm`` highs -> (index, value) or (None, None)."""
    n = len(highs)
    for i in range(n - confirm - 1, -1, -1):
        candidate = highs[i]
        if candidate == 0:
            continue
        window = highs[i + 1: i + 1 + confirm]
        if len(window) == confirm and all(h < candidate for h in window):
            return i, candidate
    return None, None


def confirmed_bottom(lows: list, top_idx: int, confirm: int) -> Optional[float]:
    """Confirmed floor from the box-top day onward; falls back to the segment minimum, None if no valid low."""
    segment = lows[top_idx:]
    for i in range(len(segment) - confirm):
        candidate = segment[i]
        if candidate == 0:
            continue
        window = segment[i + 1: i + 1 + confirm]
        if len(window) == confirm and all(low > candidate for low in window):
            return candidate
    valid = [low for low in segment if low > 0]
    return min(valid) if valid else None


def classify_box(current: float, box_top: float, box_bottom: float, confirm: int, data_points: int) -> dict:
    """Classify today's close against the historical box and report position metrics."""
    if current > box_top:
        signal = "BREAKOUT_BUY"
    elif current < box_bottom:
        signal = "BREAKDOWN_SELL"
    else:
        signal = "IN_BOX"

    box_range = box_top - box_bottom
    pos_in_box = ((current - box_bottom) / box_range * 100) if box_range else 0
    upside_to_top = ((box_top - current) / current * 100) if current else 0
    return {
        "signal":              signal,
        "box_top":             round(box_top,    2),
        "box_bottom":          round(box_bottom, 2),
        "current_price":       round(current,    2),
        "box_range":           round(box_range,  2),
        "position_in_box_pct": round(pos_in_box,    1),
        "upside_to_top_pct":   round(upside_to_top, 2),
        "confirm_days":        confirm,
        "data_points":         data_points,
    }
