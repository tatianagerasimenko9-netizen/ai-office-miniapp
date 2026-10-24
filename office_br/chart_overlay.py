"""Single validated B&R chart overlay specification for Mini App.

Presentation-only; no trades, no signal mutation. The same numbers should
appear on chart and in Telegram, sourced from the stored B&R signal.
"""
from __future__ import annotations
import json
from math import isfinite


def overlay(row):
    direction = row["direction"]
    if direction not in ("LONG", "SHORT"):
        raise ValueError("invalid direction")
    targets = row.get("targets_json", row.get("targets", []))
    if isinstance(targets, str):
        targets = json.loads(targets)
    entry, sl, level = (float(row[k]) for k in ("entry", "sl", "level"))
    tp = [float(t["p"]) for t in targets[:3]]
    values = [entry, sl, level, *tp]
    if not values or not all(isfinite(x) and x > 0 for x in values):
        raise ValueError("invalid levels")
    sign = 1 if direction == "LONG" else -1
    if sign * (entry - sl) <= 0 or any(sign * (p - entry) <= 0 for p in tp):
        raise ValueError("inverted risk or targets")
    risk = abs(entry-sl)
    lines = [{"id": "BREAKOUT", "price": level, "role": "structure"},
             {"id": "ENTRY", "price": entry, "role": "entry"},
             {"id": "SL", "price": sl, "role": "stop"}]
    lines += [{"id": f"TP{i}", "price": p, "role": "target",
               "r": round(abs(p-entry)/risk, 3)} for i,p in enumerate(tp,1)]
    return {"signal_id": row.get("sig_id"), "symbol": row["symbol"],
            "direction": direction, "source": "STORED_BR_SIGNAL",
            "execution": "MANUAL_ONLY", "lines": lines,
            "structure": [{"kind": "BREAK", "ts": row["break_ts"]},
                          {"kind": "RETEST", "ts": row["retest_ts"]},
                          {"kind": "CONFIRM", "ts": row["confirm_ts"]}]}
