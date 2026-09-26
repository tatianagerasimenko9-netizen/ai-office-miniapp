"""PR42: стоп за зоною маніпуляції, тригер входу, ведення, тихий журнал сигналу.

Не змінює ATR 80/90, Edge 85, MIN_RR 1.5. Не відкриває ордери.
Немає свічок → DATA_UNAVAILABLE, рівні не вигадуємо.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from office_radar import MIN_RR
from office_topdown import DATA_OK, DATA_UNAVAILABLE, calc_sl_with_buffer

KIND_STEER = "trade_steer"
# Еталон: office_worker_library/indicator/ict_smc_hunter_v9_9.pine
SL_ATR_MULT = 1.0  # запасний підлог, не замінює hunter 2×ATR
SL_ATR_HUNTER = 2.0
SL_LOOKBACK = 7
SC_VOL_X = 2.0
SC_ATR_X = 1.2
SC_VOL_SMA = 20
RR_TIGHT_FLAG = 6.0
OFFICE_SIGNAL_REASON = "office signal card (not /position)"
OFFICE_SIGNAL_SETUP = "OFFICE_SIGNAL"
ATR_PERIOD = 14
MIN_MANIP_BARS = 5
MANIP_NEAR_PCT = 0.04
# Pine SC OTE: 0.618 і 0.786 (підпис на графіку «62–79%»).
OTE_618 = 0.618
OTE_786 = 0.786
# Тетяна: 2 відра всередині зони, не добір біля стопа.
SCALE_ENTRY_PCT = 60
SCALE_ADD_PCT = 40
SCALE_ADD2_PCT = 0
KYIV_TZ = "Europe/Kyiv"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _bars(candles: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(candles, list):
        return out
    for c in candles:
        if not isinstance(c, dict):
            continue
        o, h, l, cl = _f(c.get("open")), _f(c.get("high")), _f(c.get("low")), _f(c.get("close"))
        if None in (o, h, l, cl):
            continue
        out.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": cl,
                "volume": _f(c.get("volume")),
                "ts": str(c.get("ts") or ""),
            }
        )
    return out


def true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr_from_candles(candles: Any, period: int = ATR_PERIOD) -> Optional[float]:
    """Wilder ATR як ta.atr у Pine. Немає рядка — None."""
    rows = _bars(candles)
    return atr_wilder(rows, period=period)


def atr_wilder(rows: List[Dict[str, Any]], *, period: int = ATR_PERIOD, end: Optional[int] = None) -> Optional[float]:
    n = len(rows) if end is None else min(int(end) + 1, len(rows))
    if n < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, n):
        trs.append(true_range(rows[i - 1]["close"], rows[i]["high"], rows[i]["low"]))
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / float(period)
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / float(period)
    return atr


def _kyiv(dt: Any) -> Optional[datetime]:
    parsed = dt if isinstance(dt, datetime) else None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.astimezone(ZoneInfo(KYIV_TZ))
    except Exception:
        return parsed


def parse_bar_ts(ts: Any) -> Optional[datetime]:
    from office_telegram_filter import parse_quote_dt

    return parse_quote_dt(ts)


def is_manip_window_kyiv(asof: Any) -> bool:
    """09:00–09:15 і 15:00–15:15 Київ — сигнал не надсилати. Скан 24/7 лишається."""
    dt = asof if isinstance(asof, datetime) else parse_bar_ts(asof)
    kyiv = _kyiv(dt) if dt is not None else None
    if kyiv is None:
        return False
    hm = kyiv.hour * 60 + kyiv.minute
    return (9 * 60 <= hm < 9 * 60 + 15) or (15 * 60 <= hm < 15 * 60 + 15)


def midnight_open_price(candles: Any, *, asof: Any = None) -> Optional[float]:
    """Open першого бара 07:00–07:05 Київ (MO у Pine)."""
    rows = _bars(candles)
    ref = asof if isinstance(asof, datetime) else parse_bar_ts(asof)
    if ref is None and rows:
        ref = parse_bar_ts(rows[-1].get("ts"))
    kyiv_ref = _kyiv(ref) if ref is not None else None
    if kyiv_ref is None:
        return None
    day = kyiv_ref.date()
    for r in rows:
        dt = parse_bar_ts(r.get("ts"))
        local = _kyiv(dt) if dt is not None else None
        if local is None or local.date() != day:
            continue
        hm = local.hour * 60 + local.minute
        if 7 * 60 <= hm < 7 * 60 + 5:
            return float(r["open"])
    return None


def last_strong_candle(candles: Any, *, direction: str) -> Optional[Dict[str, Any]]:
    """Pine: volume > SMA(vol,20)×2 і (high−low) > ATR14×1.2, тіло в бік сетапу."""
    rows = _bars(candles)
    side = str(direction or "").upper()
    if side not in ("LONG", "SHORT") or len(rows) < max(SC_VOL_SMA, ATR_PERIOD + 1):
        return None
    found: Optional[Dict[str, Any]] = None
    for i in range(SC_VOL_SMA - 1, len(rows)):
        atr = atr_wilder(rows, end=i)
        if atr is None or atr <= 0:
            continue
        window = rows[i - SC_VOL_SMA + 1 : i + 1]
        vols = [float(r["volume"]) for r in window if r.get("volume") is not None]
        if len(vols) < SC_VOL_SMA:
            continue
        vol_sma = sum(vols) / float(SC_VOL_SMA)
        r = rows[i]
        vol = r.get("volume")
        if vol is None or vol_sma <= 0 or float(vol) <= vol_sma * SC_VOL_X:
            continue
        rng = float(r["high"]) - float(r["low"])
        if rng <= atr * SC_ATR_X:
            continue
        if side == "LONG" and float(r["close"]) <= float(r["open"]):
            continue
        if side == "SHORT" and float(r["close"]) >= float(r["open"]):
            continue
        found = dict(r)
        found["atr"] = atr
    return found


def hunter_stop_price(*, direction: str, candles: Any) -> Optional[float]:
    """LONG: lowest(low,7) − ATR×2; SHORT: highest(high,7) + ATR×2."""
    rows = _bars(candles)
    side = str(direction or "").upper()
    if len(rows) < SL_LOOKBACK:
        return None
    atr = atr_wilder(rows)
    if atr is None or atr <= 0:
        return None
    last = rows[-SL_LOOKBACK:]
    if side == "LONG":
        return min(float(r["low"]) for r in last) - atr * SL_ATR_HUNTER
    if side == "SHORT":
        return max(float(r["high"]) for r in last) + atr * SL_ATR_HUNTER
    return None


def _wider_stop(side: str, a: Optional[float], b: Optional[float]) -> Optional[float]:
    xs = [x for x in (a, b) if x is not None]
    if not xs:
        return None
    if side == "LONG":
        return min(xs)
    return max(xs)


def plan_pine_targets(
    *,
    direction: str,
    entry: Any,
    sl: Any,
    atr: Any = None,
    mo: Any = None,
    asian_high: Any = None,
    asian_low: Any = None,
    pdh: Any = None,
    pdl: Any = None,
    week_high: Any = None,
    week_low: Any = None,
) -> Dict[str, Any]:
    """Драбина Pine: MO → Asian → PDH/PDL → W High/Low, запасні 1.5R/3R/5R."""
    side = str(direction or "").upper()
    e, s = _f(entry), _f(sl)
    empty = {"tp1": None, "tp2": None, "tp3": None, "data_status": DATA_UNAVAILABLE}
    if e is None or s is None or side not in ("LONG", "SHORT"):
        return empty
    risk = abs(e - s)
    atr_v = _f(atr)
    risk_pts = (atr_v * SL_ATR_HUNTER) if atr_v and atr_v > 0 else risk
    mo_v, ah, al = _f(mo), _f(asian_high), _f(asian_low)
    pdh_v, pdl_v = _f(pdh), _f(pdl)
    wh, wl = _f(week_high), _f(week_low)
    if side == "LONG":
        if mo_v is not None and mo_v > e + risk_pts * 0.3:
            tp1 = mo_v
        elif ah is not None and ah > e + risk_pts * 0.5:
            tp1 = ah
        else:
            tp1 = e + risk_pts * 1.5
        if ah is not None and ah > tp1:
            tp2 = ah
        elif pdh_v is not None and pdh_v > tp1:
            tp2 = pdh_v
        else:
            tp2 = e + risk_pts * 3.0
        if pdh_v is not None and pdh_v > tp2:
            tp3 = pdh_v
        elif wh is not None and wh > tp2:
            tp3 = wh
        else:
            tp3 = e + risk_pts * 5.0
        tp2 = max(tp2, tp1)
        tp3 = max(tp3, tp2)
    else:
        if mo_v is not None and mo_v < e - risk_pts * 0.3:
            tp1 = mo_v
        elif al is not None and al < e - risk_pts * 0.5:
            tp1 = al
        else:
            tp1 = e - risk_pts * 1.5
        if al is not None and al < tp1:
            tp2 = al
        elif pdl_v is not None and pdl_v < tp1:
            tp2 = pdl_v
        else:
            tp2 = e - risk_pts * 3.0
        if pdl_v is not None and pdl_v < tp2:
            tp3 = pdl_v
        elif wl is not None and wl < tp2:
            tp3 = wl
        else:
            tp3 = e - risk_pts * 5.0
        tp2 = min(tp2, tp1)
        tp3 = min(tp3, tp2)
    return {"tp1": tp1, "tp2": tp2, "tp3": tp3, "data_status": DATA_OK, "risk_pts": risk_pts}


def impulse_wick(candles: Any, *, direction: str) -> Optional[float]:
    """Тінь найсильнішої свічки (макс. тіло) в наборі."""
    rows = _bars(candles)
    if not rows:
        return None
    best = max(rows, key=lambda r: abs(float(r["close"]) - float(r["open"])))
    side = str(direction or "").upper()
    if side == "SHORT":
        return float(best["high"])
    if side == "LONG":
        return float(best["low"])
    return None


def zone_extreme(candles: Any, *, direction: str) -> Optional[float]:
    """Хай коридору для SHORT / лой для LONG — найдальший прокол."""
    rows = _bars(candles)
    if not rows:
        return None
    side = str(direction or "").upper()
    if side == "SHORT":
        return max(float(r["high"]) for r in rows)
    if side == "LONG":
        return min(float(r["low"]) for r in rows)
    return None


def ema_last(candles: Any, period: int = 21) -> Optional[float]:
    rows = _bars(candles)
    if len(rows) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = float(rows[0]["close"])
    for r in rows[1:]:
        ema = float(r["close"]) * k + ema * (1.0 - k)
    return ema


def plan_strong_candle_ote(
    *,
    direction: str,
    candles: Any,
    tick_size: Any = None,
    price: Any = None,
) -> Dict[str, Any]:
    """Зона SC з Pine + OTE 0.618/0.786 + відра 60/40. Без свічки — DATA_UNAVAILABLE."""
    side = str(direction or "").upper()
    empty = {
        "data_status": DATA_UNAVAILABLE,
        "high": None,
        "low": None,
        "eq": None,
        "ote_lo": None,
        "ote_hi": None,
        "buckets": [],
        "sl_anchor": None,
        "sl": None,
        "cancel_level": None,
        "trigger_level": None,
        "source": "ict_smc_hunter_v9_9",
    }
    if side not in ("LONG", "SHORT"):
        return empty
    sc = last_strong_candle(candles, direction=side)
    if not sc:
        return empty
    hi, lo = float(sc["high"]), float(sc["low"])
    if hi <= lo:
        return empty
    span = hi - lo
    eq = (hi + lo) / 2.0
    if side == "LONG":
        ote_618 = hi - span * OTE_618
        ote_786 = hi - span * OTE_786
        ote_lo, ote_hi = ote_786, ote_618
        sl_anchor = lo
        trigger_level = ote_hi
        cancel_level = lo
    else:
        ote_618 = lo + span * OTE_618
        ote_786 = lo + span * OTE_786
        ote_lo, ote_hi = ote_618, ote_786
        sl_anchor = hi
        trigger_level = ote_lo
        cancel_level = hi
    hunter = hunter_stop_price(direction=side, candles=candles)
    gerchik = calc_sl_with_buffer(sl_anchor, side, tick_size=tick_size, price=price or eq)
    sl = _wider_stop(side, hunter, gerchik.get("sl") if isinstance(gerchik, dict) else None)
    buckets = [
        {"label": "Вхід", "price": ote_618, "pct": SCALE_ENTRY_PCT},
        {"label": "Добір", "price": ote_786, "pct": SCALE_ADD_PCT},
    ]
    return {
        "data_status": DATA_OK,
        "high": hi,
        "low": lo,
        "eq": eq,
        "ote_lo": ote_lo,
        "ote_hi": ote_hi,
        "buckets": buckets,
        "sl_anchor": sl_anchor,
        "sl": sl,
        "cancel_level": cancel_level,
        "trigger_level": trigger_level,
        "source": "ict_smc_hunter_v9_9",
        "explain": gerchik.get("explain") if isinstance(gerchik, dict) else None,
        "hunter_sl": hunter,
    }


def encode_sc_zone_note(plan: Optional[Dict[str, Any]]) -> str:
    if not plan or plan.get("data_status") != DATA_OK:
        return ""
    return f"SC_ZONE {plan['low']}-{plan['high']}"


def parse_sc_zone_note(note: Any) -> Optional[Tuple[float, float]]:
    text = str(note or "")
    if "SC_ZONE" not in text:
        return None
    try:
        chunk = text.split("SC_ZONE", 1)[1].strip().split()[0]
        a, b = chunk.replace("—", "-").split("-", 1)
        lo, hi = float(a), float(b)
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi
    except Exception:
        return None


def sc_setup_cancelled(*, direction: str, close: Any, sc_low: Any, sc_high: Any) -> bool:
    """Закриття за протилежним краєм зони SC до входу — сетап мертвий."""
    c, lo, hi = _f(close), _f(sc_low), _f(sc_high)
    if c is None or lo is None or hi is None:
        return False
    side = str(direction or "").upper()
    if side == "SHORT":
        return c > hi
    if side == "LONG":
        return c < lo
    return False


def format_sc_plan_lines(plan: Optional[Dict[str, Any]], *, direction: str) -> List[str]:
    from office_telegram_filter import format_px, format_level_span

    if not plan or plan.get("data_status") != DATA_OK:
        return []
    side = str(direction or "").upper()
    cmp_in = "нижче" if side == "SHORT" else "вище"
    cmp_x = "вище" if side == "SHORT" else "нижче"
    lines = [
        f"Зона входу: {format_level_span(plan.get('ote_lo'), plan.get('ote_hi'))} "
        "(відкат у сильну свічку, OTE 62–79%)",
    ]
    for b in plan.get("buckets") or []:
        lines.append(f"{b['label']}: {format_px(b.get('price'))} — {int(b.get('pct') or 0)}% позиції")
    lines.append(
        f"Тригер: закриття M15 {cmp_in} {format_px(plan.get('trigger_level'))} в зоні SC"
    )
    lines.append(
        f"Скасування до входу: закриття M15 {cmp_x} {format_px(plan.get('cancel_level'))} "
        "— ❌ Скасовано"
    )
    return lines


def _same_side_near(entry: float, level: float, side: str, atr: Optional[float] = None) -> bool:
    if side == "SHORT" and level <= entry:
        return False
    if side == "LONG" and level >= entry:
        return False
    cap = max(entry * MANIP_NEAR_PCT, (atr or 0.0) * 2.0, entry * 0.01)
    return abs(level - entry) <= cap + 1e-12


def _ema_if_reacted(candles: Any, ema: Optional[float]) -> Optional[float]:
    if ema is None:
        return None
    rows = _bars(candles)
    if not rows:
        return None
    last = rows[-1]
    if float(last["low"]) <= ema <= float(last["high"]):
        return ema
    return None


def manipulation_anchor(
    *,
    direction: str,
    entry: Any = None,
    candles_entry: Any = None,
    candles_htf: Any = None,
    ob_bound: Any = None,
    ema_value: Any = None,
    atr: Any = None,
) -> Dict[str, Any]:
    """Найдальший рівень маніпуляції біля входу. Без свічок — DATA_UNAVAILABLE."""
    side = str(direction or "").upper()
    e = _f(entry)
    atr_v = _f(atr)
    entry_rows = _bars(candles_entry)
    if len(entry_rows) < MIN_MANIP_BARS:
        return {"level": None, "source": "", "data_status": DATA_UNAVAILABLE}
    cands: List[Tuple[str, float]] = []

    def _add(name: str, level: Optional[float]) -> None:
        if level is None or e is None:
            return
        if _same_side_near(e, float(level), side, atr_v):
            cands.append((name, float(level)))

    _add("коридор/прокол", zone_extreme(candles_entry, direction=side))
    _add("тінь імпульсу", impulse_wick(candles_entry, direction=side))
    _add("HTF зона", zone_extreme(candles_htf, direction=side))
    _add("OB", _f(ob_bound))
    em = _f(ema_value)
    if em is None:
        em = ema_last(candles_htf or candles_entry)
    _add("EMA", _ema_if_reacted(candles_htf or candles_entry, em))
    if not cands:
        return {"level": None, "source": "", "data_status": DATA_UNAVAILABLE}
    if side == "SHORT":
        source, level = max(cands, key=lambda x: x[1])
    else:
        source, level = min(cands, key=lambda x: x[1])
    return {"level": level, "source": source, "data_status": DATA_OK}


def _rr(entry: float, sl: float, tp1: float) -> Optional[float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    return abs(tp1 - entry) / risk


def plan_stop_behind_manipulation(
    *,
    entry: Any,
    tp1: Any,
    direction: str,
    candles_m15: Any = None,
    candles_h1: Any = None,
    atr_m15: Any = None,
    ob_bound: Any = None,
    tick_size: Any = None,
    current_sl: Any = None,
) -> Dict[str, Any]:
    """Стоп Pine: 7 свічок ± 2×ATR. Люфт Герчика / зона SC — лише якщо ширше."""
    e = _f(entry)
    t1 = _f(tp1)
    side = str(direction or "").upper()
    empty = {
        "sl": None,
        "send": False,
        "reason": "немає entry/TP1",
        "rr": None,
        "data_status": DATA_UNAVAILABLE,
        "anchor": None,
        "quality": "unavailable",
    }
    if e is None or e <= 0 or t1 is None or side not in ("LONG", "SHORT"):
        return empty
    hunter = hunter_stop_price(direction=side, candles=candles_m15)
    sl = hunter
    packed: Dict[str, Any] = {}
    notes: List[str] = []
    if hunter is not None:
        notes.append("стоп Hunter: 7 свічок ± 2×ATR(14)")
    sc_plan = plan_strong_candle_ote(
        direction=side, candles=candles_m15, tick_size=tick_size, price=e
    )
    if ob_bound is None and sc_plan.get("sl_anchor") is not None:
        ob_bound = sc_plan.get("sl_anchor")
    tight_rr = _rr(e, float(current_sl), t1) if _f(current_sl) is not None else None
    atr = _f(atr_m15)
    if atr is None:
        atr = atr_from_candles(candles_m15)
    anchor = manipulation_anchor(
        direction=side,
        entry=e,
        candles_entry=candles_m15,
        candles_htf=candles_h1,
        ob_bound=ob_bound,
        atr=atr,
    )
    packed_m = calc_sl_with_buffer(anchor.get("level"), side, tick_size=tick_size, price=e)
    # Люфт Герчика лише якщо стоп стає ширшим за Hunter.
    sl = _wider_stop(side, sl, packed_m.get("sl"))
    if packed_m.get("sl") is not None:
        packed = packed_m
    if sl is None and sc_plan.get("sl") is not None:
        sl = sc_plan.get("sl")
        packed = {"sl": sl, "buffer": sc_plan.get("explain"), "explain": sc_plan.get("explain")}
        notes.append("стоп за зоною сильної свічки")
    if sl is None:
        reason = "зона маніпуляції DATA_UNAVAILABLE — стоп не вигадуємо"
        if tight_rr is not None and tight_rr > RR_TIGHT_FLAG:
            reason = (
                f"RR {tight_rr:.1f} > {RR_TIGHT_FLAG:.0f} і немає зони маніпуляції "
                "— сигнал не надсилаємо"
            )
        return {
            **empty,
            "reason": reason,
            "rr": tight_rr,
            "anchor": anchor,
            "quality": "skip_tight" if tight_rr and tight_rr > RR_TIGHT_FLAG else "unavailable",
        }
    sl = float(sl)
    if sc_plan.get("sl") is not None:
        sc_sl = float(sc_plan["sl"])
        if side == "SHORT" and sc_sl > sl:
            sl = sc_sl
            notes.append("стоп за зоною сильної свічки + люфт")
        elif side == "LONG" and sc_sl < sl:
            sl = sc_sl
            notes.append("стоп за зоною сильної свічки + люфт")
    risk = abs(e - sl)
    if atr is not None and atr > 0 and risk + 1e-12 < SL_ATR_MULT * atr:
        extra = calc_sl_with_buffer(
            (e + atr) if side == "SHORT" else (e - atr),
            side,
            tick_size=tick_size,
            price=e,
        )
        if extra.get("sl") is not None:
            cand = float(extra["sl"])
            if side == "SHORT":
                sl = max(sl, cand)
            else:
                sl = min(sl, cand)
            notes.append(f"розширено до ≥{SL_ATR_MULT:.1f}×ATR(M15)")
    rr = _rr(e, sl, t1)
    if tight_rr is not None and tight_rr > RR_TIGHT_FLAG + 1e-9:
        notes.append(f"RR {tight_rr:.1f} > {RR_TIGHT_FLAG:.0f} до TP1 — стоп від зони маніпуляції")
    elif rr is not None and rr > RR_TIGHT_FLAG + 1e-9:
        notes.append(f"RR {rr:.1f} > {RR_TIGHT_FLAG:.0f} до TP1 — якір маніпуляції")
    if rr is None or rr + 1e-12 < float(MIN_RR):
        return {
            "sl": sl,
            "send": False,
            "reason": f"після зони маніпуляції RR {rr} < {MIN_RR} — сигнал не надсилаємо",
            "rr": rr,
            "data_status": DATA_OK,
            "anchor": anchor,
            "quality": "skip_rr",
            "notes": notes,
            "buffer": packed.get("buffer"),
            "explain": packed.get("explain"),
        }
    ok_side = (side == "SHORT" and sl > e) or (side == "LONG" and sl < e)
    if not ok_side:
        return {
            **empty,
            "sl": sl,
            "reason": "стоп не з того боку від входу",
            "data_status": DATA_OK,
            "anchor": anchor,
        }
    quality = "ok"
    if (tight_rr is not None and tight_rr > RR_TIGHT_FLAG) or (rr is not None and rr > RR_TIGHT_FLAG):
        quality = "widened"
    return {
        "sl": sl,
        "send": True,
        "reason": "; ".join(notes) or "стоп за зоною маніпуляції + люфт Герчика",
        "rr": rr,
        "data_status": DATA_OK,
        "anchor": anchor,
        "quality": quality,
        "notes": notes,
        "buffer": packed.get("buffer"),
        "explain": packed.get("explain"),
        "atr_m15": atr,
        "sc_plan": sc_plan,
    }


def format_entry_trigger(
    *,
    direction: str,
    tf: str = "M15",
    level: Any,
    entry: Any,
    already_done: bool = False,
    done_hhmm: str = "",
) -> str:
    """Завжди: ТФ + рівень + нижче/вище. Без «перевірте самі»."""
    from office_telegram_filter import format_px

    side = str(direction or "").upper()
    cmp_ua = "нижче" if side == "SHORT" else "вище"
    lv = format_px(level)
    en = format_px(entry)
    tf_u = str(tf or "M15").upper()
    if already_done:
        when = f" о {done_hhmm}" if done_hhmm else ""
        return (
            f"Вхід: по ринку {en} — умову вже виконано "
            f"({tf_u} закрилась {cmp_ua} {lv}{when})"
        )
    return f"Вхід: {en} — після закриття {tf_u} свічки {cmp_ua} {lv}"


def format_signal_steer_card(
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    entry: Any,
    sl: Any,
    tp1: Any,
    tp2: Any = None,
    tp3: Any = None,
    trigger: str = "",
    reentry: bool = False,
    sweep_note: str = "",
    sc_plan: Optional[Dict[str, Any]] = None,
) -> str:
    from office_telegram_filter import format_px

    side = str(direction or "").upper()
    tf = str(timeframe or "H1").upper()
    title = f"🔁 ПОВТОРНИЙ {side} · {symbol} · {tf}" if reentry else f"{side} · {symbol} · {tf}"
    lines = [title]
    if sweep_note:
        lines.append(sweep_note)
    lines.extend(format_sc_plan_lines(sc_plan, direction=side))
    if trigger:
        lines.append(trigger)
    else:
        lines.append(format_entry_trigger(direction=side, tf="M15", level=entry, entry=entry))
    lines.append(
        f"SL: {format_px(sl)} · TP1: {format_px(tp1)}"
        + (f" · TP2: {format_px(tp2)}" if tp2 is not None else "")
        + (f" · TP3: {format_px(tp3)}" if tp3 is not None else "")
    )
    lines.append("Картка сетапу, не ордер. Угода лише через /position.")
    return "\n".join(lines)


def signal_case_key(*, symbol: str, direction: str, timeframe: str = "H1", day: str = "") -> str:
    return f"{str(symbol or '').upper()}|{str(direction or '').upper()}|{str(timeframe or 'H1')}|{day}"


def wick_swept_stop(*, direction: str, sl: Any, candle: Any) -> bool:
    """Прокол стопа тінню (не обов'язково закриття за стопом)."""
    slv = _f(sl)
    if slv is None or not isinstance(candle, dict):
        return False
    h, l = _f(candle.get("high")), _f(candle.get("low"))
    side = str(direction or "").upper()
    if side == "SHORT" and h is not None:
        return h >= slv
    if side == "LONG" and l is not None:
        return l <= slv
    return False


def close_reclaimed_zone(
    *,
    direction: str,
    close: Any,
    zone_level: Any,
) -> bool:
    c, z = _f(close), _f(zone_level)
    if c is None or z is None:
        return False
    side = str(direction or "").upper()
    if side == "SHORT":
        return c < z
    return c > z


def htf_structure_intact(*, direction: str, candles_h1: Any) -> bool:
    """Груба перевірка: останнє закриття не зламало свінг проти сетапу."""
    rows = _bars(candles_h1)
    if len(rows) < 3:
        return True
    side = str(direction or "").upper()
    last = rows[-1]["close"]
    if side == "SHORT":
        swing_high = max(r["high"] for r in rows[:-1][-8:])
        return last < swing_high
    swing_low = min(r["low"] for r in rows[:-1][-8:])
    return last > swing_low


def plan_sweep_reentry(
    *,
    case_key: str,
    already_reentered: bool,
    direction: str,
    sl: Any,
    reclaim_level: Any,
    last_candle: Any,
    candles_h1: Any = None,
    wick_extreme: Any = None,
) -> Dict[str, Any]:
    """Не більше одного повторного входу на case_key."""
    if already_reentered:
        return {"allow": False, "reason": "повторний вхід уже був на цей case_key"}
    if not wick_swept_stop(direction=direction, sl=sl, candle=last_candle):
        return {"allow": False, "reason": "стоп не проколото тінню"}
    cl = last_candle.get("close") if isinstance(last_candle, dict) else None
    if not close_reclaimed_zone(direction=direction, close=cl, zone_level=reclaim_level):
        return {"allow": False, "reason": "немає закриття назад у зону"}
    if not htf_structure_intact(direction=direction, candles_h1=candles_h1):
        return {"allow": False, "reason": "структура старшого ТФ зламана"}
    ext = _f(wick_extreme)
    if ext is None and isinstance(last_candle, dict):
        side = str(direction or "").upper()
        ext = _f(last_candle.get("high") if side == "SHORT" else last_candle.get("low"))
    return {
        "allow": True,
        "reason": "свіп стопа + повернення в зону",
        "case_key": case_key,
        "wick_extreme": ext,
    }


def last_swing_hl_lh(*, direction: str, candles_m15: Any) -> Optional[float]:
    """Останній підтверджений HL (LONG) / LH (SHORT) на M15: екстремум нижчий/вищий за сусідів."""
    rows = _bars(candles_m15)
    if len(rows) < 3:
        return None
    side = str(direction or "").upper()
    swings: List[float] = []
    # Останній бар ще не підтверджує свінг — потрібен сусід справа.
    for i in range(1, len(rows) - 1):
        if side == "LONG":
            if rows[i]["low"] <= rows[i - 1]["low"] and rows[i]["low"] <= rows[i + 1]["low"]:
                swings.append(float(rows[i]["low"]))
        else:
            if rows[i]["high"] >= rows[i - 1]["high"] and rows[i]["high"] >= rows[i + 1]["high"]:
                swings.append(float(rows[i]["high"]))
    if not swings:
        return None
    return swings[-1]


def last_m15_structure_stop(*, direction: str, candles_m15: Any, fallback: Any) -> Optional[float]:
    """Трейл за останнім HL/LH, лише в бік прибутку (не послаблюємо попередній стоп)."""
    fb = _f(fallback)
    swing = last_swing_hl_lh(direction=direction, candles_m15=candles_m15)
    if swing is None:
        return fb
    side = str(direction or "").upper()
    if side == "LONG":
        return max(swing, fb) if fb is not None else swing
    return min(swing, fb) if fb is not None else swing


def _impulse_m15_rows(book: "ManageBook", candles_m15: Any) -> List[Dict[str, Any]]:
    """HL/LH лише після нового екстремуму відносно хая/лоя на момент TP2 — інакше відкат до TP1 зріже імпульс."""
    rows = _bars(candles_m15)
    if not rows:
        return []
    side = str(book.direction).upper()
    arm = _f(book.extras.get("arm_extreme"))
    if arm is None:
        return rows
    idx = book.extras.get("arm_idx")
    if idx is None:
        for i, r in enumerate(rows):
            if side == "LONG" and r["high"] > arm:
                idx = i
                break
            if side == "SHORT" and r["low"] < arm:
                idx = i
                break
        if idx is None:
            return []
        book.extras["arm_idx"] = int(idx)
        book.extras["armed"] = True
    return rows[int(idx) :]


def tp3_from_liquidity(
    *,
    direction: str,
    daily_candles: Any = None,
    h4_level: Any = None,
    h1_impulse: Any = None,
) -> Optional[float]:
    """Тільки реальний рівень. Немає даних — None, не вигадуємо."""
    side = str(direction or "").upper()
    rows = _bars(daily_candles)
    pdh = pdl = None
    if len(rows) >= 2:
        prev = rows[-2]
        pdh, pdl = float(prev["high"]), float(prev["low"])
    h4 = _f(h4_level)
    imp = _f(h1_impulse)
    # LONG — хай попереднього дня; SHORT — лой. Не вигадуємо протилежний бік.
    cands = [x for x in (pdh if side == "LONG" else pdl, h4, imp) if x is not None]
    if not cands:
        return None
    if side == "SHORT":
        return min(cands)
    return max(cands)


def m15_structure_broken(*, direction: str, candles_m15: Any) -> bool:
    """Злам проти позиції: LONG — закриття нижче останнього HL; SHORT — вище LH."""
    rows = _bars(candles_m15)
    if len(rows) < 4:
        return False
    side = str(direction or "").upper()
    swing = last_swing_hl_lh(direction=side, candles_m15=candles_m15)
    if swing is None:
        return False
    last_cl = rows[-1]["close"]
    if side == "LONG":
        return last_cl < swing
    return last_cl > swing


def m15_continuation(*, direction: str, candles_m15: Any) -> bool:
    rows = _bars(candles_m15)
    if len(rows) < 3:
        return False
    side = str(direction or "").upper()
    last = rows[-1]
    if side == "LONG":
        held = last["low"] >= min(r["low"] for r in rows[-4:-1])
        return held and last["close"] > last["open"]
    held = last["high"] <= max(r["high"] for r in rows[-4:-1])
    return held and last["close"] < last["open"]


MANAGE_STATES = ("FLAT", "ACTIVE", "TP1", "TP2", "TRAIL", "CLOSED")


@dataclass
class ManageBook:
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    state: str = "ACTIVE"
    last_event: str = ""
    mfe: float = 0.0
    mae: float = 0.0
    trail_sl: Optional[float] = None
    reentered: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)


def excursion_update(
    book: ManageBook,
    price: float,
    high: Optional[float] = None,
    low: Optional[float] = None,
) -> None:
    e = float(book.entry)
    side = str(book.direction).upper()
    hi = float(high) if high is not None else price
    lo = float(low) if low is not None else price
    if side == "LONG":
        fav = (hi - e) / e * 100.0
        adv = (e - lo) / e * 100.0
    else:
        fav = (e - lo) / e * 100.0
        adv = (hi - e) / e * 100.0
    if fav > book.mfe:
        book.mfe = fav
    if adv > book.mae:
        book.mae = adv


def _hit_tp(side: str, price: float, level: Optional[float]) -> bool:
    if level is None:
        return False
    if side == "LONG":
        return price >= float(level)
    return price <= float(level)


def _hit_sl(side: str, price: float, sl: float) -> bool:
    if side == "LONG":
        return price <= sl
    return price >= sl


def next_manage_event(
    book: ManageBook,
    *,
    price: Any,
    candles_m15: Any = None,
    high: Any = None,
    low: Any = None,
    ignore_sl: bool = False,
) -> Optional[Dict[str, Any]]:
    """Одне повідомлення лише при зміні стану. Не ордер."""
    px = _f(price)
    if px is None or book.state == "CLOSED":
        return None
    side = str(book.direction).upper()
    hi = _f(high)
    lo = _f(low)
    excursion_update(book, px, high=hi if hi is not None else px, low=lo if lo is not None else px)
    sl_now = float(book.trail_sl if book.trail_sl is not None else book.sl)
    sl_px = (lo if side == "LONG" else hi) or px
    tp_px = (hi if side == "LONG" else lo) or px

    if (not ignore_sl) and _hit_sl(side, float(sl_px), sl_now) and book.state != "CLOSED":
        if book.last_event == "SL":
            return None
        book.state = "CLOSED"
        book.last_event = "SL"
        return {
            "event": "TRADE_CLOSED",
            "kind": "SL",
            "message": f"{book.symbol} закрито по стопу {sl_now}.",
            "state": book.state,
        }

    if book.state == "ACTIVE" and _hit_tp(side, float(tp_px), book.tp1):
        if book.last_event == "TP1":
            return None
        book.state = "TP1"
        book.last_event = "TP1"
        book.trail_sl = float(book.entry)
        return {
            "event": "TRADE_UPDATE",
            "kind": "TP1",
            "message": (
                f"✅ TP1 · {book.symbol} {side}\n"
                "Закрий 50–70% позиції зараз\n"
                f"Перестав SL в беззбиток: {book.entry}"
            ),
            "state": book.state,
        }

    if book.state in ("TP1", "ACTIVE") and book.tp2 is not None and _hit_tp(side, float(tp_px), book.tp2):
        if book.last_event == "TP2":
            return None
        book.state = "TP2"
        book.last_event = "TP2"
        # Після TP2 стоп у BE, поки не з’явиться новий хай/лоу імпульсу і підтверджений HL/LH.
        book.trail_sl = float(book.entry)
        rows = _bars(candles_m15)
        if rows:
            if side == "LONG":
                book.extras["arm_extreme"] = max(r["high"] for r in rows)
            else:
                book.extras["arm_extreme"] = min(r["low"] for r in rows)
        extra = f"\nTP3: {book.tp3}" if book.tp3 is not None else ""
        return {
            "event": "TRADE_UPDATE",
            "kind": "TP2",
            "message": (
                f"✅ TP2 · {book.symbol} {side}\n"
                "Закрий ще частину\n"
                f"SL в BE {book.trail_sl}, далі трейл за M15 HL/LH після нового екстремуму"
                f"{extra}"
            ),
            "state": book.state,
        }

    if book.state in ("TP2", "TRAIL"):
        impulse = _impulse_m15_rows(book, candles_m15)
        if impulse and m15_structure_broken(direction=side, candles_m15=impulse):
            if book.last_event == "REVERSAL":
                return None
            book.state = "CLOSED"
            book.last_event = "REVERSAL"
            return {
                "event": "TRADE_CLOSED",
                "kind": "REVERSAL",
                "message": f"Ознаки розвороту. Фіксуй залишок по ринку {px}",
                "state": book.state,
            }
        new_trail = last_m15_structure_stop(
            direction=side,
            candles_m15=impulse,
            fallback=book.trail_sl,
        )
        if new_trail is not None and book.trail_sl is not None:
            moved = (side == "LONG" and new_trail > book.trail_sl) or (
                side == "SHORT" and new_trail < book.trail_sl
            )
            if moved:
                book.trail_sl = float(new_trail)
                book.state = "TRAIL"
                if book.last_event == "TRAIL" and abs(new_trail - float(book.extras.get("last_trail") or 0)) < 1e-12:
                    return None
                book.extras["last_trail"] = new_trail
                book.last_event = "TRAIL"
                return {
                    "event": "TRADE_UPDATE",
                    "kind": "TRAIL",
                    "message": f"Трейлінг: SL переставлено на {new_trail} (M15 HL/LH)",
                    "state": book.state,
                    "trail_sl": float(new_trail),
                }
        if m15_continuation(direction=side, candles_m15=candles_m15):
            if book.last_event == "HOLD":
                return None
            book.last_event = "HOLD"
            return {
                "event": "TRADE_UPDATE",
                "kind": "HOLD",
                "message": f"Відкат відпрацьовано, рух продовжується. Тримай, SL {sl_now}",
                "state": book.state,
            }

    if book.state in ("TP2", "TRAIL") and book.tp3 is not None and _hit_tp(side, float(tp_px), book.tp3):
        if book.last_event == "TP3":
            return None
        book.state = "CLOSED"
        book.last_event = "TP3"
        return {
            "event": "TRADE_CLOSED",
            "kind": "TP3",
            "message": f"{book.symbol} закрито по TP3 {book.tp3}.",
            "state": book.state,
        }
    return None


def replay_manage(book: ManageBook, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Прогін свічок. На одному барі можна TP1 потім TP2 / TRAIL потім TP3."""
    events: List[Dict[str, Any]] = []
    hist: List[Dict[str, Any]] = []
    for c in candles:
        hist.append(c)
        px = _f(c.get("close"))
        saw_event = False
        for _ in range(6):
            ev = next_manage_event(
                book,
                price=px,
                candles_m15=hist,
                high=_f(c.get("high")),
                low=_f(c.get("low")),
                ignore_sl=saw_event,
            )
            if not ev:
                break
            saw_event = True
            ev["ts"] = c.get("ts") or ""
            events.append(ev)
            if book.state == "CLOSED":
                return events
    return events
