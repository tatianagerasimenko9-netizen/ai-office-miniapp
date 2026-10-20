"""Explainable coin discovery and selection for B&R. Research only, no order execution.

The referenced video shows chart analysis of AGT and Q and retrospective percentage
claims; it does NOT establish exact screening thresholds or a verified edge.
All thresholds below are explicit hypotheses requiring out-of-sample validation.
"""
from __future__ import annotations
from typing import Any

DEFAULTS = {
    "min_quote_volume_usdt_24h": 5_000_000.0,
    "max_spread_bps": 15.0,
    "min_candles_m15": 100,
    "min_atr_pct": 0.4,
    "max_atr_pct": 12.0,
    "max_extension_atr": 3.0,
}

def screen(snapshot: dict[str, Any], cfg: dict[str, float] | None = None) -> dict[str, Any]:
    p = dict(DEFAULTS)
    if cfg:
        p.update(cfg)
    reasons: list[str] = []
    try:
        symbol = str(snapshot["symbol"]).upper()
        volume = float(snapshot["quote_volume_usdt_24h"])
        spread = float(snapshot["spread_bps"])
        candles = int(snapshot["closed_m15_candles"])
        atr_pct = float(snapshot["atr_pct"])
        extension = float(snapshot["extension_atr"])
        fresh = snapshot["fresh_closed_m15"] is True
        has_break = snapshot.get("closed_breakout") is True
        has_retest = snapshot.get("confirmed_retest") is True
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"symbol":str(snapshot.get("symbol","UNKNOWN")), "decision":"REJECT",
                "reasons":["INCOMPLETE_OR_INVALID_DATA"],"manual_only":True}
    import math
    if not all(math.isfinite(x) for x in (volume,spread,atr_pct,extension)):
        reasons.append("NONFINITE_MARKET_DATA")
    if not fresh:
        reasons.append("STALE_M15")
    if volume < p["min_quote_volume_usdt_24h"]:
        reasons.append("LOW_LIQUIDITY")
    if spread < 0 or spread > p["max_spread_bps"]:
        reasons.append("WIDE_SPREAD")
    if candles < p["min_candles_m15"]:
        reasons.append("INSUFFICIENT_HISTORY")
    if not p["min_atr_pct"] <= atr_pct <= p["max_atr_pct"]:
        reasons.append("ATR_OUT_OF_RANGE")
    if extension > p["max_extension_atr"] or extension < 0:
        reasons.append("CHASED_MOVE")
    if reasons:
        decision="REJECT"
    elif has_break and has_retest:
        decision="CANDIDATE_CONFIRMED"
    elif has_break:
        decision="WATCH_RETEST"
    else:
        decision="WATCH_LEVEL"
    return {"symbol":symbol,"decision":decision,"reasons":reasons,
            "manual_only":True,"thresholds_are_hypotheses":True,
            "evidence":{"closed_breakout":has_break,"confirmed_retest":has_retest}}
