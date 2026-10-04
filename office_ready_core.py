"""Ядро «Плану готовий» (P0): ідентичність ідеї, одні й ті самі цілі в гейті й повідомленні, знімок входів гейта, термін дії.

Без жорстких лімітів на кількість READY і без «охолодження після стопа»: нову ідею після завершення попередньої не блокуємо.
Блокуємо лише ДУБЛЬ — другий READY тієї самої ще не завершеної ідеї (інший scenario_id/basis, але той самий інструмент, напрямок і торговий діапазон).
Жодних символів у коді: працює однаково для будь-якої монети.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BAND_TOL_PCT = 0.15      # допуск (% ціни) до межі торгового діапазону старого плану
MAX_OPEN_SEC = 72 * 3600  # запобіжник: план без підсумку старший за вікно входу + 72 год вважаємо завершеним


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


# ------------------------------------------------------------------ термін дії
def kyiv_stamp(ts: float) -> str:
    """«05.10 02:40» — із датою, щоб «Діє до» не плутали з часом отримання повідомлення."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Kyiv")).strftime("%d.%m %H:%M")
    except Exception:  # noqa: BLE001
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m %H:%M") + " UTC"


def is_expired(valid_until_ts: Any, now: Optional[float] = None) -> bool:
    """Термін дії входу вичерпано — повідомлення вже не доставляємо."""
    v = _f(valid_until_ts)
    return v is not None and (time.time() if now is None else now) > v


# ------------------------------------------------------------------ повідомлення = гейт
def message_targets(*, direction: str, entry: Any, tp1: Any, tp2: Any, tp3_structural: Any = None) -> Tuple[Optional[float], Optional[float]]:
    """(TP2, TP3), які бачить користувач. TP2 — ЛИШЕ записаний у сценарії (той самий, що перевіряв гейт RR); окремого «структурного TP2» немає.
    TP3 — довідковий рівень, лише якщо є TP2 і TP3 за ним у напрямку угоди (нумерація без пропусків: ніколи TP1+TP3 без TP2)."""
    e, t1, t2, t3 = _f(entry), _f(tp1), _f(tp2), _f(tp3_structural)
    if e is None or t1 is None:
        return None, None
    sign = 1.0 if str(direction or "").upper() != "SHORT" else -1.0
    if t2 is not None and sign * (t2 - t1) <= 0:
        t2 = None
    if t2 is None:
        return None, None
    if t3 is not None and sign * (t3 - t2) <= 0:
        t3 = None
    return t2, t3


def gate_snapshot(*, direction: str, entry: Any, sl: Any, tp1: Any, tp2: Any, tp3: Any = None, max_entry: Any = None,
                  min_tp1_pct: Any = None, plan_bad: str = "", confirm: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Усі входи й виходи гейта на момент READY: за ними рішення відтворюється без жодних зовнішніх даних."""
    import office_alert_gate as g

    e, s_, t1, t2 = _f(entry), _f(sl), _f(tp1), _f(tp2)
    rr = g.net_rr(e, s_, t1, t2) or {}
    risk = abs(e - s_) / e * 100.0 if e and s_ is not None else None
    return {"direction": str(direction or "").upper(), "entry": e, "sl": s_, "tp1": t1, "tp2": t2, "tp3": _f(tp3), "max_entry": _f(max_entry),
            "risk_pct": round(risk, 4) if risk is not None else None, "rr_net": rr.get("rr_net"), "rr_weighted": rr.get("rr_weighted"),
            "rr_rule": g.rr_rule(), "fee_round_trip_pct": g.fee_round_trip_pct(), "min_tp1_pct": _f(min_tp1_pct), "gate_reject": plan_bad or "",
            "shown_tps": [x for x in (t1, t2, _f(tp3)) if x is not None], "confirm": confirm or None}


def confirm_basis(fu: Dict[str, Any]) -> Dict[str, Any]:
    """Чим саме підтверджено вхід (follow_setup): теги LTF, спосіб (закриття в зоні / ретест після пробою), деталь, ціна підтвердження."""
    return {"mode": "retest" if fu.get("need_retest") is False and "ретест" in str(fu.get("detail") or "") and "після пробою" in str(fu.get("detail") or "") else "inside_zone",
            "tags": [str(x) for x in (fu.get("confirms") or [])][:6], "detail": str(fu.get("detail") or fu.get("reason") or "")[:200], "price": _f(fu.get("price"))}


# ------------------------------------------------------------------ ідентичність ідеї
def _band(plan: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Торговий діапазон плану: від стопа до найдальшої цілі."""
    pts = [_f(plan.get(k)) for k in ("sl", "tp1", "tp2", "tp3", "entry")]
    pts = [p for p in pts if p is not None]
    return (min(pts), max(pts)) if len(pts) >= 3 else None


def same_idea(old: Dict[str, Any], *, symbol: str, direction: str, entry: Any) -> bool:
    """Та сама ідея: той самий інструмент і напрямок, а нова ціна входу лежить у торговому діапазоні старого плану (стоп…цілі).
    Інший scenario_id чи basis ідею НЕ змінюють. Вхід поза діапазоном (нова структура далі за ціль або за стопом) — нова ідея."""
    if str(old.get("symbol") or "").upper() != str(symbol or "").upper() or str(old.get("direction") or "").upper() != str(direction or "").upper():
        return False
    e, band = _f(entry), _band(old)
    if e is None or band is None:
        return False
    tol = e * BAND_TOL_PCT / 100.0
    return band[0] - tol <= e <= band[1] + tol


def unfinished_ready(db: str, *, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Доставлені READY без підсумку (SIGNAL_RESULT) — з журналу SIGNAL_PLAN; без міграцій і без пам'яті процесу."""
    import office_signal_track as trk

    now = time.time() if now is None else now
    done = {(e["p"].get("scenario_id"), e["p"].get("confirmed_ts")) for e in trk._events(db, trk.EV_RESULT)}
    out = []
    for ev in trk._events(db, trk.EV_PLAN):
        p = ev["p"]
        if p.get("rejected") or (p.get("scenario_id"), p.get("confirmed_ts")) in done:
            continue
        v = _f(p.get("valid_until_ts")) or 0.0
        if now > v + MAX_OPEN_SEC:
            continue
        out.append(p)
    return out


def find_duplicate(db: str, *, symbol: str, direction: str, entry: Any, scenario_id: str = "", now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Незавершений READY тієї самої ідеї (або той самий scenario_id) — тоді новий READY не шлемо."""
    for p in unfinished_ready(db, now=now):
        if scenario_id and str(p.get("scenario_id") or "") == scenario_id:
            return p
        if same_idea(p, symbol=symbol, direction=direction, entry=entry):
            return p
    return None


def dup_setup_event(dup: Optional[Dict[str, Any]], scenario_id: str) -> str:
    """Подія машини станів для заблокованого дубля: той самий сценарій уже має READY → лишається CONFIRMED; інший scenario_id тієї ж ідеї → CANCELLED."""
    return "CONFIRMED" if dup and str(dup.get("scenario_id") or "") == str(scenario_id or "") else "CANCELLED"
