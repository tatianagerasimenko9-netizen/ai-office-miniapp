"""Offline B&R regime + obstacle + TP3 holdout report.

Consumes timestamped, historically as-of features. No live filtering.
Features must be generated without future candles; this module cannot
independently verify their provenance.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from office_br.oos_score import evaluate
from office_br.regime_shadow import assess
from office_br.tp3_shadow import evaluate as tp3_evaluate


def report(rows: Sequence[Mapping[str, Any]], *, min_test: int = 20) -> dict[str, Any]:
    prepared = []
    missing = 0
    for row in rows:
        if row.get("status") not in ("SL", "TP3"):
            continue
        if "created_ts" not in row or "confirm_ts" not in row or "htf" not in row or "obstacle" not in row:
            missing += 1
            continue
        if (row.get("feature_asof_ts") is None or
            float(row["feature_asof_ts"]) > float(row["confirm_ts"]) + 900 or
            float(row["created_ts"]) < float(row["confirm_ts"]) + 900):
            missing += 1
            continue
        regime = assess(row, row["htf"], row["obstacle"])
        reach = tp3_evaluate(row)
        prepared.append(dict(row, research_candidate=bool(
            regime.get("candidate_for_research") and reach.get("valid")
            and reach["tp3_r"] < 4.0)))
    scored = evaluate(prepared, lambda r: r["research_candidate"], min_test=min_test)
    scored["baseline"] = evaluate(prepared, lambda r: True, min_test=min_test)
    scored["excluded_missing_or_future_features"] = missing
    scored["source_rows"] = len(rows)
    scored["mode"] = "OFFLINE_RESEARCH"
    scored["production_gate_changed"] = False
    scored["warning"] = ("Thresholds and feature choices are exploratory; "
                         "independent untouched holdout required before live review.")
    return scored
