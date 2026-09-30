"""Вайкоф: торговий діапазон, spring/upthrust і тест — лише за ціною й обсягом на закритих свічках. Фаза визначається тільки коли є і діапазон після тренду,
і подія spring/upthrust з тестом; інакше — «фаза не визначена». Теги: spring, spring_test, upthrust, upthrust_test."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office_patterns import atr as _atr, closed_only

RANGE_MIN_BARS = 20
TOUCH_TOL_ATR = 0.5
MAX_WIDTH_ATR = 8.0
PRIOR_TREND_ATR = 3.0


def _v(r: Dict[str, Any]) -> float:
    try:
        return float(r.get("volume") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def trading_range(rows: List[Dict[str, Any]], a: float) -> Optional[Dict[str, Any]]:
    """Діапазон у вікні до останніх 8 свічок: ≥2 торкання верху й низу (допуск 0,5×ATR), ширина ≤ 8×ATR. Подія (spring/upthrust) шукається ПІСЛЯ вікна."""
    if len(rows) < RANGE_MIN_BARS + 8:
        return None
    win = rows[-(RANGE_MIN_BARS + 8):-8]
    hi = max(float(r["high"]) for r in win)
    lo = min(float(r["low"]) for r in win)
    if hi - lo > MAX_WIDTH_ATR * a or hi - lo < 1.0 * a:
        return None
    tol = TOUCH_TOL_ATR * a
    if sum(1 for r in win if float(r["high"]) >= hi - tol) < 2 or sum(1 for r in win if float(r["low"]) <= lo + tol) < 2:
        return None
    return {"high": hi, "low": lo, "start": len(rows) - (RANGE_MIN_BARS + 8), "end": len(rows) - 9}


def events(candles: Any, now_ts: Optional[float] = None) -> Dict[str, Any]:
    rows = closed_only([r for r in (candles or []) if isinstance(r, dict)], now_ts)[-120:]
    res: Dict[str, Any] = {"range": None, "events": [], "phase": "фаза не визначена"}
    a = _atr(rows) if len(rows) >= 14 else None
    if not a:
        return res
    rg = trading_range(rows, a)
    if not rg:
        return res
    res["range"] = rg
    vols = [_v(r) for r in rows[rg["start"]:rg["end"] + 1]]
    avg_v = sum(vols) / len(vols) if vols else 0.0
    has_vol = avg_v > 0
    after = rows[rg["end"] + 1:]
    prior = rows[max(0, rg["start"] - 20):rg["start"]]
    prior_drop = (float(prior[0]["close"]) - float(prior[-1]["close"])) if len(prior) >= 5 else 0.0
    for i, r in enumerate(after):
        lo_, hi_, cl = float(r["low"]), float(r["high"]), float(r["close"])
        ev = None
        if lo_ < rg["low"] - 0.05 * a and cl > rg["low"]:
            ev = ("spring", "LONG", lo_)
        elif hi_ > rg["high"] + 0.05 * a and cl < rg["high"]:
            ev = ("upthrust", "SHORT", hi_)
        if not ev:
            if cl < rg["low"] - 0.5 * a or cl > rg["high"] + 0.5 * a:
                break   # діапазон пробито закриттям — події скасовано
            continue
        name, side, ext = ev
        prev = res["events"][-1] if res["events"] else None
        if prev and prev["kind"] == name and i <= prev["idx"] - (rg["end"] + 1) + 8 and ((name == "spring" and lo_ >= prev["extreme"]) or (name == "upthrust" and hi_ <= prev["extreme"])):
            continue   # повторний прокол без нового екстремуму — це тест попередньої події, а не нова подія
        vol_ev = _v(r)
        e = {"kind": name, "side": side, "extreme": ext, "idx": rg["end"] + 1 + i, "volume_ratio": round(vol_ev / avg_v, 2) if has_vol else None, "tested": False}
        # тест: у наступних 1–8 свічках повернення до екстремуму без нового екстремуму й на меншому обсязі
        for t in after[i + 1:i + 9]:
            tl, th, tc = float(t["low"]), float(t["high"]), float(t["close"])
            broke = (name == "spring" and tl < ext) or (name == "upthrust" and th > ext)
            if broke:
                break
            near = (name == "spring" and tl <= ext + 0.25 * a) or (name == "upthrust" and th >= ext - 0.25 * a)
            if near and has_vol and _v(t) <= 0.8 * vol_ev and ((name == "spring" and tc > rg["low"]) or (name == "upthrust" and tc < rg["high"])):
                e["tested"] = True
                break
        res["events"].append(e)
    if any(e["kind"] == "spring" and e["tested"] for e in res["events"]) and prior_drop >= PRIOR_TREND_ATR * a:
        res["phase"] = "накопичення (діапазон після падіння, spring з тестом)"
    elif any(e["kind"] == "upthrust" and e["tested"] for e in res["events"]) and -prior_drop >= PRIOR_TREND_ATR * a:
        res["phase"] = "розподіл (діапазон після росту, upthrust з тестом)"
    return res


def tags_for(candles: Any, side: str, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Теги підтвердження в бік side: spring/upthrust (лише з обсягом — без нього подію не рахуємо) і, якщо було, тест."""
    ev = events(candles, now_ts)
    out: List[Dict[str, Any]] = []
    for e in ev["events"]:
        if e["side"] == str(side).upper() and e["volume_ratio"] is not None:
            out.append({"kind": e["kind"], "why": f"{e['kind']} за межею діапазону {ev['range']['low' if e['kind'] == 'spring' else 'high']:.6g}, обсяг ×{e['volume_ratio']}"})
            if e["tested"]:
                out.append({"kind": e["kind"] + "_test", "why": "тест екстремуму на меншому обсязі, екстремум не оновлено"})
    return out
