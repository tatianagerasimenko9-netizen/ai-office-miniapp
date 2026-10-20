"""Read-only reconciliation of B&R paper event ledger vs independent M1 replay."""
from __future__ import annotations
from typing import Any, Mapping, Sequence

from office_br.m1_replay import replay


def reconcile(signal: Mapping[str, Any], candles: Sequence[Mapping[str, Any]],
              ledger_events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = replay(signal, candles)
    observed = {str(e["level"]) for e in ledger_events}
    expected = set(result.get("events", ()))
    # The replay's SL and TP3 are terminal states. Intermediate TP touches
    # may precede a later stop and are retained for reconciliation.
    if result["status"] in ("DATA_GAP", "INVALID"):
        return {"verdict": "UNVERIFIABLE", "reason": result["status"],
                "replay": result, "observed": sorted(observed)}
    if result["status"] in ("OPEN", "UNFILLED"):
        # An open replay is not evidence the production ledger is wrong:
        # the supplied candle interval may be incomplete.
        return {"verdict": "INCOMPLETE", "reason": result["status"],
                "replay": result, "observed": sorted(observed)}
    if result["status"] == "AMBIGUOUS":
        verdict = "MATCH" if "AMBIGUOUS" in observed else "MISMATCH"
    else:
        verdict = "MATCH" if expected == observed.intersection(
            {"ENTRY", "TP1", "TP2", "TP3", "SL", "AMBIGUOUS"}
        ) else "MISMATCH"
    return {"verdict": verdict, "replay": result, "observed": sorted(observed),
            "exchange_fills_verified": False}
