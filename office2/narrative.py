"""Setup narrative (shadow): IMPULSE → COMPRESSION → BREAKOUT на H1 (LONG; SHORT — дзеркально).

Усе розпізнається лише за барами, ЗАКРИТИМИ до моменту рішення. Майбутнє (TP/SL/MFE/MAE) — лише outcome.
Параметри — дослідницькі визначення, задані заздалегідь (HYPOTHESES.md, раунд 3), не оптимізуються за test.
Дзеркало для SHORT: ціни множимо на −1 (h' = −l, l' = −h, c' = −c, o' = −o), taker-обсяг tbv' = v − tbv; код шукає той самий LONG-патерн.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from office2 import features as F
from office2 import sim as S
from office2.pipeline import _btc_ret4h, _entry_index


@dataclass(frozen=True)
class NParams:
    imp_atr: float = 3.0        # імпульс ≥ 3 ATR_H1
    imp_window: int = 24        # origin-мінімум шукаємо у 24 барах перед хаєм імпульсу
    min_corr: int = 8
    max_corr: int = 60
    retr_min: float = 0.25
    retr_max: float = 0.90
    line_tol: float = 0.15      # ціна не вище лінії + 0,15 ATR протягом стиснення
    brk_atr: float = 0.10       # пробій: закриття вище лінії на ≥0,1 ATR
    sl_buf: float = 0.5         # SL = мінімум корекції − 0,5 ATR_H1
    min_rr: float = 1.5
    min_risk_pct: float = 0.3
    max_risk_pct: float = 10.0
    horizon_sec: int = 48 * 3600


def _mirror(b: F.Arr) -> F.Arr:
    return {"t": b["t"], "o": -b["o"], "h": -b["l"], "l": -b["h"], "c": -b["c"], "v": b["v"], "tbv": b["v"] - b["tbv"], "n": b["n"]}


def _line(pa: tuple, pb: tuple):
    (xa, ya), (xb, yb) = pa, pb
    slope = (yb - ya) / (xb - xa)
    return lambda x: ya + slope * (x - xa), slope


def find_setups_long(bars: F.Arr, atr: np.ndarray, p: NParams, stats: Dict[str, int]) -> List[dict]:
    h, l, c, o, v, tbv = bars["h"], bars["l"], bars["c"], bars["o"], bars["v"], bars["tbv"]
    n = len(h)
    sh, _sl = F.swings(bars, 2)
    out: List[dict] = []
    for ih, _kih, ph in sh:
        a0 = atr[ih]
        if ih < 30 or np.isnan(a0) or a0 <= 0:
            continue
        lo0 = max(0, ih - p.imp_window)
        io = lo0 + int(np.argmin(l[lo0:ih]))
        if ih - io < 3:
            continue
        imp = ph - l[io]
        if imp < p.imp_atr * a0:
            continue
        stats["impulses"] = stats.get("impulses", 0) + 1
        found = False
        for b in range(ih + p.min_corr, min(n - 1, ih + p.max_corr) + 1):
            ab = atr[b]
            if np.isnan(ab) or ab <= 0:
                continue
            # дві останні ПІДТВЕРДЖЕНІ (до бару b−1) нижчі swing-хаї після імпульсу; якщо лише один — лінія від хая імпульсу
            lows_hi = [(j, pj) for (j, kj, pj) in sh if j > ih + 2 and kj <= b - 1 and pj < ph]
            if not lows_hi:
                continue
            pts = lows_hi[-2:] if len(lows_hi) >= 2 and lows_hi[-1][1] < lows_hi[-2][1] else [(ih, ph), lows_hi[-1]]
            if pts[1][1] >= pts[0][1] or pts[1][0] <= pts[0][0]:
                continue
            ln, slope = _line(pts[0], pts[1])
            xs = np.arange(pts[0][0], b)
            if len(xs) and np.max(h[xs] - np.array([ln(x) for x in xs])) > p.line_tol * ab:
                continue                                    # ціна вже піднімалась над лінією — лінія не діє
            if not (c[b] > ln(b) + p.brk_atr * ab):
                continue
            if b - 1 > pts[0][0] and c[b - 1] > ln(b - 1) + p.brk_atr * ab:
                continue                                    # це не перший пробій
            minlow = float(l[ih + 1:b].min()) if b > ih + 1 else float(l[ih])
            retr = (ph - minlow) / imp
            if not (p.retr_min <= retr <= p.retr_max):
                continue
            stats["breakouts"] = stats.get("breakouts", 0) + 1
            zone_top = l[io] + atr[io] if not np.isnan(atr[io]) else l[io] + a0
            seg = slice(ih + 1, b)
            ranges = (h - l)
            first, last = ranges[ih + 1:ih + 7], ranges[max(ih + 1, b - 6):b]
            volp = float(np.mean(v[max(0, b - 20):b])) or 1.0
            ev = {
                "ih": ih, "io": io, "b": b, "ph": float(ph), "origin_low": float(l[io]), "minlow": minlow, "line_b": float(ln(b)), "slope_atr": float(slope / ab),
                "imp_atr": float(imp / a0), "imp_bars": int(ih - io),
                "imp_vol": float(np.mean(v[io:ih + 1]) / max(float(np.mean(v[max(0, io - 24):io])) if io > 0 else 1.0, 1e-12)),
                "imp_eff": float(imp / max(float(np.sum(ranges[io:ih + 1])), 1e-12)),
                "retr": float(retr), "corr_bars": int(b - ih), "compress": float(np.mean(last) / max(float(np.mean(first)), 1e-12)) if len(first) and len(last) else 1.0,
                "block_return": float((minlow - l[io]) / a0), "block_held": 1.0 if minlow >= l[io] - 0.3 * a0 else 0.0,
                "block_tests": float(np.sum(l[seg] <= zone_top + 0.3 * a0)) if b > ih + 1 else 0.0,
                "touches": float(np.sum(np.abs(h[pts[0][0]:b] - np.array([ln(x) for x in range(pts[0][0], b)])) <= 0.2 * ab)),
                "brk_body": float((c[b] - o[b]) / ab), "brk_rng": float((h[b] - l[b]) / ab), "brk_volr": float(v[b] / volp), "brk_delta": float((2 * tbv[b] - v[b]) / max(v[b], 1e-12)),
                "above_line": float((c[b] - ln(b)) / ab), "atr_b": float(ab), "room_imp": float((ph - c[b]) / ab),
            }
            # прийняття: наступне закриття над лінією (рішення ПІСЛЯ бару b+1)
            ev["accept_ok"] = bool(b + 1 < n and c[b + 1] > ln(b + 1))
            out.append(ev)
            found = True
            break
        if not found:
            stats["no_breakout"] = stats.get("no_breakout", 0) + 1
    # один пробій — одна подія: серед імпульсних хаїв, що дали той самий пробійний бар, лишаємо найвищий хай (найсильніший імпульс)
    best: Dict[int, dict] = {}
    for ev in out:
        cur = best.get(ev["b"])
        if cur is None or ev["ph"] > cur["ph"]:
            best[ev["b"]] = ev
    stats["breakouts_dedup"] = stats.get("breakouts_dedup", 0) + len(best)
    return sorted(best.values(), key=lambda e: e["b"])


def candidates(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], p: NParams = NParams(), stats: Optional[Dict[str, int]] = None) -> List[dict]:
    st = stats if stats is not None else {}
    m1 = ctx["m1"]
    h1 = ctx.get("h1")
    if h1 is None:
        h1 = ctx["h1"] = F.resample(m1, 3600)
        ctx["atr1h"] = F.atr(h1, 14)
    atr1h = ctx["atr1h"]
    out: List[dict] = []
    seen = set()
    for direction, bars in (("LONG", h1), ("SHORT", _mirror(h1))):
        sg = 1.0 if direction == "LONG" else -1.0
        for ev in find_setups_long(bars, atr1h, p, st):
            for mode in ("break", "accept"):
                jb = ev["b"] if mode == "break" else ev["b"] + 1
                if mode == "accept" and not ev["accept_ok"]:
                    st["accept_missing"] = st.get("accept_missing", 0) + 1
                    continue
                t_dec = float(h1["t"][jb] + 3600)
                ie = _entry_index(m1, t_dec)
                if ie is None:
                    continue
                entry_r = float(m1["o"][ie])
                e_t = sg * entry_r                                  # у дзеркальному просторі
                sl_t = ev["minlow"] - p.sl_buf * ev["atr_b"]
                tp_t = ev["ph"]
                risk = e_t - sl_t
                if risk <= 0 or tp_t - e_t < p.min_rr * risk:
                    st[f"{mode}_no_room"] = st.get(f"{mode}_no_room", 0) + 1
                    continue
                risk_pct = risk / abs(entry_r) * 100.0
                if risk_pct < p.min_risk_pct or risk_pct > p.max_risk_pct:
                    st[f"{mode}_risk_out"] = st.get(f"{mode}_risk_out", 0) + 1
                    continue
                k4 = F.last_closed(ctx["h4"], 4 * 3600, t_dec)
                kd = F.last_closed(ctx["d1"], F.DAY, t_dec)
                reg4 = int(ctx["reg4"][k4]) if k4 >= 0 else 0
                regd = int(ctx["regd"][kd]) if kd >= 0 else 0
                btc4 = _btc_ret4h(btc, float(h1["t"][jb] + 2700)) if symbol != "BTCUSDT" else None
                st[f"{mode}_candidate"] = st.get(f"{mode}_candidate", 0) + 1
                c = {"symbol": symbol, "dir": direction, "t_entry": t_dec, "i1": ie, "entry": entry_r, "sl": sg * sl_t, "tp": sg * tp_t, "risk_pct": risk_pct, "rr": (tp_t - e_t) / risk,
                     "trigger": mode, "etype": "NARR", "lvl_kind": "NARR", "lvl_strength": 0, "lvl_p": sg * ev["line_b"], "reg4": reg4, "regd": regd,
                     "btc4": btc4, "flow_ok": ev["brk_delta"] > 0, "atr_pct": ev["atr_b"] / abs(entry_r) * 100.0, "htf_ok": reg4 * sg >= 0,
                     "btc_ok": True if btc4 is None else (btc4 * sg >= -0.3), "tp_known": t_dec, "lvl_known": t_dec, "depth_atr": 0.0, "tp_kind": "IMPULSE_HIGH",
                     "feat": {k: ev[k] for k in ("imp_atr", "imp_bars", "imp_vol", "imp_eff", "retr", "corr_bars", "compress", "block_return", "block_held", "block_tests", "touches", "slope_atr",
                                                  "brk_body", "brk_rng", "brk_volr", "brk_delta", "above_line", "room_imp")}}
                c["feat"]["rel4"] = float(reg4 * sg)
                c["feat"]["reld"] = float(regd * sg)
                c["feat"]["btc_al"] = float(np.clip((btc4 or 0.0) * sg, -3, 3))
                c["feat"]["rr"] = float(c["rr"])
                c["feat"]["risk_pct"] = float(risk_pct)
                key = (symbol, direction, ev["ih"], mode)
                if key in seen:
                    continue
                seen.add(key)
                out.append(c)
    return out


def generic_controls(symbol: str, ctx: Dict[str, Any], n: int, p: NParams = NParams(), seed: int = 9) -> List[dict]:
    """Контроль «загальний структурний лонг/шорт»: випадкові години; SL = мінімум 12 барів − 0,5 ATR, TP = максимум 48 барів; ті самі фільтри RR/ризику. Без імпульсу/стиснення/пробою."""
    m1 = ctx["m1"]
    h1 = ctx.get("h1")
    if h1 is None:
        h1 = ctx["h1"] = F.resample(m1, 3600)
        ctx["atr1h"] = F.atr(h1, 14)
    atr1h = ctx["atr1h"]
    rnd = random.Random(seed)
    nb = len(h1["t"])
    out: List[dict] = []
    tries = 0
    while len(out) < n and tries < n * 30 and nb > 120:
        tries += 1
        j = rnd.randrange(60, nb - 60)
        a = atr1h[j]
        if np.isnan(a) or a <= 0:
            continue
        direction = rnd.choice(["LONG", "SHORT"])
        sg = 1.0 if direction == "LONG" else -1.0
        t_dec = float(h1["t"][j] + 3600)
        ie = _entry_index(m1, t_dec)
        if ie is None:
            continue
        entry = float(m1["o"][ie])
        if direction == "LONG":
            sl, tp = float(h1["l"][j - 11:j + 1].min()) - p.sl_buf * a, float(h1["h"][j - 47:j + 1].max())
        else:
            sl, tp = float(h1["h"][j - 11:j + 1].max()) + p.sl_buf * a, float(h1["l"][j - 47:j + 1].min())
        risk = sg * (entry - sl)
        if risk <= 0 or sg * (tp - entry) < p.min_rr * risk:
            continue
        risk_pct = risk / entry * 100.0
        if risk_pct < p.min_risk_pct or risk_pct > p.max_risk_pct:
            continue
        out.append({"symbol": symbol, "dir": direction, "t_entry": t_dec, "i1": ie, "entry": entry, "sl": sl, "tp": tp, "risk_pct": risk_pct, "rr": sg * (tp - entry) / risk, "trigger": "control",
                    "etype": "CTRL", "lvl_kind": "-", "lvl_strength": 0, "lvl_p": entry, "reg4": 0, "regd": 0, "btc4": None, "flow_ok": True, "atr_pct": a / entry * 100.0, "htf_ok": True,
                    "btc_ok": True, "tp_known": t_dec, "lvl_known": t_dec, "depth_atr": 0.0, "tp_kind": "-", "feat": {}})
    return out


HORIZONS_H = (1, 4, 12, 24, 48)
ORDER_K = (0.5, 1.0, 1.5, 2.0)


def _outcome_record(m1: F.Arr, i0: int, direction: str, entry: float, sl: float, ph: Optional[float], line: Optional[float], atr: float) -> Optional[dict]:
    """Діагностичні outcome-мітки (лише майбутнє, лише label): MFE/MAE в ATR і R на 1/4/12/24/48 год, рух до структурної інвалідації,
    повернення під рівень пробою, досягнення хая імпульсу. Не залежить від RR до хая і не обрізається TP/SL."""
    sg = 1.0 if direction == "LONG" else -1.0
    risk = sg * (entry - sl)
    if risk <= 0 or atr <= 0:
        return None
    t = m1["t"]
    i1 = int(np.searchsorted(t, t[i0] + 48 * 3600, side="right"))
    if i1 - i0 < 60:
        return None
    h, l = m1["h"][i0:i1], m1["l"][i0:i1]
    fav = (h - entry) if sg > 0 else (entry - l)       # хвилинні сприятливі/несприятливі відхилення
    adv = (entry - l) if sg > 0 else (h - entry)
    cf, ca = np.maximum.accumulate(fav), np.maximum.accumulate(adv)
    rec: Dict[str, Any] = {"risk": float(risk), "rr_to_high": (None if ph is None else float(sg * (ph - entry) / risk))}
    for hh in HORIZONS_H:
        k = min(hh * 60, len(h)) - 1
        rec[f"mfe_atr_{hh}"], rec[f"mae_atr_{hh}"] = float(cf[k] / atr), float(ca[k] / atr)
        rec[f"mfe_r_{hh}"], rec[f"mae_r_{hh}"] = float(cf[k] / risk), float(ca[k] / risk)
    hit_sl = adv >= risk
    k_inv = int(np.argmax(hit_sl)) if hit_sl.any() else -1
    rec["inval_min"] = k_inv if k_inv >= 0 else None
    # хвилина інвалідації не зараховується як сприятлива (стоп-first, як у first_touch)
    rec["mfe_to_inval_r"] = float(cf[-1] / risk) if k_inv < 0 else (0.0 if k_inv == 0 else float(cf[k_inv - 1] / risk))
    # ПОРЯДОК руху (exploratory): +k·R раніше за −1R (= структурний SL)? Та сама хвилина — стоп раніше. «none» = жодного з двох за 48 год
    for kr in ORDER_K:
        hit_up = fav >= kr * risk
        ku = int(np.argmax(hit_up)) if hit_up.any() else -1
        rec[f"order_{kr}"] = "none" if (ku < 0 and k_inv < 0) else ("up" if (ku >= 0 and (k_inv < 0 or ku < k_inv)) else "down")
    rec["t_mfe_min"], rec["t_mae_min"] = int(np.argmax(fav)), int(np.argmax(adv))
    if line is not None:
        under = (l <= line) if sg > 0 else (h >= line)
        rec["back_below_min"] = int(np.argmax(under)) if under.any() else None
    else:
        rec["back_below_min"] = None
    if ph is not None:
        up = (h >= ph) if sg > 0 else (l <= ph)
        k_ph = int(np.argmax(up)) if up.any() else -1
        rec["high_min"] = k_ph if k_ph >= 0 else None
        rec["high_before_inval"] = bool(k_ph >= 0 and (k_inv < 0 or k_ph < k_inv))
    else:
        rec["high_min"], rec["high_before_inval"] = None, False
    return rec


def event_outcomes(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], p: NParams = NParams(), stats: Optional[Dict[str, int]] = None) -> List[dict]:
    """ПО ВСІХ дедуплікованих подіях пробою (без фільтра RR/ризику): питання A — чи має послідовність прогнозну цінність саме по собі.
    Вхід = відкриття 1m після закриття пробійного бару H1; структурний SL = мінімум корекції − sl_buf·ATR_H1."""
    st = stats if stats is not None else {}
    m1 = ctx["m1"]
    h1 = ctx.get("h1")
    if h1 is None:
        h1 = ctx["h1"] = F.resample(m1, 3600)
        ctx["atr1h"] = F.atr(h1, 14)
    atr1h = ctx["atr1h"]
    out: List[dict] = []
    tmp: Dict[str, int] = {}
    for direction, bars in (("LONG", h1), ("SHORT", _mirror(h1))):
        sg = 1.0 if direction == "LONG" else -1.0
        for ev in find_setups_long(bars, atr1h, p, tmp):
            t_dec = float(h1["t"][ev["b"]] + 3600)
            ie = _entry_index(m1, t_dec)
            if ie is None:
                st["ev_no_entry"] = st.get("ev_no_entry", 0) + 1
                continue
            entry = float(m1["o"][ie])
            sl = sg * (ev["minlow"] - p.sl_buf * ev["atr_b"])
            rec = _outcome_record(m1, ie, direction, entry, sl, sg * ev["ph"], sg * ev["line_b"], float(ev["atr_b"]))
            if rec is None:
                st["ev_no_outcome"] = st.get("ev_no_outcome", 0) + 1
                continue
            rec.update({"symbol": symbol, "dir": direction, "t_entry": t_dec, "day": int(t_dec // 86400), "kind": "event", "risk_pct": rec["risk"] / abs(entry) * 100.0,
                        "feat": {k: ev[k] for k in ("imp_atr", "retr", "corr_bars", "compress", "touches", "brk_body", "brk_volr", "brk_delta", "room_imp")}})
            rec["rr15"] = bool(rec["rr_to_high"] is not None and rec["rr_to_high"] >= p.min_rr)
            out.append(rec)
            st["ev_n"] = st.get("ev_n", 0) + 1
    return out


def event_controls(symbol: str, ctx: Dict[str, Any], n: int, p: NParams = NParams(), seed: int = 11) -> List[dict]:
    """Контроль для event_outcomes: випадкові години, випадковий напрям, той самий структурний SL (мін./макс. 12 барів ∓ 0,5 ATR_H1), без вимог до RR."""
    m1 = ctx["m1"]
    h1 = ctx.get("h1")
    if h1 is None:
        h1 = ctx["h1"] = F.resample(m1, 3600)
        ctx["atr1h"] = F.atr(h1, 14)
    atr1h = ctx["atr1h"]
    rnd = random.Random(seed)
    nb = len(h1["t"])
    out: List[dict] = []
    tries = 0
    while len(out) < n and tries < n * 30 and nb > 120:
        tries += 1
        j = rnd.randrange(60, nb - 60)
        a = atr1h[j]
        if np.isnan(a) or a <= 0:
            continue
        direction = rnd.choice(["LONG", "SHORT"])
        t_dec = float(h1["t"][j] + 3600)
        ie = _entry_index(m1, t_dec)
        if ie is None:
            continue
        entry = float(m1["o"][ie])
        sl = float(h1["l"][j - 11:j + 1].min()) - p.sl_buf * a if direction == "LONG" else float(h1["h"][j - 11:j + 1].max()) + p.sl_buf * a
        rec = _outcome_record(m1, ie, direction, entry, sl, None, None, float(a))
        if rec is None:
            continue
        rec.update({"symbol": symbol, "dir": direction, "t_entry": t_dec, "day": int(t_dec // 86400), "kind": "control", "risk_pct": rec["risk"] / entry * 100.0, "feat": {}, "rr15": False})
        out.append(rec)
    return out
