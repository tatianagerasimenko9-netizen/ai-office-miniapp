"""Позначки на картках (лише показ, нічого не блокують) + власний архів новин/календаря під кожен сигнал.
Правила позначок — з прогону сигналів AI Office на історії 12.10–16.11.2026 (docs/handoff/br-profitability/IMPROVEMENTS_LOG_UA.md, розділ I): ГІПОТЕЗА (5 тижнів, ринок падав), не доведені правила.
Архів: таблиця signal_news — для кожного сигналу події економічного календаря (FMP, ключ NEWS_API_KEY) навколо моменту сигналу; без ключа записується статус no_key. Мета — потім прогнати «що було навколо сигналу»."""
from __future__ import annotations
import json, os, time
from typing import Any, Dict, List, Optional

DDL = """CREATE TABLE IF NOT EXISTS signal_news (
    sig_id TEXT PRIMARY KEY, symbol TEXT, ts DOUBLE PRECISION NOT NULL, status TEXT NOT NULL, events_json TEXT, created_ts DOUBLE PRECISION NOT NULL)"""
_CACHE: Dict[str, Any] = {"day": None, "ts": 0.0, "events": None, "status": ""}


def enabled() -> bool:
    return os.getenv("SIGNAL_MARKS", "1").strip().lower() in ("1", "true", "yes", "on")


def ai_marks(snap: Dict[str, Any]) -> List[str]:
    """Позначки AI Office: LONG при падінні BTC (дн. режим), лондонська сесія. Кожна — окремий пункт."""
    if not enabled():
        return []
    out: List[str] = []
    try:
        d = str(snap.get("direction") or "").upper()
        regd = ((snap.get("market_at_signal") or {}).get("market") or {}).get("btc_regd")
        if d == "LONG" and regd is not None and int(regd) < 0:
            out.append("LONG при падінні BTC — на тесті слабше")
        ses = (snap.get("session_tag") or {}).get("session")
        if ses == "LONDON":
            out.append("лондонська сесія — на тесті слабше")
    except Exception:  # noqa: BLE001
        pass
    return out


def _calendar(now: float) -> tuple[str, List[Dict[str, Any]]]:
    """Події календаря за вчора–завтра (кеш 15 хв). (status, events[{title,ts,impact}])"""
    key = os.getenv("NEWS_API_KEY", "").strip()
    if not key:
        return "no_key", []
    if _CACHE["events"] is not None and now - _CACHE["ts"] < 900:
        return _CACHE["status"], _CACHE["events"]
    from datetime import datetime, timedelta, timezone
    import office_market_data as md
    d0 = datetime.fromtimestamp(now - 86400, timezone.utc).strftime("%Y-%m-%d"); d1 = datetime.fromtimestamp(now + 86400, timezone.utc).strftime("%Y-%m-%d")
    try:
        data = md._http_get_json("https://financialmodelingprep.com/stable/economic-calendar", {"from": d0, "to": d1, "apikey": key})
    except Exception as exc:  # noqa: BLE001
        return f"error:{getattr(exc, 'code', type(exc).__name__)}", []
    ev: List[Dict[str, Any]] = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        dt = md._parse_econ_dt(str(e.get("date") or e.get("time") or ""))
        title = str(e.get("event") or e.get("title") or "")[:100]
        if dt is None or not title:
            continue
        ev.append({"title": title, "ts": dt.timestamp(), "impact": str(e.get("impact") or e.get("importance") or "").lower(), "country": str(e.get("country") or "")[:8]})
    _CACHE.update({"ts": now, "events": ev, "status": "ok"})
    return "ok", ev


def record(db: str, sig_id: str, symbol: str, now: Optional[float] = None) -> Dict[str, Any]:
    """Записати знімок календаря під сигнал (один раз) і повернути {'status','events'} для позначок. Ніколи не кидає виняток."""
    now = time.time() if now is None else now
    try:
        from office_bridge import _execute, _fetchone
        _execute(db, DDL)
        row = _fetchone(db, "SELECT status, events_json FROM signal_news WHERE sig_id = ?", (sig_id,))
        if row:
            return {"status": row[0], "events": json.loads(row[1] or "[]")}
        st, ev = _calendar(now)
        keep = [e for e in ev if -12 * 3600 <= e["ts"] - now <= 24 * 3600]
        _execute(db, "INSERT INTO signal_news(sig_id, symbol, ts, status, events_json, created_ts) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING", (sig_id, symbol, now, st, json.dumps(keep, ensure_ascii=False), now))
        return {"status": st, "events": keep}
    except Exception as exc:  # noqa: BLE001
        print(f"[marks] архів новин недоступний: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
        return {"status": "error", "events": []}


def news_marks(info: Dict[str, Any], now: Optional[float] = None) -> List[str]:
    """Пункт «📰» лише для подій, які сам календар позначив як high (або явна макро-подія), у вікні −2…+12 год."""
    if not enabled():
        return []
    now = time.time() if now is None else now
    out: List[str] = []
    for e in sorted(info.get("events") or [], key=lambda x: x["ts"]):
        dh = (e["ts"] - now) / 3600
        if "high" in str(e.get("impact")) and -2 <= dh <= 12:
            when = f"через {dh:.0f} год" if dh >= 0.5 else ("зараз" if dh > -0.5 else f"{-dh:.0f} год тому")
            out.append(f"новини: {e['title']} ({when})")
        if len(out) >= 2:
            break
    return out


PAIR_HOURS = 4.0


def opposite_recent_td(db: str, symbol: str, direction: str, now: Optional[float] = None) -> Optional[str]:
    """ІНТРАДЕЙ: якщо за останні 4 год по цій монеті вже був сигнал ІНТРАДЕЙ у ПРОТИЛЕЖНИЙ бік і він ще діє — текст попередження. Лише показ, сигнал не блокується.
    Історія 2024–2026 (журнал, розділ BC): 32 пари, перший +$10,29 на угоду, другий −$1,76. Вигляд погоджено власницею 26.11.2026."""
    if not enabled():
        return None
    try:
        import time as _t
        from office_bridge import _fetchone
        now = _t.time() if now is None else now
        row = _fetchone(db, "SELECT seq, created_ts FROM br_test_signal WHERE sig_id LIKE 'TD|%' AND symbol = ? AND direction != ? AND status IN ('NEW', 'SENT') AND created_ts >= ? ORDER BY created_ts DESC LIMIT 1",
                        (symbol, direction, now - PAIR_HOURS * 3600))
        if row:
            mins = max(1, int(round((now - float(row[1])) / 60))); ago = f"{mins} хв" if mins < 90 else f"{int(round(mins / 60))} год"
            num = f" №{int(row[0])}" if row[0] else ""
            return f"{ago} тому був протилежний сигнал ІНТРАДЕЙ{num} по {symbol.replace('USDT', '')}. На історії в таких парах частіше правий перший"
    except Exception:  # noqa: BLE001
        pass
    return None


_LINK_PFX = {"ІНТРАДЕЙ": "TD", "СВІНГ": "SW", "ВІДСКОК": "BN"}


def links(db: str, *texts: Optional[str]) -> Dict[str, int]:
    """Для згадок «ІНТРАДЕЙ №N / СВІНГ №N / ВІДСКОК №N» у текстах позначок — номер повідомлення того сигналу в Telegram, щоб картка зробила згадку посиланням (прохання власниці 27.11.2026). Лише показ."""
    import re
    out: Dict[str, int] = {}
    try:
        from office_bridge import _fetchone
        for name, num in set(re.findall(r"(ІНТРАДЕЙ|СВІНГ|ВІДСКОК) №(\d+)", " ".join(t for t in texts if t))):
            row = _fetchone(db, "SELECT msg_id FROM br_test_signal WHERE sig_id LIKE ? AND seq = ? AND msg_id IS NOT NULL ORDER BY created_ts DESC LIMIT 1", (_LINK_PFX[name] + "|%", int(num)))
            if row and row[0]: out[f"{name} №{num}"] = int(row[0])
    except Exception:  # noqa: BLE001
        pass
    return out


def opposite_open(db: str, symbol: str, direction: str, own: str) -> Optional[str]:
    """Якщо інша стратегія (ІНТРАДЕЙ ↔ СВІНГ) вже тримає відкриту угоду по цій монеті у ПРОТИЛЕЖНИЙ бік — короткий текст попередження. Лише показ."""
    if not enabled():
        return None
    try:
        from office_bridge import _fetchone
        other, name = ("SW", "СВІНГ") if own == "TD" else ("TD", "ІНТРАДЕЙ")
        row = _fetchone(db, "SELECT direction, seq FROM br_test_signal WHERE sig_id LIKE ? AND symbol = ? AND direction != ? AND status IN ('NEW', 'SENT') ORDER BY created_ts DESC LIMIT 1", (other + "|%", symbol, direction))
        if row:
            num = f" №{int(row[1])}" if row[1] else ""
            return f"{name}{num} уже тримає {row[0]} по {symbol.replace('USDT', '')} — протилежно"
    except Exception:  # noqa: BLE001
        pass
    return None


REPEAT_TEXT = "повторний сигнал після стопа цієї ж монети за останню добу, історично слабший"


def recent_stop(db: str, symbol: str, direction: str, now: Optional[float] = None, hours: float = 24.0) -> Optional[str]:
    """СВІНГ: якщо угоду по ЦІЙ ЖЕ монеті в ТОЙ САМИЙ бік вибило по стопу за останні `hours` годин — текст позначки. Лише показ, сигнал не блокується.
    Історія (durations_sw_60, 42 монети, 5 років, одна позиція на монету): повтор ≤1 доби після стопа ≈ $+0.08 на угоду (Bollinger −$0.72), проти $+1.33 у середньому."""
    if not enabled():
        return None
    try:
        import time as _t
        from office_bridge import _fetchone
        t = float(now if now is not None else _t.time())
        row = _fetchone(db, "SELECT 1 FROM br_test_event e JOIN br_test_signal s ON s.sig_id = e.sig_id WHERE e.level = 'SL' AND s.sig_id LIKE 'SW|%' AND s.symbol = ? AND s.direction = ? AND e.touched_ts >= ? AND e.touched_ts <= ? LIMIT 1", (symbol, direction, t - hours * 3600.0, t))
        if row:
            return REPEAT_TEXT
    except Exception:  # noqa: BLE001
        pass
    return None
