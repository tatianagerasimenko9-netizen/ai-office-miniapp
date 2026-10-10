"""Збирає аналітичний звіт з нормалізованих угод. Усі цифри — з даних, нічого не округлюється на користь висновку."""
from __future__ import annotations

from typing import Any, Dict, List

from office2.learning import classify as CL
from office2.learning import compare as CP
from office2.learning import pnl as P

CODES = ["DELIVERY_LAG", "STALE_AT_DELIVERY", "COST_HEAVY", "LOW_RR", "HTF_CONFLICT", "WEAK_LEVEL", "PRE_SESSION", "OFF_HOURS", "OPPOSITE_EXPOSURE", "DUPLICATE_THESIS"]


def build(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    for t in trades:
        t["flags"] = CL.flags(t, trades)
    rep: Dict[str, Any] = {"n_trades": len(trades), "first_result": {}, "pnl": {}, "by_flag": {}, "filters": {}, "by_group": {}}
    for t in trades:
        rep["first_result"][t["first"]] = rep["first_result"].get(t["first"], 0) + 1
    for m in ("A", "B"):
        rep["pnl"][m] = P.summarize(trades, m)
    for d in ("LONG", "SHORT"):
        rep["by_group"]["direction=" + d] = P.summarize([t for t in trades if t["direction"] == d], "A")
    for s in sorted({t.get("session") for t in trades if t.get("session")}):
        rep["by_group"]["session=" + s] = P.summarize([t for t in trades if t.get("session") == s], "A")
    for k in sorted({t.get("kind") for t in trades if t.get("kind")}):
        rep["by_group"]["kind=" + k] = P.summarize([t for t in trades if t.get("kind") == k], "A")
    for c in CODES:
        pred = (lambda t, c=c: c in t["flags"])
        rep["by_flag"][c] = CP.contrast(trades, pred)
        rep["filters"][c] = {"effect": CP.filter_effect(trades, pred), "walk_forward": CP.walk_forward(trades, pred)}
    rep["undetermined_sl"] = sum(1 for t in trades if t["first"] == "SL" and not t["flags"])
    rep["not_evaluable"] = CL.NOT_EVALUABLE
    return rep
