"""Неефективність ціни за SM Trader: FVG, Volume Imbalance (OHLC-проксі), Liquidity Void, Opening Gap, BPR + рівні всередині зони (0,25 / 0,5 / 0,75 / FF) і «повага».
«Тіла несуть інформацію, тіні наносять урон»: прокол тінню ≠ злам; зона зламана лише закриттям ТІЛА за її дальньою межею.
OHLC-VI — геометрія двох сусідніх тіл, а НЕ доказ реального дисбалансу bid/ask; Opening Gap для 24/7 крипто майже не трапляється (лічимо, без висновків)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from office2.smc import core as K
from office2.smc.core import Arr

FVG_MIN_ATR = 0.10
VOID_BAR_ATR = 0.9
VOID_MIN_BARS = 3
VOID_MIN_MOVE_ATR = 3.0
GAP_MIN_ATR = 0.10


def fill_state(b: Arr, zone: List[float], direction: str, start: int) -> Dict[str, Any]:
    """Як ціна відпрацювала зону після її формування (бари > start).
    direction='LONG' — бичача зона (ціна повертається згори вниз), 'SHORT' — дзеркально.
    wick_frac/body_frac: частка зони (0..1) від ближньої межі до дальньої, пройдена тінню / закриттям."""
    lo, hi = float(zone[0]), float(zone[1])
    size = hi - lo
    N = len(b["t"])
    if size <= 0 or start + 1 >= N:
        return {"state": "ACTIVE", "wick_frac": 0.0, "body_frac": 0.0, "touched_i": None, "levels": {"0.25": False, "0.5": False, "0.75": False, "FF": False}, "tests": 0}
    seg_l, seg_h, seg_c = b["l"][start + 1:], b["h"][start + 1:], b["c"][start + 1:]
    if direction == "LONG":
        wick = np.clip((hi - seg_l) / size, 0, 1.0 + 1e9)
        body = (hi - seg_c) / size
    else:
        wick = np.clip((seg_h - lo) / size, 0, 1.0 + 1e9)
        body = (seg_c - lo) / size
    wmax = float(max(0.0, wick.max()))
    bmax = float(max(0.0, body.max()))
    touched = np.flatnonzero(wick > 0)
    touched_i = int(start + 1 + touched[0]) if len(touched) else None
    # «тести» — окремі входи в зону (виходи між ними)
    inside = wick > 0
    tests = int(np.sum(inside & ~np.r_[False, inside[:-1]])) if len(inside) else 0
    lev = {"0.25": wmax >= 0.25, "0.5": wmax >= 0.5, "0.75": wmax >= 0.75, "FF": wmax >= 1.0}
    if touched_i is None:
        st = "ACTIVE"
    elif bmax > 1.0:
        st = "BROKEN"                  # тіло закрилось за дальньою межею: сила дисбалансу знята (інверсія)
    elif bmax > 0.5:
        st = "PARTIAL"                 # тіло закрилось за серединою зони (CE), але не наскрізь
    elif lev["FF"]:
        st = "FILLED_RESPECTED"        # тінь пройшла зону наскрізь, тіла не закріпились: зона ще «працює»
    else:
        st = "RESPECTED"
    return {"state": st, "wick_frac": round(min(wmax, 1.0), 3), "body_frac": round(min(bmax, 1.0), 3), "touched_i": touched_i, "levels": lev, "tests": tests}


def fvgs(b: Arr, a: np.ndarray, min_atr: float = FVG_MIN_ATR) -> List[Dict[str, Any]]:
    """FVG з трьох свічок (i-1, i, i+1): бичача — low[i+1] > high[i-1]; ведмежа — high[i+1] < low[i-1]. Відомий після закриття i+1."""
    out: List[Dict[str, Any]] = []
    h, l = b["h"], b["l"]
    for i in range(1, len(h) - 1):
        ia = K.atr_at(a, i + 1)
        if ia <= 0:
            continue
        if l[i + 1] > h[i - 1] and (l[i + 1] - h[i - 1]) >= min_atr * ia:
            z = [float(h[i - 1]), float(l[i + 1])]
            d = "LONG"
        elif h[i + 1] < l[i - 1] and (l[i - 1] - h[i + 1]) >= min_atr * ia:
            z = [float(h[i + 1]), float(l[i - 1])]
            d = "SHORT"
        else:
            continue
        fs = fill_state(b, z, d, i + 1)
        out.append({"kind": "FVG", "dir": d, "i": i, "conf": i + 1, "zone": z, "mid": (z[0] + z[1]) / 2.0, "size_atr": round((z[1] - z[0]) / ia, 3),
                    "mid_body_atr": round(K.body(b, i) / ia, 3), "levels_px": {"0.25": z[0] + 0.25 * (z[1] - z[0]), "0.5": z[0] + 0.5 * (z[1] - z[0]), "0.75": z[0] + 0.75 * (z[1] - z[0])}, **fs, "times": [float(b["t"][i - 1]), float(b["t"][i]), float(b["t"][i + 1])]})
    return out


def volume_imbalances(b: Arr, a: np.ndarray, min_atr: float = FVG_MIN_ATR) -> List[Dict[str, Any]]:
    """OHLC-VI: тіла двох сусідніх свічок одного напрямку не перекриваються, тіні перекриваються (немає FVG). Зона = проміжок між тілами."""
    out: List[Dict[str, Any]] = []
    o, c, h, l = b["o"], b["c"], b["h"], b["l"]
    for i in range(1, len(o)):
        ia = K.atr_at(a, i)
        if ia <= 0:
            continue
        pb_lo, pb_hi = min(o[i - 1], c[i - 1]), max(o[i - 1], c[i - 1])
        cb_lo, cb_hi = min(o[i], c[i]), max(o[i], c[i])
        if c[i] > o[i] and c[i - 1] > o[i - 1] and cb_lo > pb_hi and l[i] <= h[i - 1] and (cb_lo - pb_hi) >= min_atr * ia:
            z, d = [float(pb_hi), float(cb_lo)], "LONG"
        elif c[i] < o[i] and c[i - 1] < o[i - 1] and cb_hi < pb_lo and h[i] >= l[i - 1] and (pb_lo - cb_hi) >= min_atr * ia:
            z, d = [float(cb_hi), float(pb_lo)], "SHORT"
        else:
            continue
        out.append({"kind": "VI", "dir": d, "i": i, "conf": i, "zone": z, "note": "OHLC-проксі; не доказ реального bid/ask-дисбалансу", **fill_state(b, z, d, i), "times": [float(b["t"][i - 1]), float(b["t"][i])]})
    return out


def liquidity_voids(b: Arr, a: np.ndarray) -> List[Dict[str, Any]]:
    """Void: ≥3 імпульсні свічки одного напрямку підряд (діапазон ≥ 0,9 ATR), чистий рух ≥ 3 ATR. Зона = від початку першої до кінця останньої свічки ноги."""
    out: List[Dict[str, Any]] = []
    o, c, h, l = b["o"], b["c"], b["h"], b["l"]
    N = len(o)
    i = 0
    while i < N:
        ia = K.atr_at(a, i)
        if ia <= 0 or (h[i] - l[i]) < VOID_BAR_ATR * ia or c[i] == o[i]:
            i += 1
            continue
        up = c[i] > o[i]
        j = i
        while j + 1 < N and ((c[j + 1] > o[j + 1]) == up) and (h[j + 1] - l[j + 1]) >= VOID_BAR_ATR * K.atr_at(a, j + 1) and c[j + 1] != o[j + 1]:
            j += 1
        if j - i + 1 >= VOID_MIN_BARS:
            move = (c[j] - o[i]) if up else (o[i] - c[j])
            if move >= VOID_MIN_MOVE_ATR * K.atr_at(a, j):
                z = [float(l[i] if up else l[j]), float(h[j] if up else h[i])]
                out.append({"kind": "VOID", "dir": "LONG" if up else "SHORT", "i": i, "conf": j, "zone": z, "bars": j - i + 1, "move_atr": round(move / K.atr_at(a, j), 2), **fill_state(b, z, "LONG" if up else "SHORT", j), "times": [float(b["t"][i]), float(b["t"][j])]})
        i = j + 1
    return out


def opening_gaps(b: Arr, a: np.ndarray, min_atr: float = GAP_MIN_ATR) -> List[Dict[str, Any]]:
    """Гепи між закриттям і відкриттям сусідніх барів. Для 24/7 крипто фактично відсутні; лічимо для повноти (схеми: акції/індекси)."""
    out = []
    for i in range(1, len(b["o"])):
        ia = K.atr_at(a, i)
        d = float(b["o"][i] - b["c"][i - 1])
        if ia > 0 and abs(d) >= min_atr * ia:
            z = sorted([float(b["c"][i - 1]), float(b["o"][i])])
            dr = "LONG" if d > 0 else "SHORT"
            out.append({"kind": "GAP", "dir": dr, "i": i, "conf": i, "zone": z, **fill_state(b, z, dr, i), "times": [float(b["t"][i - 1]), float(b["t"][i])]})
    return out


def bprs(fv: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """BPR: перекриття двох протилежних FVG (схема: спочатку бичача, потім ведмежа, що перекриває її). Зона = перетин."""
    out = []
    for k, f2 in enumerate(fv):
        for f1 in fv[:k]:
            if f1["dir"] == f2["dir"] or f2["conf"] <= f1["conf"]:
                continue
            lo, hi = max(f1["zone"][0], f2["zone"][0]), min(f1["zone"][1], f2["zone"][1])
            if hi > lo:
                out.append({"kind": "BPR", "dir": f2["dir"], "i": f1["i"], "conf": f2["conf"], "zone": [float(lo), float(hi)], "parts": [f1["i"], f2["i"]], "times": f1["times"] + f2["times"]})
    return out


def respected(f: Dict[str, Any]) -> bool:
    """Уважена зона: торкання без закріплення тілом за серединою/дальньою межею."""
    return f["state"] in ("ACTIVE", "RESPECTED", "FILLED_RESPECTED")
