"""Adapters for the desktop JSON configuration format."""
from __future__ import annotations

from datetime import time


def _as_time(value) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, dict):
        return time(int(value.get("hour", 0)), int(value.get("minute", 0)), int(value.get("second", 0)))
    if isinstance(value, (list, tuple)):
        return time(int(value[0]), int(value[1]), int(value[2]) if len(value) > 2 else 0)
    if isinstance(value, str):
        parts = [int(part) for part in value.split(":")]
        return time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)
    raise ValueError(f"Unsupported time value: {value!r}")


def custom_market_timings(value) -> dict:
    """Turn JSON {MARKET_OP: [{hour...}, weekday, {hour...}]} into legacy timings."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for market, row in value.items():
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            continue
        try:
            result[str(market)] = [_as_time(row[0]), int(row[1]), _as_time(row[2])]
        except (TypeError, ValueError, KeyError):
            continue
    return result
