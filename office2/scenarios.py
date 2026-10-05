"""Сценарний шар Office 2.0 (shadow): що зробила ціна ПІСЛЯ зняття ліквідності — а не «sweep ⇒ розворот».

Подія (pierce): ціна проколює активний рівень. Поведінка після неї визначається лише закритими барами:
  A       — wick-reclaim: бар закрився назад за рівнем;
  B1      — перший бар закрився за рівнем, наступний повернувся (reclaim після 1 закриття);
  ACCEPT  — два закриття поспіль за рівнем (прийняття), далі:
  TRAP    — прийняття, але на 3-му барі повернення за рівень (пастка).
Сценарні кандидати: CONT (вхід у бік пробою на прийнятті), RETEST (вхід у бік пробою після ретесту рівня ≤8 барів), плюс reclaim-кандидати з v0 (REVERSAL/RANGE).
Дослідницькі поля fwd1h_atr/fwd4h_atr (рух у бік пробою після рішення, в ATR15) — ЛИШЕ для звіту, у рішенні не беруть участі.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from office2 import features as F
from office2.pipeline import Params, _btc_ret4h, _entry_index


def pierces(ctx: Dict[str, Any], p: Params) -> List[dict]:
    m15 = ctx["m15"]
    levels = ctx["levels"]
    nb = len(m15["t"])
    h, l, c, t = m15["h"], m15["l"], m15["c"], m15["t"]
    active: List[dict] = []
    ptr = 0
    out: List[dict] = []
    for j in range(nb):
        topen = t[j]
        while ptr < len(levels) and levels[ptr]["known"] <= topen:
            lv = levels[ptr]
            ptr += 1
            if j > 0 and ((lv["side"] == "high" and c[j - 1] > lv["p"]) or (lv["side"] == "low" and c[j - 1] < lv["p"])):
                continue
            active.append(lv)
        keep: List[dict] = []
        for lv in active:
            pr = lv["p"]
            high = lv["side"] == "high"
            sg = 1 if high else -1                      # напрям пробою: LONG для high-рівня, SHORT для low-рівня
            pierced = h[j] > pr if high else l[j] < pr
            if not pierced:
                keep.append(lv)
                continue
            ext = float(h[j] if high else l[j])
            beyond = lambda k: (c[k] > pr) if high else (c[k] < pr)
            ev = {"lv": lv, "s": j, "brk": sg, "ext": ext}
            if not beyond(j):
                ev.update(behavior="A", d=j, r=j, ext_d=ext)
            elif j + 1 >= nb:
                break
            else:
                ext = max(ext, float(h[j + 1] if high else l[j + 1])) if high else min(ext, float(l[j + 1]))
                if not beyond(j + 1):
                    ev.update(behavior="B1", d=j + 1, r=j + 1, ext=ext, ext_d=ext)
                else:
                    ev.update(behavior="ACCEPT", d=j + 1, a=j + 1, ext=ext, ext_d=ext)
                    if j + 2 < nb and not beyond(j + 2):
                        ev["behavior"] = "TRAP"
                        ev["r"] = j + 2
                        ev["ext"] = max(ext, float(h[j + 2])) if high else min(ext, float(l[j + 2]))
            out.append(ev)   # рівень «з'їдено» після першої події (одноразовий)
        active = keep
    return out


def _fwd(m15: F.Arr, d: int, brk: int, atr: float) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    for name, k in (("fwd1h_atr", 4), ("fwd4h_atr", 16)):
        if d + k < len(m15["c"]) and atr > 0:
            out[name] = float((m15["c"][d + k] - m15["c"][d]) * brk / atr)
        else:
            out[name] = None
    return out


def _tp(levels: List[dict], direction: str, entry: float, risk: float, t_trig: float, p: Params) -> Optional[dict]:
    best: Optional[dict] = None
    for lv in levels:
        if lv["known"] > t_trig:
            break
        if direction == "LONG" and lv["side"] == "high" and lv["p"] >= entry + p.min_rr * risk and (best is None or lv["p"] < best["p"]):
            best = lv
        if direction == "SHORT" and lv["side"] == "low" and lv["p"] <= entry - p.min_rr * risk and (best is None or lv["p"] > best["p"]):
            best = lv
    return best


def _build(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], p: Params, ev: dict, jb: int, trigger: str, bump) -> Optional[dict]:
    m15, m1, levels, atr15 = ctx["m15"], ctx["m1"], ctx["levels"], ctx["atr15"]
    if jb < 20 or np.isnan(atr15[jb]):
        bump("no_atr")
        return None
    lv = ev["lv"]
    brk = ev["brk"]
    direction = "LONG" if brk > 0 else "SHORT"          # сценарії продовження торгують У БІК пробою
    sgn = 1.0 if direction == "LONG" else -1.0
    t_trig = float(m15["t"][jb] + 900)
    ie = _entry_index(m1, t_trig)
    if ie is None:
        bump(f"{trigger}_no_entry_bar")
        return None
    entry = float(m1["o"][ie])
    sl = lv["p"] - sgn * p.k_buf * float(atr15[jb])     # структурна інвалідація: повернення за рівень на буфер
    risk = (entry - sl) if direction == "LONG" else (sl - entry)
    if risk <= 0:
        bump(f"{trigger}_bad_risk")
        return None
    risk_pct = risk / entry * 100.0
    if risk_pct < p.min_risk_pct or risk_pct > p.max_risk_pct:
        bump(f"{trigger}_risk_out_of_range")
        return None
    best = _tp(levels, direction, entry, risk, t_trig, p)
    if best is None:
        bump(f"{trigger}_no_target")
        return None
    tdist = abs(best["p"] - entry)
    if tdist > p.max_tp_r * risk:
        bump(f"{trigger}_target_too_far")
        return None
    k4 = F.last_closed(ctx["h4"], 4 * 3600, t_trig)
    kd = F.last_closed(ctx["d1"], F.DAY, t_trig)
    reg4 = int(ctx["reg4"][k4]) if k4 >= 0 else 0
    regd = int(ctx["regd"][kd]) if kd >= 0 else 0
    btc4 = _btc_ret4h(btc, float(m15["t"][jb])) if symbol != "BTCUSDT" else None
    delta = F.flow_delta(m15, jb)
    bump(f"{trigger}_candidate")
    return {"symbol": symbol, "dir": direction, "t_entry": t_trig, "i1": ie, "entry": entry, "sl": float(sl), "tp": float(best["p"]), "risk_pct": risk_pct, "rr": tdist / risk,
            "trigger": trigger, "etype": "ACCEPT", "lvl_kind": lv["kind"], "lvl_strength": lv["strength"], "lvl_p": lv["p"],
            "depth_atr": abs(ev.get("ext_d", ev["ext"]) - lv["p"]) / float(atr15[jb]), "tp_kind": best["kind"], "tp_known": best["known"], "lvl_known": lv["known"], "reg4": reg4, "regd": regd,
            "btc4": btc4, "flow_ok": (delta > 0) if direction == "LONG" else (delta < 0), "atr_pct": float(atr15[jb]) / entry * 100.0,
            "htf_ok": (reg4 * sgn) >= 0, "btc_ok": True if btc4 is None else ((btc4 * sgn) >= -0.3), "brk": brk}


def scenario_candidates(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]] = None, p: Params = Params(), stats: Optional[Dict[str, int]] = None) -> Dict[str, List[dict]]:
    """Повертає {"cands": кандидати CONT/RETEST, "behav": записи поведінки після проколу (для звіту)}."""
    m15, atr15 = ctx["m15"], ctx["atr15"]
    st = stats if stats is not None else {}

    def bump(k: str) -> None:
        st[k] = st.get(k, 0) + 1

    cands: List[dict] = []
    behav: List[dict] = []
    nb = len(m15["t"])
    for ev in pierces(ctx, p):
        bump("pierces")
        d = ev["d"]
        if d < 20 or d >= nb or np.isnan(atr15[d]):
            continue
        t_d = float(m15["t"][d] + 900)
        k4 = F.last_closed(ctx["h4"], 4 * 3600, t_d)
        reg4 = int(ctx["reg4"][k4]) if k4 >= 0 else 0
        rel = "за трендом пробою" if reg4 * ev["brk"] > 0 else "проти тренду пробою" if reg4 * ev["brk"] < 0 else "діапазон"
        rec = {"symbol": symbol, "day": int(t_d // 86400), "t": t_d, "behavior": ev["behavior"], "kind": ev["lv"]["kind"], "side": ev["lv"]["side"], "rel": rel, "reg4": reg4, "brk": ev["brk"],
               "btc4": _btc_ret4h(btc, float(m15["t"][d])) if symbol != "BTCUSDT" else None}
        rec.update(_fwd(m15, d, ev["brk"], float(atr15[d])))
        behav.append(rec)
        if ev["behavior"] in ("ACCEPT", "TRAP"):
            bump("accept_events")
            c = _build(symbol, ctx, btc, p, ev, ev["a"], "accept", bump)
            if c:
                c["scenario_ref"] = "CONT"
                cands.append(c)
            # ретест: ≤8 барів після прийняття; закриття за рівнем скасовує сценарій
            pr = ev["lv"]["p"]
            high = ev["lv"]["side"] == "high"
            for m in range(ev["a"] + 1, min(nb, ev["a"] + 1 + 8)):
                cm = m15["c"][m]
                if (high and cm < pr) or ((not high) and cm > pr):
                    break
                touch = (m15["l"][m] <= pr + 0.2 * atr15[m]) if high else (m15["h"][m] >= pr - 0.2 * atr15[m])
                if touch:
                    c2 = _build(symbol, ctx, btc, p, ev, m, "retest", bump)
                    if c2:
                        c2["scenario_ref"] = "RETEST"
                        cands.append(c2)
                    break
    return {"cands": cands, "behav": behav}
