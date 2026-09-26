"""PUMP & DUMP HUNTER v2 — бали 0–18. Еталон: pump_dump_hunter_v2.pine.

OTE денний = 0.786, EQ = 0.5 (не плутати з ICT SMC HUNTER).
Стоп 7 свічок ± 1.5 ATR. TP 1.5R/3R/5R, добір 40% до стопа.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office_trade_steer import atr_wilder, ema_last, _bars, _f


VOL_MULT = 2.0
SL_ATR = 1.5
SIGNAL_MIN = 10
WATCH_MIN = 6
FRESH_PCT = 20.0
TOL_PCT = 0.6
PUMP_OTE = 0.786
PUMP_EQ = 0.5


def _vol_sma(rows: List[Dict[str, Any]], n: int = 20) -> Optional[float]:
    if len(rows) < n:
        return None
    vols = [float(r["volume"]) for r in rows[-n:] if r.get("volume") is not None]
    if len(vols) < n:
        return None
    return sum(vols) / float(n)


def _rsi(rows: List[Dict[str, Any]]) -> Optional[float]:
    from office_rsi_heat import rsi_from_candles

    return rsi_from_candles(rows)


def daily_eq_ote(daily: Any) -> Dict[str, Optional[float]]:
    """PUMP pine: EQ 0.5, OTE 0.786 від попереднього дня."""
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
        eq = d_h - rng * PUMP_EQ
        ote = d_h - rng * PUMP_OTE
    else:
        eq = d_l + rng * PUMP_EQ
        ote = d_l + rng * PUMP_OTE
    return {"eq": eq, "ote": ote, "d_h": d_h, "d_l": d_l, "d_bull": d_bull}


def evaluate_pump_dump(
    *,
    candles: Any,
    daily: Any = None,
    weekly: Any = None,
) -> Dict[str, Any]:
    rows = _bars(candles)
    empty = {
        "signal": None,
        "total_l": 0,
        "total_s": 0,
        "ote_model": "pump_dump_0.786",
        "eq_model": "pump_dump_0.5",
    }
    if len(rows) < 22:
        return {**empty, "reason": "DATA_UNAVAILABLE"}
    last = rows[-1]
    close = float(last["close"])
    high, low, opn = float(last["high"]), float(last["low"]), float(last["open"])
    vol = last.get("volume")
    vsma = _vol_sma(rows)
    atr = atr_wilder(rows)
    ema21 = ema_last(rows, 21)
    ema55 = ema_last(rows, 55)
    rsi = _rsi(rows)
    if vsma is None or atr is None or ema21 is None or vol is None:
        return {**empty, "reason": "DATA_UNAVAILABLE"}
    vol_spike = float(vol) > vsma * VOL_MULT
    vol_grow = False
    if len(rows) >= 3 and rows[-2].get("volume") is not None and rows[-3].get("volume") is not None:
        vol_grow = float(vol) > float(rows[-2]["volume"]) > float(rows[-3]["volume"])

    vol_score = 3 if vol_spike else (1 if vol_grow else 0)

    big_red = close < opn and (opn - close) / opn > 0.015 and float(vol) > vsma * 1.8
    wick_down = (opn - low) > (high - close) * 1.5 and float(vol) > vsma * 1.3
    delev = 0
    for back in range(1, min(16, len(rows))):
        b = rows[-1 - back]
        bv = b.get("volume")
        if bv is None:
            continue
        br = float(b["close"]) < float(b["open"]) and (float(b["open"]) - float(b["close"])) / float(b["open"]) > 0.015 and float(bv) > vsma * 1.8
        wd = (float(b["open"]) - float(b["low"])) > (float(b["high"]) - float(b["close"])) * 1.5 and float(bv) > vsma * 1.3
        if br or wd:
            conf = close > opn and close > float(rows[-2]["close"])
            if conf:
                delev = 3 if back <= 3 else (2 if back <= 8 else 1)
            break

    hi10 = max(r["high"] for r in rows[-10:])
    lo10 = min(r["low"] for r in rows[-10:])
    squeeze = lo10 > 0 and (hi10 - lo10) / lo10 * 100 < 1.0
    acc = 3 if squeeze and vol_spike else (2 if squeeze else 0)

    skviz = 0
    if rsi is not None and len(rows) >= 3:
        r0, r1, r2 = rsi, _rsi(rows[:-1]), _rsi(rows[:-2])
        if r0 is not None and r1 is not None and r2 is not None:
            if r0 < 35 and r0 > r1 > r2:
                skviz = 3
            elif r0 < 40 and r0 > r1:
                skviz = 1

    hh20 = max(r["high"] for r in rows[-21:-1]) if len(rows) >= 21 else None
    brk_up = hh20 is not None and close > hh20 and float(rows[-2]["close"]) <= hh20
    hl = low > float(rows[-2]["low"]) and float(rows[-2]["low"]) > float(rows[-3]["low"])
    str_l = 3 if brk_up else (2 if hl and ema55 is not None and ema21 > ema55 else (1 if hl else 0))

    lv = daily_eq_ote(daily)
    w_rows = _bars(weekly)
    w_h = float(w_rows[-2]["high"]) if len(w_rows) >= 2 else None
    w_l = float(w_rows[-2]["low"]) if len(w_rows) >= 2 else None
    tol = close * TOL_PCT / 100.0

    def near(level: Optional[float], mult: float = 1.0) -> bool:
        return level is not None and abs(close - level) < close * (TOL_PCT * mult) / 100.0

    d_bull = bool(lv.get("d_bull"))
    near_ote = near(lv.get("ote"))
    near_eq = near(lv.get("eq"))
    near_d_low = near(lv.get("d_l"))
    near_d_high = near(lv.get("d_h"))
    near_w_low = near(w_l, 1.5)
    near_w_high = near(w_h, 1.5)
    lvl_l = 3 if near_w_low else (2 if near_d_low or (near_ote and d_bull) else (1 if near_eq and d_bull else 0))
    if near_ote and d_bull:
        lvl_l = max(lvl_l, 2)
    lvl_s = 3 if near_w_high else (2 if near_d_high or (near_ote and not d_bull) else (1 if near_eq and not d_bull else 0))

    total_l = vol_score + delev + acc + skviz + str_l + lvl_l
    lo20 = min(r["low"] for r in rows[-21:-1]) if len(rows) >= 21 else None
    fresh_l = lo20 is not None and lo20 > 0 and (close - lo20) / lo20 * 100 < FRESH_PCT
    sig_pump = total_l >= SIGNAL_MIN and vol_spike and bool(fresh_l) and close > ema21

    big_green = close > opn and (close - opn) / opn > 0.015 and float(vol) > vsma * 1.8
    wick_up = (high - close) > (close - low) * 1.5 and float(vol) > vsma * 1.3
    exhaust = 0
    for back in range(1, min(16, len(rows))):
        b = rows[-1 - back]
        bv = b.get("volume")
        if bv is None:
            continue
        bg = float(b["close"]) > float(b["open"]) and (float(b["close"]) - float(b["open"])) / float(b["open"]) > 0.015 and float(bv) > vsma * 1.8
        wu = (float(b["high"]) - float(b["close"])) > (float(b["close"]) - float(b["low"])) * 1.5 and float(bv) > vsma * 1.3
        if bg or wu:
            conf = close < opn and close < float(rows[-2]["close"])
            if conf:
                exhaust = 3 if back <= 3 else (2 if back <= 8 else 1)
            break
    overbuy = 0
    if rsi is not None and len(rows) >= 3:
        r0, r1, r2 = rsi, _rsi(rows[:-1]), _rsi(rows[:-2])
        if r0 is not None and r1 is not None and r2 is not None:
            if r0 > 65 and r0 < r1 < r2:
                overbuy = 3
            elif r0 > 60 and r0 < r1:
                overbuy = 1
    ll20 = min(r["low"] for r in rows[-21:-1]) if len(rows) >= 21 else None
    brk_dn = ll20 is not None and close < ll20 and float(rows[-2]["close"]) >= ll20
    lh = high < float(rows[-2]["high"]) and float(rows[-2]["high"]) < float(rows[-3]["high"])
    str_s = 3 if brk_dn else (2 if lh and ema55 is not None and ema21 < ema55 else (1 if lh else 0))
    total_s = vol_score + exhaust + acc + overbuy + str_s + lvl_s
    hi20 = max(r["high"] for r in rows[-21:-1]) if len(rows) >= 21 else None
    fresh_s = hi20 is not None and hi20 > 0 and (hi20 - close) / hi20 * 100 < FRESH_PCT
    sig_dump = total_s >= SIGNAL_MIN and vol_spike and bool(fresh_s) and close < ema21

    side = "LONG" if sig_pump else ("SHORT" if sig_dump else None)
    sl = None
    tps = {}
    if side:
        last7 = rows[-7:]
        if side == "LONG":
            raw = min(r["low"] for r in last7) - atr * SL_ATR
        else:
            raw = max(r["high"] for r in last7) + atr * SL_ATR
        sl = raw
        risk = abs(close - sl)
        if side == "LONG":
            tps = {"tp1": close + risk * 1.5, "tp2": close + risk * 3.0, "tp3": close + risk * 5.0, "add": close - risk * 0.4}
        else:
            tps = {"tp1": close - risk * 1.5, "tp2": close - risk * 3.0, "tp3": close - risk * 5.0, "add": close + risk * 0.4}

    return {
        "signal": "PUMP" if sig_pump else ("DUMP" if sig_dump else None),
        "direction": side,
        "total_l": total_l,
        "total_s": total_s,
        "entry": close,
        "sl": sl,
        "tps": tps,
        "vol_spike": vol_spike,
        "rsi": rsi,
        "ote": lv.get("ote"),
        "eq": lv.get("eq"),
        "ote_model": "pump_dump_0.786",
        "eq_model": "pump_dump_0.5",
        "watch_l": WATCH_MIN <= total_l < SIGNAL_MIN and bool(fresh_l),
        "watch_s": WATCH_MIN <= total_s < SIGNAL_MIN and bool(fresh_s),
    }


def format_pump_card(symbol: str, timeframe: str, ev: Dict[str, Any]) -> str:
    from office_trade_steer import format_signal_steer_card

    tps = ev.get("tps") or {}
    sc = ev.get("total_l") if ev.get("signal") == "PUMP" else ev.get("total_s")
    return format_signal_steer_card(
        symbol=symbol,
        direction=str(ev.get("direction") or ""),
        timeframe=timeframe,
        entry=ev.get("entry"),
        sl=ev.get("sl"),
        tp1=tps.get("tp1"),
        tp2=tps.get("tp2"),
        tp3=tps.get("tp3"),
        setup_type=str(ev.get("signal") or ""),
        score=sc,
        min_score=SIGNAL_MIN,
        score_max=18,
        ote_model=f"PUMP OTE {PUMP_OTE} / EQ {PUMP_EQ}",
    )


def pump_continuation(*, direction: str, entry: Any, candle: Any, candles: Any) -> bool:
    e = _f(entry)
    rows = _bars(candles)
    if e is None or len(rows) < 55 or not isinstance(candle, dict):
        return False
    vsma = _vol_sma(rows)
    vol = candle.get("volume")
    if vsma is None or vol is None or float(vol) <= vsma * VOL_MULT:
        return False
    ema21 = ema_last(rows, 21)
    ema55 = ema_last(rows, 55)
    if ema21 is None or ema55 is None:
        return False
    c, o = _f(candle.get("close")), _f(candle.get("open"))
    if c is None or o is None:
        return False
    side = str(direction or "").upper()
    if side == "LONG":
        return c > e * 1.01 and float(vol) > vsma * VOL_MULT and c > o and ema21 > ema55
    if side == "SHORT":
        return c < e * 0.99 and float(vol) > vsma * VOL_MULT and c < o and ema21 < ema55
    return False


def pump_add_retest(*, direction: str, entry: Any, candle: Any, candles: Any) -> bool:
    e = _f(entry)
    rows = _bars(candles)
    if e is None or len(rows) < 20 or not isinstance(candle, dict):
        return False
    vsma = _vol_sma(rows)
    vol = candle.get("volume")
    c = _f(candle.get("close"))
    if vsma is None or vol is None or c is None:
        return False
    if float(vol) <= vsma * VOL_MULT:
        return False
    return abs(c - e) / e * 100.0 < TOL_PCT
