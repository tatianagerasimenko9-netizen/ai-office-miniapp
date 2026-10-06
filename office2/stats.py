"""LIVE BETA: що накопичено по сценаріях Office2 (без заяв про прибутковість). Рахується з frozen-знімка і lifecycle-подій у БД, без look-ahead.

Результат сценарію ≠ особиста угода власниці. R — брутто, до комісій: SL після входу = −1 R; досягнутий TPn = R цього рівня з тези (позиція до рівня).
Розріз за кількістю факторів ПРОТИ (0 / 1 / 2+) — для пізнішого аналізу; жодного блокування за ним немає.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from office2.webview import _rows


def _ms(db: str, sid: str) -> List[Dict[str, Any]]:
    out = []
    for (pj,) in _rows(db, "SELECT payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id = ? ORDER BY id ASC", (sid,)):
        try:
            out.append(json.loads(pj))
        except ValueError:
            pass
    return out


def scenario_outcome(snap: Dict[str, Any], created_ts: float, miles: List[Dict[str, Any]]) -> Dict[str, Any]:
    th = snap.get("thesis") or {}
    tg = th.get("targets") or []
    lv = {m.get("level"): m for m in miles}
    entry = lv.get("ENTRY")
    state = "WAITING_ENTRY"
    r = None
    if "EXPIRED" in lv and not entry:
        state = "EXPIRED"
    elif entry:
        state = "ACTIVE"
        reached = [i for i in (1, 2, 3) if f"TP{i}" in lv]
        if "SL" in lv and (not reached or float(lv["SL"].get("touched_ts") or 0) <= float(lv[f"TP{reached[0]}"].get("touched_ts") or 1e18)):
            state, r = "SL", -1.0
        elif reached:
            top = max(reached)
            state = f"TP{top}"
            r = float(tg[top - 1]["r"]) if len(tg) >= top and tg[top - 1].get("r") is not None else None
            if "SL" in lv:
                state += "→SL"
        elif "SL" in lv:
            state, r = "SL", -1.0
    first_tp = next((lv[k] for k in ("TP1", "TP2", "TP3") if k in lv), None)
    terminal = lv.get("SL") or first_tp
    return {"state": state, "r": r, "entry_touched_ts": entry.get("touched_ts") if entry else None,
            "time_to_entry_s": (float(entry["touched_ts"]) - created_ts) if entry and entry.get("touched_ts") else None,
            "time_to_first_result_s": (float(terminal["touched_ts"]) - created_ts) if terminal and terminal.get("touched_ts") else None,
            "order": [m.get("level") for m in sorted(miles, key=lambda m: float(m.get("touched_ts") or 0))]}


def collect(db: str) -> Dict[str, Any]:
    rows = _rows(db, "SELECT scenario_id, symbol, direction, created_ts, status, snapshot_json FROM office2_live_signal ORDER BY created_ts ASC")
    total = {"ready": 0, "delivered": 0, "not_sent": 0, "waiting_entry": 0, "active": 0, "sl": 0, "tp": 0, "expired": 0}
    buckets: Dict[str, Dict[str, Any]] = {k: {"n": 0, "closed": 0, "sum_r": 0.0} for k in ("0", "1", "2+")}
    items = []
    for sid, sym, d, ct, status, sj in rows:
        snap = json.loads(sj or "{}")
        total["ready"] += 1
        if status != "DELIVERED":
            total["not_sent"] += 1
            continue
        total["delivered"] += 1
        oc = scenario_outcome(snap, float(ct), _ms(db, sid))
        st = oc["state"]
        total["waiting_entry" if st == "WAITING_ENTRY" else "active" if st == "ACTIVE" else "expired" if st == "EXPIRED" else "sl" if st == "SL" else "tp"] += 1
        ag = int((snap.get("alignment_summary") or {}).get("against", 0))
        b = buckets["0" if ag == 0 else "1" if ag == 1 else "2+"]
        b["n"] += 1
        if oc["r"] is not None:
            b["closed"] += 1
            b["sum_r"] += oc["r"]
        items.append({"id": sid, "symbol": sym, "direction": d, "against": ag, **oc})
    for b in buckets.values():
        b["sum_r"] = round(b["sum_r"], 2)
    return {"total": total, "by_against": buckets, "items": items[-30:],
            "note": "LIVE BETA · статистика накопичується; R брутто до комісій; результат сценарію ≠ особиста угода; висновків про прибутковість немає"}
