"""Рівні як ЗОНИ (Герчик): кластери свінгів у допуску ≤0,5×ATR, дзеркальні рівні (були і опором, і підтримкою), PDH/PDL і тижневі. Події за ЗАКРИТИМИ свічками:
- хибний пробій (ЛП): тінь за зону ≥0,1×ATR, а закриття повернулось всередину/назад;
- закріплення: ≥2 закриття поспіль за зоною;
- ретест: після закріплення ціна повертається в зону, а закриття знову за зоною.
Теги для підтверджень: level_false_break, level_retest, level_hold. Рівень без ≥2 торкань зоною не вважається."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office_patterns import atr as _atr, closed_only

K = 2
ZONE_W_ATR = 0.5
MIN_TOUCH = 2
PIERCE_ATR = 0.1


def _rows(c: Any, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    return closed_only([r for r in (c or []) if isinstance(r, dict)], now_ts)


def _swings(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for i in range(K, len(rows) - K):
        h, l = float(rows[i]["high"]), float(rows[i]["low"])
        if all(h > float(rows[j]["high"]) for j in range(i - K, i + K + 1) if j != i):
            out.append({"i": i, "p": h, "t": "H"})
        if all(l < float(rows[j]["low"]) for j in range(i - K, i + K + 1) if j != i):
            out.append({"i": i, "p": l, "t": "L"})
    return out


def zones(candles: Any, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Зони рівнів: кластери свінгів (H і L разом — рівень працював по-різному) шириною ≤0,5×ATR, ≥2 торкань. mirror=True, якщо зона була і опором (H), і підтримкою (L)."""
    rows = _rows(candles, now_ts)[-300:]
    a = _atr(rows) if len(rows) >= 20 else None
    if not a:
        return []
    sw = sorted(_swings(rows), key=lambda s: s["p"])
    out: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = []
    for s in sw:
        if cur and s["p"] - cur[0]["p"] > ZONE_W_ATR * a:
            if len(cur) >= MIN_TOUCH:
                out.append(cur)
            cur = []
        cur.append(s)
    if len(cur) >= MIN_TOUCH:
        out.append(cur)
    res = []
    for grp in out:
        lo, hi = min(x["p"] for x in grp), max(x["p"] for x in grp)
        kinds = {x["t"] for x in grp}
        res.append({"lo": lo, "hi": hi, "touches": len(grp), "mirror": kinds == {"H", "L"}, "last": max(x["i"] for x in grp)})
    return sorted(res, key=lambda z: z["lo"])


def previous_levels(daily: Any, weekly: Any) -> Dict[str, Optional[float]]:
    def prev(rows, key):
        rr = [r for r in (rows or []) if isinstance(r, dict)]
        return float(rr[-2][key]) if len(rr) >= 2 else None

    return {"PDH": prev(daily, "high"), "PDL": prev(daily, "low"), "PWH": prev(weekly, "high"), "PWL": prev(weekly, "low")}


def events(candles: Any, zone: Dict[str, Any], side: str, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Події навколо зони для сценарію `side` (LONG — від підтримки, SHORT — від опору) на останніх свічках."""
    rows = _rows(candles, now_ts)[-60:]
    a = _atr(rows) if len(rows) >= 15 else None
    if not a:
        return []
    lo, hi = zone["lo"], zone["hi"]
    long_ = str(side).upper() != "SHORT"
    out: List[Dict[str, Any]] = []
    last = rows[-1]
    # хибний пробій: LONG — тінь під зоною і закриття назад над її низом; SHORT — дзеркально
    if long_ and float(last["low"]) < lo - PIERCE_ATR * a and float(last["close"]) > lo:
        out.append({"kind": "level_false_break", "why": f"тінь під зоною {lo:.6g}, закриття повернулось"})
    if (not long_) and float(last["high"]) > hi + PIERCE_ATR * a and float(last["close"]) < hi:
        out.append({"kind": "level_false_break", "why": f"тінь над зоною {hi:.6g}, закриття повернулось"})
    # закріплення й ретест (пробій зони ВГОРУ для LONG, ВНИЗ для SHORT)
    beyond = [((float(r["close"]) > hi) if long_ else (float(r["close"]) < lo)) for r in rows]
    for i in range(len(rows) - 1, 0, -1):
        c0 = i
        while c0 > 0 and beyond[c0 - 1]:
            c0 -= 1
        # закріплення = ≥2 закриття поспіль за зоною ПІСЛЯ пробою (був хоч один закритий бар не за зоною раніше, у межах вікна)
        if beyond[i] and beyond[i - 1] and c0 >= 1:
            # закріплення знайдено на i-1,i; після нього — ретест: свічка торкнулась зони, а закриття знову за нею
            for j in range(c0 + 2, len(rows)):
                r = rows[j]
                touched = (float(r["low"]) <= hi) if long_ else (float(r["high"]) >= lo)
                if touched and beyond[j]:
                    out.append({"kind": "level_retest", "why": f"ретест зони {lo:.6g}–{hi:.6g} після закріплення"})
                    break
            if i >= len(rows) - 6 and not [e for e in out if e["kind"] == "level_retest"]:
                out.append({"kind": "level_hold", "why": f"≥2 закриття поспіль за зоною {lo:.6g}–{hi:.6g}"})
            break
    if any(e["kind"] in ("level_retest", "level_hold") for e in out):
        out = [e for e in out if e["kind"] != "level_false_break"]   # тінь у зону після пробою — це ретест, а не хибний пробій
    return out


def tags_for(candles: Any, side: str, zone_lo: Any, zone_hi: Any, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Теги подій біля ЗОНИ сценарію; зона береться з кластерів рівнів, що перетинають zone_lo..zone_hi (інакше — нічого)."""
    try:
        zl, zh = sorted((float(zone_lo), float(zone_hi)))
    except (TypeError, ValueError):
        return []
    out: List[Dict[str, Any]] = []
    for z in zones(candles, now_ts):
        if z["hi"] >= zl and z["lo"] <= zh:
            out.extend(events(candles, z, side, now_ts))
    seen, res = set(), []
    for t in out:
        if t["kind"] not in seen:
            seen.add(t["kind"]); res.append(t)
    return res
