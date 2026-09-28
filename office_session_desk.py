"""Session Desk: план сесії з реальних свічок. Лише спостереження, не сигнал.

Межі сесій — як у session_clock_dst(): Asia 00:00–08:00 UTC, London 08:00–16:00
Europe/London, New York 08:00–16:00 America/New_York (літній/зимовий час).

Що рахуємо (тільки з OHLCV):
- діапазон попередньої завершеної сесії (high/low/close);
- діапазон поточної сесії на цю мить;
- чи ціна виходила за high/low попередньої сесії, і що далі:
  SWEEP — вийшла й закрилася назад усередині; ACCEPTED — закриття за рівнем;
  NOT_TESTED — рівень не зачеплено.
Свіп не трактуємо як розворот автоматично — лише фіксуємо подію.
Немає свічок / дірки → DATA_UNAVAILABLE. Ордерів і Telegram немає.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

SESSIONS = (
    ("asia", timezone.utc, 0, 8),
    ("london", ZoneInfo("Europe/London"), 8, 16),
    ("ny", ZoneInfo("America/New_York"), 8, 16),
)
LABEL = {"asia": "Азія", "london": "Лондон", "ny": "Нью-Йорк"}
MIN_BARS = 4


def _ts(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def _windows(now: datetime, days_back: int = 3) -> List[Tuple[str, datetime, datetime]]:
    out = []
    for name, tz, a, b in SESSIONS:
        local_today = now.astimezone(tz).date()
        for d in range(-days_back, 1):
            day = local_today + timedelta(days=d)
            start = datetime.combine(day, time(a), tzinfo=tz).astimezone(timezone.utc)
            end = datetime.combine(day, time(b), tzinfo=tz).astimezone(timezone.utc)
            if start <= now:
                out.append((name, start, end))
    return sorted(out, key=lambda x: x[1])


def _range(bars: List[Dict[str, Any]], start: datetime, end: datetime) -> Optional[Dict[str, Any]]:
    sel = [b for b in bars if start <= b["_t"] < end]
    if len(sel) < MIN_BARS:
        return None
    return {
        "high": max(b["high"] for b in sel),
        "low": min(b["low"] for b in sel),
        "close": sel[-1]["close"],
        "bars": len(sel),
    }


def _test_level(bars: List[Dict[str, Any]], level: float, side: str) -> Dict[str, Any]:
    """side='high': вихід вище; 'low': вихід нижче. Рішення за закриттям останньої свічки."""
    broke = [b for b in bars if (b["high"] > level if side == "high" else b["low"] < level)]
    if not broke:
        return {"state": "NOT_TESTED", "at": None}
    last_close = bars[-1]["close"]
    back_inside = last_close < level if side == "high" else last_close > level
    return {
        "state": "SWEEP" if back_inside else "ACCEPTED",
        "at": broke[0]["ts"],
        "extreme": max(b["high"] for b in broke) if side == "high" else min(b["low"] for b in broke),
    }


def session_brief(candles_m15: Any, *, now_utc: Optional[datetime] = None, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    bars = []
    for c in candles_m15 or []:
        if not isinstance(c, dict):
            continue
        t = _ts(c.get("ts"))
        try:
            h, l, cl = float(c["high"]), float(c["low"]), float(c["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if t is None or h < l:
            continue
        bars.append({"_t": t, "ts": t.isoformat(), "high": h, "low": l, "close": cl})
    bars.sort(key=lambda b: b["_t"])
    base = {"symbol": symbol, "as_of": now.isoformat(), "order_authorized": False, "is_signal": False}
    if not bars:
        return {**base, "data_status": "DATA_UNAVAILABLE", "reason": "немає свічок M15"}
    wins = _windows(now)
    current = [w for w in wins if w[1] <= now < w[2]]
    done = [w for w in wins if w[2] <= now]
    prev = done[-1] if done else None
    out: Dict[str, Any] = {**base, "data_status": "DATA_OK", "active": [LABEL[w[0]] for w in current]}
    if prev is None:
        return {**out, "data_status": "DATA_UNAVAILABLE", "reason": "немає завершеної сесії у вікні"}
    prev_rng = _range(bars, prev[1], prev[2])
    if prev_rng is None:
        return {**out, "data_status": "DATA_UNAVAILABLE", "reason": f"мало свічок за {LABEL[prev[0]]}"}
    out["previous"] = {"name": LABEL[prev[0]], "start": prev[1].isoformat(), "end": prev[2].isoformat(), **prev_rng}
    after = [b for b in bars if b["_t"] >= prev[2]]
    if after:
        out["since_previous"] = {
            "high_test": _test_level(after, prev_rng["high"], "high"),
            "low_test": _test_level(after, prev_rng["low"], "low"),
            "last_close": after[-1]["close"],
            "bars": len(after),
        }
    if current:
        cur = current[-1]
        cr = _range(bars, cur[1], min(cur[2], now + timedelta(seconds=1)))
        out["current"] = {"name": LABEL[cur[0]], "start": cur[1].isoformat(), **(cr or {"bars": 0})}
    return out
