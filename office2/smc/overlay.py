"""Overlay для графіка: що саме побачив SMC-аналіз і в якому порядку. Усі елементи прив'язані до часу відкриття конкретних свічок (lineage), ціни — реальні.
Формат малий і самодостатній (зберігається в знімку READY, незмінний); малювання — на клієнті (lightweight-charts: лінії, маркери)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office2.smc.core import Arr

LABEL = {"RAID": "RAID", "MS": "MS", "MS1": "MS1", "MS2 (друге оновлення)": "MS2", "POI": "POI", "ретрейс у POI": "ретрейс", "тригер M15": "тригер"}


def build(verdict: Optional[Dict[str, Any]], m15: Arr, events: Optional[List[Dict[str, Any]]] = None, max_events: int = 40) -> Optional[Dict[str, Any]]:
    """verdict — результат engine.analyze()['models'][dir][model] (реальні ціни). Повертає None, якщо вердикту немає."""
    if not verdict:
        return None
    N = len(m15["t"])
    T = lambda j: float(m15["t"][min(max(int(j), 0), N - 1)])   # noqa: E731
    d = verdict.get("dir_real") or verdict.get("dir")
    items: List[Dict[str, Any]] = []
    sw = verdict.get("sweep") or {}
    if sw:
        lv = sw.get("level") or {}
        items.append({"k": "level", "p": lv.get("p"), "t0": T(sw["j"]), "label": f"{lv.get('kind')} {sw.get('class')}", "role": "liquidity"})
        items.append({"k": "marker", "t": T(sw["reclaim_j"]), "p": sw.get("extreme"), "label": "RAID", "up": d == "LONG", "role": "raid"})
    for st in verdict.get("steps", []):
        if st.get("ok") and st.get("j") is not None and st["step"] in ("MS", "MS1", "MS2 (друге оновлення)", "тригер M15", "ретрейс у POI"):
            px = None
            for a in verdict.get("anchors", []):
                if a.get("type") in ("MSS", "BMS", "CONFIRM") and a.get("j") == st["j"]:
                    px = a.get("p")
            items.append({"k": "marker", "t": T(st["j"]), "p": px, "label": LABEL.get(st["step"], st["step"]), "up": d == "LONG", "role": "step"})
    for p in verdict.get("pois", []) or []:
        items.append({"k": "zone", "lo": p["zone"][0], "hi": p["zone"][1], "t0": T(p["conf"]), "t1": None, "label": p["kind"], "role": "poi"})
    z = verdict.get("zone")
    if z:
        t_first = min([T(p["conf"]) for p in (verdict.get("pois") or [])] or [None]) if verdict.get("pois") else None
        items.append({"k": "zone", "lo": z[0], "hi": z[1], "t0": t_first, "t1": None, "label": "вхід (POI)", "role": "entry_zone"})
    if verdict.get("entry") is not None:
        items.append({"k": "line", "p": verdict["entry"], "label": "READY (вхід)", "role": "entry"})
    if verdict.get("sl") is not None:
        items.append({"k": "line", "p": verdict["sl"], "label": "SL", "role": "sl"})
    for i, t in enumerate(verdict.get("targets", []) or []):
        items.append({"k": "line", "p": t["p"], "label": f"TP{i + 1} {t['kind']} ({t['r']:.1f}R)", "role": "tp"})
    ev_out = []
    for e in (events or [])[-max_events:]:
        ev_out.append({"id": e["event_id"], "kind": e["kind"], "dir": e["direction"], "t": e["candle_open_times"][-1], "zone": [e["zone_low"], e["zone_high"]] if e.get("zone_low") is not None else None,
                       "p": (e["anchor_price"] or [None])[0], "state": e["state"], "src": e["source_section_id"]})
    return {"v": 1, "dir": d, "model": verdict.get("model"), "state": verdict.get("state"), "reason": verdict.get("reason"), "items": items, "events": ev_out,
            "steps": [{"step": s["step"], "ok": s["ok"], "value": s["value"], "t": s.get("t")} for s in verdict.get("steps", [])]}
