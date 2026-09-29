"""Перевірювані правила розворотних патернів на закритих свічках молодшого ТФ.

Потрійне/подвійне дно (LONG) і вершина (SHORT):
- екстремуми — локальні свінги (по 2 свічки з кожного боку);
- рівень екстремумів: розкид у межах max(0,3% ціни; 0,5×ATR(14)) — «або» означає, що достатньо ширшого з двох допусків;
- між сусідніми екстремумами щонайменше 3 свічки;
- підтвердження — ЗАКРИТТЯ свічки за «лінією шиї» (найвищий пік між мінімумами / найнижчий мінімум між вершинами) ПІСЛЯ останнього екстремуму;
- патерн скасовується, якщо закриття після нього вийшло за екстремум на допуск у протилежний бік;
- екстремуми мають бути в зоні (з допуском).
Повертається не лише «так/ні», а й які саме свічки: ціна й час кожного екстремуму, шия, свічка підтвердження.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

PRICE_TOL_PCT = 0.3
ATR_K = 0.5
MIN_GAP = 3
SWING_K = 2


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[float]:
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except (TypeError, ValueError):
        return None


def closed_only(rows: List[Dict[str, Any]], now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Без свічки, що ще формується: крок ТФ виводимо з різниці двох останніх свічок."""
    if len(rows) < 3:
        return list(rows)
    t1, t2 = _ts(rows[-1].get("ts")), _ts(rows[-2].get("ts"))
    if t1 is None or t2 is None or t1 <= t2:
        return list(rows)
    import time

    now = time.time() if now_ts is None else now_ts
    return list(rows[:-1]) if t1 + (t1 - t2) > now else list(rows)


def atr(rows: List[Dict[str, Any]], n: int = 14) -> Optional[float]:
    trs: List[float] = []
    for i in range(1, len(rows)):
        h, l, pc = _f(rows[i].get("high")), _f(rows[i].get("low")), _f(rows[i - 1].get("close"))
        if h is None or l is None or pc is None:
            continue
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    trs = trs[-n:]
    return sum(trs) / len(trs) if len(trs) >= 3 else None


def tolerance(price: float, atr_v: Optional[float]) -> float:
    return max(price * PRICE_TOL_PCT / 100.0, ATR_K * atr_v if atr_v else 0.0)


def _swing_idx(rows: List[Dict[str, Any]], key: str, low: bool) -> List[int]:
    out = []
    for i in range(SWING_K, len(rows) - SWING_K):
        v = float(rows[i][key])
        around = [float(rows[j][key]) for j in range(i - SWING_K, i + SWING_K + 1) if j != i]
        if (low and all(v <= a for a in around)) or ((not low) and all(v >= a for a in around)):
            out.append(i)
    return out


def find_multi(rows_in: Any, *, direction: str, n: int, zone_lo: Any = None, zone_hi: Any = None,
               now_ts: Optional[float] = None, lookback: int = 96) -> Optional[Dict[str, Any]]:
    """n=3 — потрійне, n=2 — подвійне. LONG → дно, SHORT → вершина. None — патерну немає (або скасований)."""
    rows = closed_only([r for r in (rows_in or []) if isinstance(r, dict)], now_ts)[-lookback:]
    if len(rows) < 12:
        return None
    long_ = str(direction).upper() != "SHORT"
    a = atr(rows)
    px = _f(rows[-1].get("close"))
    if px is None:
        return None
    tol = tolerance(px, a)
    ext = _swing_idx(rows, "low" if long_ else "high", low=long_)
    lo, hi = _f(zone_lo), _f(zone_hi)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    for end in range(len(ext) - 1, n - 2, -1):
        idx = ext[end - n + 1: end + 1]
        if any(idx[k + 1] - idx[k] < MIN_GAP for k in range(len(idx) - 1)):
            continue
        vals = [float(rows[i]["low" if long_ else "high"]) for i in idx]
        if max(vals) - min(vals) > tol:
            continue
        if lo is not None and hi is not None and not all(lo - tol <= v <= hi + tol for v in vals):
            continue
        between = rows[idx[0]: idx[-1] + 1]
        neck = max(float(r["high"]) for r in between) if long_ else min(float(r["low"]) for r in between)
        after = rows[idx[-1] + 1:]
        broken = any((float(r["close"]) < min(vals) - tol) if long_ else (float(r["close"]) > max(vals) + tol) for r in after)
        if broken:
            return None
        conf = None
        for r in after:
            cl = float(r["close"])
            if (long_ and cl > neck) or ((not long_) and cl < neck):
                conf = {"ts": r.get("ts"), "close": cl}
                break
        return {
            "kind": ("triple" if n == 3 else "double") + ("_bottom" if long_ else "_top"),
            "extremes": [{"ts": rows[i].get("ts"), "price": v} for i, v in zip(idx, vals)],
            "neckline": neck, "tolerance": tol, "confirmed": conf is not None, "confirm": conf,
        }
    return None
