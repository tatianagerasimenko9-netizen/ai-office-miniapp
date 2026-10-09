"""Інваріанти детекторів SMC на ДОВІЛЬНИХ свічках (синтетика або реальні OHLCV): кожен знайдений об'єкт відповідає власному визначенню з методички, дзеркало симетричне, майбутнє не впливає.
Це перевірка КОРЕКТНОСТІ за визначенням на реальних даних, а не доказ корисності для рішень."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from office2.smc import core as K
from office2.smc import view as V
from office2.smc.core import Arr


def check_view(b: Arr, max_report: int = 20) -> Dict[str, Any]:
    v = V.analyze_view(b)
    st = v["structure"]
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    N = len(c)
    bad: List[str] = []
    seen: Dict[str, int] = {}

    def need(ok: bool, msg: str) -> None:
        seen["checks"] = seen.get("checks", 0) + 1
        if not ok and len(bad) < max_report:
            bad.append(msg)

    for s in st["swings_h"]:
        i = s["i"]
        need(h[i] > h[i - 1] and h[i] > h[i + 1] and s["p"] == h[i] and s["conf"] == i + 1, f"swing high {i}")
    for s in st["swings_l"]:
        i = s["i"]
        need(l[i] < l[i - 1] and l[i] < l[i + 1] and s["p"] == l[i] and s["conf"] == i + 1, f"swing low {i}")
    last_bms, last_mss = -1, -1
    for e in st["events"]:
        seen[e["kind"]] = seen.get(e["kind"], 0) + 1
        j = e["j"]
        if e["kind"] in ("BMS", "MSS", "CONFIRM"):
            need((c[j] > e["level"]) if e["dir"] == "LONG" else (c[j] < e["level"]), f"{e['kind']} {j}: закриття не за рівнем")
        if e["kind"] == "BMS":
            last_bms = j
        if e["kind"] == "MSS":
            need(last_bms >= 0 and j > last_bms, f"MSS {j} без попереднього BMS")
            last_mss = j
        if e["kind"] == "CONFIRM":
            need(last_mss >= 0 and j > last_mss, f"CONFIRM {j} без MSS")
    for f in v["fvg"]:
        i = f["i"]
        z = f["zone"]
        if f["dir"] == "LONG":
            need(l[i + 1] > h[i - 1] and z == [float(h[i - 1]), float(l[i + 1])], f"FVG LONG {i}")
        else:
            need(h[i + 1] < l[i - 1] and z == [float(h[i + 1]), float(l[i - 1])], f"FVG SHORT {i}")
        seen["FVG"] = seen.get("FVG", 0) + 1
    for ob in v["ob_demand"]:
        i, k = ob["i"], ob["conf"]
        need(c[i] < o[i] and c[k] > h[i] and l[i] <= ob["zone"][0] and ob["zone"][1] <= h[i] and abs(ob["mt"] - (o[i] + c[i]) / 2) < 1e-9, f"OB demand {i}")
        inv = bool(np.any(c[k + 1:] < ob["mt"]))
        need(inv == (ob["state"] == "INVALIDATED"), f"OB state {i}")
        seen["OB"] = seen.get("OB", 0) + 1
    for s in v["sweeps"]:
        j, r = s["j"], s["reclaim_j"]
        if s["dir"] == "LONG":
            need(l[s["extreme_i"]] < s["level"]["p"] and c[r] >= s["level"]["p"], f"sweep LONG {j}")      # закриття РІВНО на рівні = повернення (злам вимагає суворого закриття за рівнем; на реальних тікових цінах рівність трапляється)
        else:
            need(h[s["extreme_i"]] > s["level"]["p"] and c[r] <= s["level"]["p"], f"sweep SHORT {j}")
        need(s["class"] != "SFP" or r == j, f"SFP {j} не на тому ж барі")
        seen["SWEEP"] = seen.get("SWEEP", 0) + 1
    for lv in v["levels"]:
        hist = lv["history"]
        from office2.smc.liquidity import ALLOWED

        need(all(b2 in ALLOWED[a] for (a, _), (b2, _) in zip(hist, hist[1:])), f"перехід стану рівня {lv['kind']}")
    for k_ in ("breaker", "rjb", "stb", "sc"):
        for x in v[k_]:
            need(x["zone"][1] >= x["zone"][0], f"{k_} зона")
            seen[k_.upper()] = seen.get(k_.upper(), 0) + 1
    return {"violations": bad, "seen": seen}


def check_no_lookahead(b: Arr, cuts: Optional[List[int]] = None) -> Dict[str, Any]:
    N = len(b["t"])
    cuts = cuts or [int(N * q) for q in (0.45, 0.6, 0.75, 0.9)]
    full = V.analyze_view(b)
    bad: List[str] = []
    for cut in cuts:
        part = V.analyze_view({k: x[:cut] for k, x in b.items()})
        ef = [(e["kind"], e["j"], round(e["level"], 9)) for e in full["structure"]["events"] if e["j"] < cut]
        ep = [(e["kind"], e["j"], round(e["level"], 9)) for e in part["structure"]["events"]]
        if ef != ep:
            bad.append(f"структура cut={cut}")
        sf = sorted((s["j"], s["reclaim_j"], s["class"]) for s in full["sweeps"] if s["reclaim_j"] < cut)
        sp = sorted((s["j"], s["reclaim_j"], s["class"]) for s in part["sweeps"])
        if [x for x in sf if x in sp] != sf:
            bad.append(f"sweep cut={cut}")
        ff = [(f["i"], tuple(f["zone"])) for f in full["fvg"] if f["conf"] < cut]
        fp = [(f["i"], tuple(f["zone"])) for f in part["fvg"]]
        if ff != fp:
            bad.append(f"fvg cut={cut}")
    return {"violations": bad, "cuts": cuts}


def check_mirror(b: Arr) -> Dict[str, Any]:
    v, m = V.analyze_view(b), V.analyze_view(K.mirror(b))
    ok = [(e["kind"], e["j"]) for e in v["structure"]["events"]] == [(e["kind"], e["j"]) for e in m["structure"]["events"]] and len(v["sweeps"]) == len(m["sweeps"])
    return {"violations": [] if ok else ["дзеркальна симетрія порушена"]}


def run(m15: Arr, max_report: int = 20) -> Dict[str, Any]:
    """Повний набір для одного ряду M15 (закриті бари)."""
    a, b_, c_ = check_view(m15, max_report), check_no_lookahead(m15), check_mirror(m15)
    return {"bars": int(len(m15["t"])), "checks": a["seen"].get("checks", 0), "violations": a["violations"] + b_["violations"] + c_["violations"], "objects": {k: v for k, v in a["seen"].items() if k != "checks"}}
