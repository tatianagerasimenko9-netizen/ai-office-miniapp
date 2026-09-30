"""Свічкові моделі ЛИШЕ в контексті: біля зони/рівня, з обсягом і ATR, у активну сесію. Голої «красивої свічки» як аргументу немає.
Теги: pin_bar, inside_bar_break, engulfing_ctx, exhaustion. Правила на закритих свічках LTF:
- pin bar: тінь у бік зони ≥ 2×тіла і ≥ 60% діапазону, діапазон ≥ 0,8×ATR, закриття у верхній (для LONG) / нижній (SHORT) третині;
- inside bar: свічка повністю всередині попередньої («мати»), підтвердження — закриття наступної за межею матері у бік сценарію;
- поглинання: тіло поглинає тіло попередньої протилежної і ≥ 1×ATR діапазон;
- виснаження: серія ≥3 свічок в один бік, остання з тінню проти руху ≥ 50% діапазону та обсягом ≥ 1,5× середнього.
Контекст обов'язковий: (а) свічка торкається зони (з допуском 0,25×ATR); (б) обсяг ≥ 1,2× середнього за 20 свічок, якщо обсяг є; (в) активна сесія."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office_patterns import atr as _atr, closed_only

ZONE_TOL_ATR = 0.25
VOL_MIN = 1.2


def _f(v: Any) -> float:
    return float(v)


def _ctx_ok(rows: List[Dict[str, Any]], i: int, a: float, zone_lo: float, zone_hi: float, need_vol: bool = True) -> bool:
    r = rows[i]
    tol = ZONE_TOL_ATR * a
    if not (_f(r["low"]) <= zone_hi + tol and _f(r["high"]) >= zone_lo - tol):
        return False
    vols = [float(x.get("volume") or 0) for x in rows[max(0, i - 20):i]]
    avg = sum(vols) / len(vols) if vols else 0.0
    if need_vol and avg > 0 and float(r.get("volume") or 0) < VOL_MIN * avg:
        return False
    return True


def tags_for(candles: Any, side: str, zone_lo: Any, zone_hi: Any, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    from office_sessions import active_sessions
    import time as _t

    rows = closed_only([r for r in (candles or []) if isinstance(r, dict)], now_ts)
    if len(rows) < 25:
        return []
    try:
        lo, hi = sorted((float(zone_lo), float(zone_hi)))
    except (TypeError, ValueError):
        return []
    a = _atr(rows)
    if not a:
        return []
    from office_patterns import _ts

    t_last = _ts(rows[-1].get("ts")) or (now_ts or _t.time())
    if not active_sessions(t_last):
        return []          # поза активними сесіями свічкові моделі не рахуємо
    long_ = str(side).upper() != "SHORT"
    out: List[Dict[str, Any]] = []
    i = len(rows) - 1
    r, p = rows[i], rows[i - 1]
    o, c, h, l = _f(r["open"]), _f(r["close"]), _f(r["high"]), _f(r["low"])
    rng = h - l
    body = abs(c - o)
    if rng >= 0.8 * a and _ctx_ok(rows, i, a, lo, hi):
        wick = (min(o, c) - l) if long_ else (h - max(o, c))
        pos = (c - l) / rng if rng else 0
        if wick >= 2 * max(body, 1e-12) and wick >= 0.6 * rng and ((long_ and pos >= 2 / 3) or ((not long_) and pos <= 1 / 3)):
            out.append({"kind": "pin_bar", "why": f"тінь {wick / rng * 100:.0f}% діапазону біля зони, закриття у потрібній третині"})
    po, pc, ph, pl = _f(p["open"]), _f(p["close"]), _f(p["high"]), _f(p["low"])
    if rng >= 1.0 * a and _ctx_ok(rows, i, a, lo, hi):
        if long_ and pc < po and c > o and c >= po and o <= pc and body > abs(pc - po):
            out.append({"kind": "engulfing_ctx", "why": "бичаче поглинання ≥1×ATR біля зони"})
        if (not long_) and pc > po and c < o and c <= po and o >= pc and body > abs(pc - po):
            out.append({"kind": "engulfing_ctx", "why": "ведмеже поглинання ≥1×ATR біля зони"})
    # inside bar: rows[i-1] всередині rows[i-2] (мати); rows[i] закрилась за межею матері в бік сценарію
    m = rows[i - 2]
    mh, ml = _f(m["high"]), _f(m["low"])
    if ph < mh and pl > ml and _ctx_ok(rows, i - 1, a, lo, hi, need_vol=False):
        if (long_ and c > mh) or ((not long_) and c < ml):
            out.append({"kind": "inside_bar_break", "why": "пробій «матері» закриттям після inside bar біля зони"})
    # виснаження: 3+ свічки в один бік проти сценарію, остання з довгою тінню й сплеском обсягу
    seq = rows[i - 3:i + 1]
    down = all(_f(x["close"]) < _f(x["open"]) for x in seq[:-1]) if long_ else all(_f(x["close"]) > _f(x["open"]) for x in seq[:-1])
    if down and rng > 0 and _ctx_ok(rows, i, a, lo, hi):
        wick = (min(o, c) - l) if long_ else (h - max(o, c))
        vols = [float(x.get("volume") or 0) for x in rows[i - 20:i]]
        avg = sum(vols) / len(vols) if vols else 0
        if wick >= 0.5 * rng and (avg == 0 or float(r.get("volume") or 0) >= 1.5 * avg):
            out.append({"kind": "exhaustion", "why": "серія свічок проти сценарію, остання з тінню ≥50% і сплеском обсягу"})
    return out
