"""Щогодинний облік стабільності свічок: частка ф'ючерсних і кількість 429 — для авто-вмикання стакана (24 год поспіль).

Кожну повну годину роботи процесу пишемо подію DATA_STABILITY {hour, futures, total, share, rate_limited}. Година, у яку процес стартував або
перезапускався, НЕ записується (неповна) — тож перезапуск обриває серію, і «24 год стабільно» означає 24 години без перезапусків і збоїв.
`stable_24h` — true, лише коли є 24 послідовні години поспіль, кожна з часткою ф'ючерсних ≥ 95% і без жодного 429.
Стакан (OFFICE_DEPTH_ENABLED=auto) вмикається сам за цією умовою; 1 — примусово, 0 — вимкнено."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

MIN_SHARE = 0.95
MIN_CALLS_PER_HOUR = 10          # година без жодного читання свічок нічого не доводить
HOURS = 24
_STATE: Dict[str, Any] = {"db": None, "hour": None, "base": None, "proc_start": time.time()}


def set_db(db_path: str) -> None:
    _STATE["db"] = db_path


def _counters() -> Dict[str, int]:
    from office_market_data import _HEALTH

    by = _HEALTH.get("by_src") or {}
    return {"futures": int(by.get("binance_futures", 0)), "total": int(sum(by.values())), "rate_limited": int(_HEALTH.get("rate_limited", 0))}


def tick(now: Optional[float] = None, db: Optional[str] = None, counters: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
    """Викликається періодично (кожні ~5 хв). На межі години записує попередню годину, якщо вона була повною. Повертає запис або None."""
    now = time.time() if now is None else now
    h = int(now // 3600)
    cur = counters if counters is not None else _counters()
    if _STATE["hour"] is None:
        _STATE["hour"], _STATE["base"] = h, cur
        return None
    if h == _STATE["hour"]:
        return None
    rec = None
    prev_h, base = _STATE["hour"], _STATE["base"]
    if _STATE["proc_start"] <= prev_h * 3600 + 120:          # процес працював уже на початку тієї години → вона повна
        d_total = cur["total"] - base["total"]
        d_fut = cur["futures"] - base["futures"]
        rec = {"hour": prev_h, "futures": d_fut, "total": d_total, "share": round(d_fut / d_total, 4) if d_total > 0 else None,
               "rate_limited": cur["rate_limited"] - base["rate_limited"]}
        target = db or _STATE["db"]
        if target:
            try:
                from office_bridge import log_event

                log_event(target, "DATA_STABILITY", rec)
            except Exception as exc:  # noqa: BLE001
                print(f"[stability] запис не вдався: {type(exc).__name__}: {exc}")
    _STATE["hour"], _STATE["base"] = h, cur
    return rec


def _records(db: str, limit: int = 120) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT ?", ("DATA_STABILITY", limit))
    out = []
    for r in rows or []:
        try:
            out.append(json.loads(r[0]) if isinstance(r[0], str) else dict(r[0]))
        except (TypeError, ValueError):
            continue
    return out


def hour_ok(rec: Dict[str, Any]) -> bool:
    try:
        return (int(rec.get("total") or 0) >= MIN_CALLS_PER_HOUR and float(rec.get("share") or 0.0) >= MIN_SHARE and int(rec.get("rate_limited") or 0) == 0)
    except (TypeError, ValueError):
        return False


def status(db: Optional[str] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """{'stable': bool, 'streak_hours': n, 'need': 24}: скільки годин поспіль стабільно (від найновішої запису назад)."""
    now = time.time() if now is None else now
    target = db or _STATE["db"]
    if not target:
        return {"stable": False, "streak_hours": 0, "need": HOURS, "note": "БД недоступна"}
    try:
        recs = _records(target)
    except Exception:  # noqa: BLE001
        return {"stable": False, "streak_hours": 0, "need": HOURS, "note": "БД недоступна"}
    by_hour: Dict[int, Dict[str, Any]] = {}
    for r in recs:
        try:
            by_hour.setdefault(int(r["hour"]), r)
        except (KeyError, TypeError, ValueError):
            continue
    cur = int(now // 3600)
    streak = 0
    h = cur - 1
    if h not in by_hour and (h - 1) in by_hour:     # остання година ще не записана (запис на межі години) — рахуємо від попередньої
        h -= 1
    while h in by_hour and hour_ok(by_hour[h]):
        streak += 1
        h -= 1
    return {"stable": streak >= HOURS, "streak_hours": streak, "need": HOURS}


_AUTO_CACHE: Dict[str, Any] = {"at": 0.0, "v": False}


def auto_ok(now: Optional[float] = None) -> bool:
    """Кеш 5 хв: чи виконано умову 24 год для авто-вмикання стакана."""
    now = time.time() if now is None else now
    if now - _AUTO_CACHE["at"] < 300:
        return bool(_AUTO_CACHE["v"])
    _AUTO_CACHE["at"], _AUTO_CACHE["v"] = now, bool(status(now=now)["stable"])
    return bool(_AUTO_CACHE["v"])


def reset_for_tests() -> None:
    _STATE.update(db=None, hour=None, base=None, proc_start=time.time())
    _AUTO_CACHE.update(at=0.0, v=False)
