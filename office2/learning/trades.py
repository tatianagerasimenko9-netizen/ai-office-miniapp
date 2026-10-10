"""Нормалізований запис угоди з ПОХОДЖЕННЯМ даних. Нічого не вигадується: відсутнє поле = None, а в `missing` перелічено, чого бракує."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office2.learning import costs as C
from office2.learning.sessions import session_of

TERMINAL_FIRST = ("TP1", "SL")


def first_result(ms: List[List[Any]]) -> str:
    """NOFILL (немає ENTRY) | TP1 | SL (що першим) | OPEN. Порядок за часом milestone."""
    lv = {}
    for name, ts in ms or []:
        lv.setdefault(name, float(ts))
    if "ENTRY" not in lv:
        return "NOFILL"
    t1, sl = lv.get("TP1"), lv.get("SL")
    if t1 is not None and (sl is None or t1 <= sl):
        return "TP1"
    if sl is not None:
        return "SL"
    return "OPEN"


def from_office2(row: Dict[str, Any]) -> Dict[str, Any]:
    ms = row.get("milestones") or []
    lv = {}
    for name, ts in ms:
        lv.setdefault(name, float(ts))
    created, delivered = row.get("created_ts"), row.get("delivered_ts")
    sess = session_of(created) if created else {}
    miss = [k for k in ("r1", "stop_pct", "risk_atr15", "align_against") if row.get(k) is None]
    entry_ts = lv.get("ENTRY")
    sl_ts = lv.get("SL")
    return {
        "id": row["sid"], "source": "office2_live_signal+SCENARIO_MILESTONE", "engine": "office2",
        "symbol": row["symbol"], "direction": row["direction"], "kind": row.get("kind"),
        "created_ts": created, "delivered_ts": delivered, "entry_ts": entry_ts,
        "lag_s": (delivered - created) if created and delivered else None,
        "stop_pct": row.get("stop_pct"), "risk_atr15": row.get("risk_atr15"),
        "r1": row.get("r1"), "r2": row.get("r2"), "r3": row.get("r3"),
        "cost_r": C.cost_r(row.get("stop_pct")),
        "level_kind": row.get("level_kind"), "level_strength": row.get("level_strength"),
        "align_against": row.get("align_against"), "align_for": row.get("align_for"),
        "milestones": {k: v for k, v in lv.items()},
        "first": first_result(ms),
        "sl_after_entry_s": (sl_ts - entry_ts) if sl_ts and entry_ts else None,
        "eventually_tp1": "TP1" in lv, "eventually_sl": "SL" in lv, "eventually_tp2": "TP2" in lv, "eventually_tp3": "TP3" in lv,
        **sess, "missing": miss,
    }


def from_old_lev(plan: Dict[str, Any], res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Старий Лев: SIGNAL_PLAN + SIGNAL_RESULT. Це ІНШИЙ рушій (H1, TP-цілі за рівнями), тому engine='old_lev'; не змішувати з Office2.
    outcome: STOP → SL; TP1/TP2/TP3 → TP1-first (за моделлю A; глибше не зараховуємо); OPEN_TIMEOUT/NOT_FILLED → не розв'язано."""
    try:
        entry, sl, tp1 = float(plan["entry"]), float(plan["sl"]), float(plan["tp1"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(entry - sl)
    if entry <= 0 or risk <= 0:
        return None
    stop_pct = risk / entry * 100
    oc = res.get("outcome")
    if not res.get("filled") or oc in ("NOT_FILLED", "OPEN_TIMEOUT", None):
        first = "NOFILL" if not res.get("filled") else "OPEN"
    elif oc == "STOP":
        first = "SL"
    elif oc in ("TP1", "TP2", "TP3"):
        first = "TP1"
    else:
        first = "OPEN"
    ts = plan.get("confirmed_ts")
    sess = session_of(float(ts)) if ts else {}
    return {"id": plan["scenario_id"], "source": "SIGNAL_PLAN+SIGNAL_RESULT", "engine": "old_lev", "delivered_to_user": not bool(res.get("rejected")),
            "symbol": plan["symbol"], "direction": plan["direction"], "kind": plan.get("tf"), "created_ts": ts, "delivered_ts": None, "entry_ts": None, "lag_s": None,
            "stop_pct": stop_pct, "risk_atr15": None, "r1": abs(tp1 - entry) / risk, "r2": None, "r3": None, "cost_r": C.cost_r(stop_pct),
            "level_kind": None, "level_strength": None, "align_against": None, "align_for": None, "milestones": {}, "first": first,
            "sl_after_entry_s": res.get("time_to_result_sec") if first == "SL" else None,
            "eventually_tp1": first == "TP1", "eventually_sl": first == "SL", "eventually_tp2": oc in ("TP2", "TP3"), "eventually_tp3": oc == "TP3",
            "mfe_pct": res.get("mfe_pct"), "mae_pct": res.get("mae_pct"), **sess, "missing": ["align", "level_strength", "lag"]}
