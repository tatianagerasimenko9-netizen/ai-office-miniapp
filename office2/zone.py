"""N2 — поведінка ціни в зоні origin/demand після імпульсу (shadow, research-only). H1; LONG, SHORT — дзеркально.

Усе — лише за барами, закритими до моменту рішення. Майбутнє (outcome) береться окремо в office2/outcome.py.
Подія EXIT: ціна атакувала зону (low ≤ верх зони), і атака закінчилась закриттям бару ВИЩЕ верху зони (rejection); рішення — після цього бару.
Подія BOS (exploratory): після ≥1 завершеної атаки закриття вище останнього підтвердженого swing-хая корекції.
Стан-контроль (pool): бари тієї ж корекції, де зону ще НЕ атаковано (low > верх зони з моменту хая імпульсу).
Зона: [мінімум origin; max хаїв барів io..io+2, обмежений 0,5…2 ATR_H1 від мінімуму]. Зона провалена, якщо закриття < низ зони − 0,25 ATR (стеження за імпульсом припиняється).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from office2 import features as F
from office2 import outcome as O
from office2.narrative import _btc_bucket, _mirror, _session
from office2.pipeline import _btc_ret4h, _entry_index


@dataclass(frozen=True)
class ZParams:
    imp_atr: float = 3.0
    imp_window: int = 24
    max_corr: int = 60
    zone_min_atr: float = 0.5
    zone_max_atr: float = 2.0
    zone_fail_atr: float = 0.25
    sl_buf: float = 0.5
    horizon_sec: int = 48 * 3600
    # matching (зафіксовано до test)
    cal_imp: tuple = (0.7, 1.3)
    cal_atrp: tuple = (0.7, 1.0 / 0.7)
    cal_risk: tuple = (0.75, 1.0 / 0.75)
    shape_drift_atr: float = 0.75


# ознаки, які ПОВИННІ мати змінність (перевіряється автоматично; константа = непридатна)
EVENT_FEATURES = ("k", "depth_last", "depth_first", "depth_max", "depth_pct_last", "close_state_last", "rebound_last", "run_len_last", "close_loc_last", "gap_bars",
                  "depth_ratio", "rebound_ratio", "vol_ratio", "bars_since_imp", "imp_atr", "retr_max", "width_atr", "atr_ratio", "range_slope", "vol_slope",
                  "n_lh", "n_hh", "n_hl", "n_ll", "shape_range", "shape_down", "shape_up", "shape_conv", "shape_exp", "shape_unk", "bos", "disp_body", "disp_range",
                  "m15_disp", "m15_loc", "room", "rel4", "reld", "btc_al", "risk_atr")


def _slope(y: np.ndarray) -> float:
    n = len(y)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    x -= x.mean()
    return float(np.dot(x, y - y.mean()) / max(np.dot(x, x), 1e-12))


def _impulses(bars: F.Arr, atr: np.ndarray, p: ZParams) -> List[dict]:
    l = bars["l"]
    sh, _ = F.swings(bars, 2)
    out = []
    for ih, kih, ph in sh:
        a0 = atr[ih]
        if ih < 30 or np.isnan(a0) or a0 <= 0:
            continue
        lo0 = max(0, ih - p.imp_window)
        io = lo0 + int(np.argmin(l[lo0:ih]))
        if ih - io < 3:
            continue
        imp = ph - l[io]
        if imp >= p.imp_atr * a0:
            out.append({"ih": ih, "kih": kih, "io": io, "ph": float(ph), "imp": float(imp), "imp_atr": float(imp / a0)})
    return out


def _levels_arrays(ctx: Dict[str, Any]) -> Dict[str, np.ndarray]:
    if "_lv" not in ctx:
        lv = ctx["levels"]
        ctx["_lv"] = {"known": np.array([x["known"] for x in lv], dtype=float), "p": np.array([x["p"] for x in lv], dtype=float), "high": np.array([x["side"] == "high" for x in lv])}
    return ctx["_lv"]


def _room(ctx: Dict[str, Any], price: float, atr_abs: float, t_dec: float, sg: float) -> float:
    a = _levels_arrays(ctx)
    ok = a["known"] <= t_dec
    if sg > 0:
        m = ok & a["high"] & (a["p"] > price)
        d = (a["p"][m] - price) if m.any() else None
    else:
        m = ok & (~a["high"]) & (a["p"] < price)
        d = (price - a["p"][m]) if m.any() else None
    return 20.0 if d is None else float(min(d.min() / atr_abs, 20.0))


def _market(ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], symbol: str, t_dec: float, h1_t_open: float, sg: float) -> Dict[str, Any]:
    k4, kd = F.last_closed(ctx["h4"], 4 * 3600, t_dec), F.last_closed(ctx["d1"], F.DAY, t_dec)
    btc4 = _btc_ret4h(btc, h1_t_open + 2700) if (btc and symbol != "BTCUSDT") else None
    return {"r4": (int(ctx["reg4"][k4]) * int(sg) if k4 >= 0 else 0), "rd": (int(ctx["regd"][kd]) * int(sg) if kd >= 0 else 0), "btc4": btc4, "btcb": _btc_bucket(btc4, sg)}


def _structure(sh_all, sl_all, ih: int, j: int, atr_j: float, p: ZParams) -> Dict[str, float]:
    """Swing-структура корекції (лише підтверджені до j): лічильники HH/LH/HL/LL серед останніх 4 точок і форма діапазону."""
    hs = [(i, pr) for (i, ki, pr) in sh_all if i > ih and ki <= j]
    ls = [(i, pr) for (i, ki, pr) in sl_all if i > ih and ki <= j]
    hs, ls = hs[-4:], ls[-4:]
    n_hh = sum(1 for a, b in zip(hs, hs[1:]) if b[1] > a[1])
    n_lh = sum(1 for a, b in zip(hs, hs[1:]) if b[1] < a[1])
    n_hl = sum(1 for a, b in zip(ls, ls[1:]) if b[1] > a[1])
    n_ll = sum(1 for a, b in zip(ls, ls[1:]) if b[1] < a[1])
    shape = dict(shape_range=0.0, shape_down=0.0, shape_up=0.0, shape_conv=0.0, shape_exp=0.0, shape_unk=0.0)
    if len(hs) >= 2 and len(ls) >= 2 and atr_j > 0:
        i0 = min(hs[0][0], ls[0][0])
        i1 = max(hs[-1][0], ls[-1][0])
        span = max(i1 - i0, 1)
        dh = _slope(np.array([x[1] for x in hs])) / max(np.mean(np.diff([x[0] for x in hs])), 1.0) * span / atr_j
        dl = _slope(np.array([x[1] for x in ls])) / max(np.mean(np.diff([x[0] for x in ls])), 1.0) * span / atr_j
        w0 = abs(hs[0][1] - ls[0][1])
        w1 = abs(hs[-1][1] - ls[-1][1])
        if dh > p.shape_drift_atr and dl > p.shape_drift_atr:
            shape["shape_up"] = 1.0
        elif dh < -p.shape_drift_atr and dl < -p.shape_drift_atr:
            shape["shape_down"] = 1.0
        elif abs(dh) <= p.shape_drift_atr and abs(dl) <= p.shape_drift_atr:
            shape["shape_range"] = 1.0
        elif w1 < 0.7 * w0:
            shape["shape_conv"] = 1.0
        elif w1 > 1.3 * w0:
            shape["shape_exp"] = 1.0
        else:
            shape["shape_unk"] = 1.0
    else:
        shape["shape_unk"] = 1.0
    return {"n_hh": float(n_hh), "n_lh": float(n_lh), "n_hl": float(n_hl), "n_ll": float(n_ll), **shape}


def scan(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], p: ZParams = ZParams(), stats: Optional[Dict[str, int]] = None) -> Dict[str, List[dict]]:
    """Повертає {"events": [...], "pool": [...]} для LONG і SHORT. Усі поля — decision-time; sl/entry для outcome обчислюються в `build`."""
    st = stats if stats is not None else {}
    m1, m15 = ctx["m1"], ctx["m15"]
    h1 = ctx.get("h1")
    if h1 is None:
        h1 = ctx["h1"] = F.resample(m1, 3600)
        ctx["atr1h"] = F.atr(h1, 14)
    atr1h = ctx["atr1h"]
    events: List[dict] = []
    pool: List[dict] = []

    def bump(k: str) -> None:
        st[k] = st.get(k, 0) + 1

    for direction, bars in (("LONG", h1), ("SHORT", _mirror(h1))):
        sg = 1.0 if direction == "LONG" else -1.0
        h, l, c, o, v = bars["h"], bars["l"], bars["c"], bars["o"], bars["v"]
        n = len(h)
        sh_all, sl_all = F.swings(bars, 2)
        seen_ev = set()
        for im in _impulses(bars, atr1h, p):
            bump("impulses")
            ih, io, ph = im["ih"], im["io"], im["ph"]
            a_io = atr1h[io] if not np.isnan(atr1h[io]) else atr1h[ih]
            if a_io <= 0 or np.isnan(a_io):
                continue
            zone_low = float(l[io])
            top_raw = float(h[io:min(io + 3, ih)].max())
            zone_top = min(max(top_raw, zone_low + p.zone_min_atr * a_io), zone_low + p.zone_max_atr * a_io)
            width = zone_top - zone_low
            runs: List[dict] = []
            cur: Optional[dict] = None
            left = True
            bos_done = set()
            for j in range(ih + 3, min(n - 1, ih + p.max_corr) + 1):
                aj = atr1h[j]
                if np.isnan(aj) or aj <= 0:
                    continue
                if h[j] > ph:
                    break
                touch = l[j] <= zone_top
                t_open = float(h1["t"][j])
                t_dec = t_open + 3600.0
                if cur is None and not touch:
                    left = True
                    if not runs:
                        lows_since = float(l[ih + 1:j + 1].min())
                        mk = _market(ctx, btc, symbol, t_dec, t_open, sg)
                        pool.append({"r4": mk["r4"], "rd": mk["rd"], "btcb": mk["btcb"], "symbol": symbol, "dir": direction, "j": j, "ih": ih, "t_dec": t_dec, "t_open": t_open, "ph": ph, "sl_t": lows_since - p.sl_buf * aj, "c_t": float(c[j]),
                                     "atr": float(aj), "imp_atr": im["imp_atr"], "atrp": float(aj / abs(c[j])), "sess": _session(t_dec), "risk_atr": float((c[j] - (lows_since - p.sl_buf * aj)) / aj),
                                     "bos": bool(_last_swing_high_break(sh_all, ih, j, c[j])), "ctx": ctx})
                    # BOS після ≥1 атаки
                    if runs:
                        lvl = _last_swing_high(sh_all, ih, j - 1)
                        if lvl is not None and c[j] > lvl[1] and lvl[0] not in bos_done:
                            bos_done.add(lvl[0])
                            ev = _make_event("BOS", symbol, ctx, btc, direction, sg, bars, atr1h, h1, m15, sh_all, sl_all, ih, io, ph, im, zone_low, zone_top, width, runs, j, p, bos=1.0)
                            if ev is not None:
                                _add(events, seen_ev, ev, bump)
                    continue
                if cur is None:
                    if not left and runs:      # повторний дотик без виходу з зони — це продовження попередньої атаки, не нова
                        runs[-1]["low"] = min(runs[-1]["low"], float(l[j]))
                        if c[j] < zone_low - p.zone_fail_atr * aj:
                            bump("zone_failed")
                            break
                        continue
                    cur = {"start": j, "low": float(l[j]), "minc": float(c[j]), "vol": float(v[j]), "n": 1}
                    left = False
                else:
                    cur["low"] = min(cur["low"], float(l[j]))
                    cur["minc"] = min(cur["minc"], float(c[j]))
                    cur["vol"] += float(v[j])
                    cur["n"] += 1
                if c[j] < zone_low - p.zone_fail_atr * aj:
                    bump("zone_failed")
                    break
                if c[j] > zone_top:          # атаку відбито: закриття назад над зоною
                    cur["end"] = j
                    runs.append(cur)
                    cur = None
                    bump("attacks")
                    ev = _make_event("EXIT", symbol, ctx, btc, direction, sg, bars, atr1h, h1, m15, sh_all, sl_all, ih, io, ph, im, zone_low, zone_top, width, runs, j, p, bos=0.0)
                    if ev is not None:
                        _add(events, seen_ev, ev, bump)
    return {"events": events, "pool": pool}


def _add(events: List[dict], seen: set, ev: dict, bump) -> None:
    key = (ev["type"], ev["dir"], ev["j"])
    if key in seen:
        # дедуплікація: той самий бар рішення з різних імпульсів — лишаємо сильніший імпульс
        for i, e in enumerate(events):
            if (e["type"], e["dir"], e["j"]) == key and ev["feat"]["imp_atr"] > e["feat"]["imp_atr"]:
                events[i] = ev
        bump("dedup")
        return
    seen.add(key)
    events.append(ev)
    bump(f"events_{ev['type']}")


def _last_swing_high(sh_all, ih: int, j: int):
    best = None
    for (i, ki, pr) in sh_all:
        if i > ih and ki <= j:
            best = (i, pr)
    return best


def _last_swing_high_break(sh_all, ih: int, j: int, close_j: float) -> bool:
    lv = _last_swing_high(sh_all, ih, j - 1)
    return lv is not None and close_j > lv[1]


def _make_event(etype, symbol, ctx, btc, direction, sg, bars, atr1h, h1, m15, sh_all, sl_all, ih, io, ph, im, zone_low, zone_top, width, runs, j, p, bos) -> Optional[dict]:
    h, l, c, o, v = bars["h"], bars["l"], bars["c"], bars["o"], bars["v"]
    aj = float(atr1h[j])
    atr_ih = float(atr1h[ih])
    t_open = float(h1["t"][j])
    t_dec = t_open + 3600.0
    last, first = runs[-1], runs[0]
    k = len(runs)
    depth = lambda r: (zone_top - r["low"]) / aj
    d_last, d_first = depth(last), depth(first)
    d_max = max(depth(r) for r in runs)
    mean_v = lambda r: r["vol"] / max(r["n"], 1)
    reb = lambda r: (float(c[r["end"]]) - r["low"]) / aj
    if k >= 2:
        prev = runs[-2]
        gap = last["start"] - prev["end"]
    else:
        gap = last["start"] - ih
    min_low_since = float(l[ih + 1:j + 1].min())
    attack_low = min(r["low"] for r in runs)
    sl_t = attack_low - p.sl_buf * aj          # структурна інвалідація: злам найглибшої атаки (мірор-простір)
    c_close_state = 0.0 if last["minc"] > zone_top else (1.0 if last["minc"] >= zone_low else 2.0)
    rng = (np.maximum(h[ih + 1:j + 1] - l[ih + 1:j + 1], 0.0)) / aj
    lv = np.log(np.maximum(v[ih + 1:j + 1], 1e-9))
    struct = _structure(sh_all, sl_all, ih, j, aj, p)
    last_sh = _last_swing_high(sh_all, ih, j - 1)
    bos_now = 1.0 if (last_sh is not None and c[j] > last_sh[1]) else 0.0
    if etype == "BOS":
        bos_now = 1.0
    # M15 усередині бару рішення (закриті 15-хв бари цієї години)
    i15 = int(np.searchsorted(m15["t"], t_open, side="left"))
    seg = slice(i15, i15 + 4)
    if i15 + 4 <= len(m15["t"]) and abs(m15["t"][i15] - t_open) < 1:
        m15_disp = float(np.max(m15["h"][seg] - m15["l"][seg]) / aj)
        hh, ll = float(m15["h"][i15 + 3]), float(m15["l"][i15 + 3])
        m15_loc = float((m15["c"][i15 + 3] - ll) / max(hh - ll, 1e-12))
        if sg < 0:
            m15_loc = 1.0 - m15_loc          # у дзеркалі: позиція закриття відносно напрямку угоди
    else:
        m15_disp, m15_loc = 0.0, 0.5
    room = _room(ctx, sg * float(c[j]), aj, t_dec, sg)
    mk = _market(ctx, btc, symbol, t_dec, t_open, sg)
    feat = {"k": float(k), "depth_last": float(d_last), "depth_first": float(d_first), "depth_max": float(d_max), "depth_pct_last": float((zone_top - last["low"]) / max(width, 1e-12)),
            "close_state_last": c_close_state, "rebound_last": float(reb(last)), "run_len_last": float(last["n"]), "close_loc_last": float((c[last["end"]] - l[last["end"]]) / max(h[last["end"]] - l[last["end"]], 1e-12)),
            "gap_bars": float(gap), "depth_ratio": float(d_last / max(d_first, 0.05)) if k >= 2 else 1.0, "rebound_ratio": float(reb(last) / max(reb(first), 0.05)) if k >= 2 else 1.0,
            "vol_ratio": float(mean_v(last) / max(mean_v(first), 1e-9)) if k >= 2 else 1.0, "bars_since_imp": float(j - ih), "imp_atr": float(im["imp_atr"]),
            "retr_max": float((ph - min_low_since) / max(im["imp"], 1e-12)), "width_atr": float(width / aj), "atr_ratio": float(aj / max(atr_ih, 1e-12)),
            "range_slope": _slope(rng), "vol_slope": _slope(lv), **struct, "bos": float(bos_now), "disp_body": float((c[j] - o[j]) / aj), "disp_range": float((h[j] - l[j]) / aj),
            "m15_disp": m15_disp, "m15_loc": m15_loc, "room": float(room), "rel4": float(mk["r4"]), "reld": float(mk["rd"]), "btc_al": float(np.clip((mk["btc4"] or 0.0) * sg, -3, 3)),
            "risk_atr": float((c[j] - sl_t) / aj)}
    return {"runs": [(r["start"], r["end"]) for r in runs], "type": etype, "symbol": symbol, "dir": direction, "j": j, "ih": ih, "t_dec": t_dec, "t_open": t_open, "ph": ph, "sl_t": float(sl_t), "c_t": float(c[j]), "atr": aj, "atrp": float(aj / abs(c[j])),
            "sess": _session(t_dec), "r4": mk["r4"], "rd": mk["rd"], "btcb": mk["btcb"], "feat": feat, "ctx": ctx, "risk_atr": feat["risk_atr"]}


def build_records(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], p: ZParams = ZParams(), stats: Optional[Dict[str, int]] = None, rnd_n: int = 40, with_controls: bool = True) -> Dict[str, List[dict]]:
    """Події + matched-пари + випадковий контроль, усе з outcome-мітками. Один контроль на подію, без повторів; coverage рахується."""
    st = stats if stats is not None else {}
    sc = scan(symbol, ctx, btc, p, st)
    m1 = ctx["m1"]
    out_ev: List[dict] = []
    out_ct: List[dict] = []
    for etype in ("EXIT", "BOS"):
        for direction in ("LONG", "SHORT"):
            evs = [e for e in sc["events"] if e["type"] == etype and e["dir"] == direction]
            pool = [q for q in sc["pool"] if q["dir"] == direction and (etype == "EXIT" or q["bos"])]
            used = set()
            sg = 1.0 if direction == "LONG" else -1.0
            buckets: Dict[tuple, List[dict]] = {}
            for q in pool:
                buckets.setdefault((q["sess"], q["r4"], q["rd"]), []).append(q)
            for ev in evs:
                rec = _outcome(m1, ev, sg, p)
                if rec is None:
                    st["ev_no_outcome"] = st.get("ev_no_outcome", 0) + 1
                    continue
                st[f"cov_total_{etype}"] = st.get(f"cov_total_{etype}", 0) + 1
                best, bd = None, 1e9
                for q in (buckets.get((ev["sess"], ev["r4"], ev["rd"]), []) if with_controls else []):
                    if q["j"] in used or q["ih"] == ev["ih"]:
                        continue          # контроль НЕ з тієї самої корекції: бари до майбутньої атаки умовні на її настання (lookahead-зсув, виявлено калібруванням)
                    ri, ra, rr = q["imp_atr"] / ev["feat"]["imp_atr"], q["atrp"] / ev["atrp"], q["risk_atr"] / max(ev["risk_atr"], 1e-9)
                    if not (p.cal_imp[0] <= ri <= p.cal_imp[1] and p.cal_atrp[0] <= ra <= p.cal_atrp[1] and p.cal_risk[0] <= rr <= p.cal_risk[1]):
                        continue
                    d = abs(ri - 1.0) + abs(math.log(ra)) + abs(math.log(rr)) + (0.0 if q["btcb"] == ev["btcb"] else 1.0)
                    if d < bd:
                        bd, best = d, q
                base = {"runs": ev.get("runs"), "j": ev["j"], "symbol": symbol, "dir": direction, "etype": etype, "day": int(ev["t_dec"] // 86400), "t_dec": ev["t_dec"], "feat": ev["feat"], "k": int(ev["feat"]["k"])}
                crec = None
                if best is not None:
                    crec = _outcome(m1, best, sg, p)
                    if crec is not None:
                        used.add(best["j"])
                pid = f"{symbol}:{direction}:{etype}:{ev['j']}"
                out_ev.append({**base, **rec, "pair": pid, "matched": crec is not None, "kind": "event"})
                if crec is not None:
                    out_ct.append({**base, **crec, "pair": pid, "kind": "matched", "match_d": float(bd)})
                    st[f"cov_matched_{etype}"] = st.get(f"cov_matched_{etype}", 0) + 1
    out_rnd = random_controls(symbol, ctx, rnd_n, p) if with_controls else []
    return {"events": out_ev, "matched": out_ct, "random": out_rnd}


def _outcome(m1, e: dict, sg: float, p: ZParams) -> Optional[dict]:
    ie = _entry_index(m1, e["t_dec"])
    if ie is None:
        return None
    entry = float(m1["o"][ie])
    sl = sg * e["sl_t"]
    return O.outcome_record(m1, ie, "LONG" if sg > 0 else "SHORT", entry, sl, e["atr"], p.horizon_sec)


def random_controls(symbol: str, ctx: Dict[str, Any], n: int, p: ZParams, seed: int = 21) -> List[dict]:
    """Допоміжний контроль: випадкові години/напрям; SL = екстремум 12 барів ∓ 0,5 ATR_H1. Той самий outcome."""
    m1 = ctx["m1"]
    if "h1" not in ctx:
        ctx["h1"] = F.resample(m1, 3600)
        ctx["atr1h"] = F.atr(ctx["h1"], 14)
    h1, atr1h = ctx["h1"], ctx["atr1h"]
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
        rec = O.outcome_record(m1, ie, direction, entry, sl, float(a), p.horizon_sec)
        if rec is None:
            continue
        out.append({"symbol": symbol, "dir": direction, "etype": "RANDOM", "day": int(t_dec // 86400), "t_dec": t_dec, "feat": {}, "k": 0, "pair": None, "kind": "random", **rec})
    return out


def variance_report(rows: List[dict], names=EVENT_FEATURES) -> List[dict]:
    """Автоматична перевірка змінності: константа/майже константа (std≈0 або одне значення ≥95%) = НЕПРИДАТНА."""
    res = []
    for k in names:
        x = np.array([r["feat"].get(k, float("nan")) for r in rows], dtype=float)
        x = x[~np.isnan(x)]
        if len(x) < 30:
            res.append({"feature": k, "n": len(x), "std": float("nan"), "top_share": float("nan"), "usable": False, "why": "мало даних"})
            continue
        vals, cnt = np.unique(np.round(x, 6), return_counts=True)
        top = float(cnt.max() / len(x))
        std = float(x.std())
        usable = std > 1e-9 and top < 0.95
        res.append({"feature": k, "n": len(x), "std": std, "top_share": top, "usable": bool(usable), "why": "" if usable else ("константа" if std <= 1e-9 else f"одне значення {top * 100:.0f}%")})
    return res
