"""Independent B&R ledger vs historical Binance Futures M1 replay comparison.

Read-only: accepts signal/event exports and historical closed 1m candles.
Does not place orders or change production signal statuses.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from office_br.m1_replay import replay


def compare(signal: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
            candles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required = ("sig_id", "confirm_ts", "direction", "entry", "sl", "targets")
    if any(k not in signal for k in required):
        return {"verdict": "INVALID_INPUT", "missing": [k for k in required if k not in signal]}
    eligibility = float(signal["confirm_ts"]) + 900
    # Require an actual M1 bar at the exact eligibility time; a truncated
    # history must not be misinterpreted as an unfilled signal.
    times = [float(x["ts"]) for x in candles]
    if eligibility not in times:
        return {"verdict": "INSUFFICIENT_M1", "sig_id": signal["sig_id"]}
    ordered = sorted((x for x in candles if float(x["ts"]) >= eligibility),
                     key=lambda x: float(x["ts"]))
    outcome = replay(dict(signal, eligible_ts=eligibility), ordered)
    # Never call a 48h replay complete if the terminal event was not found
    # and the downloaded M1 history ends before the expected horizon.
    horizon_end = eligibility + 48 * 3600
    if outcome["status"] in ("OPEN", "UNFILLED") and (not ordered or float(ordered[-1]["ts"]) < horizon_end - 60):
        return {"sig_id": signal["sig_id"], "verdict": "INSUFFICIENT_M1",
                "m1_status": outcome["status"], "eligible_ts": eligibility,
                "last_m1_ts": float(ordered[-1]["ts"]) if ordered else None,
                "mode": "READ_ONLY_REPLAY", "exchange_fills_verified": False}
    recorded = {str(e["level"]) for e in events}
    if outcome["status"] in ("INVALID", "DATA_GAP", "AMBIGUOUS"):
        verdict = "REVIEW"
    elif outcome["status"] in ("OPEN", "UNFILLED"):
        verdict = "PENDING_OR_MISSING_HISTORY"
    elif outcome["status"] in ("SL", "TP3"):
        verdict = "MATCH" if outcome["status"] in recorded else "MISMATCH"
    else:
        verdict = "REVIEW"
    return {"sig_id": signal["sig_id"], "verdict": verdict,
            "m1_status": outcome["status"], "ledger_levels": sorted(recorded),
            "m1_events": outcome.get("events", []), "eligible_ts": eligibility,
            "exchange_fills_verified": False, "mode": "READ_ONLY_REPLAY"}


def summarize(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {}
    for item in results:
        key = str(item["verdict"])
        counts[key] = counts.get(key, 0) + 1
    return {"total": len(results), "verdicts": counts,
            "verified_profitable": False, "mode": "READ_ONLY_REPLAY"}
