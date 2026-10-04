"""Календарна структура часу: Weekly/Monthly/Quarterly Open, попередні H/L/C, відстані, час до закриття.

Чиста функція: бере денні (і, за потреби, годинні) свічки, нічого не викликає в мережі.
Це ІНФОРМАЦІЯ до сигналу, а не правило: жодних «у п'ятницю не торгуємо». Режими нижче — лише мітки часу (за календарем UTC):
  тиждень: WEEK_OPEN (понеділок), WEEK_CLOSE (неділя), інакше MID_WEEK;
  місяць: MONTH_OPEN (перші 2 дні), MONTH_CLOSE (останні 2 дні), інакше MID_MONTH;
  квартал: QUARTER_OPEN (перші 7 днів), QUARTER_CLOSE (останні 7 днів), інакше MID_QUARTER.
Тиждень, місяць і квартал рахуємо за UTC (так само, як свічки 1w/1M на біржі).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

DAYS_UA = ("понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя")


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def _day(c: Dict[str, Any]) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(c.get("ts")).replace("Z", "+00:00"))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _ohlc(rows: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not rows:
        return None
    return {"open": float(rows[0]["open"]), "high": max(float(r["high"]) for r in rows), "low": min(float(r["low"]) for r in rows),
            "close": float(rows[-1]["close"])}


def _quarter_start(d: datetime) -> datetime:
    return datetime(d.year, 3 * ((d.month - 1) // 3) + 1, 1, tzinfo=timezone.utc)


def _add_months(d: datetime, n: int) -> datetime:
    m = d.month - 1 + n
    return datetime(d.year + m // 12, m % 12 + 1, 1, tzinfo=timezone.utc)


def bounds(now: datetime) -> Dict[str, Any]:
    """Початки/кінці поточного й попереднього тижня, місяця, кварталу (UTC)."""
    day0 = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    w0 = day0 - timedelta(days=day0.weekday())
    m0 = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    q0 = _quarter_start(now)
    return {"w0": w0, "w1": w0 + timedelta(days=7), "pw0": w0 - timedelta(days=7),
            "m0": m0, "m1": _add_months(m0, 1), "pm0": _add_months(m0, -1),
            "q0": q0, "q1": _add_months(q0, 3), "pq0": _add_months(q0, -3)}


def _span(days: List[Dict[str, Any]], lo: datetime, hi: datetime) -> List[Dict[str, Any]]:
    out = []
    for c in days:
        d = c.get("_d")
        if d is not None and lo <= d < hi:
            out.append(c)
    return out


def _phase(now: datetime, a: datetime, b: datetime, open_days: float, close_days: float, names: tuple) -> str:
    if (now - a).total_seconds() < open_days * 86400:
        return names[0]
    if (b - now).total_seconds() <= close_days * 86400:
        return names[2]
    return names[1]


def _hm(sec: float) -> str:
    sec = max(0.0, sec)
    d, rem = divmod(int(sec), 86400)
    h, m = divmod(rem, 3600)
    m //= 60
    if d >= 2:
        return f"{d} дн {h} год"
    if d == 1:
        return f"1 дн {h} год"
    return f"{h} год {m:02d} хв"


def snapshot(now_ts: float, price: Any, daily: Any, *, hourly: Any = None) -> Dict[str, Any]:
    """Знімок структури часу на момент now_ts. Немає свічок для частини полів → ці поля None (нічого не вигадуємо)."""
    now = datetime.fromtimestamp(float(now_ts), tz=timezone.utc)
    p = _f(price)
    days = []
    for c in (daily if isinstance(daily, list) else []):
        d = _day(c)
        if d is not None and _f(c.get("open")) is not None:
            days.append(dict(c, _d=datetime(d.year, d.month, d.day, tzinfo=timezone.utc)))
    days.sort(key=lambda c: c["_d"])
    b = bounds(now)
    out: Dict[str, Any] = {"at": float(now_ts), "weekday": DAYS_UA[now.weekday()], "weekday_n": now.weekday(), "price": p}
    for key, a, z, pa in (("week", b["w0"], b["w1"], b["pw0"]), ("month", b["m0"], b["m1"], b["pm0"]), ("quarter", b["q0"], b["q1"], b["pq0"])):
        cur = _span(days, a, min(z, now + timedelta(days=1)))
        # період має бути покритий із першого дня, інакше «Open» був би вигаданим
        full = bool(cur) and cur[0]["_d"] == a
        o = _ohlc(cur) if full else None
        prev_rows = _span(days, pa, a)
        prev_need = (a - pa).days
        prev = _ohlc(prev_rows) if len(prev_rows) >= prev_need else None
        out[key] = {"open": o["open"] if o else None, "high": o["high"] if o else None, "low": o["low"] if o else None,
                    "prev": prev, "hours_to_close": round((z - now).total_seconds() / 3600.0, 2), "close_in": _hm((z - now).total_seconds()),
                    "dist_open_pct": round((p / o["open"] - 1.0) * 100.0, 3) if (p is not None and o and o["open"]) else None}
    out["week"]["phase"] = _phase(now, b["w0"], b["w1"], 1.0, 1.0, ("WEEK_OPEN", "MID_WEEK", "WEEK_CLOSE"))
    out["month"]["phase"] = _phase(now, b["m0"], b["m1"], 2.0, 2.0, ("MONTH_OPEN", "MID_MONTH", "MONTH_CLOSE"))
    out["quarter"]["phase"] = _phase(now, b["q0"], b["q1"], 7.0, 7.0, ("QUARTER_OPEN", "MID_QUARTER", "QUARTER_CLOSE"))
    out["closing"] = [k for k in ("week", "month", "quarter") if out[k]["phase"].endswith("_CLOSE")]
    try:
        from office_sessions import active_sessions

        out["sessions"] = active_sessions(float(now_ts))
    except Exception:  # noqa: BLE001
        out["sessions"] = []
    # прийняття нового тижневого Open: скільки годинних закриттів з початку тижня були вище/нижче Weekly Open
    wo = out["week"]["open"]
    hs = [h for h in (hourly if isinstance(hourly, list) else []) if _day(h) is not None and b["w0"] <= _day(h) <= now and _f(h.get("close")) is not None]
    if wo and len(hs) >= 6:
        above = sum(1 for h in hs if float(h["close"]) > wo)
        cross = sum(1 for a_, b_ in zip(hs, hs[1:]) if (float(a_["close"]) > wo) != (float(b_["close"]) > wo))
        out["week"]["accept"] = {"hours": len(hs), "above_pct": round(above / len(hs) * 100.0), "crossings": cross}
    return out


def _px(v: Any) -> str:
    x = _f(v)
    if x is None:
        return "—"
    return (f"{x:,.2f}" if abs(x) >= 100 else f"{x:.4f}".rstrip("0").rstrip(".")).replace(",", " ").replace(".", ",")


def _pct(v: Any) -> str:
    x = _f(v)
    return "—" if x is None else f"{x:+.2f}%".replace(".", ",").replace("+", "+").replace("-", "−")


def lines(snap: Dict[str, Any], name: str = "") -> List[str]:
    """Короткі рядки з цифрами для картки (без загальних слів на кшталт «кінець тижня може впливати»)."""
    out: List[str] = []
    w, m = snap.get("week") or {}, snap.get("month") or {}
    if w.get("close_in"):
        out.append(f"До закриття тижня {w['close_in']}" + (f"; до закриття місяця {m['close_in']}" if m.get("hours_to_close") is not None and m["hours_to_close"] <= 72 else "") + ".")
    who = f"{name} " if name else ""
    if w.get("dist_open_pct") is not None:
        side = "вище" if w["dist_open_pct"] >= 0 else "нижче"
        out.append(f"{who}на {abs(w['dist_open_pct']):.2f}% {side} Weekly Open ({_px(w['open'])})".replace(".", ",") + ".")
    if m.get("dist_open_pct") is not None:
        side = "вище" if m["dist_open_pct"] >= 0 else "нижче"
        out.append(f"{who}на {abs(m['dist_open_pct']):.2f}% {side} Monthly Open ({_px(m['open'])})".replace(".", ",") + ".")
    return out


def _hm_short(sec: float) -> str:
    sec = max(0.0, sec)
    d, rem = divmod(int(sec), 86400)
    h, m = divmod(rem, 3600)
    m //= 60
    return f"{d}д {h}г" if d >= 1 else f"{h}г {m:02d}хв"


def week_line(snap: Dict[str, Any], name: str = "BTC") -> str:
    """«Тиждень: BTC +1,06% від відкриття · до закриття 6г 24хв» (+ місяць, якщо до його закриття ≤ 3 днів). Порожньо, якщо даних немає."""
    w, m = snap.get("week") or {}, snap.get("month") or {}
    parts = []
    if w.get("dist_open_pct") is not None:
        parts.append(f"{name} {_pct(w['dist_open_pct']).replace('+', '+')} від відкриття".replace("%", "%"))
    if w.get("hours_to_close") is not None:
        parts.append(f"до закриття {_hm_short(w['hours_to_close'] * 3600)}")
    if m.get("hours_to_close") is not None and m["hours_to_close"] <= 72:
        parts.append(f"місяця {_hm_short(m['hours_to_close'] * 3600)}")
    return ("Тиждень: " + " · ".join(parts)) if parts else ""
