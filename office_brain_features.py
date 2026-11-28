"""Ознаки для Market Brain: де лежить ліквідність, чи її забрали й повернули, що робить OI відносно ціни, перекіс натовпу, ширина ринку.

Чисті функції без мережі. Кожна бере ТІЛЬКИ дані, що існували до моменту `now` (рядки з пізнішим часом ігноруються) — так само
працює живий цикл і перевірка на історії без look-ahead. Порогові константи — ГІПОТЕЗИ, не калібровані на історії: вони нічого не
вирішують самі, поки дослідження (scripts/brain_study.py) не покаже, які ознаки справді передують рухам.
Свічка: dict(open, high, low, close, ts ISO), по зростанню часу.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SWEEP_MIN_PCT = 0.03      # виніс: максимум вийшов за рівень щонайменше на стільки % ціни
SWEEP_LOOKBACK = 24       # скільки останніх свічок шукаємо виніс
EQUAL_TOL_PCT = 0.10      # однакові максимуми/мінімуми: різниця менша за це, %
LIQ_MAX_DIST_PCT = 1.5    # ліквідність далі за стільки від ціни не розглядаємо
OI_BUILD_PCT = 2.0        # OI зріс за 30 хв щонайменше на стільки %
PRICE_FLAT_PCT = 0.15     # ціна «не рухається»: |зміна| менша за це, %
FUNDING_CROWD_PCT = 0.01  # funding (за 8 год, %) від якого натовп «перекошений»
LS_CROWD_HI = 1.5         # покупців/продавців (рахунки) від якого натовп у лонгах
LS_CROWD_LO = 0.67        # і відповідно в шортах
BREADTH_HI = 0.65         # частка монет, що рухаються в один бік


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def _t(c: Dict[str, Any]) -> Optional[float]:
    try:
        d = datetime.fromisoformat(str(c.get("ts")).replace("Z", "+00:00"))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except Exception:  # noqa: BLE001
        return None


def upto(candles: Any, now: float, bar_sec: float) -> List[Dict[str, Any]]:
    """Лише ЗАКРИТІ свічки до моменту now (open_time + bar_sec ≤ now): майбутнього та формованої свічки немає."""
    out = []
    for c in candles if isinstance(candles, list) else []:
        t = _t(c)
        if t is not None and t + bar_sec <= now and _f(c.get("close")) is not None:
            out.append(c)
    return out


# ------------------------------------------------------------------ рівні й ліквідність
def named_levels(now: float, daily: Any, week: Optional[Dict[str, Any]] = None, month: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """PDH/PDL (вчора), PWH/PWL, поточні тижневі/місячні H/L — з денних свічок до now; week/month — готовий знімок office_time_structure."""
    out: Dict[str, float] = {}
    days = upto(daily, now, 86400.0)
    if days:
        out["PDH"], out["PDL"] = float(days[-1]["high"]), float(days[-1]["low"])
    for key, snap, hi, lo in (("W", week, "WH", "WL"), ("M", month, "MH", "ML")):
        if snap:
            if _f(snap.get("high")) is not None:
                out[hi] = float(snap["high"])
            if _f(snap.get("low")) is not None:
                out[lo] = float(snap["low"])
            if _f(snap.get("open")) is not None:
                out[key + "O"] = float(snap["open"])
            prev = snap.get("prev") or {}
            if _f(prev.get("high")) is not None:
                out["P" + hi] = float(prev["high"])
            if _f(prev.get("low")) is not None:
                out["P" + lo] = float(prev["low"])
    return out


LEVEL_UA = {"PDH": "максимум вчора", "PDL": "мінімум вчора", "WH": "максимум тижня", "WL": "мінімум тижня", "MH": "максимум місяця", "ML": "мінімум місяця",
            "PWH": "максимум минулого тижня", "PWL": "мінімум минулого тижня", "PMH": "максимум минулого місяця", "PML": "мінімум минулого місяця",
            "WO": "відкриття тижня", "MO": "відкриття місяця", "EQH": "рівні максимуми", "EQL": "рівні мінімуми"}


def swings(candles: List[Dict[str, Any]], k: int = 2) -> Dict[str, List[Dict[str, float]]]:
    """Локальні максимуми/мінімуми: свічка вища (нижча) за k сусідів з обох боків; підтверджується лише після k закритих свічок."""
    hi, lo = [], []
    for i in range(k, len(candles) - k):
        h, l_ = float(candles[i]["high"]), float(candles[i]["low"])
        if all(h > float(candles[i + j]["high"]) for j in range(-k, k + 1) if j) :
            hi.append({"i": i, "px": h})
        if all(l_ < float(candles[i + j]["low"]) for j in range(-k, k + 1) if j):
            lo.append({"i": i, "px": l_})
    return {"highs": hi, "lows": lo}


def liquidity(price: float, levels: Dict[str, float], c15: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Ліквідність над і під ціною в межах LIQ_MAX_DIST_PCT: іменовані рівні + «рівні» максимуми/мінімуми зі свінгів 15m."""
    above: List[Dict[str, Any]] = []
    below: List[Dict[str, Any]] = []

    def add(kind: str, px: float) -> None:
        d = (px / price - 1.0) * 100.0
        if abs(d) <= LIQ_MAX_DIST_PCT:
            (above if px > price else below).append({"kind": kind, "px": px, "dist_pct": round(d, 3)})

    for k, v in levels.items():
        if k not in ("WO", "MO"):
            add(k, v)
    sw = swings(c15[-96:])
    for key, kind, bucket in (("highs", "EQH", above), ("lows", "EQL", below)):
        pts = sorted(p["px"] for p in sw[key])
        for a, b in zip(pts, pts[1:]):
            if abs(b / a - 1.0) * 100.0 <= EQUAL_TOL_PCT:
                add(kind, max(a, b) if kind == "EQH" else min(a, b))
    above.sort(key=lambda x: x["px"])
    below.sort(key=lambda x: -x["px"])
    return {"above": above, "below": below}


def sweep(bars: List[Dict[str, Any]], level: float, side: str, lookback: int = SWEEP_LOOKBACK) -> Optional[Dict[str, Any]]:
    """Виніс ліквідності: side='up' — максимум вийшов над level не менше ніж на SWEEP_MIN_PCT, а остання свічка закрилась нижче level.
    side='down' — дзеркально. Повертає {level, extreme, back_close, bars_ago} або None."""
    rows = bars[-lookback:]
    if not rows or level <= 0:
        return None
    last = float(rows[-1]["close"])
    if side == "up":
        ext = max(float(c["high"]) for c in rows)
        if (ext / level - 1.0) * 100.0 >= SWEEP_MIN_PCT and last < level:
            i = max(range(len(rows)), key=lambda j: float(rows[j]["high"]))
            return {"level": level, "extreme": ext, "back_close": last, "bars_ago": len(rows) - 1 - i}
    else:
        ext = min(float(c["low"]) for c in rows)
        if (1.0 - ext / level) * 100.0 >= SWEEP_MIN_PCT and last > level:
            i = min(range(len(rows)), key=lambda j: float(rows[j]["low"]))
            return {"level": level, "extreme": ext, "back_close": last, "bars_ago": len(rows) - 1 - i}
    return None


# ------------------------------------------------------------------ OI, натовп, ширина
def pct_change(candles: List[Dict[str, Any]], minutes: float, bar_min: float) -> Optional[float]:
    n = int(round(minutes / bar_min))
    if len(candles) < n + 1:
        return None
    a, b = float(candles[-1 - n]["close"]), float(candles[-1]["close"])
    return round((b / a - 1.0) * 100.0, 3) if a else None


def oi_change(oi_hist: Any, now: float, minutes: float = 30.0) -> Optional[float]:
    """Зміна OI за `minutes` хв за точками {ts(unix), oi} з часом ≤ now."""
    pts = sorted(((_f(p.get("ts")), _f(p.get("oi"))) for p in (oi_hist if isinstance(oi_hist, list) else [])), key=lambda x: (x[0] or 0))
    pts = [(t, v) for t, v in pts if t is not None and v is not None and t <= now]
    if len(pts) < 2:
        return None
    t1, v1 = pts[-1]
    base = [(t, v) for t, v in pts if t <= t1 - minutes * 60.0 + 1.0]
    if not base or v1 is None or not base[-1][1]:
        return None
    return round((v1 / base[-1][1] - 1.0) * 100.0, 3)


def breadth(basket_close_now: Dict[str, float], basket_close_then: Dict[str, float]) -> Optional[Dict[str, Any]]:
    up = down = n = 0
    for s, now_px in basket_close_now.items():
        old = basket_close_then.get(s)
        if old and now_px:
            n += 1
            up += now_px > old
            down += now_px < old
    return {"up": up, "down": down, "n": n} if n >= 8 else None


def compute(now: float, *, c1: Any, c5: Any, c15: Any, daily: Any, week: Optional[Dict[str, Any]] = None, month: Optional[Dict[str, Any]] = None,
            oi_hist: Any = None, funding_pct: Optional[float] = None, ls_ratio: Optional[float] = None, basket_now: Optional[Dict[str, float]] = None,
            basket_then: Optional[Dict[str, float]] = None, eth_c15: Any = None) -> Dict[str, Any]:
    """Усі ознаки для BTC (або іншого інструмента) на момент now. Нема даних → поле None (нічого не вигадуємо)."""
    b1, b5, b15 = upto(c1, now, 60.0), upto(c5, now, 300.0), upto(c15, now, 900.0)
    if not b15:
        return {"ok": False, "reason": "немає закритих свічок 15m до цього моменту"}
    price = float((b1 or b5 or b15)[-1]["close"])
    lv = named_levels(now, daily, week, month)
    liq = liquidity(price, lv, b15)
    sw_up = sw_dn = None
    bars = b5 or b15
    for z in liq["above"]:
        s = sweep(bars, z["px"], "up")
        if s:
            sw_up = dict(s, kind=z["kind"])
            break
    for z in liq["below"]:
        s = sweep(bars, z["px"], "down")
        if s:
            sw_dn = dict(s, kind=z["kind"])
            break
    # виніс ліквідності, що лежала НАД ціною на момент початку вікна: рівні рахуємо відносно ціни 24 свічки тому
    if sw_up is None or sw_dn is None:
        ref = float(bars[-SWEEP_LOOKBACK]["close"]) if len(bars) >= SWEEP_LOOKBACK else price
        liq0 = liquidity(ref, lv, b15)
        if sw_up is None:
            for z in liq0["above"]:
                s = sweep(bars, z["px"], "up")
                if s:
                    sw_up = dict(s, kind=z["kind"])
                    break
        if sw_dn is None:
            for z in liq0["below"]:
                s = sweep(bars, z["px"], "down")
                if s:
                    sw_dn = dict(s, kind=z["kind"])
                    break
    p30 = pct_change(b5, 30, 5) if len(b5) > 6 else pct_change(b15, 30, 15)
    p60 = pct_change(b5, 60, 5) if len(b5) > 12 else pct_change(b15, 60, 15)
    sw = swings(b15[-64:])
    below_lows = [p["px"] for p in sw["lows"] if p["px"] < price]
    above_highs = [p["px"] for p in sw["highs"] if p["px"] > price]
    eth60 = pct_change(upto(eth_c15, now, 900.0), 60, 15) if eth_c15 else None
    return {"ok": True, "t": now, "price": price, "levels": lv, "liquidity": liq, "sweep_up": sw_up, "sweep_down": sw_dn,
            "price_30m": p30, "price_60m": p60, "oi_30m": oi_change(oi_hist, now, 30.0), "oi_60m": oi_change(oi_hist, now, 60.0),
            "funding_pct": _f(funding_pct), "ls_ratio": _f(ls_ratio), "breadth": breadth(basket_now or {}, basket_then or {}),
            "swing_low": max(below_lows) if below_lows else None, "swing_high": min(above_highs) if above_highs else None,
            "eth_60m": eth60, "atr15_pct": _atr_pct(b15)}


def _atr_pct(c15: List[Dict[str, Any]], n: int = 14) -> Optional[float]:
    rows = c15[-(n + 1):]
    if len(rows) < n + 1:
        return None
    trs = []
    for a, b in zip(rows, rows[1:]):
        trs.append(max(float(b["high"]) - float(b["low"]), abs(float(b["high"]) - float(a["close"])), abs(float(b["low"]) - float(a["close"]))))
    px = float(rows[-1]["close"])
    return round(sum(trs) / len(trs) / px * 100.0, 4) if px else None
