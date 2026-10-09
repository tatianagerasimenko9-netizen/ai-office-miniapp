"""Моделі входу SM Trader як ПОДІЄВІ ГРАФИ (S26, схеми 39–40): Reversal і Continuation, окремо для LONG/SHORT (SHORT = дзеркало).
READY не може випливати зі збігу назв індикаторів: потрібна хронологічна послідовність подій з точними свічками.

REVERSAL (LONG):   [контекст HTF: рівень/POI] → RAID (прокол SSL з поверненням) → MS (MSS/BMS вгору) → POI (OB/FVG/BB у знижці) → ретрейс у POI → тригер M15 → SL за екстремумом raid → цілі.
CONTINUATION:      HTF-bias за напрямом → RAID (корекційний) → MS1 → відкат → MS2 (друге оновлення структури, «2 MS») → POI → ретрейс → тригер.
Без контексту HTF розворот проти старшої структури не береться (схема 39, праворуч: «точки опори вище, контексту для пошуку входу немає»)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2.smc import core as K
from office2.smc import pd as PD
from office2.smc.core import Arr

MAX_RAID_AGE = 96          # барів M15 від повернення з raid, поки сценарій актуальний (24 год)
MAX_MS_GAP = 40            # макс. бар від raid до MS
MIN_LEG_ATR = 2.0          # як у Brain v2.1 (порівнянність): нога зміщення ≥ 2 ATR
MAX_WAIT_BARS = 32         # як у Brain v2.1
MISS_R = 3.0               # як у Brain v2.1
DEEP = 0.90                # глибокий ретрейс ноги (інвалідація зони)
STAGES = {"REVERSAL": ["контекст HTF", "RAID", "MS (зсув структури)", "POI", "ретрейс у POI", "тригер M15", "SL/цілі"],
          "CONTINUATION": ["bias HTF", "RAID", "MS1", "MS2 (друге оновлення)", "POI", "ретрейс у POI", "тригер M15", "SL/цілі"]}


def _step(name: str, ok: Optional[bool], value: str = "", j: Optional[int] = None, t: Optional[float] = None, ordered: bool = True) -> Dict[str, Any]:
    return {"step": name, "ok": ok, "value": value, "j": j, "t": t, "ordered": ordered}


def _chron_ok(steps: List[Dict[str, Any]]) -> bool:
    """Хронологія: часові мітки кроків з відомим j не спадають (RAID ≤ MS ≤ POI ≤ ретрейс ≤ тригер)."""
    js = [s["j"] for s in steps if s.get("j") is not None and s.get("ok") and s.get("ordered", True)]
    return all(a <= b for a, b in zip(js, js[1:]))


def _first_ms(events: List[Dict[str, Any]], j0: int, j1: int, kinds=("MSS", "BMS", "CONFIRM")) -> Optional[Dict[str, Any]]:
    for e in events:
        if e["dir"] == "LONG" and e["kind"] in kinds and j0 <= e["j"] <= j1:
            return e
    return None


def _htf_context(v: Dict[str, Any], htf: Dict[str, Dict[str, Any]], sweep: Dict[str, Any]) -> Dict[str, Any]:
    """Контекст розвороту: рівень raid значущий (strength ≥ 2 / HTF / сесія) або екстремум raid потрапив у HTF POI (H1/H4 demand OB/FVG/BB, не зламаний)."""
    lvl = sweep["level"]
    strong = lvl.get("strength", 1) >= 2 or lvl.get("tf") in ("htf", "session")
    ext = sweep["extreme"]
    poi = []
    for tf, hv in htf.items():
        for z in hv.get("ob_demand", []) + hv.get("fvg", []) + hv.get("breaker", []):
            if z.get("dir", "LONG") != "LONG" or z.get("state") in ("INVALIDATED", "BROKEN"):
                continue
            lo, hi = z["zone"]
            if lo - 1e-12 <= ext <= hi + 1e-12 or (lo <= lvl["p"] <= hi):
                poi.append({"tf": tf, "kind": z["kind"], "zone": z["zone"]})
    return {"strong_level": bool(strong), "htf_poi": poi[:3], "ok": bool(strong or poi)}


def _bias(htf: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    h4 = (htf.get("h4") or {}).get("structure", {}).get("trend")
    h1 = (htf.get("h1") or {}).get("structure", {}).get("trend")
    t4 = (htf.get("h4") or {}).get("structure", {}).get("transition")
    up = h4 == "UP" or (h4 in ("RANGE", "UNKNOWN", None) and h1 == "UP") or (h4 == "TRANSITION" and (t4 or {}).get("to") == "UP")
    down = h4 == "DOWN" or (h4 in ("RANGE", "UNKNOWN", None) and h1 == "DOWN") or (h4 == "TRANSITION" and (t4 or {}).get("to") == "DOWN")
    return {"h4": h4, "h1": h1, "dir": "UP" if up and not down else "DOWN" if down and not up else "NEUTRAL"}


def _poi_zone(v: Dict[str, Any], b: Arr, j_from: int, j_to: int, lo: float, lo_i: int, hi: float) -> Tuple[Optional[List[float]], List[Dict[str, Any]], Dict[str, Any]]:
    """Зона входу = перетин POI (OB / FVG / BB, сформовані між raid і MS) зі «знижкою» ноги (від DEEP до EQ). Лише OTE без POI — не зона (OTE без тригера ≠ READY)."""
    dr = PD.dealing_range(lo, hi, lo_i, int(np.argmax(b["h"][j_to:]) + j_to), len(b["t"]) - 1)
    ote = PD.ote(dr, "LONG")
    leg = hi - lo
    band = [hi - DEEP * leg, dr["eq"]]
    pois = []
    for z in v["ob_demand"] + v["fvg"] + v["breaker"]:
        if z.get("dir", "LONG") != "LONG" or z.get("state") in ("INVALIDATED", "BROKEN"):
            continue
        if not (j_from - 2 <= z["conf"] <= j_to + 2):
            continue
        zl, zh = max(z["zone"][0], band[0]), min(z["zone"][1], band[1])
        if zh > zl:
            pois.append({"kind": z["kind"], "zone": [float(zl), float(zh)], "conf": z["conf"], "src": z["zone"], "state": z.get("state"), "tests": z.get("tests", 0)})
    if not pois:
        return None, [], {"dealing_range": dr, "ote": ote, "band": band}
    zl = min(p["zone"][0] for p in pois)
    zh = max(p["zone"][1] for p in pois)
    return [float(zl), float(zh)], pois, {"dealing_range": dr, "ote": ote, "band": band}


def evaluate(v: Dict[str, Any], b: Arr, htf: Dict[str, Dict[str, Any]], k: int, model: str, sweep: Dict[str, Any], sg: int = 1) -> Dict[str, Any]:
    """Вердикт однієї моделі для одного raid у view-координатах (LONG). Повертає dict зі станом і кроками; ціни — у координатах view."""
    a = v["atr"]
    ia = K.atr_at(a, k)

    def P(x: float) -> float:       # у тексті — реальні ціни (для SHORT view дзеркальний)
        return float(sg * x)

    events = v["structure"]["events"]
    steps: List[Dict[str, Any]] = []
    ctxh = _htf_context(v, htf, sweep)
    bias = _bias(htf)
    base: Dict[str, Any] = {"model": model, "dir": "LONG", "sweep": sweep, "bias": bias, "htf_context": ctxh, "state": "WAIT", "stage": 1, "steps": steps, "need": None, "zone": None,
                            "evidence_for": [], "evidence_against": [], "anchors": []}
    # --- 0. контекст
    if model == "REVERSAL":
        steps.append(_step("контекст HTF", ctxh["ok"], ("рівень " + sweep["level"]["kind"] + (f"; HTF POI {ctxh['htf_poi'][0]['tf']} {ctxh['htf_poi'][0]['kind']}" if ctxh["htf_poi"] else "")) if ctxh["ok"] else "рівень локальний і raid не в HTF POI"))
        counter = bias["dir"] == "DOWN"
        if counter and not ctxh["ok"]:
            return dict(base, state="NO_CONTEXT", stage=1, need={"text": "розворот проти старшої структури без HTF-контексту: потрібен raid HTF-рівня або HTF POI"},
                        reason="розворот проти старшої структури (H4 " + str(bias["h4"]) + ") без HTF-контексту (схема 39, праворуч)")
        base["evidence_against"] += ["розворот проти старшої структури, контекст HTF є"] if counter else []
        base["evidence_for"] += (["raid HTF-рівня " + sweep["level"]["kind"]] if ctxh["strong_level"] else []) + (["екстремум raid у HTF POI"] if ctxh["htf_poi"] else [])
    else:
        ok_b = bias["dir"] == "UP"
        steps.append(_step("bias HTF", ok_b, f"H4 {bias['h4']}, H1 {bias['h1']}"))
        if not ok_b:
            return dict(base, state="NO_CONTEXT", stage=1, need={"text": "continuation потребує bias HTF за напрямом (H4/H1 вгору)"}, reason="немає bias HTF за напрямом")
        base["evidence_for"].append(f"HTF bias вгору (H4 {bias['h4']}, H1 {bias['h1']})")
    # --- 1. RAID
    age = k - sweep["reclaim_j"]
    steps.append(_step("RAID", True, f"{sweep['level']['kind']} {P(sweep['level']['p']):.6g}: екстремум {P(sweep['extreme']):.6g}, клас {sweep['class']}", sweep["reclaim_j"], sweep["t"]))
    base["anchors"].append({"type": "RAID", "j": sweep["j"], "p": sweep["extreme"], "level": sweep["level"]["p"]})
    if age > MAX_RAID_AGE:
        return dict(base, state="EXPIRED", stage=2, reason=f"raid старший за {MAX_RAID_AGE} барів")
    if np.any(b["c"][sweep["reclaim_j"] + 1:k + 1] < sweep["extreme"]):
        return dict(base, state="INVALIDATED", stage=2, reason=f"закриття нижче екстремуму raid {P(sweep['extreme']):.6g}")
    # --- 2. MS (1 або 2)
    ms1 = _first_ms(events, sweep["j"], min(k, sweep["reclaim_j"] + MAX_MS_GAP))
    if ms1 is None:
        lh = [s for s in v["structure"]["swings_h"] if s["i"] < sweep["j"] and s["conf"] <= k]
        need_px = lh[-1]["p"] if lh else None
        return dict(base, state="WAIT", stage=2, need={"px": need_px, "text": f"MS: закриття M15 вище {P(need_px):.6g} (злам останнього lower high)" if need_px else "MS: злам структури вгору"},
                    reason="WAIT · RAID є, чекаємо зсув структури (MS)")
    steps.append(_step("MS" if model == "REVERSAL" else "MS1", True, f"{ms1['kind']} вгору: закриття вище {P(ms1['level']):.6g}" + (f", тіло {ms1['body_atr']:.2f} ATR" if ms1.get("body_atr") else ""), ms1["j"], float(b["t"][ms1["j"]])))
    base["anchors"].append({"type": ms1["kind"], "j": ms1["j"], "p": ms1["level"]})
    ms_last = ms1
    if model == "CONTINUATION":
        ms2 = None
        for e in events:
            if e["dir"] == "LONG" and e["kind"] in ("BMS", "CONFIRM", "MSS") and e["j"] > ms1["j"] and e["level"] > ms1["level"] - 1e-12 and e["j"] <= k:
                ms2 = e
                break
        if ms2 is None:
            peak = float(b["h"][ms1["j"]:k + 1].max())
            return dict(base, state="WAIT", stage=3, need={"px": peak, "text": f"MS2: закриття M15 вище {P(peak):.6g} (нове оновлення структури після відкату)"}, reason="WAIT · потрібен другий MS (continuation = 2 MS)")
        steps.append(_step("MS2 (друге оновлення)", True, f"{ms2['kind']}: закриття вище {P(ms2['level']):.6g}", ms2["j"], float(b["t"][ms2["j"]])))
        base["anchors"].append({"type": ms2["kind"], "j": ms2["j"], "p": ms2["level"]})
        ms_last = ms2
    # --- 3. нога і POI
    if model == "REVERSAL":
        lo, lo_i, j_from = float(sweep["extreme"]), int(sweep["extreme_i"]), sweep["j"]
    else:                                                   # continuation: нога = від вищого мінімуму перед MS2 (початок останньої ноги), а не від raid
        seg = b["l"][ms1["j"] + 1:ms_last["j"] + 1]
        lo_i = ms1["j"] + 1 + int(np.argmin(seg))
        lo, j_from = float(seg.min()), ms1["j"]
    hi = float(b["h"][ms_last["j"]:k + 1].max())
    leg_atr = (hi - lo) / ia if ia > 0 else 0.0
    if leg_atr < MIN_LEG_ATR:
        return dict(base, state="WAIT", stage=4, reason=f"WAIT · нога зміщення {leg_atr:.1f} ATR < {MIN_LEG_ATR:g}", need={"text": f"нога ≥ {MIN_LEG_ATR:g} ATR"})
    zone, pois, pdx = _poi_zone(v, b, j_from, ms_last["j"], lo, lo_i, hi)
    base["dealing_range"], base["ote"] = pdx["dealing_range"], pdx["ote"]
    base["leg"] = {"from": lo, "to": hi, "atr": round(leg_atr, 2)}
    if zone is None:
        steps.append(_step("POI", False, "між raid і MS не сформовано OB/FVG/BB у знижці ноги"))
        return dict(base, state="WAIT", stage=5, need={"text": "POI (OB/FVG/BB) у знижці ноги; лише OTE без POI — не вхід"}, reason="WAIT · немає POI у зоні знижки (OTE без POI ≠ вхід)")
    base["zone"], base["pois"] = zone, pois
    steps.append(_step("POI", True, "+".join(sorted({p['kind'] for p in pois})) + f" {P(zone[0]):.6g}–{P(zone[1]):.6g}", max(p["conf"] for p in pois), float(b["t"][max(p["conf"] for p in pois)]), ordered=False))   # POI формується в нозі між raid і ретрейсом: не в строгому ряду
    base["anchors"] += [{"type": p["kind"], "zone": p["zone"], "conf": p["conf"]} for p in pois]
    # --- 4. ретрейс
    px = float(b["c"][k])
    if px < pdx["band"][0] or np.any(b["c"][ms_last["j"]:k + 1] < max(lo, pdx["band"][0])):
        return dict(base, state="INVALIDATED", stage=5, reason=f"ретрейс глибший за {DEEP:.0%} ноги або закриття нижче екстремуму raid")
    poi_done = max([ms_last["j"]] + [p["conf"] for p in pois])                   # POI має бути повністю сформований ДО ретрейсу в нього
    touch = next((q for q in range(poi_done + 1, k + 1) if b["l"][q] <= zone[1]), None)
    bars_since = k - ms_last["j"]
    if touch is None:
        run = (px - zone[1]) / max(zone[1] - lo, 1e-12)
        if run > MISS_R or bars_since > MAX_WAIT_BARS:
            return dict(base, state="MISSED", stage=5, reason=f"ціна пішла без ретрейсу в POI ({run:.1f} R від зони, {bars_since} барів)")
        return dict(base, state="WAIT", stage=5, need={"px": zone[1], "text": f"ретрейс у POI {P(zone[0]):.6g}–{P(zone[1]):.6g}"}, reason="WAIT · чекаємо ретрейс у POI")
    steps.append(_step("ретрейс у POI", True, f"low {P(float(b['l'][touch])):.6g} у зоні {P(zone[0]):.6g}–{P(zone[1]):.6g}", touch, float(b["t"][touch])))
    # --- 5. тригер
    mid = (zone[0] + zone[1]) / 2.0
    trig = next((q for q in range(touch, k + 1) if b["c"][q] > b["o"][q] and b["c"][q] >= mid and b["l"][q] <= zone[1]), None)
    if trig is None:
        return dict(base, state="ARMED", stage=6, need={"px": mid, "text": f"бичаче закриття M15 вище {P(mid):.6g}"}, reason="ARMED · ціна в POI, чекаємо тригер M15")
    steps.append(_step("тригер M15", True, f"закриття {P(float(b['c'][trig])):.6g} ≥ середини POI {P(mid):.6g}", trig, float(b["t"][trig])))
    if trig != k:
        run = (px - float(b["c"][trig])) / max(float(b["c"][trig]) - lo, 1e-12)
        return dict(base, state="MISSED" if run > 0.5 else "TRIGGERED_EARLIER", stage=7, trigger_j=trig, reason=f"тригер був на барі {trig} (поточний {k}); не свіжий")
    base.update(trigger_j=trig, entry=px, extreme=lo)
    base["chronology_ok"] = _chron_ok(steps)
    if not base["chronology_ok"]:
        return dict(base, state="WAIT", stage=6, reason="порушено хронологію кроків моделі")
    return dict(base, state="CANDIDATE", stage=7, reason="повна послідовність подій; потрібні SL/цілі/ризик")


def to_real(res: Dict[str, Any], sg: int) -> Dict[str, Any]:
    """Дзеркальні ціни → реальні (для SHORT sg=-1). Кроки/тексти, що містять ціни, формуються вже з реальних значень у engine."""
    if sg > 0:
        res["dir_real"] = "LONG"
        return res
    r = dict(res)
    r["dir_real"] = "SHORT"
    for k in ("entry", "extreme"):
        if r.get(k) is not None:
            r[k] = -r[k]
    if r.get("zone"):
        r["zone"] = [-r["zone"][1], -r["zone"][0]]
    if r.get("leg"):
        r["leg"] = {"from": -r["leg"]["from"], "to": -r["leg"]["to"], "atr": r["leg"]["atr"]}
    if r.get("need") and r["need"].get("px") is not None:
        r["need"] = dict(r["need"], px=-r["need"]["px"])
    return r
