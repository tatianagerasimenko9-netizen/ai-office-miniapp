"""ICT SMC HUNTER v9.9 — патерни і score 0–20.

Еталон: office_worker_library/indicator/ict_smc_hunter_v9_9.pine
Денний EQ = 0.786, OTE = 0.5 (навпаки від PUMP & DUMP).
Поріг: LTF 8, H1 7, H4 6. Не змішувати OTE/EQ з pump_dump.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from office_trade_steer import _bars, _f, ema_last, midnight_open_price, parse_bar_ts
from office_topdown import ASIA_KYIV
from office_trade_steer import _kyiv


HUNTER_EQ = 0.786
HUNTER_OTE = 0.5
SCORE_MAX = 20
MIN_LTF = 8
MIN_H1 = 7
MIN_H4 = 6
TOL_PCT = 0.6
PTS_SMS = 4
PTS_DRIVES = 3
PTS_TAP = 2
PTS_IFVG = 3
PTS_AMD = 3
PTS_TURTLE = 3
PTS_JUDAS = 2
PENALTY_EMA200 = 3
PENALTY_EMA55 = 1


def hunter_min_score(timeframe: str) -> int:
    tf = str(timeframe or "").upper().replace(" ", "")
    if tf in ("H4", "4H", "240"):
        return MIN_H4
    if tf in ("H1", "1H", "60"):
        return MIN_H1
    return MIN_LTF


def daily_eq_ote_hunter(daily: Any) -> Dict[str, Optional[float]]:
    """Hunter: EQ 0.786, OTE 0.5 від попереднього дня."""
    rows = _bars(daily)
    if len(rows) < 2:
        return {"eq": None, "ote": None, "d_h": None, "d_l": None, "d_bull": None}
    prev = rows[-2]
    d_h, d_l = float(prev["high"]), float(prev["low"])
    d_bull = float(prev["close"]) > float(prev["open"])
    rng = d_h - d_l
    if rng <= 0:
        return {"eq": None, "ote": None, "d_h": d_h, "d_l": d_l, "d_bull": d_bull}
    if d_bull:
        eq = d_h - rng * HUNTER_EQ
        ote = d_h - rng * HUNTER_OTE
    else:
        eq = d_l + rng * HUNTER_EQ
        ote = d_l + rng * HUNTER_OTE
    return {"eq": eq, "ote": ote, "d_h": d_h, "d_l": d_l, "d_bull": d_bull}


def _swings(rows: List[Dict[str, Any]], *, wing: int = 2) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    highs: List[Tuple[int, float]] = []
    lows: List[Tuple[int, float]] = []
    if len(rows) < wing * 2 + 1:
        return highs, lows
    for i in range(wing, len(rows) - wing):
        h, l = rows[i]["high"], rows[i]["low"]
        if all(h >= rows[j]["high"] for j in range(i - wing, i + wing + 1)):
            highs.append((i, h))
        if all(l <= rows[j]["low"] for j in range(i - wing, i + wing + 1)):
            lows.append((i, l))
    return highs, lows


def detect_sms(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Smart Money Shift / CHoCH: закриття ламає останній свінг проти попереднього тренду."""
    highs, lows = _swings(rows)
    out = {"ok": False, "side": "", "pts": 0}
    if len(rows) < 6 or (len(highs) < 2 and len(lows) < 2):
        return out
    last = rows[-1]["close"]
    if len(highs) >= 2 and len(lows) >= 1:
        # Даунтренд (LH) → пробій останнього хая вгору.
        if highs[-1][1] < highs[-2][1] and last > highs[-1][1]:
            return {"ok": True, "side": "LONG", "pts": PTS_SMS}
    if len(lows) >= 2 and len(highs) >= 1:
        if lows[-1][1] > lows[-2][1] and last < lows[-1][1]:
            return {"ok": True, "side": "SHORT", "pts": PTS_SMS}
    return out


def detect_three_drives(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Три послідовні драйви зі стисканням розмаху."""
    highs, lows = _swings(rows, wing=1)
    out = {"ok": False, "side": "", "pts": 0}
    if len(highs) >= 3:
        h1, h2, h3 = highs[-3][1], highs[-2][1], highs[-1][1]
        d1, d2 = abs(h2 - h1), abs(h3 - h2)
        if h1 < h2 < h3 and d2 < d1:
            return {"ok": True, "side": "SHORT", "pts": PTS_DRIVES}
    if len(lows) >= 3:
        l1, l2, l3 = lows[-3][1], lows[-2][1], lows[-1][1]
        d1, d2 = abs(l1 - l2), abs(l2 - l3)
        if l1 > l2 > l3 and d2 < d1:
            return {"ok": True, "side": "LONG", "pts": PTS_DRIVES}
    return out


def detect_three_tap(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Три торкання одного рівня (±tol)."""
    out = {"ok": False, "side": "", "pts": 0, "level": None}
    if len(rows) < 8:
        return out
    last = rows[-8:]
    px = float(rows[-1]["close"])
    tol = px * TOL_PCT / 100.0
    lows = [r["low"] for r in last]
    highs = [r["high"] for r in last]
    for series, side in ((lows, "LONG"), (highs, "SHORT")):
        for i, lv in enumerate(series):
            n = sum(1 for x in series if abs(x - lv) <= tol)
            if n >= 3:
                return {"ok": True, "side": side, "pts": PTS_TAP, "level": lv}
    return out


def detect_ifvg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Inversion FVG: геп 3 свічок, потім ціна проходить наскрізь і тримає зворотний бік."""
    out = {"ok": False, "side": "", "pts": 0}
    if len(rows) < 6:
        return out
    close = float(rows[-1]["close"])
    # Шукаємо FVG у вікні, інверсію на останніх барах.
    for i in range(2, len(rows) - 1):
        c0, c2 = rows[i], rows[i - 2]
        bull_gap = float(c0["low"]) > float(c2["high"])
        bear_gap = float(c0["high"]) < float(c2["low"])
        if bull_gap:
            lo, hi = float(c2["high"]), float(c0["low"])
            later = rows[i + 1 :]
            filled = any(float(r["low"]) <= lo for r in later)
            hold = close <= lo
            if filled and hold:
                return {"ok": True, "side": "SHORT", "pts": PTS_IFVG}
        if bear_gap:
            lo, hi = float(c0["high"]), float(c2["low"])
            later = rows[i + 1 :]
            filled = any(float(r["high"]) >= hi for r in later)
            hold = close >= hi
            if filled and hold:
                return {"ok": True, "side": "LONG", "pts": PTS_IFVG}
    return out


def detect_amd_3(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """AMD на 3 свічках: вузька → свіп → закриття проти свіпу."""
    out = {"ok": False, "side": "", "pts": 0}
    if len(rows) < 3:
        return out
    a, m, d = rows[-3], rows[-2], rows[-1]
    a_rng = float(a["high"]) - float(a["low"])
    if a_rng <= 0:
        return out
    mid = (float(a["high"]) + float(a["low"])) / 2.0
    # LONG: свіп лою, дистрибуція вгору.
    if float(m["low"]) < float(a["low"]) and float(d["close"]) > mid and float(d["close"]) > float(d["open"]):
        return {"ok": True, "side": "LONG", "pts": PTS_AMD}
    if float(m["high"]) > float(a["high"]) and float(d["close"]) < mid and float(d["close"]) < float(d["open"]):
        return {"ok": True, "side": "SHORT", "pts": PTS_AMD}
    return out


def detect_turtle_soup(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """False break 20-свічкового хаю/лою з закриттям назад."""
    out = {"ok": False, "side": "", "pts": 0}
    if len(rows) < 22:
        return out
    last = rows[-1]
    prev20h = max(r["high"] for r in rows[-21:-1])
    prev20l = min(r["low"] for r in rows[-21:-1])
    if float(last["high"]) > prev20h and float(last["close"]) < prev20h:
        return {"ok": True, "side": "SHORT", "pts": PTS_TURTLE}
    if float(last["low"]) < prev20l and float(last["close"]) > prev20l:
        return {"ok": True, "side": "LONG", "pts": PTS_TURTLE}
    return out


def _asia_range(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    hi = lo = None
    for r in rows:
        dt = parse_bar_ts(r.get("ts"))
        local = _kyiv(dt) if dt is not None else None
        if local is None:
            continue
        if ASIA_KYIV[0] <= local.hour < ASIA_KYIV[1]:
            h, l = float(r["high"]), float(r["low"])
            hi = h if hi is None else max(hi, h)
            lo = l if lo is None else min(lo, l)
    return {"high": hi, "low": lo}


def detect_judas(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Judas: свіп азійського хаю/лою і закриття назад."""
    out = {"ok": False, "side": "", "pts": 0}
    ar = _asia_range(rows)
    if ar["high"] is None or ar["low"] is None or not rows:
        return out
    last = rows[-1]
    dt = parse_bar_ts(last.get("ts"))
    local = _kyiv(dt) if dt is not None else None
    if local is not None and local.hour < ASIA_KYIV[1]:
        return out
    if float(last["high"]) > float(ar["high"]) and float(last["close"]) < float(ar["high"]):
        return {"ok": True, "side": "SHORT", "pts": PTS_JUDAS}
    if float(last["low"]) < float(ar["low"]) and float(last["close"]) > float(ar["low"]):
        return {"ok": True, "side": "LONG", "pts": PTS_JUDAS}
    return out


def mo_filter_ok(*, direction: str, close: Any, mo: Any) -> bool:
    """LONG лише нижче MO, SHORT лише вище. Немає MO — фільтр не блокує."""
    c, m = _f(close), _f(mo)
    if c is None or m is None:
        return True
    side = str(direction or "").upper()
    if side == "LONG":
        return c < m
    if side == "SHORT":
        return c > m
    return True


def trend_penalty(*, direction: str, close: float, ema55: Optional[float], ema200: Optional[float]) -> int:
    side = str(direction or "").upper()
    pen = 0
    if ema200 is not None:
        if side == "LONG" and close < ema200:
            pen += PENALTY_EMA200
        if side == "SHORT" and close > ema200:
            pen += PENALTY_EMA200
    if ema55 is not None:
        if side == "LONG" and close < ema55:
            pen += PENALTY_EMA55
        if side == "SHORT" and close > ema55:
            pen += PENALTY_EMA55
    return pen


def evaluate_ict_hunter(
    *,
    candles: Any,
    timeframe: str = "M15",
    daily: Any = None,
    mo: Any = None,
    asof: Any = None,
) -> Dict[str, Any]:
    rows = _bars(candles)
    empty = {
        "ok": False,
        "score": 0,
        "min_score": hunter_min_score(timeframe),
        "signal": False,
        "direction": "",
        "patterns": [],
        "ote_model": "hunter_ote_0.5",
        "eq_model": "hunter_eq_0.786",
        "reason": "DATA_UNAVAILABLE",
    }
    if len(rows) < 8:
        return empty
    close = float(rows[-1]["close"])
    sms = detect_sms(rows)
    drv = detect_three_drives(rows)
    tap = detect_three_tap(rows)
    ifvg = detect_ifvg(rows)
    amd = detect_amd_3(rows)
    turt = detect_turtle_soup(rows)
    jud = detect_judas(rows)
    parts = [("SMS", sms), ("3 Drives", drv), ("3 Tap", tap), ("iFVG", ifvg), ("AMD", amd), ("Turtle Soup", turt), ("Judas", jud)]
    votes: Dict[str, int] = {"LONG": 0, "SHORT": 0}
    patterns: List[str] = []
    raw = 0
    for name, p in parts:
        if p.get("ok"):
            raw += int(p.get("pts") or 0)
            side = str(p.get("side") or "")
            if side in votes:
                votes[side] += int(p.get("pts") or 0)
            patterns.append(name)
    direction = ""
    if votes["LONG"] > votes["SHORT"]:
        direction = "LONG"
    elif votes["SHORT"] > votes["LONG"]:
        direction = "SHORT"
    ema55 = ema_last(rows, 55)
    ema200 = ema_last(rows, 200) if len(rows) >= 200 else ema_last(rows, min(200, len(rows)))
    if len(rows) < 55:
        ema55 = ema_last(rows, min(55, len(rows)))
    pen = trend_penalty(direction=direction, close=close, ema55=ema55, ema200=ema200) if direction else 0
    score = max(0, min(SCORE_MAX, raw - pen))
    lv = daily_eq_ote_hunter(daily)
    mo_v = _f(mo)
    if mo_v is None:
        mo_v = midnight_open_price(candles, asof=asof or (rows[-1].get("ts") if rows else None))
    filt = mo_filter_ok(direction=direction, close=close, mo=mo_v) if direction else True
    mn = hunter_min_score(timeframe)
    signal = bool(direction) and score >= mn and filt
    return {
        "ok": True,
        "score": score,
        "raw": raw,
        "penalty": pen,
        "min_score": mn,
        "signal": signal,
        "direction": direction,
        "patterns": patterns,
        "mo": mo_v,
        "mo_ok": filt,
        "close": close,
        "eq": lv.get("eq"),
        "ote": lv.get("ote"),
        "ote_model": "hunter_ote_0.5",
        "eq_model": "hunter_eq_0.786",
        "reason": "" if signal else ("MO_FILTER" if direction and not filt else "below_threshold"),
    }
