"""LIVE BETA: що накопичено по сценаріях Office2 (без заяв про прибутковість). Рахується з frozen-знімка і lifecycle-подій у БД, без look-ahead.

Результат сценарію ≠ особиста угода власниці. R — брутто, до комісій: SL після входу = −1 R; досягнутий TPn = R цього рівня з тези (позиція до рівня).
Розріз за кількістю факторів ПРОТИ (0 / 1 / 2+) — для пізнішого аналізу; жодного блокування за ним немає.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from office2.webview import _rows, parent_id


def _ms(db: str, sid: str) -> List[Dict[str, Any]]:
    out = []
    for (pj,) in _rows(db, "SELECT payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id = ? ORDER BY id ASC", (sid,)):
        try:
            out.append(json.loads(pj))
        except ValueError:
            pass
    return out


def scenario_outcome(snap: Dict[str, Any], created_ts: float, miles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Модельний підсумок сценарію за фактичними віхами (вхід/TP1-3/SL/строк). Правила виходу в системі НЕ визначено, тому реалізованого PnL тут немає:
    лише факти — що було першим (TP чи SL), яка найдальша ціль досягнута і її R за початковим ризиком (потенціал при утриманні, не прибуток)."""
    th = snap.get("thesis") or {}
    tg = th.get("targets") or []
    lv = {m.get("level"): m for m in miles}
    tt = lambda k: float(lv[k].get("touched_ts") or 0)    # noqa: E731
    entry = lv.get("ENTRY")
    reached = [i for i in (1, 2, 3) if f"TP{i}" in lv]
    first = None
    if "SL" in lv and (not reached or tt("SL") <= tt(f"TP{reached[0]}")):
        first = "SL"
    elif reached:
        first = "TP"
    top = max(reached) if reached else 0
    if "TP3" in lv:
        state = "TP3"
    elif "SL" in lv and entry:
        state = "SL" if first == "SL" else f"TP{top}→SL"
    elif "EXPIRED" in lv and not entry:
        state = "EXPIRED"
    elif reached:
        state = f"TP{top}"                  # проміжний етап: сценарій триває до TP3 або SL
    elif entry:
        state = "ACTIVE"
    else:
        state = "WAITING_ENTRY"
    final = state in ("TP3", "SL", "EXPIRED", "TP1→SL", "TP2→SL")
    max_r = float(tg[top - 1]["r"]) if top and len(tg) >= top and tg[top - 1].get("r") is not None else None
    last_ts = max([float(m.get("touched_ts") or 0) for m in miles] or [0.0])
    return {"state": state, "final": final, "first": first, "max_tp": top, "max_r": max_r, "entry_touched_ts": entry.get("touched_ts") if entry else None,
            "time_to_entry_s": (float(entry["touched_ts"]) - created_ts) if entry and entry.get("touched_ts") else None, "finished_ts": last_ts if final else None,
            "order": [m.get("level") for m in sorted(miles, key=lambda m: float(m.get("touched_ts") or 0))]}


def _median(xs: List[float]) -> Any:
    xs = sorted(xs)
    return None if not xs else round((xs[len(xs) // 2] + xs[(len(xs) - 1) // 2]) / 2.0, 2)


def collect(db: str) -> Dict[str, Any]:
    """Унікальні сценарії (за батьківським scenario id, не за повідомленнями Telegram і не за циклами), окремо за версією Brain."""
    rows = _rows(db, "SELECT scenario_id, symbol, direction, created_ts, status, snapshot_json FROM office2_live_signal ORDER BY created_ts ASC")
    total = {"ready": 0, "delivered": 0, "not_sent": 0, "entered": 0, "tp1_first": 0, "sl_first": 0, "tp3": 0, "expired": 0, "unresolved": 0}
    by_brain: Dict[str, Dict[str, Any]] = {}
    items = []
    seen = set()
    maxr: Dict[str, List[float]] = {}
    for sid, sym, d, ct, status, sj in rows:
        parent = parent_id(sid)
        if parent in seen:
            continue
        seen.add(parent)
        snap = json.loads(sj or "{}")
        total["ready"] += 1
        if status != "DELIVERED":
            total["not_sent"] += 1
            continue
        total["delivered"] += 1
        oc = scenario_outcome(snap, float(ct), _ms(db, sid))
        bv = str(snap.get("version_id") or snap.get("brain") or "unknown")   # версії Brain не змішуються
        bb = by_brain.setdefault(bv, {"delivered": 0, "entered": 0, "tp1_first": 0, "sl_first": 0, "tp3": 0, "expired": 0, "unresolved": 0, "median_max_r": None})
        bb["delivered"] += 1
        for tgt in (total, bb):
            if oc["entry_touched_ts"]:
                tgt["entered"] += 1
            if oc["first"] == "TP":
                tgt["tp1_first"] += 1
            if oc["first"] == "SL":
                tgt["sl_first"] += 1
            if oc["state"] == "TP3":
                tgt["tp3"] += 1
            if oc["state"] == "EXPIRED":
                tgt["expired"] += 1
            if not oc["final"]:
                tgt["unresolved"] += 1
        if oc["max_r"] is not None:
            maxr.setdefault(bv, []).append(oc["max_r"])
        items.append({"id": sid, "symbol": sym, "direction": d, "brain": bv, **oc})
    for bv, b in by_brain.items():
        b["median_max_r"] = _median(maxr.get(bv, []))
    return {"total": total, "by_brain": by_brain, "items": items[-30:],
            "note": "LIVE BETA · унікальні сценарії; правила виходу в системі не визначено, тому реалізованого PnL і суми R немає. «Макс. R» — найдальша досягнута ціль за початковим ризиком "
                    "(потенціал при утриманні, не прибуток). Результат сценарію ≠ особиста угода"}
