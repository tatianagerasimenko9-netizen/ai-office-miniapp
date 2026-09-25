"""Top-down структура для карток Лева: D1→H4→H1, азія, свіп, SL з люфтом.

Без вигаданих свічок: немає даних → DATA_UNAVAILABLE, не CONFIRMED.
Не змінює пороги ATR 80/90 і Edge 85.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from math import ceil, floor
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from office_radar import MIN_RR, detect_sweep_from_candles

KIND_TOPDOWN = "topdown"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
DATA_OK = "DATA_OK"
ASIA_UTC = (0, 8)
ASIA_MIN_BARS = 4
ASIA_RANGE_MAX_PCT = 0.15
SWEEP_NEAR_PCT = 0.004
ENTRY_WAITING_SWEEP = "WAITING_SWEEP"
ENTRY_CONFIRMED = "CONFIRMED_ENTRY"
SWEEP_AHEAD = "ще попереду"
SWEEP_DONE = "стався"
COUNTER_TREND_MIN_RR = 2.5
ENTRY_KIND_PULLBACK = "impulse_pullback"
ENTRY_KIND_MARKET = "market"
ENTRY_KIND_RETEST = "sweep_retest"
IMPULSE_BODY_RATIO = 0.55
IMPULSE_MIN_BODY_PCT = 0.002
PULLBACK_38 = 0.38
PULLBACK_50 = 0.50
# Люфт Герчика: 0.12% ціни або 3 кроки округлення — що більше, у коридорі 0.10–0.15%.
BUFFER_PCT = 0.0012
BUFFER_TICKS = 3


def _px(value: Any) -> str:
    from office_telegram_filter import format_px

    return format_px(value)


def _parse_ts(ts: Any) -> Optional[datetime]:
    from office_telegram_filter import parse_quote_dt

    return parse_quote_dt(ts)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x <= 0:
        return None
    return x


def infer_round_to(price: float, tick_size: Any = None) -> float:
    t = _f(tick_size)
    if t is not None and t > 0:
        return t
    p = float(price)
    if p >= 1000:
        return 1.0
    if p >= 100:
        return 0.5
    if p >= 10:
        return 0.1
    if p >= 1:
        return 0.01
    if p >= 0.1:
        return 0.001
    if p >= 0.01:
        return 0.0001
    return 0.000001


def calc_sl_with_buffer(
    level: Any,
    direction: str,
    tick_size: Any = None,
    price: Any = None,
) -> Dict[str, Any]:
    """Стоп за круглим рівнем + люфт. Повертає цифри, не словесний опис."""
    lv = _f(level)
    if lv is None:
        return {"sl": None, "round_level": None, "buffer": None, "data_status": DATA_UNAVAILABLE}
    px = _f(price) or lv
    step = infer_round_to(px, tick_size)
    buf = max(step * BUFFER_TICKS, px * BUFFER_PCT)
    buf = min(max(buf, px * 0.0010), px * 0.0015)
    side = str(direction or "").upper()
    if side == "SHORT":
        round_level = ceil(lv / step - 1e-12) * step
        sl = round_level + buf
    else:
        round_level = floor(lv / step + 1e-12) * step
        sl = round_level - buf
        if sl <= 0:
            sl = max(lv * 0.998, step)
    return {
        "sl": sl,
        "round_level": round_level,
        "buffer": buf,
        "step": step,
        "data_status": DATA_OK,
        "explain": (
            f"{'вище' if side == 'SHORT' else 'нижче'} круглого {_px(round_level)} "
            f"+ люфт {_px(buf)}"
        ),
    }


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
        row = {"open": o, "high": h, "low": l, "close": cl, "ts": c.get("ts") or ""}
        out.append(row)
    return out


def swing_points(candles: List[Dict[str, Any]], *, wing: int = 2) -> Tuple[List[Tuple[int, float, str]], List[Tuple[int, float, str]]]:
    rows = _bars(candles)
    highs: List[Tuple[int, float, str]] = []
    lows: List[Tuple[int, float, str]] = []
    if len(rows) < wing * 2 + 1:
        return highs, lows
    for i in range(wing, len(rows) - wing):
        h = rows[i]["high"]
        l = rows[i]["low"]
        if all(h >= rows[j]["high"] for j in range(i - wing, i + wing + 1)):
            highs.append((i, h, str(rows[i].get("ts") or "")))
        if all(l <= rows[j]["low"] for j in range(i - wing, i + wing + 1)):
            lows.append((i, l, str(rows[i].get("ts") or "")))
    return highs, lows


def structure_label(candles: Any) -> Dict[str, Any]:
    """HH/HL vs LH/LL зі свінгів. Немає двох свінгів — DATA_UNAVAILABLE, не вигадуємо тренд."""
    highs, lows = swing_points(list(candles or []))
    if len(highs) < 2 or len(lows) < 2:
        return {
            "label": "немає двох підтверджених свінгів",
            "bias": "",
            "last_high": highs[-1][1] if highs else None,
            "last_low": lows[-1][1] if lows else None,
            "data_status": DATA_UNAVAILABLE,
        }
    h1, h2 = highs[-2][1], highs[-1][1]
    l1, l2 = lows[-2][1], lows[-1][1]
    if h2 > h1 and l2 > l1:
        bias, label = "LONG", "висхідний тренд (HH/HL)"
    elif h2 < h1 and l2 < l1:
        bias, label = "SHORT", "низхідний тренд (LH/LL)"
    else:
        bias, label = "", "змішана структура / флет"
    return {
        "label": label,
        "bias": bias,
        "last_high": h2,
        "last_low": l2,
        "data_status": DATA_OK,
    }


def last_fvg(candles: Any) -> Dict[str, Any]:
    rows = _bars(candles)
    if len(rows) < 3:
        return {"found": False, "data_status": DATA_UNAVAILABLE}
    for i in range(len(rows) - 1, 1, -1):
        a, b, c = rows[i - 2], rows[i - 1], rows[i]
        if c["low"] > a["high"]:
            return {
                "found": True,
                "side": "bullish",
                "low": a["high"],
                "high": c["low"],
                "ts": c.get("ts") or "",
                "data_status": DATA_OK,
            }
        if c["high"] < a["low"]:
            return {
                "found": True,
                "side": "bearish",
                "low": c["high"],
                "high": a["low"],
                "ts": c.get("ts") or "",
                "data_status": DATA_OK,
            }
    return {"found": False, "data_status": DATA_OK}


def asian_session_range(
    candles: Any,
    *,
    asof: Any = None,
    current_price: Any = None,
) -> Dict[str, Any]:
    """Asian High/Low лише з UTC 00–08 ПОТОЧНОЇ доби. Вчорашню сесію не мішаємо."""
    rows = _bars(candles)
    now = _parse_ts(asof) if asof is not None else datetime.now(timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date()
    session_start = datetime.combine(today, time(ASIA_UTC[0], 0), tzinfo=timezone.utc)
    session_end = datetime.combine(today, time(ASIA_UTC[1], 0), tzinfo=timezone.utc)
    asian: List[Dict[str, Any]] = []
    for c in rows:
        dt = _parse_ts(c.get("ts"))
        if dt is None:
            continue
        dt = dt.astimezone(timezone.utc)
        if session_start <= dt < session_end:
            asian.append(c)
    if len(asian) < ASIA_MIN_BARS:
        return {
            "high": None,
            "low": None,
            "data_status": DATA_UNAVAILABLE,
            "note": DATA_UNAVAILABLE,
        }
    high = max(float(c["high"]) for c in asian)
    low = min(float(c["low"]) for c in asian)
    px = _f(current_price)
    if px is None and rows:
        px = _f(rows[-1].get("close"))
    if px is not None and px > 0:
        if abs(high - px) / px > ASIA_RANGE_MAX_PCT or abs(low - px) / px > ASIA_RANGE_MAX_PCT:
            return {
                "high": None,
                "low": None,
                "data_status": DATA_UNAVAILABLE,
                "note": "DATA_UNAVAILABLE — range підозрілий",
            }
    return {
        "high": high,
        "low": low,
        "data_status": DATA_OK,
        "note": "",
    }


def _hhmm_kyiv(ts: Any) -> str:
    dt = _parse_ts(ts)
    if dt is None:
        return ""
    try:
        local = dt.astimezone(ZoneInfo("Europe/Kyiv"))
    except Exception:
        local = dt
    return f"{local.hour:02d}:{local.minute:02d}"


def last_impulse_candle(candles: Any, *, direction: str) -> Optional[Dict[str, Any]]:
    """Остання імпульсна свічка в бік сетапу. Без сильного тіла — None, зону не вигадуємо."""
    rows = _bars(candles)
    side = str(direction or "").upper()
    best: Optional[Dict[str, Any]] = None
    for c in reversed(rows[-16:]):
        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        rng = h - l
        body = abs(cl - o)
        if rng <= 0 or body / rng + 1e-12 < IMPULSE_BODY_RATIO:
            continue
        mid = (h + l) / 2.0 or cl
        if mid > 0 and body / mid + 1e-12 < IMPULSE_MIN_BODY_PCT:
            continue
        if side == "LONG" and cl <= o:
            continue
        if side == "SHORT" and cl >= o:
            continue
        if side not in ("LONG", "SHORT"):
            continue
        best = {
            "open": o,
            "high": h,
            "low": l,
            "close": cl,
            "ts": c.get("ts") or "",
            "body": body,
        }
        break
    return best


def _same_px(a: Any, b: Any) -> bool:
    fa, fb = _f(a), _f(b)
    if fa is None or fb is None or fa <= 0 or fb <= 0:
        return False
    if abs(fa - fb) / max(fa, fb) <= 1e-6:
        return True
    from office_telegram_filter import format_px

    return format_px(fa) == format_px(fb) and bool(format_px(fa))


def plan_entry_point(
    *,
    direction: str,
    price: Any,
    candles: Any = None,
    sweep_level: Any = None,
    sweep_happened: bool = False,
    tf: str = "M15",
) -> Dict[str, Any]:
    """Точка входу: відкат 38–50% імпульсу, ретест свіпу або явно «по ринку»."""
    from office_telegram_filter import format_px

    side = str(direction or "").upper()
    px = _f(price)
    tf_s = str(tf or "M15").upper()
    if tf_s in ("1H", "H1", "60"):
        tf_s = "M15"
    if tf_s in ("5M", "5"):
        tf_s = "M5"
    market = {
        "kind": ENTRY_KIND_MARKET,
        "entry": px,
        "sl_anchor": None,
        "wait": False,
        "tf": tf_s,
        "retrace_pct": None,
        "card_note": f"по ринку {format_px(px)} (зона вже досягнута)" if format_px(px) else "",
    }
    if px is None:
        market["card_note"] = ""
        return market
    impulse = last_impulse_candle(candles, direction=side)
    if impulse:
        body = float(impulse["body"])
        o, cl = float(impulse["open"]), float(impulse["close"])
        if side == "LONG":
            top = max(o, cl)
            fib38 = top - PULLBACK_38 * body
            fib50 = top - PULLBACK_50 * body
            zone_lo, zone_hi = min(fib50, fib38), max(fib50, fib38)
            in_zone = zone_lo - 1e-12 <= px <= zone_hi + 1e-12
            need_wait = px > zone_hi
            entry_px = fib50
            sl_anchor = float(impulse["low"])
        else:
            bot = min(o, cl)
            fib38 = bot + PULLBACK_38 * body
            fib50 = bot + PULLBACK_50 * body
            zone_lo, zone_hi = min(fib38, fib50), max(fib38, fib50)
            in_zone = zone_lo - 1e-12 <= px <= zone_hi + 1e-12
            need_wait = px < zone_lo
            entry_px = fib50
            sl_anchor = float(impulse["high"])
        if in_zone:
            return {
                "kind": ENTRY_KIND_MARKET,
                "entry": px,
                "sl_anchor": sl_anchor,
                "wait": False,
                "tf": tf_s,
                "retrace_pct": 50,
                "card_note": f"по ринку {format_px(px)} (зона вже досягнута)",
            }
        if need_wait and entry_px and entry_px > 0:
            return {
                "kind": ENTRY_KIND_PULLBACK,
                "entry": entry_px,
                "sl_anchor": sl_anchor,
                "wait": True,
                "tf": tf_s,
                "retrace_pct": 50,
                "card_note": f"{format_px(entry_px)} (відкат 50% імпульсної свічки {tf_s})",
            }
    sw_lv = _f(sweep_level)
    if sweep_happened and sw_lv is not None and not _same_px(px, sw_lv):
        away = abs(px - sw_lv) / px
        if away > 0.0015:
            return {
                "kind": ENTRY_KIND_RETEST,
                "entry": sw_lv,
                "sl_anchor": sw_lv,
                "wait": True,
                "tf": tf_s,
                "retrace_pct": None,
                "card_note": f"{format_px(sw_lv)} (ретест після свіпу — чекати)",
            }
    note = f"по ринку {format_px(px)} (зона вже досягнута)"
    return {
        "kind": ENTRY_KIND_MARKET,
        "entry": px,
        "sl_anchor": None,
        "wait": False,
        "tf": tf_s,
        "retrace_pct": None,
        "card_note": note,
    }


def _bias_key(bias: Any) -> str:
    b = str(bias or "").strip().lower()
    if b in ("long", "bullish", "bull", "бичачий"):
        return "bullish"
    if b in ("short", "bearish", "bear", "ведмежий"):
        return "bearish"
    return ""


def structure_confluence(
    *,
    d1: Any = None,
    h1: Any = None,
    direction: str = "",
) -> Dict[str, Any]:
    """Суперечність D1/H1 — одне речення логіки, не мовчазний LONG."""
    d1d = d1 if isinstance(d1, dict) else {}
    h1d = h1 if isinstance(h1, dict) else {}
    d1_ok = str(d1d.get("data_status") or "") == DATA_OK
    h1_ok = str(h1d.get("data_status") or "") == DATA_OK
    d1_trend = _bias_key(d1d.get("bias")) if d1_ok else ""
    h1_trend = _bias_key(h1d.get("bias")) if h1_ok else ""
    d1_label = str(d1d.get("label") or "").strip()
    h1_label = str(h1d.get("label") or "").strip()
    parts = []
    if d1_ok and d1_label:
        parts.append(f"D1 {d1_label}")
    if h1_ok and h1_label:
        parts.append(f"H1 {h1_label}")
    structure_line = " · ".join(parts) if parts else "структура: DATA_UNAVAILABLE (немає свічок)"
    out: Dict[str, Any] = {
        "d1_trend": d1_trend,
        "h1_trend": h1_trend,
        "structure_line": structure_line,
        "logic_line": "",
        "confluence_note": "",
        "requires_m15_bos": False,
        "min_rr": float(MIN_RR),
        "conflict": False,
    }
    if d1_trend and h1_trend and d1_trend != h1_trend:
        out["conflict"] = True
        out["requires_m15_bos"] = True
        if d1_trend == "bullish" and h1_trend == "bearish":
            out["structure_line"] = "D1 бичачий · H1 корекція (LH/LL)"
            out["logic_line"] = "купуємо корекцію в D1 тренді після BOS на M15"
            out["confluence_note"] = (
                "D1 бичачий → шукаємо LONG від рівня підтримки\n"
                "H1 корекція вниз — чекаємо завершення корекції і BOS на M15"
            )
            out["min_rr"] = float(MIN_RR)
        elif d1_trend == "bearish" and h1_trend == "bullish":
            out["structure_line"] = "D1 ведмежий · H1 корекція (HH/HL)"
            out["logic_line"] = "проти D1 тренду — підвищений поріг, лише після BOS на M15"
            out["confluence_note"] = (
                "D1 ведмежий → SHORT у пріоритеті\n"
                "H1 бичача корекція — не входимо без BOS на M15 і RR≥2.5"
            )
            out["min_rr"] = float(COUNTER_TREND_MIN_RR)
        return out
    if d1_trend and h1_trend and d1_trend == h1_trend:
        ua = "бичачий" if d1_trend == "bullish" else "ведмежий"
        out["confluence_note"] = f"D1 і H1 {ua} — тренди збігаються"
        side = str(direction or "").upper()
        if side and ((side == "LONG" and d1_trend == "bearish") or (side == "SHORT" and d1_trend == "bullish")):
            out["requires_m15_bos"] = True
            out["min_rr"] = float(COUNTER_TREND_MIN_RR)
            out["logic_line"] = "напрям проти збігу D1/H1 — лише після BOS на M15"
    return out


def m15_bos_confirmed(candles: Any, *, direction: str) -> bool:
    """BOS на M15: закриття за останній підтверджений свінг у бік сетапу."""
    rows = _bars(candles)
    if len(rows) < 5:
        return False
    highs, lows = swing_points(rows)
    cl = float(rows[-1]["close"])
    side = str(direction or "").upper()
    if side == "LONG":
        if not highs:
            return False
        return cl > float(highs[-1][1])
    if side == "SHORT":
        if not lows:
            return False
        return cl < float(lows[-1][1])
    return False


def sweep_near(*, price: Any, level: Any, pct: float = SWEEP_NEAR_PCT) -> bool:
    p, lv = _f(price), _f(level)
    if p is None or lv is None or p <= 0:
        return False
    return abs(p - lv) / p <= float(pct) + 1e-12


def entry_gate_from_topdown(
    *,
    sweep: Any = None,
    confluence: Any = None,
    direction: str = "",
    rr_net: Any = None,
    m15_bos: bool = False,
    already_confirmed: bool = False,
) -> Dict[str, Any]:
    """Не підвищує WATCHING до сигналу. Свіп попереду — лише WAITING_SWEEP."""
    sw = sweep if isinstance(sweep, dict) else {}
    conf = confluence if isinstance(confluence, dict) else {}
    if (
        sw.get("ahead")
        or str(sw.get("status") or "") == SWEEP_AHEAD
        or str(sw.get("entry_mode") or "") == ENTRY_WAITING_SWEEP
    ):
        if already_confirmed:
            return {
                "entry_mode": ENTRY_WAITING_SWEEP,
                "allow_signal": False,
                "status": "WATCHING",
                "reason": "свіп ще попереду — вхід після свіпу",
            }
        return {
            "entry_mode": "",
            "allow_signal": False,
            "status": "WATCHING",
            "reason": "свіп ще попереду",
        }
    if not already_confirmed:
        return {
            "entry_mode": str(sw.get("entry_mode") or ENTRY_CONFIRMED),
            "allow_signal": False,
            "status": "WATCHING",
            "reason": "немає внутрішнього підтвердження рівня",
        }
    if conf.get("requires_m15_bos") and not m15_bos:
        return {
            "entry_mode": "WAITING_BOS",
            "allow_signal": False,
            "status": "WATCHING",
            "reason": "чекаємо BOS на M15",
        }
    try:
        need = float(conf.get("min_rr") if conf.get("min_rr") is not None else MIN_RR)
    except (TypeError, ValueError):
        need = float(MIN_RR)
    try:
        net = float(rr_net) if rr_net is not None else None
    except (TypeError, ValueError):
        net = None
    if net is not None and net + 1e-12 < need:
        return {
            "entry_mode": "BLOCKED_RR",
            "allow_signal": False,
            "status": "WATCHING",
            "reason": f"RR {net} < {need}",
        }
    _ = direction
    return {
        "entry_mode": ENTRY_CONFIRMED,
        "allow_signal": True,
        "status": "CONFIRMED",
        "reason": "свіп стався, структура дозволяє",
    }


def sweep_story(candles: Any, *, direction: str) -> Dict[str, Any]:
    """Свіп уже був (рівень+час) або ще попереду (рівень ліквідності). Без наміру MM."""
    rows = _bars(candles)
    empty = {
        "happened": False,
        "ahead": False,
        "status": "",
        "entry_mode": ENTRY_WAITING_SWEEP,
        "kind": "",
        "level": None,
        "ts": "",
        "hhmm": "",
        "line": "свіп: немає підтверджених свічок",
        "data_status": DATA_UNAVAILABLE,
        "mm_intent_claimed": False,
    }
    if len(rows) < 3:
        return empty
    sw = detect_sweep_from_candles(rows)
    last = rows[-1]
    side = str(direction or "").upper()
    ts = last.get("ts") or ""
    hhmm = _hhmm_kyiv(ts)
    if side == "SHORT" and sw.get("bsl_sweep"):
        lv = sw.get("sweep_level")
        return {
            "happened": True,
            "ahead": False,
            "status": SWEEP_DONE,
            "entry_mode": ENTRY_CONFIRMED,
            "kind": "BSL",
            "level": lv,
            "ts": ts,
            "hhmm": hhmm,
            "line": f"BSL знято о {hhmm or 'н/д'} на рівні {_px(lv)}",
            "data_status": DATA_OK,
            "mm_intent_claimed": False,
        }
    if side == "LONG" and sw.get("ssl_sweep"):
        lv = sw.get("sweep_level")
        return {
            "happened": True,
            "ahead": False,
            "status": SWEEP_DONE,
            "entry_mode": ENTRY_CONFIRMED,
            "kind": "SSL",
            "level": lv,
            "ts": ts,
            "hhmm": hhmm,
            "line": f"SSL знято о {hhmm or 'н/д'} на рівні {_px(lv)}",
            "data_status": DATA_OK,
            "mm_intent_claimed": False,
        }
    prev_high = max(rows[-3]["high"], rows[-2]["high"])
    prev_low = min(rows[-3]["low"], rows[-2]["low"])
    if side == "SHORT":
        return {
            "happened": False,
            "ahead": True,
            "status": SWEEP_AHEAD,
            "entry_mode": ENTRY_WAITING_SWEEP,
            "kind": "BSL",
            "level": prev_high,
            "ts": "",
            "hhmm": "",
            "line": f"ще попереду — BSL вище {_px(prev_high)}",
            "data_status": DATA_OK,
            "mm_intent_claimed": False,
        }
    return {
        "happened": False,
        "ahead": True,
        "status": SWEEP_AHEAD,
        "entry_mode": ENTRY_WAITING_SWEEP,
        "kind": "SSL",
        "level": prev_low,
        "ts": "",
        "hhmm": "",
        "line": f"ще попереду — SSL нижче {_px(prev_low)}",
        "data_status": DATA_OK,
        "mm_intent_claimed": False,
    }


def build_topdown(
    *,
    symbol: str = "",
    d1: Any = None,
    h4: Any = None,
    h1: Any = None,
    m15: Any = None,
    m5: Any = None,
    direction: str = "",
) -> Dict[str, Any]:
    """Знімок структури. Порожні ТФ не заповнюємо вигадкою."""
    d1s = structure_label(d1)
    h4s = structure_label(h4)
    h1s = structure_label(h1 if h1 is not None else m15)
    asia_src = m15 if m15 is not None else h1
    asia_asof = None
    asia_px = None
    if isinstance(asia_src, list) and asia_src and isinstance(asia_src[-1], dict):
        asia_asof = asia_src[-1].get("ts")
        asia_px = asia_src[-1].get("close")
    asia = asian_session_range(asia_src, asof=asia_asof, current_price=asia_px)
    sweep_src = m5 if (isinstance(m5, list) and len(m5) >= 3) else (h1 or m15)
    sweep = sweep_story(sweep_src, direction=direction) if direction else sweep_story(sweep_src, direction="LONG")
    fvg = last_fvg(h4 if h4 is not None else h1)
    conf = structure_confluence(d1=d1s, h1=h1s, direction=direction)
    have = any(
        x.get("data_status") == DATA_OK
        for x in (d1s, h4s, h1s, asia)
        if isinstance(x, dict)
    )
    return {
        "kind": KIND_TOPDOWN,
        "symbol": str(symbol or "").upper(),
        "d1": d1s,
        "h4": h4s,
        "h1": h1s,
        "asia": asia,
        "sweep": sweep,
        "fvg": fvg,
        "confluence": conf,
        "structure_line": str(conf.get("structure_line") or ""),
        "logic_line": str(conf.get("logic_line") or ""),
        "entry_mode": str(sweep.get("entry_mode") or ""),
        "requires_m15_bos": bool(conf.get("requires_m15_bos")),
        "data_status": DATA_OK if have else DATA_UNAVAILABLE,
        "opens_position": False,
        "mm_intent_claimed": False,
    }


def clock_pair_ua(source_at: Any, review_at: Any, *, scalp: bool = True) -> str:
    """«Сигнал від 23:09, зараз 23:53 — для скальпу застарів»."""
    a = _hhmm_kyiv(source_at) or "н/д"
    b = _hhmm_kyiv(review_at) or "н/д"
    age = ""
    da, db = _parse_ts(source_at), _parse_ts(review_at)
    if da and db:
        mins = int((db - da).total_seconds() // 60)
        if mins > 0:
            age = f" ({mins} хв)"
    kind = "для скальпу застарів" if scalp else "застарів для цього ТФ"
    return f"Сигнал від {a}, зараз {b}{age} — {kind}"
