"""Top-down структура для карток Лева: D1→H4→H1, азія, свіп, SL з люфтом.

Без вигаданих свічок: немає даних → DATA_UNAVAILABLE, не CONFIRMED.
Не змінює пороги ATR 80/90 і Edge 85.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import ceil, floor
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from office_radar import detect_sweep_from_candles

KIND_TOPDOWN = "topdown"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
DATA_OK = "DATA_OK"
ASIA_UTC = (0, 8)
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


def asian_session_range(candles: Any) -> Dict[str, Any]:
    """Asian High/Low з 15m (UTC 00–08), як fetch_session_levels. Без свічок — UNAVAILABLE."""
    rows = _bars(candles)
    highs: List[float] = []
    lows: List[float] = []
    for c in rows:
        dt = _parse_ts(c.get("ts"))
        if dt is None:
            continue
        h = int(dt.hour)
        if ASIA_UTC[0] <= h < ASIA_UTC[1]:
            highs.append(float(c["high"]))
            lows.append(float(c["low"]))
    if not highs or not lows:
        return {"high": None, "low": None, "data_status": DATA_UNAVAILABLE}
    return {
        "high": max(highs),
        "low": min(lows),
        "data_status": DATA_OK,
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


def sweep_story(candles: Any, *, direction: str) -> Dict[str, Any]:
    """Свіп уже був (рівень+час) або ще попереду (рівень ліквідності). Без наміру MM."""
    rows = _bars(candles)
    empty = {
        "happened": False,
        "ahead": False,
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
            "kind": "BSL",
            "level": lv,
            "ts": ts,
            "hhmm": hhmm,
            "line": f"BSL знято о {hhmm or 'н/д'} (High {_px(lv)})",
            "data_status": DATA_OK,
            "mm_intent_claimed": False,
        }
    if side == "LONG" and sw.get("ssl_sweep"):
        lv = sw.get("sweep_level")
        return {
            "happened": True,
            "ahead": False,
            "kind": "SSL",
            "level": lv,
            "ts": ts,
            "hhmm": hhmm,
            "line": f"SSL знято о {hhmm or 'н/д'} (Low {_px(lv)})",
            "data_status": DATA_OK,
            "mm_intent_claimed": False,
        }
    prev_high = max(rows[-3]["high"], rows[-2]["high"])
    prev_low = min(rows[-3]["low"], rows[-2]["low"])
    if side == "SHORT":
        return {
            "happened": False,
            "ahead": True,
            "kind": "BSL",
            "level": prev_high,
            "ts": "",
            "hhmm": "",
            "line": f"ще попереду — ліквідність лонгів вище {_px(prev_high)}",
            "data_status": DATA_OK,
            "mm_intent_claimed": False,
        }
    return {
        "happened": False,
        "ahead": True,
        "kind": "SSL",
        "level": prev_low,
        "ts": "",
        "hhmm": "",
        "line": f"ще попереду — ліквідність шортів нижче {_px(prev_low)}",
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
    asia = asian_session_range(m15 if m15 is not None else h1)
    sweep_src = m5 if (isinstance(m5, list) and len(m5) >= 3) else (h1 or m15)
    sweep = sweep_story(sweep_src, direction=direction) if direction else sweep_story(sweep_src, direction="LONG")
    fvg = last_fvg(h4 if h4 is not None else h1)
    have = any(
        x.get("data_status") == DATA_OK
        for x in (d1s, h4s, h1s, asia)
        if isinstance(x, dict)
    )
    parts = []
    if d1s.get("data_status") == DATA_OK:
        parts.append(f"D1 {d1s.get('label')}")
    if h1s.get("data_status") == DATA_OK:
        parts.append(f"H1 {h1s.get('label')}")
    structure_line = " · ".join(parts) if parts else "структура: DATA_UNAVAILABLE (немає свічок)"
    return {
        "kind": KIND_TOPDOWN,
        "symbol": str(symbol or "").upper(),
        "d1": d1s,
        "h4": h4s,
        "h1": h1s,
        "asia": asia,
        "sweep": sweep,
        "fvg": fvg,
        "structure_line": structure_line,
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
