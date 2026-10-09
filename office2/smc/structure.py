"""Структура ринку за SM Trader: swing (3 свічки) → HH/HL/LH/LL → BMS / MSS / CONFIRM, range / deviation / expansion, синхронізація ТФ.

Правила (формалізація схем 04–11, див. docs/office2/SMC_RULES.md):
• Swing High: центральна свічка має high ВИЩИЙ за обидві сусідні; підтверджується закриттям правої сусідньої свічки (conf = i + 1). Дві свічки поспіль / рівні high без вищого центру — не swing (схема 04, червоний хрестик).
• BMS (схеми 05, 06, 08): закриття ТІЛОМ за структурним swing у напрямку тренду (структурний high = найвищий підтверджений swing high після останнього зламу).
• Захищений мінімум (protected low) висхідної структури = найнижчий low між зламаним swing high і баром зламу, тобто початок ноги, що дала останній HH.
• MSS (схеми 09–11): закриття ТІЛОМ за захищеним мінімумом ПІСЛЯ останнього BMS. Злам внутрішнього мінімуму, що не є початком останньої ноги (корекція всередині розширення, схеми 10-праворуч, 11), — НЕ MSS (CORRECTION_BREAK).
• CONFIRM: після MSS перше закриття за swing-мінімумом, утвореним у нозі MSS (оновлення в новому напрямку). Якщо до CONFIRM ціна закрилась над вершиною, що дала MSS, — MSS_FAILED + повернення тренду (BMS).
Тіла несуть інформацію, тіні наносять урон: усі зломи — лише за close."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2.smc import core as K
from office2.smc.core import Arr



def swings(b: Arr, n: int = 1, tie: str = "strict") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Swing за методичкою (n=1: три свічки). Повертає (highs, lows): {'i','conf','p'}; conf = i+n — бар, на закритті якого swing став відомим.
    tie='strict' — центр суворо вищий за сусідів; 'first' — перша з рівних висот (плато)."""
    h, l = b["h"], b["l"]
    N = len(h)
    hs: List[Dict[str, Any]] = []
    ls: List[Dict[str, Any]] = []
    for i in range(n, N - n):
        lh, rh = h[i - n:i], h[i + 1:i + 1 + n]
        ll, rl = l[i - n:i], l[i + 1:i + 1 + n]
        if tie == "first":
            ok_h = bool(np.all(h[i] > lh) and np.all(h[i] >= rh))
            ok_l = bool(np.all(l[i] < ll) and np.all(l[i] <= rl))
        else:
            ok_h = bool(np.all(h[i] > lh) and np.all(h[i] > rh))
            ok_l = bool(np.all(l[i] < ll) and np.all(l[i] < rl))
        if ok_h:
            hs.append({"i": i, "conf": i + n, "p": float(h[i])})
        if ok_l:
            ls.append({"i": i, "conf": i + n, "p": float(l[i])})
    return hs, ls


def label_swings(hs: List[Dict[str, Any]], ls: List[Dict[str, Any]], eps: float = 0.0) -> List[Dict[str, Any]]:
    """HH/LH/EQH для highs і HL/LL/EQL для lows (порівняння з попереднім swing того ж типу), у порядку підтвердження."""
    out: List[Dict[str, Any]] = []
    for arr, up, nm in ((hs, True, "H"), (ls, False, "L")):
        prev = None
        for s in arr:
            if prev is None:
                lab = "H0" if up else "L0"
            elif abs(s["p"] - prev["p"]) <= eps:
                lab = "EQH" if up else "EQL"
            elif up:
                lab = "HH" if s["p"] > prev["p"] else "LH"
            else:
                lab = "HL" if s["p"] > prev["p"] else "LL"
            out.append({"i": s["i"], "conf": s["conf"], "p": s["p"], "type": "high" if up else "low", "label": lab})
            prev = s
    out.sort(key=lambda x: (x["conf"], x["i"]))
    return out


def analyze(b: Arr, n: int = 1, tie: str = "strict", atr: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Повний аналіз структури на закритих барах b. Без lookahead: стан на барі j залежить лише від барів ≤ j."""
    N = len(b["t"])
    o, h, l, c, t = b["o"], b["h"], b["l"], b["c"], b["t"]
    a = atr if atr is not None else K.atr_arr(b, 14)
    hs_all, ls_all = swings(b, n, tie)
    events: List[Dict[str, Any]] = []

    # окремі черги підтверджених swing за час підтвердження
    sh_conf = {s["conf"]: [] for s in hs_all}
    for s in hs_all:
        sh_conf.setdefault(s["conf"], []).append(s)
    sl_conf: Dict[int, List[Dict[str, Any]]] = {}
    for s in ls_all:
        sl_conf.setdefault(s["conf"], []).append(s)
    known_h: List[Dict[str, Any]] = []
    known_l: List[Dict[str, Any]] = []

    # стан: sg=+1 висхідна / −1 нисхідна; mode TREND | TRANSITION
    st: Dict[str, Any] = {"sg": 0, "mode": "NONE", "anchor": 0, "prot": None, "origin": None, "trans": None}
    corr_seen: set = set()

    def coords(sg: int):
        """Повертає (hi, lo, cl, swH, swL): ціни в координатах тренду (для sg=−1 дзеркало)."""
        if sg > 0:
            return (lambda i: float(h[i])), (lambda i: float(l[i])), (lambda i: float(c[i])), known_h, known_l
        return (lambda i: float(-l[i])), (lambda i: float(-h[i])), (lambda i: float(-c[i])), known_l, known_h

    def sg_price(sg: int, p: float) -> float:
        return float(sg * p) if sg < 0 else float(p)

    def struct_high(sg: int, anchor: int) -> Optional[Tuple[int, float]]:
        _, _, _, swH, _ = coords(sg)
        cand = [s for s in swH if s["i"] >= anchor]
        if not cand:
            return None
        if sg > 0:
            s = max(cand, key=lambda x: x["p"])
            return s["i"], s["p"]
        s = min(cand, key=lambda x: x["p"])          # у координатах тренду −p: найвищий = найнижчий реальний
        return s["i"], -s["p"]

    def lowest(sg: int, i0: int, i1: int) -> Tuple[int, float]:
        _, lo, _, _, _ = coords(sg)
        seg = [lo(i) for i in range(i0, i1 + 1)]
        k = int(np.argmin(seg))
        return i0 + k, seg[k]

    def highest(sg: int, i0: int, i1: int) -> Tuple[int, float]:
        hi, _, _, _, _ = coords(sg)
        seg = [hi(i) for i in range(i0, i1 + 1)]
        k = int(np.argmax(seg))
        return i0 + k, seg[k]

    def emit(kind: str, sg_dir: int, j: int, level: float, level_idx: int, **extra: Any) -> None:
        body_atr = float(abs(c[j] - o[j]) / a[j]) if np.isfinite(a[j]) and a[j] > 0 else None
        events.append({"kind": kind, "dir": "LONG" if sg_dir > 0 else "SHORT", "j": j, "t": float(t[j]), "level": float(level), "level_i": int(level_idx), "body_atr": body_atr, **extra})

    for j in range(N):
        for s in sh_conf.get(j, []):
            known_h.append(s)
        for s in sl_conf.get(j, []):
            known_l.append(s)
        sg, mode = st["sg"], st["mode"]
        if sg == 0:
            # початок структури: перше закриття за найвищим / найнижчим підтвердженим swing
            if known_h and c[j] > max(s["p"] for s in known_h):
                x = max(known_h, key=lambda s: s["p"])
                pi, pp = lowest(+1, x["i"], j)
                st.update(sg=+1, mode="TREND", anchor=j, prot=(pi, pp), origin=None)
                emit("BMS", +1, j, x["p"], x["i"], protected=float(pp), protected_i=int(pi), initial=True)
            elif known_l and c[j] < min(s["p"] for s in known_l):
                x = min(known_l, key=lambda s: s["p"])
                pi, pp = lowest(-1, x["i"], j)
                st.update(sg=-1, mode="TREND", anchor=j, prot=(pi, pp), origin=None)
                emit("BMS", -1, j, x["p"], x["i"], protected=float(-pp), protected_i=int(pi), initial=True)
            continue
        hi, lo, cl, swH, swL = coords(sg)
        if mode == "TREND":
            sh = struct_high(sg, st["anchor"])
            prot = st["prot"]
            if sh is not None and cl(j) > sh[1]:
                # BMS: злам структурного high у напрямку тренду → новий захищений мінімум = початок ноги
                pi, pp = lowest(sg, sh[0], j)
                st.update(anchor=j, prot=(pi, pp))
                emit("BMS", sg, j, sg_price(sg, sh[1]), sh[0], protected=float(sg_price(sg, pp)), protected_i=int(pi))
                continue
            if prot is not None and cl(j) < prot[1]:
                top_i, top_p = highest(sg, prot[0], j)
                emit("MSS", -sg, j, sg_price(sg, prot[1]), prot[0], origin_extreme=float(sg_price(sg, top_p)), origin_i=int(top_i))
                st.update(mode="TRANSITION", trans={"old_sg": sg, "top": (top_i, top_p), "mss_j": j}, anchor=j)
                st["sg"] = sg    # старий напрямок зберігаємо до CONFIRM / MSS_FAILED
                continue
            # внутрішній злам, що не є захищеним мінімумом → корекція в межах структури (схеми 10-праворуч, 11): подія CORRECTION_BREAK, НЕ MSS
            for s in swL:
                tp_ = s["p"] if sg > 0 else -s["p"]                 # ціна swing у координатах тренду (для sg<0 це swing high, дзеркало)
                if prot is not None and s["i"] > prot[0] and tp_ > prot[1] and cl(j) < tp_ and s["conf"] < j and s["i"] not in corr_seen:
                    corr_seen.add(s["i"])
                    emit("CORRECTION_BREAK", -sg, j, sg_price(sg, tp_), s["i"], protected=float(sg_price(sg, prot[1])), protected_i=int(prot[0]))
                    break
        else:  # TRANSITION: чекаємо CONFIRM у новому напрямку або MSS_FAILED
            tr = st["trans"]
            old = tr["old_sg"]
            ohi, olo, ocl, oswH, oswL = coords(old)
            top_i, top_p = tr["top"]
            if ocl(j) > top_p:
                pi, pp = lowest(old, top_i, j)
                emit("MSS_FAILED", old, j, sg_price(old, top_p), top_i)
                emit("BMS", old, j, sg_price(old, top_p), top_i, protected=float(sg_price(old, pp)), protected_i=int(pi), reclaim=True)
                st.update(mode="TREND", sg=old, anchor=j, prot=(pi, pp), trans=None)
                continue
            new = -old
            nhi, nlo, ncl, nswH, nswL = coords(new)
            cand = [s for s in nswH if s["i"] >= tr["mss_j"]]
            if cand:
                x = max(cand, key=lambda s: s["p"]) if new > 0 else min(cand, key=lambda s: s["p"])
                lvl = x["p"] if new > 0 else -x["p"]
                if ncl(j) > lvl:
                    pi, pp = lowest(new, x["i"], j)
                    emit("CONFIRM", new, j, sg_price(new, lvl), x["i"], protected=float(sg_price(new, pp)), protected_i=int(pi))
                    st.update(mode="TREND", sg=new, anchor=j, prot=(pi, pp), trans=None)
                    continue

    # --- підсумок
    sg = st["sg"]
    mode = st["mode"]
    brk = [e for e in events if e["kind"] in ("BMS", "MSS", "CONFIRM", "MSS_FAILED")]
    last_break = brk[-1]["j"] if brk else None
    out: Dict[str, Any] = {"n": N, "swings_h": hs_all, "swings_l": ls_all, "events": events, "labels": label_swings(hs_all, ls_all),
                           "structural_high": None, "structural_low": None, "protected_low": None, "protected_high": None, "range": None, "transition": None}
    if sg == 0:
        trend = "UNKNOWN"
    elif mode == "TRANSITION":
        trend = "TRANSITION"
    else:
        trend = "UP" if sg > 0 else "DOWN"
    if sg != 0 and mode == "TREND":
        shp = struct_high(sg, st["anchor"])
        if sg > 0:
            out["structural_high"] = {"i": shp[0], "p": shp[1]} if shp else None
            out["protected_low"] = {"i": st["prot"][0], "p": st["prot"][1]} if st["prot"] else None
        else:
            out["structural_low"] = {"i": shp[0], "p": shp[1]} if shp else None
            out["protected_high"] = {"i": st["prot"][0], "p": -st["prot"][1]} if st["prot"] else None
    if mode == "TRANSITION" and st["trans"]:
        tr = st["trans"]
        old = tr["old_sg"]
        out["transition"] = {"from": "UP" if old > 0 else "DOWN", "to": "DOWN" if old > 0 else "UP", "origin_extreme": float(sg_price(old, tr["top"][1])), "origin_i": int(tr["top"][0]), "mss_j": int(tr["mss_j"])}
    bars_since = (N - 1 - last_break) if last_break is not None else N
    out["bars_since_break"] = int(bars_since)
    rg = detect_range(b, hs_all, ls_all, a)
    out["range"] = rg
    if rg and trend in ("UP", "DOWN", "UNKNOWN"):
        trend = "RANGE"
    out["trend"] = trend
    return out


RANGE_TOL_ATR = 1.5      # допуск розкиду swing-ів однієї межі (в ATR) — калібрується історично, не оптимізується під окремий кейс
RANGE_MIN_ATR = 2.0      # мінімальна висота коридору (в ATR), інакше це шум, а не range


def detect_range(b: Arr, hs: List[Dict[str, Any]], ls: List[Dict[str, Any]], a: np.ndarray, upto: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Range = коридор, у якому ≥2 swing high лежать в межах RANGE_TOL_ATR одне від одного і ≥2 swing low — теж; межі 0 / 1, EQ 0,5 (схема 07).
    upto — враховувати лише swing-и, підтверджені до цього бару (щоб девіація не спотворювала межі, які вона знімає)."""
    N = len(b["t"])
    end = N - 1 if upto is None else min(upto, N - 1)
    ia = K.atr_at(a, end)
    if ia <= 0:
        return None
    H = [s for s in hs if s["conf"] <= end]
    L = [s for s in ls if s["conf"] <= end]
    best = None
    for m in range(min(5, len(H), len(L)), 1, -1):
        wh, wl = H[-m:], L[-m:]
        top = max(s["p"] for s in wh)
        bot = min(s["p"] for s in wl)
        if (top - min(s["p"] for s in wh)) > RANGE_TOL_ATR * ia or (max(s["p"] for s in wl) - bot) > RANGE_TOL_ATR * ia or (top - bot) < RANGE_MIN_ATR * ia:
            continue
        c_last = float(b["c"][end])
        if not (bot - 0.5 * ia <= c_last <= top + 0.5 * ia):
            continue
        i0 = min(wh[0]["i"], wl[0]["i"])
        best = {"high": float(top), "low": float(bot), "eq": float((top + bot) / 2.0), "i0": int(i0), "height_atr": float((top - bot) / ia), "swings": int(m),
                "high_i": int(max(wh, key=lambda s: s["p"])["i"]), "low_i": int(min(wl, key=lambda s: s["p"])["i"]), "levels": {"0": float(bot), "0.5": float((top + bot) / 2.0), "1": float(top)}}
        break
    return best


def deviation_events(b: Arr, rg: Dict[str, Any], a: np.ndarray, accept_closes: int = 2, reclaim_bars: int = 3, min_excess_atr: float = 0.05) -> List[Dict[str, Any]]:
    """Девіація (схема 07): вихід за межу range з поверненням = захоплення ліквідності; прийнятий вихід (≥ accept_closes закриттів за межею) = EXPANSION, а не девіація.
    Агресивний вхід — на виході за межу; консервативний — після закріплення/повернення. Лише факти по закритих барах."""
    out: List[Dict[str, Any]] = []
    if not rg:
        return out
    N = len(b["t"])
    c, h, l = b["c"], b["h"], b["l"]
    for side, lvl in (("high", rg["high"]), ("low", rg["low"])):
        up = side == "high"
        j = rg["i0"]
        while j < N:
            ia = K.atr_at(a, j)
            tol = min_excess_atr * ia
            beyond = (h[j] > lvl + tol) if up else (l[j] < lvl - tol)
            if not beyond:
                j += 1
                continue
            k = j
            closes_beyond = 0
            returned_at = None
            while k < N and k <= j + max(accept_closes, reclaim_bars) + 1:
                cb = (c[k] > lvl) if up else (c[k] < lvl)
                closes_beyond = closes_beyond + 1 if cb else 0
                if closes_beyond >= accept_closes:
                    break
                if not cb and k >= j and returned_at is None and k - j <= reclaim_bars:
                    returned_at = k
                    break
                k += 1
            ext_i = j + int(np.argmax(h[j:(returned_at or k) + 1])) if up else j + int(np.argmin(l[j:(returned_at or k) + 1]))
            if returned_at is not None:
                out.append({"kind": "DEVIATION", "side": side, "dir": "SHORT" if up else "LONG", "j": int(j), "back_j": int(returned_at), "extreme_i": int(ext_i),
                            "extreme": float(h[ext_i] if up else l[ext_i]), "level": float(lvl), "target_eq": rg["eq"], "t": float(b["t"][returned_at])})
            elif closes_beyond >= accept_closes:
                out.append({"kind": "EXPANSION", "side": side, "dir": "LONG" if up else "SHORT", "j": int(j), "accepted_j": int(k), "level": float(lvl), "t": float(b["t"][k])})
            j = max(k + 1, j + 1)
    out.sort(key=lambda x: x["t"])
    return out


def tf_sync(states: Dict[str, Dict[str, Any]], order: Tuple[str, ...] = ("d1", "h4", "h1", "m15")) -> Dict[str, Any]:
    """Синхронізація структури (S09.4): пріоритет старшого ТФ. Локальна корекція ≠ зміна старшої структури:
    якщо LTF у TRANSITION/протилежному напрямку, а захищений рівень HTF не порушений — це корекція в межах HTF."""
    bias = None
    htf = None
    for tf in order:
        s = states.get(tf)
        if s and s.get("trend") in ("UP", "DOWN"):
            bias, htf = s["trend"], tf
            break
    notes: List[str] = []
    aligned = True
    ltf = states.get("m15") or {}
    lt = ltf.get("trend")
    if bias and lt in ("UP", "DOWN", "TRANSITION"):
        want = bias
        cur = lt if lt != "TRANSITION" else ("DOWN" if (ltf.get("transition") or {}).get("to") == "DOWN" else "UP")
        if cur != want:
            aligned = False
            notes.append(f"M15 {cur} проти старшого {htf.upper()} {want}: корекція в межах старшої структури, поки захищений рівень {htf.upper()} не зламано")
    return {"htf_bias": bias, "htf": htf, "aligned": aligned, "notes": notes, "trends": {k: v.get("trend") for k, v in states.items() if v}}
