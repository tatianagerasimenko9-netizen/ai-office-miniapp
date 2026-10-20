"""B&R-only production freshness classifier; no Office2 changes.

A stale candle is a genuine data-quality fault, not a no-signal verdict.
"""
from __future__ import annotations
from typing import Any

def classify(last_open_ts: float | None, now_ts: float, *,
             timeframe_seconds: int = 900, max_lag_seconds: int = 900) -> dict[str, Any]:
    if last_open_ts is None:
        return {"state":"MISSING","allow_new_signals":False}
    close_ts=float(last_open_ts)+timeframe_seconds
    lag=float(now_ts)-close_ts
    if lag < 0:
        return {"state":"NOT_CLOSED","allow_new_signals":False,"lag_seconds":lag}
    if lag >= max_lag_seconds:
        return {"state":"STALE","allow_new_signals":False,"lag_seconds":lag}
    return {"state":"FRESH","allow_new_signals":True,"lag_seconds":lag}

def aggregate(health: dict[str,dict[str,Any]]) -> dict[str,Any]:
    counts={k:sum(v["state"]==k for v in health.values())
            for k in ("FRESH","STALE","MISSING","NOT_CLOSED")}
    return {"counts":counts,"symbols":len(health),
            "ready":bool(health) and counts["FRESH"]==len(health),
            "degraded":counts["STALE"]+counts["MISSING"]+counts["NOT_CLOSED"]>0}
