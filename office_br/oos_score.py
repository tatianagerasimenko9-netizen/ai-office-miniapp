"""Chronological out-of-sample scoring for exploratory B&R selectors.

Paper outcomes only. Prevents tuning a rule on the same rows used to score it.
"""
from __future__ import annotations
from typing import Any, Callable, Mapping, Sequence


def evaluate(rows: Sequence[Mapping[str, Any]], selector: Callable[[Mapping[str, Any]], bool],
             *, min_test: int = 20) -> dict[str, Any]:
    ordered = sorted((r for r in rows if r.get("status") in ("SL", "TP3")),
                     key=lambda r: float(r["created_ts"]))
    midpoint = len(ordered) // 2
    train, test = ordered[:midpoint], ordered[midpoint:]
    def score(group: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        selected = [r for r in group if selector(r)]
        tp = sum(r["status"] == "TP3" for r in selected)
        sl = sum(r["status"] == "SL" for r in selected)
        n = tp + sl
        return {"n": n, "tp3": tp, "sl": sl, "tp3_pct": round(100*tp/n, 2) if n else None}
    tr, te = score(train), score(test)
    return {"train": tr, "test": te, "eligible_for_live_review": (
        te["n"] >= min_test and te["tp3"] > te["sl"]
    ), "mode": "OFFLINE_RESEARCH", "caution": "Selection must be frozen before test; "
        "fees, fills and multi-period stability still required"}
