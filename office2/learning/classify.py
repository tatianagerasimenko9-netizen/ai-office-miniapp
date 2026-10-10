"""Класифікатор повторюваних причин збитків. Правила — ОБ'ЄКТИВНІ ВИЗНАЧЕННЯ за наявними полями (не підігнані під результат).
Коди, які неможливо оцінити без свічок/контексту, повертаються в `not_evaluable` з причиною, а не вгадуються.
Якщо жоден код не спрацював для SL — `UNDETERMINED` («причина не встановлена»)."""
from __future__ import annotations

from typing import Any, Dict, List

LAG_S = 120                 # верхня межа типової затримки доставки (див. аудит: 40–120 с)
COST_HEAVY_R = 0.25         # витрати кола ≥ чверті ризику
WEAK_STRENGTH = 1
STALE_SL_S = 60             # SL протягом хвилини після ENTRY → вхід був уже непридатний
DUP_WINDOW_S = 6 * 3600
LIFECYCLE_S = 48 * 3600

NOT_EVALUABLE = {
    "EARLY_ENTRY": "потрібні свічки M1/M5 і стан підтвердження на момент входу",
    "LATE_ENTRY": "chase_r зберігається лише для старого kind=SWEEP_RECLAIM; для SWEEP_SEQ завжди 0",
    "NO_PULLBACK": "потрібні свічки: чи був ретест зони до входу",
    "NO_SWEEP": "kind=SWEEP_* за означенням має sweep; контрольної групи без sweep серед доставлених немає",
    "FALSE_BREAKOUT": "потрібні свічки навколо рівня",
    "STALE_LEVEL": "немає віку/кількості тестів рівня у знімку",
    "TIGHT_SL": "потрібні ATR M1 і шум M1 (свічки Binance)",
    "BAD_SL_LOCATION": "потрібні swing-и й зони ліквідності на момент входу",
    "BTC_CONFLICT": "BTC-контекст у знімку не зберігається у вигляді, придатному для групування",
    "NEWS_RISK": "календар новин не збережено поруч із сигналом",
    "VOLATILITY_SPIKE": "потрібні ATR-ряди та свічки",
    "LIQUIDITY_TRAP": "потрібні свічки: повернення за рівень після проколу",
}


def flags(t: Dict[str, Any], all_trades: List[Dict[str, Any]] = ()) -> List[str]:
    out: List[str] = []
    if t.get("lag_s") is not None and t["lag_s"] > LAG_S:
        out.append("DELIVERY_LAG")
    if t.get("first") == "SL" and t.get("sl_after_entry_s") is not None and t["sl_after_entry_s"] <= STALE_SL_S:
        out.append("STALE_AT_DELIVERY")
    if t.get("cost_r") is not None and t["cost_r"] >= COST_HEAVY_R:
        out.append("COST_HEAVY")
    if t.get("r1") is not None and t.get("cost_r") is not None and (t["r1"] - t["cost_r"]) < 1.0:
        out.append("LOW_RR")
    if t.get("align_against") is not None and t.get("align_for") is not None and t["align_against"] > t["align_for"]:
        out.append("HTF_CONFLICT")
    try:
        if t.get("level_strength") is not None and int(t["level_strength"]) <= WEAK_STRENGTH:
            out.append("WEAK_LEVEL")
    except (TypeError, ValueError):
        pass
    if t.get("session") in ("PRE_LONDON", "PRE_NEW_YORK"):
        out.append("PRE_SESSION")
    c = t.get("created_ts")
    if c:
        for o in all_trades:
            if o is t or o["symbol"] != t["symbol"] or not o.get("created_ts"):
                continue
            end = min(o["milestones"].get(k, 1e18) for k in ("SL", "TP3")) if o.get("milestones") else 1e18
            end = min(end, o["created_ts"] + LIFECYCLE_S)
            if o["direction"] != t["direction"] and o["created_ts"] < c < end:
                out.append("OPPOSITE_EXPOSURE")
                break
        for o in all_trades:
            if o is t or o["symbol"] != t["symbol"] or o["direction"] != t["direction"] or not o.get("created_ts"):
                continue
            if o["created_ts"] < c and c - o["created_ts"] <= DUP_WINDOW_S and o.get("level_kind") == t.get("level_kind"):
                out.append("DUPLICATE_THESIS")
                break
    return out


def classify(t: Dict[str, Any], all_trades: List[Dict[str, Any]] = ()) -> Dict[str, Any]:
    f = flags(t, all_trades)
    res = {"id": t["id"], "flags": f, "not_evaluable": sorted(NOT_EVALUABLE)}
    if t.get("first") == "SL" and not f:
        res["flags"] = ["UNDETERMINED"]
    return res
