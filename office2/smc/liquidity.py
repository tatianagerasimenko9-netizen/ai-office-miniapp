"""Ліквідність за SM Trader: пули (swing, EQH/EQL, межі range, PDH/PDL/PWH/PWL/PMH/PML, session H/L, трендова), життєвий цикл рівня і класифікація проколу.

Життєвий цикл: IDENTIFIED → APPROACHED → TOUCHED → SWEPT | ACCEPTED_BREAKOUT → RETESTED | INVALIDATED. Допустимі переходи — у ALLOWED (перевіряє тест).
Класи проколу (Masterplan §2.7): FRESH_RAID (прокол + повернення за ≤ reclaim_bars), SFP (прокол і закриття назад на тому ж барі), ACCEPTED_BREAKOUT (≥ accept_closes закриттів за рівнем),
LATE_SWEEP (рівень ВЖЕ був прийнятий раніше — «sweep» не свіжий; кейс ONDO 0,4882), WICK_ONLY (перевищення менше min_excess_atr — шум), PENDING (ще немає достатньо барів для класифікації).
Лише закриті бари; рівень відомий із бару conf (swing — i+1, добовий — після закриття доби)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2.smc import core as K
from office2.smc.core import Arr

ALLOWED = {
    "IDENTIFIED": {"APPROACHED", "TOUCHED", "SWEPT", "ACCEPTED_BREAKOUT"},
    "APPROACHED": {"TOUCHED", "SWEPT", "ACCEPTED_BREAKOUT"},
    "TOUCHED": {"SWEPT", "ACCEPTED_BREAKOUT"},
    "ACCEPTED_BREAKOUT": {"RETESTED", "INVALIDATED"},
    "SWEPT": set(), "RETESTED": {"INVALIDATED"}, "INVALIDATED": set(),
}
ACCEPT_CLOSES = 3
RECLAIM_BARS = 3
APPROACH_ATR = 1.0
TOUCH_TOL_ATR = 0.05
MIN_EXCESS_ATR = 0.10
PRIOR_LOOKBACK = 64


def swing_levels(b: Arr, hs: List[Dict[str, Any]], ls: List[Dict[str, Any]], a: np.ndarray, eq_tol_atr: float = 0.15) -> List[Dict[str, Any]]:
    """Swing-рівні + EQH/EQL (≥2 swing в межах eq_tol_atr·ATR; рівень = крайній з кластера)."""
    out: List[Dict[str, Any]] = []
    for side, arr in (("high", hs), ("low", ls)):
        for s in arr:
            out.append({"side": side, "p": s["p"], "kind": "SWING_H" if side == "high" else "SWING_L", "i": s["i"], "conf": s["conf"], "strength": 1, "tf": "m15"})
        # EQ-кластери (послідовно: кожен swing приєднується до попереднього, якщо в допуску)
        for k in range(1, len(arr)):
            s1, s0 = arr[k], arr[k - 1]
            tol = eq_tol_atr * K.atr_at(a, s1["conf"])
            if tol > 0 and abs(s1["p"] - s0["p"]) <= tol:
                p = max(s1["p"], s0["p"]) if side == "high" else min(s1["p"], s0["p"])
                out.append({"side": side, "p": float(p), "kind": "EQH" if side == "high" else "EQL", "i": s0["i"], "conf": s1["conf"], "strength": 2, "tf": "m15", "members": [s0["i"], s1["i"]]})
    return out


def htf_levels(b: Arr, d1: Optional[Arr], w1: Optional[Arr], mn: Optional[Arr]) -> List[Dict[str, Any]]:
    """PDH/PDL, PWH/PWL, PMH/PML — high/low ПОПЕРЕДНЬОГО закритого дня/тижня/місяця; відомі з першого M15-бару після закриття періоду. Лише закриті бари HTF."""
    out: List[Dict[str, Any]] = []
    t = b["t"]
    now = float(t[-1]) + 900
    for arr, width, hn, ln in ((d1, 86400, "PDH", "PDL"), (w1, 604800, "PWH", "PWL"), (mn, 0, "PMH", "PML")):
        if arr is None or len(arr["t"]) < 2:
            continue
        ends = arr["t"] + width if width else np.r_[arr["t"][1:], arr["t"][-1] + 31 * 86400]
        closed = np.flatnonzero(ends <= now)
        if len(closed) == 0:
            continue
        k = int(closed[-1])
        conf = int(np.searchsorted(t, float(ends[k]), side="left"))
        conf = min(max(conf, 0), len(t) - 1)
        out.append({"side": "high", "p": float(arr["h"][k]), "kind": hn, "i": k, "conf": conf, "strength": 3, "tf": "htf", "period_open": float(arr["t"][k])})
        out.append({"side": "low", "p": float(arr["l"][k]), "kind": ln, "i": k, "conf": conf, "strength": 3, "tf": "htf", "period_open": float(arr["t"][k])})
    return out


def range_levels(rg: Optional[Dict[str, Any]], conf: int) -> List[Dict[str, Any]]:
    if not rg:
        return []
    return [{"side": "high", "p": rg["high"], "kind": "RANGE_H", "i": rg["high_i"], "conf": conf, "strength": 2, "tf": "m15"},
            {"side": "low", "p": rg["low"], "kind": "RANGE_L", "i": rg["low_i"], "conf": conf, "strength": 2, "tf": "m15"}]


def trendline_levels(hs: List[Dict[str, Any]], ls: List[Dict[str, Any]], N: int) -> List[Dict[str, Any]]:
    """Ліквідність за трендовою (схема 15): лінія через два останні swing high (спадна) / low (висхідна), проєкція на останній бар. Наближення, strength=1."""
    out: List[Dict[str, Any]] = []
    for side, arr, falling in (("high", hs, True), ("low", ls, False)):
        if len(arr) < 2:
            continue
        s0, s1 = arr[-2], arr[-1]
        if (falling and s1["p"] < s0["p"]) or (not falling and s1["p"] > s0["p"]):
            slope = (s1["p"] - s0["p"]) / max(s1["i"] - s0["i"], 1)
            out.append({"side": side, "p": float(s1["p"] + slope * (N - 1 - s1["i"])), "kind": "TL_H" if side == "high" else "TL_L", "i": s1["i"], "conf": s1["conf"], "strength": 1, "tf": "m15", "approx": True})
    return out


def _view(b: Arr, side: str):
    return (b["h"], b["l"], b["c"], 1.0) if side == "high" else (-b["l"], -b["h"], -b["c"], -1.0)


def track(b: Arr, lv: Dict[str, Any], a: np.ndarray, accept_closes: int = ACCEPT_CLOSES, reclaim_bars: int = RECLAIM_BARS) -> Dict[str, Any]:
    """Життєвий цикл одного рівня від бару conf до кінця даних. Повертає копію рівня зі state, history, sweep/accepted/retest."""
    N = len(b["t"])
    H, L, C, sg = _view(b, lv["side"])
    p = sg * lv["p"]
    conf = int(lv["conf"])
    state = "IDENTIFIED"
    hist: List[Tuple[str, int]] = [("IDENTIFIED", conf)]
    sweep = accepted = retest = None
    pending = None

    def go(new: str, j: int) -> None:
        nonlocal state
        assert new in ALLOWED[state], (state, new)
        state = new
        hist.append((new, j))

    j = conf + 1
    while j < N:
        ia = K.atr_at(a, j)
        tol = TOUCH_TOL_ATR * ia
        if state in ("IDENTIFIED", "APPROACHED", "TOUCHED"):
            if H[j] <= p + tol:
                if H[j] >= p - tol and state != "TOUCHED":
                    go("TOUCHED", j)
                elif state == "IDENTIFIED" and (p - H[j]) <= APPROACH_ATR * ia:
                    go("APPROACHED", j)
                j += 1
                continue
            # перевищення тілом/тінню рівня на барі j
            k = j
            run = 0
            r = None
            while k < N and k - j <= max(reclaim_bars, accept_closes) + 1:
                if C[k] > p:
                    run += 1
                    if run >= accept_closes:
                        break
                else:
                    if k - j <= reclaim_bars:
                        r = k
                    break
                k += 1
            prior = int(np.sum(C[max(0, j - PRIOR_LOOKBACK):j] > p)) if j > 0 else 0   # закриття за ціною РІВНЯ до цього проколу, навіть до появи самого рівня: ціна вже була «прийнята» вище
            ext_i = j + int(np.argmax(H[j:(r if r is not None else min(k, N - 1)) + 1]))
            excess = float(H[ext_i] - p)
            ex_atr = excess / ia if ia > 0 else 0.0
            if r is not None:
                if prior >= accept_closes:
                    cls = "LATE_SWEEP"
                elif ex_atr < MIN_EXCESS_ATR:
                    cls = "WICK_ONLY"
                elif r == j and lv["kind"] in ("SWING_H", "SWING_L", "EQH", "EQL"):
                    cls = "SFP"
                else:
                    cls = "FRESH_RAID"
                sweep = {"class": cls, "j": int(j), "reclaim_j": int(r), "extreme_i": int(ext_i), "extreme": float(sg * H[ext_i]), "excess_atr": round(ex_atr, 3),
                         "closes_beyond": int(r - j), "prior_closes_beyond": prior, "close_back": float(sg * C[r]), "t": float(b["t"][r])}
                go("SWEPT", r)
                break
            if run >= accept_closes:
                accepted = {"j": int(j), "confirmed_j": int(k), "closes": run, "t": float(b["t"][k])}
                go("ACCEPTED_BREAKOUT", k)
                j = k + 1
                continue
            # ще не вирішено (кінець даних): жодних висновків про майбутнє
            pending = {"j": int(j), "closes_beyond_so_far": run, "extreme": float(sg * H[ext_i]), "excess_atr": round(ex_atr, 3), "prior_closes_beyond": prior}
            break
        elif state in ("ACCEPTED_BREAKOUT", "RETESTED"):
            if C[j] < p - tol:
                go("INVALIDATED", j)
                break
            if state == "ACCEPTED_BREAKOUT" and L[j] <= p + tol and C[j] > p:
                retest = {"j": int(j), "t": float(b["t"][j])}
                go("RETESTED", j)
            j += 1
            continue
        else:
            break
    out = dict(lv)
    out.update({"state": state, "history": [(s, int(i)) for s, i in hist], "sweep": sweep, "accepted": accepted, "retest": retest, "pending": pending})
    return out


def ledger(b: Arr, levels: List[Dict[str, Any]], a: np.ndarray) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for lv in sorted(levels, key=lambda x: (x["conf"], x["p"])):
        key = (lv["kind"], round(lv["p"], 10), lv["conf"])
        if key in seen:
            continue
        seen.add(key)
        out.append(track(b, lv, a))
    return out


def sweeps_of(led: List[Dict[str, Any]], classes: Tuple[str, ...] = ("FRESH_RAID", "SFP")) -> List[Dict[str, Any]]:
    """Свіжі проколи (за замовчуванням лише FRESH_RAID і SFP). Від найновішого. direction очікуваного руху: прокол high → SHORT."""
    out = []
    for lv in led:
        s = lv.get("sweep")
        if s and s["class"] in classes:
            out.append({"level": {k: lv[k] for k in ("kind", "side", "p", "strength", "tf")}, "dir": "SHORT" if lv["side"] == "high" else "LONG", **s})
    out.sort(key=lambda x: -x["reclaim_j"])
    return out


def ie_class(level_p: float, rg: Optional[Dict[str, Any]], tol_atr_px: float = 0.0) -> str:
    """External vs Internal (S15): external — на/поза межами поточного range (або range немає — вважаємо зовнішнім), internal — всередині коридору."""
    if not rg:
        return "EXTERNAL"
    return "INTERNAL" if rg["low"] + tol_atr_px < level_p < rg["high"] - tol_atr_px else "EXTERNAL"
