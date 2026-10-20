"""Causal M15 -> M5/M1 read-only confirmation of an existing B&R signal.

No order placement, no mutation of signal delivery, no Office2 changes.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite

SECONDS = {"5m": 300, "1m": 60}


def _epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def evaluate(symbol, signal, confirm_close, fetch, *, limit=120):
    """Use only candles closed by the M15 confirmation close.

    Confirming a direction requires both M5 and M1 closing beyond the
    breakout level, and their latest candle bodies agreeing with direction.
    No later candles are admissible.
    """
    direction = signal.get("direction")
    level = float(signal["level"])
    if direction not in ("LONG", "SHORT") or not isfinite(level):
        return {"status": "UNKNOWN", "reason": "INVALID_SIGNAL", "mode": "SHADOW_ONLY"}
    frames = {}
    for tf, seconds in SECONDS.items():
        try:
            raw = fetch(symbol, tf, limit, closed_only=True)
            if not isinstance(raw, list):
                raise ValueError("missing")
            rows = []
            for b in raw:
                ts = _epoch(b["ts"])
                if ts + seconds > confirm_close:
                    continue
                op, high, low, close = (float(b[k]) for k in ("open", "high", "low", "close"))
                if not all(isfinite(x) for x in (ts, op, high, low, close)):
                    raise ValueError("nonfinite")
                if not (0 < low <= min(op, close) <= max(op, close) <= high):
                    raise ValueError("ohlc")
                rows.append((ts, op, close))
            rows.sort()
            if len(rows) < 3 or rows[-1][0] + seconds != confirm_close:
                raise ValueError("missing_asof")
            if any(rows[i][0] - rows[i-1][0] != seconds for i in (-2, -1)):
                raise ValueError("gap")
            frames[tf] = rows[-3:]
        except (ValueError, KeyError, TypeError, OverflowError):
            return {"status": "UNKNOWN", "reason": f"{tf}_DATA_UNAVAILABLE", "mode": "SHADOW_ONLY"}
    sign = 1 if direction == "LONG" else -1
    checks = {}
    for tf, rows in frames.items():
        _, op, close = rows[-1]
        checks[tf] = sign * (close - level) > 0 and sign * (close - op) > 0
    return {"status": "CONFIRMED" if all(checks.values()) else "NOT_CONFIRMED",
            "reason": "M5_M1_CLOSE_ALIGNMENT" if all(checks.values()) else "LOWER_TF_NOT_ALIGNED",
            "checks": checks, "mode": "SHADOW_ONLY"}
