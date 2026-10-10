"""Генерація кандидатів Office 2.0 (shadow). Усі рішення — лише за барами, закритими на момент рішення.

Базова подія (етапи 3–5): sweep ліквідності ключового рівня + reclaim (повернення за рівень) на M15.
  type A: wick-sweep — бар пробив рівень тінню і закрився за ним;
  type B: failed breakout — бар закрився за рівнем, але протягом ≤2 наступних барів ціна повернулась.
Тригер (етап 8): 'reclaim' — вхід після закриття reclaim-бару; 'choch' — вхід після зламу локальної структури M15 у бік угоди (≤8 барів).
Інвалідація (етап 9): SL за екстремумом sweep + K_BUF·ATR(M15). TP (етап 10): найближчий протилежний рівень ліквідності з RR ≥ MIN_RR.
Фільтри-етапи (позначки в кандидаті, застосовуються в абляції): htf (H4 режим не проти), btc (BTC 4 год не проти), flow (taker-дельта reclaim-бару у бік угоди).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from office2 import features as F


@dataclass(frozen=True)
class Params:
    k_buf: float = 0.5          # буфер за екстремумом sweep, в ATR(M15)
    min_rr: float = 1.5         # мінімальна відстань до TP у ризиках
    max_tp_r: float = 8.0       # найдальша ціль, у ризиках
    min_risk_pct: float = 0.15  # відсікання вироджених стопів (%, апріорі)
    max_risk_pct: float = 6.0
    choch_bars: int = 8
    choch_lookback: int = 6
    reclaim_wait: int = 2       # type B: скільки барів після закриття над рівнем чекаємо повернення
    horizon_sec: int = 24 * 3600


def _entry_index(m1: F.Arr, t_entry: float) -> Optional[int]:
    i = int(np.searchsorted(m1["t"], t_entry, side="left"))
    if i >= len(m1["t"]) or m1["t"][i] - t_entry > 120:
        return None
    return i


def build_context(m1: F.Arr) -> Dict[str, Any]:
    """Попередньо обчислені бари/ATR/режими/рівні одного символу."""
    m15 = F.resample(m1, 900)
    h1 = F.resample(m1, 3600)
    h4 = F.resample(m1, 4 * 3600)
    d1 = F.resample(m1, F.DAY)
    w1 = F.resample(m1, 7 * F.DAY, offset=F.WEEK_OFFSET)
    return {"m1": m1, "m15": m15, "h4": h4, "d1": d1, "w1": w1, "atr15": F.atr(m15, 14), "reg4": F.regime_by_bar(h4), "regd": F.regime_by_bar(d1),
            "levels": F.build_levels(h4, d1, w1)}


def _events(ctx: Dict[str, Any], p: Params) -> List[dict]:
    """Sweep+reclaim події по M15 з одноразовими рівнями. Рівень має бути ВІДОМИЙ до відкриття бару sweep."""
    m15 = ctx["m15"]
    levels = ctx["levels"]
    nb = len(m15["t"])
    h, l, c, o, t = m15["h"], m15["l"], m15["c"], m15["o"], m15["t"]
    active: List[dict] = []   # {"lv":..., "pending": None|{"s":..,"ext":..}}
    ptr = 0
    ev: List[dict] = []
    for j in range(nb):
        topen = t[j]
        while ptr < len(levels) and levels[ptr]["known"] <= topen:
            lv = levels[ptr]
            ptr += 1
            # рівень, який ціна вже «з'їла» до моменту, коли він став відомим, не активуємо
            if j > 0 and ((lv["side"] == "high" and c[j - 1] > lv["p"]) or (lv["side"] == "low" and c[j - 1] < lv["p"])):
                continue
            active.append({"lv": lv, "pending": None})
        keep: List[dict] = []
        for a in active:
            lv = a["lv"]
            pr = lv["p"]
            if lv["side"] == "high":
                if a["pending"] is None:
                    if h[j] > pr:
                        if c[j] < pr:   # type A
                            ev.append({"lv": lv, "s": j, "r": j, "type": "A", "dir": "SHORT", "ext": float(h[j])})
                            continue
                        a["pending"] = {"s": j, "ext": float(h[j])}
                else:
                    a["pending"]["ext"] = max(a["pending"]["ext"], float(h[j]))
                    if c[j] < pr:
                        ev.append({"lv": lv, "s": a["pending"]["s"], "r": j, "type": "B", "dir": "SHORT", "ext": a["pending"]["ext"]})
                        continue
                    if j - a["pending"]["s"] >= p.reclaim_wait:
                        continue   # прийнято над рівнем: рівень «з'їдений»
            else:
                if a["pending"] is None:
                    if l[j] < pr:
                        if c[j] > pr:
                            ev.append({"lv": lv, "s": j, "r": j, "type": "A", "dir": "LONG", "ext": float(l[j])})
                            continue
                        a["pending"] = {"s": j, "ext": float(l[j])}
                else:
                    a["pending"]["ext"] = min(a["pending"]["ext"], float(l[j]))
                    if c[j] > pr:
                        ev.append({"lv": lv, "s": a["pending"]["s"], "r": j, "type": "B", "dir": "LONG", "ext": a["pending"]["ext"]})
                        continue
                    if j - a["pending"]["s"] >= p.reclaim_wait:
                        continue
            keep.append(a)
        active = keep
    return ev


def _btc_ret4h(btc: Optional[Dict[str, Any]], open_r: float) -> Optional[float]:
    """Зміна BTC за 4 год (16 барів M15) до закриття бару, що відкрився в open_r; лише закриті бари."""
    if not btc:
        return None
    m = btc["m15"]
    # open_r is the opening timestamp of the decision M15 bar.
    # At that instant bar j is NOT closed: using c[j] leaks future data.
    j = int(np.searchsorted(m["t"], open_r, side="left"))
    if j >= len(m["t"]) or abs(m["t"][j] - open_r) > 1 or j < 17:
        return None
    return float((m["c"][j - 1] / m["c"][j - 17] - 1.0) * 100.0)


def candidates(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]] = None, p: Params = Params(), stats: Optional[Dict[str, int]] = None) -> List[dict]:
    m15, m1 = ctx["m15"], ctx["m1"]
    atr15 = ctx["atr15"]
    levels = ctx["levels"]
    out: List[dict] = []
    nb = len(m15["t"])
    st = stats if stats is not None else {}

    def bump(k: str) -> None:
        st[k] = st.get(k, 0) + 1

    for ev in _events(ctx, p):
        bump("events")
        s, r = ev["s"], ev["r"]
        if r < 20 or np.isnan(atr15[r]):
            bump("no_atr")
            continue
        direction = ev["dir"]
        sgn = 1.0 if direction == "LONG" else -1.0
        t_rec = float(m15["t"][r] + 900)
        # ознаки етапів 1,2,7 на момент reclaim (лише закрите)
        k4 = F.last_closed(ctx["h4"], 4 * 3600, t_rec)
        kd = F.last_closed(ctx["d1"], F.DAY, t_rec)
        reg4 = int(ctx["reg4"][k4]) if k4 >= 0 else 0
        regd = int(ctx["regd"][kd]) if kd >= 0 else 0
        btc4 = _btc_ret4h(btc, float(m15["t"][r])) if symbol != "BTCUSDT" else None
        delta_r = F.flow_delta(m15, r)
        flow_ok = (delta_r > 0) if direction == "LONG" else (delta_r < 0)
        triggers = [("reclaim", r)]
        # CHoCH: злам локальної структури M15 у бік угоди протягом choch_bars після reclaim
        lo_ref = float(m15["l"][max(0, r - p.choch_lookback):r + 1].min())
        hi_ref = float(m15["h"][max(0, r - p.choch_lookback):r + 1].max())
        for m in range(r + 1, min(nb, r + 1 + p.choch_bars)):
            if (direction == "SHORT" and m15["c"][m] > ev["ext"]) or (direction == "LONG" and m15["c"][m] < ev["ext"]):
                break   # інвалідація до тригера
            if (direction == "SHORT" and m15["c"][m] < lo_ref) or (direction == "LONG" and m15["c"][m] > hi_ref):
                triggers.append(("choch", m))
                break
        if len(triggers) == 1:
            bump("choch_absent")
        for trig, jb in triggers:
            bump(f"{trig}_trigger")
            t_trig = float(m15["t"][jb] + 900)
            ie = _entry_index(m1, t_trig)
            if ie is None:
                bump(f"{trig}_no_entry_bar")
                continue
            entry = float(m1["o"][ie])
            sl = ev["ext"] + (p.k_buf * float(atr15[jb]) if direction == "SHORT" else -p.k_buf * float(atr15[jb]))
            risk = (sl - entry) if direction == "SHORT" else (entry - sl)
            if risk <= 0:
                bump(f"{trig}_bad_risk")
                continue
            risk_pct = risk / entry * 100.0
            if risk_pct < p.min_risk_pct or risk_pct > p.max_risk_pct:
                bump(f"{trig}_risk_out_of_range")
                continue
            # TP: найближчий протилежний рівень, відомий на t_trig, з RR ≥ min_rr
            best: Optional[dict] = None
            for lv in levels:
                if lv["known"] > t_trig:
                    break
                if direction == "SHORT" and lv["side"] == "low" and lv["p"] <= entry - p.min_rr * risk:
                    if best is None or lv["p"] > best["p"]:
                        best = lv
                if direction == "LONG" and lv["side"] == "high" and lv["p"] >= entry + p.min_rr * risk:
                    if best is None or lv["p"] < best["p"]:
                        best = lv
            if best is None:
                bump(f"{trig}_no_target")
                continue
            tp = best["p"]
            tdist = abs(tp - entry)
            if tdist > p.max_tp_r * risk:
                bump(f"{trig}_target_too_far")
                continue
            bump(f"{trig}_candidate")
            out.append({"symbol": symbol, "dir": direction, "t_entry": t_trig, "i1": ie, "entry": entry, "sl": float(sl), "tp": float(tp), "risk_pct": risk_pct,
                        "rr": tdist / risk, "trigger": trig, "etype": ev["type"], "lvl_kind": ev["lv"]["kind"], "lvl_strength": ev["lv"]["strength"], "lvl_p": ev["lv"]["p"],
                        "depth_atr": abs(ev["ext"] - ev["lv"]["p"]) / float(atr15[r]), "tp_kind": best["kind"], "tp_known": best["known"], "lvl_known": ev["lv"]["known"], "reg4": reg4, "regd": regd,
                        "btc4": btc4, "flow_ok": bool(flow_ok), "atr_pct": float(atr15[r]) / entry * 100.0,
                        "htf_ok": (reg4 * sgn) >= 0,
                        "btc_ok": True if btc4 is None else ((btc4 * sgn) >= -0.3)})
    return out
