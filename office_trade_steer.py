"""PR42: стоп за зоною маніпуляції, тригер входу, ведення, тихий журнал сигналу.

Не змінює ATR 80/90, Edge 85, MIN_RR 1.5. Не відкриває ордери.
Немає свічок → DATA_UNAVAILABLE, рівні не вигадуємо.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from office_radar import MIN_RR
from office_topdown import DATA_OK, DATA_UNAVAILABLE, calc_sl_with_buffer, last_impulse_candle

KIND_STEER = "trade_steer"
SL_ATR_MULT = 1.0
RR_TIGHT_FLAG = 6.0
OFFICE_SIGNAL_REASON = "office signal card (not /position)"
OFFICE_SIGNAL_SETUP = "OFFICE_SIGNAL"
ATR_PERIOD = 14
# Свічок M15 у зоні входу, інакше стоп не вигадуємо.
MIN_MANIP_BARS = 5
# Хай/лой далеко від входу — не «зона маніпуляції входу».
MANIP_NEAR_PCT = 0.04
# Бібліотека: OTE 0.62–0.79 (SMC_ANALIZ / SMART_MANY 0.13.1). 0.618/0.786 — pd_array.
OTE_062 = 0.62
OTE_705 = 0.705
OTE_079 = 0.79
# Старий сканер (STATISTYKA_SNAPSHOT): вхід 70% / добір 20%. Залишок 10% — друге відро глибше.
SCALE_ENTRY_PCT = 70
SCALE_ADD_PCT = 20
SCALE_ADD2_PCT = 10


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
        out.append({"open": o, "high": h, "low": l, "close": cl, "ts": str(c.get("ts") or "")})
    return out


def true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr_from_candles(candles: Any, period: int = ATR_PERIOD) -> Optional[float]:
    rows = _bars(candles)
    if len(rows) < 2:
        return None
    trs: List[float] = []
    for i in range(1, len(rows)):
        trs.append(true_range(rows[i - 1]["close"], rows[i]["high"], rows[i]["low"]))
    if not trs:
        return None
    take = trs[-max(1, int(period)) :]
    return sum(take) / float(len(take))


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
    """Зона сильної свічки + OTE-відкат + відра 70/20/10. Без свічки — DATA_UNAVAILABLE."""
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
        "source": "last_impulse_candle",
    }
    if side not in ("LONG", "SHORT"):
        return empty
    sc = last_impulse_candle(candles, direction=side)
    if not sc:
        return empty
    hi, lo = float(sc["high"]), float(sc["low"])
    if hi <= lo:
        return empty
    span = hi - lo
    eq = (hi + lo) / 2.0
    if side == "LONG":
        ote_062 = hi - span * OTE_062
        ote_705 = hi - span * OTE_705
        ote_079 = hi - span * OTE_079
        ote_lo, ote_hi = ote_079, ote_062
        sl_anchor = lo
        trigger_level = ote_hi
        cancel_level = lo
    else:
        ote_062 = lo + span * OTE_062
        ote_705 = lo + span * OTE_705
        ote_079 = lo + span * OTE_079
        ote_lo, ote_hi = ote_062, ote_079
        sl_anchor = hi
        trigger_level = ote_lo
        cancel_level = hi
    packed = calc_sl_with_buffer(sl_anchor, side, tick_size=tick_size, price=price or eq)
    buckets = [
        {"label": "Вхід 1", "price": ote_062, "pct": SCALE_ENTRY_PCT},
        {"label": "Добір", "price": ote_705, "pct": SCALE_ADD_PCT},
        {"label": "Добір 2", "price": ote_079, "pct": SCALE_ADD2_PCT},
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
        "sl": packed.get("sl"),
        "cancel_level": cancel_level,
        "trigger_level": trigger_level,
        "source": "last_impulse_candle",
        "explain": packed.get("explain"),
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
    """Стоп за зоною маніпуляції + люфт Герчика. RR>6 — червоний прапор (стоп занадто тісний)."""
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
    packed = calc_sl_with_buffer(anchor.get("level"), side, tick_size=tick_size, price=e)
    sl = packed.get("sl")
    notes: List[str] = []
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


def last_m15_structure_stop(*, direction: str, candles_m15: Any, fallback: Any) -> Optional[float]:
    rows = _bars(candles_m15)
    fb = _f(fallback)
    if len(rows) < 3:
        return fb
    side = str(direction or "").upper()
    if side == "LONG":
        raw = min(r["low"] for r in rows[-5:])
        return max(raw, fb) if fb is not None else raw
    raw = max(r["high"] for r in rows[-5:])
    return min(raw, fb) if fb is not None else raw


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
    last_cl = rows[-1]["close"]
    if side == "LONG":
        hl = min(r["low"] for r in rows[-6:-1])
        return last_cl < hl
    lh = max(r["high"] for r in rows[-6:-1])
    return last_cl > lh


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

    if _hit_sl(side, float(sl_px), sl_now) and book.state != "CLOSED":
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
        struct = last_m15_structure_stop(direction=side, candles_m15=candles_m15, fallback=book.tp1)
        book.trail_sl = float(struct if struct is not None else book.tp1)
        extra = f"\nTP3: {book.tp3}" if book.tp3 is not None else ""
        return {
            "event": "TRADE_UPDATE",
            "kind": "TP2",
            "message": (
                f"✅ TP2 · {book.symbol} {side}\n"
                "Закрий ще частину\n"
                f"SL на {book.trail_sl}{extra}"
            ),
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

    if book.state in ("TP2", "TRAIL"):
        if m15_structure_broken(direction=side, candles_m15=candles_m15):
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
        new_trail = last_m15_structure_stop(direction=side, candles_m15=candles_m15, fallback=book.trail_sl)
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
                    "message": f"Трейлінг: SL переставлено на {new_trail}",
                    "state": book.state,
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
    return None


def replay_manage(book: ManageBook, candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Прогін свічок. Події лише при зміні стану."""
    events: List[Dict[str, Any]] = []
    hist: List[Dict[str, Any]] = []
    for c in candles:
        hist.append(c)
        px = _f(c.get("close"))
        ev = next_manage_event(
            book,
            price=px,
            candles_m15=hist,
            high=_f(c.get("high")),
            low=_f(c.get("low")),
        )
        if ev:
            ev["ts"] = c.get("ts") or ""
            events.append(ev)
        if book.state == "CLOSED":
            break
    return events
