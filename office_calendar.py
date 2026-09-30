"""Макрокалендар (безкоштовне джерело) і блок входу навколо важливих новин.

Джерело: тижневий JSON економічного календаря (faireconomy/ForexFactory), без ключа й оплати. Беремо лише події з високою
важливістю (impact=High) по країнах з OFFICE_CALENDAR_COUNTRIES (за замовчуванням USD — саме вони рухають крипторинок).
Правило блоку: нові плани не відкриваємо за OFFICE_CALENDAR_BEFORE_MIN (30) хв до виходу новини і OFFICE_CALENDAR_AFTER_MIN (15) хв після —
те саме вікно, що й у правилі NEWS_CHAOS. Немає даних календаря → статус DATA_UNAVAILABLE, вхід НЕ блокується, але про це чесно пишемо
(нічого не вигадуємо). Вмикається OFFICE_CALENDAR_BLOCK=1 (за замовчуванням вимкнено — тести й CI не ходять у мережу). Джерело ніколи не створює Telegram-повідомлень.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_CACHE: Dict[str, Any] = {"at": 0.0, "events": None, "fail_at": 0.0, "error": None}
_LOCK = threading.Lock()
_TTL = 3600.0          # джерело оновлюється рідко й лімітує частоту — раз на годину
_RETRY_AFTER_FAIL = 900.0
_STALE_OK = 7 * 86400.0  # тижневий календар — старі записи про заплановані події лишаються правдивими


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


def block_enabled() -> bool:
    return os.getenv("OFFICE_CALENDAR_BLOCK", "0").strip() == "1"


def _countries() -> List[str]:
    return [c.strip().upper() for c in os.getenv("OFFICE_CALENDAR_COUNTRIES", "USD").split(",") if c.strip()]


def parse(raw: Any) -> List[Dict[str, Any]]:
    """Сирий JSON → події {ts (UTC epoch), title, country, impact, forecast, previous}; сміття пропускаємо."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for e in raw:
        if not isinstance(e, dict):
            continue
        title = str(e.get("title") or e.get("event") or "").strip()
        try:
            dt = datetime.fromisoformat(str(e.get("date") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if not title:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append({"ts": dt.timestamp(), "title": title[:120], "country": str(e.get("country") or "").upper(),
                    "impact": str(e.get("impact") or "").strip().capitalize(), "forecast": e.get("forecast"), "previous": e.get("previous")})
    out.sort(key=lambda x: x["ts"])
    return out


def _fetch() -> List[Dict[str, Any]]:
    req = Request(os.getenv("OFFICE_CALENDAR_URL", URL).strip() or URL,
                  headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(req, timeout=10) as resp:
        return parse(json.loads(resp.read().decode("utf-8", errors="replace")))


def load(now: Optional[float] = None) -> Dict[str, Any]:
    """{'status': 'DATA_OK'|'DATA_UNAVAILABLE', 'events': [...]}. Кеш 1 год; після збою 15 хв не смикаємо джерело, віддаємо останні добрі дані."""
    now = time.time() if now is None else now
    with _LOCK:
        ev = _CACHE["events"]
        fresh = ev is not None and now - _CACHE["at"] < _TTL
        cooling = now - _CACHE["fail_at"] < _RETRY_AFTER_FAIL
        if not fresh and not cooling:
            try:
                ev = _fetch()
                _CACHE.update(at=now, events=ev, error=None)
            except Exception as exc:  # noqa: BLE001
                _CACHE.update(fail_at=now, error=f"{type(exc).__name__}: {exc}"[:160])
                ev = _CACHE["events"]
        if ev is not None and now - _CACHE["at"] <= _STALE_OK:
            return {"status": "DATA_OK", "events": ev}
        return {"status": "DATA_UNAVAILABLE", "events": [], "error": _CACHE["error"]}


def set_events_for_tests(events: Optional[List[Dict[str, Any]]], at: Optional[float] = None) -> None:
    with _LOCK:
        _CACHE.update(at=(time.time() if at is None else at) if events is not None else 0.0, events=events, fail_at=0.0, error=None)


def _relevant(e: Dict[str, Any]) -> bool:
    return e.get("impact") == "High" and e.get("country") in _countries()


def block_for(now: float, events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Подія, що зараз блокує вхід (вікно: −BEFORE_MIN … +AFTER_MIN від виходу), або None."""
    before = _env_int("OFFICE_CALENDAR_BEFORE_MIN", 30) * 60
    after = _env_int("OFFICE_CALENDAR_AFTER_MIN", 15) * 60
    for e in events:
        if _relevant(e) and e["ts"] - before <= now <= e["ts"] + after:
            return e
    return None


def next_event(now: float, events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in events:
        if _relevant(e) and e["ts"] > now:
            return e
    return None


def _hhmm(ts: float) -> str:
    try:
        from office_scenario_lifecycle import kyiv_hhmm

        return kyiv_hhmm(ts)
    except Exception:  # noqa: BLE001
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M UTC")


def entry_block(now: Optional[float] = None) -> Optional[str]:
    """Текст причини, якщо вхід зараз заблокований новиною; інакше None (у т.ч. коли календар недоступний — це видно в summary())."""
    if not block_enabled():
        return None
    now = time.time() if now is None else now
    data = load(now)
    e = block_for(now, data["events"]) if data["status"] == "DATA_OK" else None
    if not e:
        return None
    return (f"Вихід новини «{e['title']}» ({e['country']}) о {_hhmm(e['ts'])} за Києвом — за {_env_int('OFFICE_CALENDAR_BEFORE_MIN', 30)} хв до "
            f"і {_env_int('OFFICE_CALENDAR_AFTER_MIN', 15)} хв після виходу нові плани не відкриваємо.")


def summary(now: Optional[float] = None) -> Dict[str, Any]:
    """Для Mini App: статус джерела, чи є блок зараз, найближча важлива подія."""
    now = time.time() if now is None else now
    data = load(now)
    if data["status"] != "DATA_OK":
        return {"status": "DATA_UNAVAILABLE", "block": None, "next": None, "note": "Календар новин недоступний — блок входу за новинами не діє."}
    b = block_for(now, data["events"]) if block_enabled() else None
    n = next_event(now, data["events"])
    return {"status": "DATA_OK", "block": ({"title": b["title"], "country": b["country"], "at": _hhmm(b["ts"])} if b else None),
            "next": ({"title": n["title"], "country": n["country"], "at": _hhmm(n["ts"])} if n else None), "note": ""}
