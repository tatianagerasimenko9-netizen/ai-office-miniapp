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


def _pct(xs: List[float], q: float) -> Any:
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(len(xs) - 1, int(k) + 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


LATENCY_FIELDS = ("bar_to_sent_ms", "decision_to_sent_ms", "wake_ms", "bar_wait_ms", "fetch_ms", "brain_ms", "queue_ms", "chart_ms", "late_check_ms", "render_ms", "send_ms")
TARGET_DECISION_TO_SENT_MS = 10_000      # ціль: рішення Brain → підтвердження Telegram
TARGET_BAR_TO_SENT_MS = 30_000           # ціль: закриття M15 → Telegram (якщо дані доступні)


def latency(db: str, days: float = 14.0, now: Any = None) -> Dict[str, Any]:
    """Фактична затримка READY за записами доставки (мс): p50/p95/max по етапах, частка в межах цілей, кількість відсічених/помилок. Лише факти з БД."""
    import time as _t

    t = _t.time() if now is None else float(now)
    rows = _rows(db, "SELECT payload_json FROM office_events WHERE event_type = 'OFFICE2_READY_SENT' AND ts_utc >= ? ORDER BY id ASC", (__import__("datetime").datetime.fromtimestamp(t - days * 86400, tz=__import__("datetime").timezone.utc).isoformat(),))
    series: Dict[str, List[float]] = {k: [] for k in LATENCY_FIELDS}
    n_new = n_old = 0
    for (pj,) in rows:
        try:
            tm = (json.loads(pj) or {}).get("timing") or {}
        except ValueError:
            continue
        if tm.get("bar_to_sent_ms") is not None or tm.get("send_ms") is not None:
            n_new += 1
            for k in LATENCY_FIELDS:
                if isinstance(tm.get(k), (int, float)):
                    series[k].append(float(tm[k]))
        elif tm.get("emit_to_sent_s") is not None:
            n_old += 1                                   # старий формат (секунди, без хронології від закриття бару)
            series["decision_to_sent_ms"].append(float(tm["emit_to_sent_s"]) * 1000)
            if tm.get("send_s") is not None:
                series["send_ms"].append(float(tm["send_s"]) * 1000)
            if tm.get("pickup_s") is not None:
                series["queue_ms"].append(float(tm["pickup_s"]) * 1000)
    out_s = {k: {"n": len(v), "p50": _pct(v, 0.5), "p95": _pct(v, 0.95), "max": (round(max(v), 1) if v else None)} for k, v in series.items() if v}
    d2s, b2s = series["decision_to_sent_ms"], series["bar_to_sent_ms"]
    sup = _rows(db, "SELECT last_error FROM office2_live_signal WHERE status = 'SUPPRESSED' AND created_ts >= ?", (t - days * 86400,))
    reasons: Dict[str, int] = {}
    for (e,) in sup:
        key = str(e or "").split(":", 1)[0].strip().upper()[:12] or "інше"
        reasons[key if key in ("STALE", "MISSED", "INVALIDATED") else "інше"] = reasons.get(key if key in ("STALE", "MISSED", "INVALIDATED") else "інше", 0) + 1
    return {"days": days, "delivered_n": n_new + n_old, "new_format_n": n_new, "stages": out_s,
            "targets": {"decision_to_sent_ms": TARGET_DECISION_TO_SENT_MS, "bar_to_sent_ms": TARGET_BAR_TO_SENT_MS},
            "within_target": {"decision_to_sent": (sum(1 for x in d2s if x <= TARGET_DECISION_TO_SENT_MS), len(d2s)), "bar_to_sent": (sum(1 for x in b2s if x <= TARGET_BAR_TO_SENT_MS), len(b2s))},
            "suppressed": reasons, "late_notes": None}


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
    try:
        from office2.smc import shadow as _SMC

        smc_stats = _SMC.shadow_stats(db)
    except Exception:  # noqa: BLE001
        smc_stats = None
    return {"total": total, "by_brain": by_brain, "items": items[-30:], "latency": latency(db), "smc": smc_stats,
            "note": "LIVE BETA · унікальні сценарії; правила виходу в системі не визначено, тому реалізованого PnL і суми R немає. «Макс. R» — найдальша досягнута ціль за початковим ризиком "
                    "(потенціал при утриманні, не прибуток). Результат сценарію ≠ особиста угода"}
