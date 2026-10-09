"""SMC engine: analyze(ctx, now) → повний знімок SMC-аналізу символу на момент now БЕЗ lookahead (лише бари, закриті до now).
Нічого не пише в БД, не шле, не змінює READY: це shadow/overlay-шар. Рішення Brain v2.1 лишається джерелом істини, поки власниця не погодила вплив."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np

from office2 import brain as B
from office2 import brain2 as B2
from office2.smc import blocks as BL
from office2.smc import core as K
from office2.smc import flow as FL
from office2.smc import models as MD
from office2.smc import sessions as SS
from office2.smc import structure as ST
from office2.smc import view as V
from office2.smc.core import Arr

VERSION = "smc-engine-1"
WIDTH = {"m15": 900, "h1": 3600, "h4": 14400, "d1": 86400, "w1": 604800}
KEEP_BARS = 200                 # події старші за стільки M15-барів в знімок/overlay не потрапляють
STATE_RANK = {"READY": 9, "NO_TRADE": 8, "CANDIDATE": 8, "ARMED": 7, "WAIT": 6, "MISSED": 1, "TRIGGERED_EARLIER": 1, "INVALIDATED": 1, "EXPIRED": 1, "NO_CONTEXT": 1}   # неактивні стани рівні; між ними вирішує свіжість raid
SRC = {"BMS": "S09.3", "MSS": "S12", "CONFIRM": "S09.3", "MSS_FAILED": "S12", "CORRECTION_BREAK": "S12", "FVG": "S14", "VI": "S14.2", "VOID": "S14.2", "GAP": "S14.2", "BPR": "S14.2",
       "OB": "S18", "BB": "S19", "MB": "S20", "RJB": "S21", "SC": "S25", "STB": "S24", "BTS": "S24", "SWEEP": "S22", "SFP": "S23", "LEVEL": "S15", "RANGE": "S10.4", "DEVIATION": "S10.4", "EXPANSION": "S11"}


def _mir_arr(b: Optional[Arr]) -> Optional[Arr]:
    return None if b is None else K.mirror(b)


def _closed(ctx: Dict[str, Any], tf: str, now: float) -> Optional[Arr]:
    return K.closed_slice(ctx.get(tf), WIDTH[tf], now)


def _mir_level(x: Dict[str, Any]) -> Dict[str, Any]:
    y = dict(x)
    y["side"] = "low" if x["side"] == "high" else "high"
    y["p"] = -x["p"]
    return y


def _flip(x: Any, sg: int) -> Any:
    """Дзеркальні ціни/напрям → реальні для SHORT-view (sg=-1). Рекурсивно по відомих ключах."""
    if sg > 0:
        return x
    if isinstance(x, list):
        return [_flip(i, sg) for i in x]
    if not isinstance(x, dict):
        return x
    y: Dict[str, Any] = {}
    for k, v in x.items():
        if k in ("p", "level_p", "extreme", "level", "mt", "open", "mid", "close_back", "entry", "protected", "origin_extreme", "wick_low", "trigger", "sl", "to", "from") and isinstance(v, (int, float)):
            y[k] = -float(v)
        elif k == "zone" and isinstance(v, list) and len(v) == 2 and all(isinstance(q, (int, float)) for q in v):
            y[k] = [-float(v[1]), -float(v[0])]
        elif k in ("dir", "dir_real") and v in ("LONG", "SHORT"):
            y[k] = "SHORT" if v == "LONG" else "LONG"
        elif k == "side" and v in ("high", "low"):
            y[k] = "low" if v == "high" else "high"
        else:
            y[k] = _flip(v, sg)
    if "wick_low" in y:
        y["wick_high"] = y.pop("wick_low")
    return y


def _slim(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k not in ("history",)}


def _event(kind: str, tf: str, d: Dict[str, Any], b: Arr, j: int, symbol: str) -> Dict[str, Any]:
    z = d.get("zone")
    anchors = [float(d["level"])] if d.get("level") is not None and not isinstance(d.get("level"), dict) else ([float(d["extreme"])] if d.get("extreme") is not None else [])
    times = d.get("times") or [float(b["t"][min(max(j, 0), len(b["t"]) - 1)])]
    ev = K.Event(kind=kind, tf=tf, direction=d.get("dir") or "LONG", source=SRC.get(kind, "S?"), times=times, anchors=anchors, zone=z,
                 confirmed_at=float(b["t"][min(d.get("conf", j), len(b["t"]) - 1)] + WIDTH.get(tf, 900)) if d.get("conf", j) is not None else None, state=d.get("state", "ACTIVE"),
                 extra={k: v for k, v in d.items() if k not in ("zone", "times", "dir", "state", "history")}, symbol=symbol)
    return ev.to_dict()


def _best(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cands:
        return None
    return max(cands, key=lambda r: (STATE_RANK.get(r["state"], 0), r.get("stage", 0) if STATE_RANK.get(r["state"], 0) > 1 else 0, r.get("sweep", {}).get("reclaim_j", 0)))


def _finalize(res: Dict[str, Any], sg: int, bview: Arr, a_real: np.ndarray, k: int, real_levels: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """CANDIDATE → READY / NO_TRADE: SL (люфт Brain), ризик, шум ATR, цілі від РЕАЛЬНИХ рівнів (brain.targets_for), перешкоди. Пороги Brain не змінюються."""
    if res["state"] != "CANDIDATE":
        return res
    d = "LONG" if sg > 0 else "SHORT"
    entry = res["entry"]            # реальні (to_real уже застосовано)
    ext = res["extreme"]
    atr15 = K.atr_at(a_real, k)
    luft, luft_why = B2.level_luft(bview, float(res["sweep"]["level"]["p"]) if res["model"] == "REVERSAL" else None, atr15)      # той самий люфт, що й у Brain v2.1 (медіана проколів рівня), у view-координатах
    sl = ext - luft if d == "LONG" else ext + luft
    risk = abs(entry - sl)
    res["luft"], res["luft_basis"] = float(luft), luft_why
    res["sl"] = float(sl)
    if risk <= 0:
        return dict(res, state="NO_TRADE", reason="ціна вже за структурною інвалідацією")
    risk_pct = risk / abs(entry) * 100.0
    risk_atr = risk / atr15 if atr15 > 0 else None
    res["risk"], res["risk_pct"], res["risk_atr15"] = float(risk), float(risk_pct), (float(risk_atr) if risk_atr else None)
    if not (B.MIN_RISK_PCT <= risk_pct <= B.MAX_RISK_PCT):
        return dict(res, state="NO_TRADE", reason=f"структурний стоп {risk_pct:.2f}% поза допустимим {B.MIN_RISK_PCT}–{B.MAX_RISK_PCT}%")
    if risk_atr is not None and risk_atr < B.MIN_STOP_ATR15:
        return dict(res, state="NO_TRADE", reason=f"стоп {risk_atr:.2f} ATR(M15) < {B.MIN_STOP_ATR15:g}: інвалідація всередині шуму")
    if real_levels is None:
        return dict(res, state="CANDIDATE", reason="кандидат; цілі не обчислено (немає карти рівнів)")
    tg = B.targets_for(d, entry, risk, real_levels, near_r=0.0)
    res["targets"], res["obstacles_before_tp1"] = tg["targets"], tg["obstacles_before_tp1"]
    major = [o for o in tg["obstacles_before_tp1"] if o["kind"] in B.MAJOR_OBSTACLE_KINDS]
    if major:
        return dict(res, state="NO_TRADE", reason=f"до першої цілі {major[0]['kind']} {major[0]['p']:.6g} лише {major[0]['r']:.2f} R (< {B.MIN_TP1_R:g})")
    if not tg["targets"]:
        return dict(res, state="NO_TRADE", reason=f"немає реальної цілі ≥ {B.MIN_TP1_R} R")
    return dict(res, state="READY", reason="повна послідовність SMC-моделі: " + " → ".join(s["step"] for s in res["steps"] if s.get("ok")))


def analyze(ctx: Dict[str, Any], now: float, symbol: str = "", real_levels: Optional[List[Dict[str, Any]]] = None, with_events: bool = True) -> Dict[str, Any]:
    t0 = time.perf_counter()
    arr = {tf: _closed(ctx, tf, now) for tf in WIDTH}
    m15 = arr["m15"]
    if m15 is None or len(m15["t"]) < 60:
        return {"version": VERSION, "symbol": symbol, "now": now, "error": "недостатньо закритих барів M15", "data_health": {"m15_bars": 0 if m15 is None else len(m15["t"])}}
    k = len(m15["t"]) - 1
    a_real = K.atr_arr(m15, 14)
    sess_levels = SS.session_levels(m15, now)
    mn = ctx.get("mn")
    views: Dict[int, Dict[str, Any]] = {}
    for sg in (1, -1):
        f = (lambda x: x) if sg > 0 else _mir_arr
        htf_arr = {"d1": f(arr["d1"]), "w1": f(arr["w1"]), "mn": f(mn)}
        extra = [(_mir_level(x) if sg < 0 else x) for x in sess_levels]
        mv = V.analyze_view(f(m15), htf_arr, extra_levels=extra)
        hv = {tf: V.analyze_view(f(arr[tf])) for tf in ("h1", "h4") if arr[tf] is not None and len(arr[tf]["t"]) >= 30}
        views[sg] = {"v": mv, "htf": hv, "b": f(m15)}
    models: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {"LONG": {}, "SHORT": {}}
    for sg, dname in ((1, "LONG"), (-1, "SHORT")):
        vw = views[sg]
        for model in ("REVERSAL", "CONTINUATION"):
            cands = []
            for s in vw["v"]["sweeps"]:
                if s["dir"] != "LONG" or k - s["reclaim_j"] > MD.MAX_RAID_AGE:
                    continue
                r = MD.evaluate(vw["v"], vw["b"], vw["htf"], k, model, s, sg)
                r = MD.to_real(r, sg)
                r = _finalize(r, sg, vw["b"], a_real, k, real_levels)
                if sg < 0:
                    r["sweep"] = _flip(r["sweep"], sg)
                    for kk in ("pois", "anchors", "dealing_range", "ote"):
                        if kk in r:
                            r[kk] = _flip(r[kk], sg)
                cands.append(r)
            models[dname][model] = _best(cands)
    best = _best([m for d in models.values() for m in d.values() if m])
    out: Dict[str, Any] = {"version": VERSION, "detector_version": K.DETECTOR_VERSION, "symbol": symbol, "now": now, "k": k, "bar_open": float(m15["t"][k]), "price": float(m15["c"][k]),
                           "models": models, "best": ({"dir": best["dir_real"], "model": best["model"], "state": best["state"]} if best else None),
                           "structure": {tf: {"trend": (views[1]["htf"].get(tf) or {}).get("structure", {}).get("trend")} for tf in ("h1", "h4")}}
    out["structure"]["m15"] = {"trend": views[1]["v"]["structure"]["trend"], "bars_since_break": views[1]["v"]["structure"]["bars_since_break"], "range": views[1]["v"]["structure"].get("range")}
    out["sync"] = ST.tf_sync({"h4": {"trend": out["structure"]["h4"]["trend"]}, "h1": {"trend": out["structure"]["h1"]["trend"]}, "m15": views[1]["v"]["structure"]})
    out["order_flow"] = FL.order_flow(views[1]["v"]["structure"], views[1]["v"]["fvg"])
    out["sessions"] = SS.window_view(now)
    out["judas"] = SS.judas(m15, now)
    out["amd"] = SS.amd(m15, now)
    out["data_health"] = {"m15_bars": k + 1, "h1_bars": 0 if arr["h1"] is None else len(arr["h1"]["t"]), "h4_bars": 0 if arr["h4"] is None else len(arr["h4"]["t"]),
                          "lookahead": False, "closed_only": True, "flow_data": "proxy (OHLC); CVD/OI/DOM — окремі докази Brain"}
    if with_events:
        out["events"] = collect_events(views, m15, symbol, k)
    out["timing_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return out


def collect_events(views: Dict[int, Dict[str, Any]], m15: Arr, symbol: str, k: int) -> List[Dict[str, Any]]:
    """Серіалізовані події (схема Masterplan §3) у реальних цінах: структура/FVG/OB/ліквідність — з реального view; Breaker/RJB/SC/StB бичачі — з real, ведмежі — з дзеркала."""
    real, mir = views[1]["v"], views[-1]["v"]
    out: List[Dict[str, Any]] = []
    lo_j = k - KEEP_BARS

    def add(kind, items, tf="m15", sg=1):
        for d in items:
            j = d.get("conf", d.get("j", 0))
            if j < lo_j:
                continue
            x = _flip(d, sg)
            out.append(_event(kind, tf, x, m15, j, symbol))

    add_struct = [e for e in real["structure"]["events"]]
    for e in add_struct:
        if e["j"] >= lo_j:
            dd = {"dir": e["dir"], "conf": e["j"], "level": e["level"], "times": [float(m15["t"][e["level_i"]]), float(m15["t"][e["j"]])], "state": "CONFIRMED",
                  **{q: e[q] for q in ("protected", "protected_i", "body_atr", "initial", "reclaim") if q in e}}
            out.append(_event(e["kind"], "m15", dd, m15, e["j"], symbol))
    add("FVG", real["fvg"])
    add("VI", real["vi"])
    add("VOID", real["void"])
    add("BPR", real["bpr"])
    add("OB", real["ob_demand"] + real["ob_supply"])
    add("BB", [x for x in real["breaker"] if x["kind"] == "BB"]) 
    add("MB", [x for x in real["breaker"] if x["kind"] == "MB"])
    add("BB", [x for x in mir["breaker"] if x["kind"] == "BB"], sg=-1)
    add("MB", [x for x in mir["breaker"] if x["kind"] == "MB"], sg=-1)
    add("RJB", real["rjb"])
    add("RJB", mir["rjb"], sg=-1)
    add("SC", real["sc"])
    add("SC", mir["sc"], sg=-1)
    add("STB", real["stb"])
    add("STB", [dict(x, kind="BTS") for x in mir["stb"]], sg=-1)
    for s in real["sweeps"]:
        if s["reclaim_j"] >= lo_j:
            kind = "SFP" if s["class"] == "SFP" else "SWEEP"
            dd = {"dir": s["dir"], "conf": s["reclaim_j"], "extreme": s["extreme"], "level": s["level"]["p"], "times": [float(m15["t"][s["j"]]), float(m15["t"][s["reclaim_j"]])], "state": s["class"],
                  "level_kind": s["level"]["kind"], "excess_atr": s["excess_atr"], "prior_closes_beyond": s["prior_closes_beyond"]}
            out.append(_event(kind, "m15", dd, m15, s["reclaim_j"], symbol))
    out.sort(key=lambda e: (e.get("confirmed_at") or 0, e["event_id"]))
    return out
