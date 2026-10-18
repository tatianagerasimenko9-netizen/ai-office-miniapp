"""Independent B&R M1 candle outcome replay, research only.

OHLC cannot resolve intra-candle ordering. Never treats a touched price as a fill.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence


def replay(signal: Mapping[str, Any], candles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    direction = str(signal["direction"]).upper()
    if direction not in ("LONG", "SHORT"):
        return {"status": "INVALID", "reason": "DIRECTION"}
    sign = 1 if direction == "LONG" else -1
    entry, stop = float(signal["entry"]), float(signal["sl"])
    targets = [float(t["p"]) for t in signal["targets"][:3]]
    if sign * (entry - stop) <= 0 or not targets or any(sign * (p - entry) <= 0 for p in targets):
        return {"status": "INVALID", "reason": "GEOMETRY"}
    if any(sign * (b - a) <= 0 for a, b in zip(targets, targets[1:])):
        return {"status": "INVALID", "reason": "TARGET_ORDER"}
    entered = False
    hits: list[str] = []
    last_ts = None
    for candle in candles:
        ts = float(candle["ts"])
        if last_ts is not None and ts != last_ts + 60:
            return {"status": "DATA_GAP", "events": hits}
        last_ts = ts
        hi, lo = float(candle["high"]), float(candle["low"])
        if hi < lo:
            return {"status": "INVALID", "reason": "OHLC"}
        # An M1 bar may only be evaluated after the confirmation M15 bar closed.
        # Earlier bars can make a hindsight entry look executable.
        if ts < float(signal.get("eligible_ts", float("-inf"))):
            continue
        if not entered:
            if not lo <= entry <= hi:
                continue
            entered = True
            hits.append("ENTRY")
            if (lo <= stop if sign > 0 else hi >= stop) or any(
                hi >= t if sign > 0 else lo <= t for t in targets
            ):
                return {"status": "AMBIGUOUS", "events": hits}
            continue
        stop_hit = lo <= stop if sign > 0 else hi >= stop
        tp_hits = [i for i, t in enumerate(targets, 1) if (hi >= t if sign > 0 else lo <= t)]
        if stop_hit and any(f"TP{i}" not in hits for i in tp_hits):
            return {"status": "AMBIGUOUS", "events": hits}
        if stop_hit:
            hits.append("SL")
            return {"status": "SL", "events": hits}
        for i in tp_hits:
            if f"TP{i}" not in hits:
                hits.append(f"TP{i}")
        if f"TP{len(targets)}" in hits:
            return {"status": f"TP{len(targets)}", "events": hits}
    return {"status": "OPEN" if entered else "UNFILLED", "events": hits,
            "exchange_fills_verified": False}
