"""ICT/SMC як формальні правила на закритих свічках: пули ліквідності BSL/SSL, sweep, BOS, CHoCH, displacement, FVG (з mitigation), order block і breaker,
premium/discount та OTE. Кожне правило має критерії виявлення, актуальності й скасування; тег = `kind` у журналі. Допуски — від ATR(14).
Теги, які метод віддає для підтверджень входу: sweep_pool, bos, choch, displacement, fvg_retest, ob_retest, breaker_retest, ote."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from office_patterns import atr as _atr, closed_only

K = 2
EQ_TOL_ATR = 0.25          # «рівні» максимуми/мінімуми: розкид ≤ 0,25×ATR
DISP_BODY_ATR = 1.5        # displacement: тіло ≥ 1,5×ATR
DISP_CLOSE_FRAC = 0.75     # закриття в крайній чверті діапазону свічки
FVG_MIN_ATR = 0.25
OTE_LO, OTE_HI = 0.62, 0.79


def _rows(candles: Any, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    return closed_only([r for r in (candles or []) if isinstance(r, dict)], now_ts)


def swings(rows: List[Dict[str, Any]]) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    hi, lo = [], []
    for i in range(K, len(rows) - K):
        h, l = float(rows[i]["high"]), float(rows[i]["low"])
        if all(h > float(rows[j]["high"]) for j in range(i - K, i + K + 1) if j != i):
            hi.append((i, h))
        if all(l < float(rows[j]["low"]) for j in range(i - K, i + K + 1) if j != i):
            lo.append((i, l))
    return hi, lo


def liquidity_pools(rows: List[Dict[str, Any]], a: float) -> Dict[str, List[Dict[str, Any]]]:
    """BSL — рівні максимуми (≥2 свінги в допуску) над ринком; SSL — рівні мінімуми. Пул «живий», доки його не пробито закриттям."""
    hi, lo = swings(rows)
    out: Dict[str, List[Dict[str, Any]]] = {"BSL": [], "SSL": []}
    for name, pts, up in (("BSL", hi, True), ("SSL", lo, False)):
        used = set()
        for i, (ix, v) in enumerate(pts):
            grp = [(jx, w) for j, (jx, w) in enumerate(pts) if j not in used and abs(w - v) <= EQ_TOL_ATR * a]
            if len(grp) >= 2:
                lvl = max(w for _j, w in grp) if up else min(w for _j, w in grp)
                first = min(jx for jx, _w in grp)
                last = max(jx for jx, _w in grp)
                closed_through = any((float(r["close"]) > lvl) if up else (float(r["close"]) < lvl) for r in rows[last + 1:])
                if not closed_through:
                    out[name].append({"level": lvl, "touches": len(grp), "first": first, "last": last})
                used.update(j for j, (jx, w) in enumerate(pts) if (jx, w) in grp)
    return out


def sweeps(rows: List[Dict[str, Any]], pools: Dict[str, List[Dict[str, Any]]], since: int = 0) -> List[Dict[str, Any]]:
    """Sweep: тінь за рівень пулу, а ЗАКРИТТЯ повернулось назад. BSL-sweep → ведмежий сигнал (SHORT), SSL-sweep → бичачий (LONG)."""
    out = []
    for name, side, up in (("BSL", "SHORT", True), ("SSL", "LONG", False)):
        for p in pools.get(name, []):
            for i in range(max(p["last"] + 1, since), len(rows)):
                r = rows[i]
                if (up and float(r["high"]) > p["level"] and float(r["close"]) < p["level"]) or ((not up) and float(r["low"]) < p["level"] and float(r["close"]) > p["level"]):
                    out.append({"kind": "sweep_pool", "side": side, "pool": name, "level": p["level"], "idx": i})
                    break
                if (up and float(r["close"]) > p["level"]) or ((not up) and float(r["close"]) < p["level"]):
                    break   # закріплення за рівнем — це пробій, а не sweep
    return out


def structure(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Тренд за двома останніми свінгами; BOS — закриття за останнім свінгом У бік тренду (продовження), CHoCH — закриття за останнім свінгом ПРОТИ тренду."""
    hi, lo = swings(rows)
    res: Dict[str, Any] = {"trend": None, "events": []}
    if len(hi) < 2 or len(lo) < 2:
        return res
    up = hi[-1][1] > hi[-2][1] and lo[-1][1] > lo[-2][1]
    dn = hi[-1][1] < hi[-2][1] and lo[-1][1] < lo[-2][1]
    res["trend"] = "UP" if up else ("DOWN" if dn else None)
    last_idx = max(hi[-1][0], lo[-1][0])
    for i in range(last_idx + 1, len(rows)):
        cl = float(rows[i]["close"])
        if cl > hi[-1][1]:
            res["events"].append({"kind": "bos" if res["trend"] == "UP" else "choch", "side": "LONG", "level": hi[-1][1], "idx": i})
            break
        if cl < lo[-1][1]:
            res["events"].append({"kind": "bos" if res["trend"] == "DOWN" else "choch", "side": "SHORT", "level": lo[-1][1], "idx": i})
            break
    return res


def displacement(rows: List[Dict[str, Any]], a: float) -> List[Dict[str, Any]]:
    out = []
    for i, r in enumerate(rows):
        o, c, h, l = float(r["open"]), float(r["close"]), float(r["high"]), float(r["low"])
        rng = h - l
        if rng <= 0 or abs(c - o) < DISP_BODY_ATR * a:
            continue
        pos = (c - l) / rng
        if c > o and pos >= DISP_CLOSE_FRAC:
            out.append({"kind": "displacement", "side": "LONG", "idx": i})
        elif c < o and pos <= 1 - DISP_CLOSE_FRAC:
            out.append({"kind": "displacement", "side": "SHORT", "idx": i})
    return out


def fvgs(rows: List[Dict[str, Any]], a: float) -> List[Dict[str, Any]]:
    """Три свічки: бичачий FVG — low[i+1] > high[i-1] (≥0,25×ATR); ведмежий дзеркально. Стан: OPEN / MITIGATED (ціна зайшла в проміжок) / FILLED (закриття за ним)."""
    out = []
    for i in range(1, len(rows) - 1):
        a_hi, a_lo = float(rows[i - 1]["high"]), float(rows[i - 1]["low"])
        c_hi, c_lo = float(rows[i + 1]["high"]), float(rows[i + 1]["low"])
        if c_lo - a_hi >= FVG_MIN_ATR * a:
            lo_, hi_, side = a_hi, c_lo, "LONG"
        elif a_lo - c_hi >= FVG_MIN_ATR * a:
            lo_, hi_, side = c_hi, a_lo, "SHORT"
        else:
            continue
        state = "OPEN"
        for r in rows[i + 2:]:
            if side == "LONG":
                if float(r["close"]) < lo_:
                    state = "FILLED"; break
                if float(r["low"]) <= hi_:
                    state = "MITIGATED"
            else:
                if float(r["close"]) > hi_:
                    state = "FILLED"; break
                if float(r["high"]) >= lo_:
                    state = "MITIGATED"
        out.append({"kind": "fvg", "side": side, "lo": lo_, "hi": hi_, "idx": i, "state": state})
    return out


def order_blocks(rows: List[Dict[str, Any]], a: float) -> List[Dict[str, Any]]:
    """OB — остання протилежна свічка перед displacement у бік сценарію. Актуальний, доки закриття не пробило його межу; пробитий стає breaker (flip)."""
    out = []
    for d in displacement(rows, a):
        i = d["idx"] - 1
        while i >= 0 and ((float(rows[i]["close"]) > float(rows[i]["open"])) == (d["side"] == "LONG")):
            i -= 1
        if i < 0:
            continue
        o = rows[i]
        lo_, hi_ = float(o["low"]), float(o["high"])
        state, flip_idx = "ACTIVE", None
        for j in range(d["idx"] + 1, len(rows)):
            cl = float(rows[j]["close"])
            if (d["side"] == "LONG" and cl < lo_) or (d["side"] == "SHORT" and cl > hi_):
                state, flip_idx = "BREAKER", j
                break
        out.append({"kind": "ob" if state == "ACTIVE" else "breaker", "side": d["side"] if state == "ACTIVE" else ("SHORT" if d["side"] == "LONG" else "LONG"),
                    "lo": lo_, "hi": hi_, "idx": i, "state": state, "flip_idx": flip_idx})
    return out


def dealing_range(rows: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    hi, lo = swings(rows)
    if not hi or not lo:
        return None
    h, l = hi[-1][1], lo[-1][1]
    return {"high": h, "low": l, "mid": (h + l) / 2.0} if h > l else None


def zone_of(price: float, rng: Dict[str, float], side: str) -> Dict[str, Any]:
    """Premium/discount відносно рівноваги діапазону; OTE — 0,62–0,79 відкату від протилежного краю. LONG цікавий у discount/OTE, SHORT — у premium/OTE."""
    span = rng["high"] - rng["low"]
    frac_from_low = (price - rng["low"]) / span
    prem = price > rng["mid"]
    if str(side).upper() != "SHORT":
        ret = (rng["high"] - price) / span            # відкат вниз від максимуму
    else:
        ret = (price - rng["low"]) / span
    return {"zone": "PREMIUM" if prem else "DISCOUNT", "frac": round(frac_from_low, 3), "ote": OTE_LO <= ret <= OTE_HI}


def tags_for(candles: Any, side: str, zone_lo: Any = None, zone_hi: Any = None, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Теги підтвердження в бік side: sweep_pool, bos, choch, displacement, fvg_retest, ob_retest, breaker_retest, ote — лише за фактом на закритих свічках."""
    rows = _rows(candles, now_ts)[-120:]
    if len(rows) < 15:
        return []
    a = _atr(rows)
    if not a:
        return []
    side = str(side).upper()
    last = rows[-1]
    out: List[Dict[str, Any]] = []
    pools = liquidity_pools(rows, a)
    for s in sweeps(rows, pools, since=len(rows) - 6):
        if s["side"] == side:
            out.append({"kind": "sweep_pool", "why": f"{s['pool']} {s['level']:.6g} знято тінню, закриття повернулось"})
    st = structure(rows)
    for e in st["events"]:
        if e["side"] == side and e["idx"] >= len(rows) - 4:
            out.append({"kind": e["kind"], "why": f"закриття за {e['level']:.6g}"})
    for d in displacement(rows, a):
        if d["side"] == side and d["idx"] >= len(rows) - 4:
            out.append({"kind": "displacement", "why": "сильна свічка ≥1,5×ATR із закриттям біля краю"})
            break
    lo_, hi_ = float(last["low"]), float(last["high"])
    for g in fvgs(rows, a)[-6:]:
        if g["side"] == side and g["state"] == "MITIGATED" and lo_ <= g["hi"] and hi_ >= g["lo"] and g["idx"] < len(rows) - 3:
            out.append({"kind": "fvg_retest", "why": f"ретест FVG {g['lo']:.6g}–{g['hi']:.6g}"})
            break
    for ob in order_blocks(rows, a)[-4:]:
        if ob["side"] == side and lo_ <= ob["hi"] and hi_ >= ob["lo"] and ob["idx"] < len(rows) - 3 and (ob["kind"] == "ob" or (ob["flip_idx"] or 0) < len(rows) - 1):
            out.append({"kind": "ob_retest" if ob["kind"] == "ob" else "breaker_retest", "why": f"ретест {'OB' if ob['kind'] == 'ob' else 'breaker'} {ob['lo']:.6g}–{ob['hi']:.6g}"})
            break
    rng = dealing_range(rows)
    if rng:
        z = zone_of(float(last["close"]), rng, side)
        if z["ote"]:
            out.append({"kind": "ote", "why": f"ціна в OTE 0,62–0,79 діапазону ({z['zone'].lower()})"})
    return out
