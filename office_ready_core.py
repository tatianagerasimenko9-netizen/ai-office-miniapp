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
                  min_tp1_pct: Any = None, plan_bad: str = "", confirm: Optional[Dict[str, Any]] = None, tp3_why: str = "",
                  zone_lo: Any = None, zone_hi: Any = None) -> Dict[str, Any]:
    """Усі входи й виходи гейта на момент READY: за ними рішення відтворюється без жодних зовнішніх даних."""
    import office_alert_gate as g

    e, s_, t1, t2 = _f(entry), _f(sl), _f(tp1), _f(tp2)
    rr = g.net_rr(e, s_, t1, t2) or {}
    risk = abs(e - s_) / e * 100.0 if e and s_ is not None else None
    zl, zh = _f(zone_lo), _f(zone_hi)
    zone = [min(zl, zh), max(zl, zh)] if zl is not None and zh is not None else None   # зона сетапу (де шукали вхід); max_entry — інше: межа «далі не входити»
    return {"zone": zone, "direction": str(direction or "").upper(), "entry": e, "sl": s_, "tp1": t1, "tp2": t2, "tp3": _f(tp3), "max_entry": _f(max_entry),
            "risk_pct": round(risk, 4) if risk is not None else None, "rr_net": rr.get("rr_net"), "rr_weighted": rr.get("rr_weighted"),
            "rr_rule": g.rr_rule(), "fee_round_trip_pct": g.fee_round_trip_pct(), "min_tp1_pct": _f(min_tp1_pct), "gate_reject": plan_bad or "",
            "shown_tps": [x for x in (t1, t2, _f(tp3)) if x is not None], "confirm": confirm or None, "tp3_why": tp3_why or ""}


def entry_zone(entry: Any, zone: Any) -> tuple:
    """Зона входу для показу: зона сетапу зі знімка, якщо вона містить ціну входу (з допуском 0,15%); інакше лише ціна входу. max_entry сюди НЕ входить."""
    e = _f(entry)
    try:
        lo, hi = float(zone[0]), float(zone[1])
    except (TypeError, ValueError, IndexError):
        return e, e
    if e is not None and lo - e * 0.0015 <= e <= hi + e * 0.0015:
        return lo, hi
    return e, e


FUTURES_SRC = "binance_futures"


def non_futures_sources(*series: Any) -> list:
    """Джерела свічок, що НЕ є Binance USDT-M Futures (запасні: спот Vision, Bybit…). Рядок без позначки джерела не вважається запасним (WS-потік фʼючерсів)."""
    bad = set()
    for rows in series:
        for r in (rows if isinstance(rows, list) else []):
            src = r.get("src") if isinstance(r, dict) else None
            if src and src != FUTURES_SRC:
                bad.add(str(src))
    return sorted(bad)


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
    # Lifecycle 1m (SCENARIO_MILESTONE) — друге джерело правди: 15m-симулятор SIGNAL_RESULT може оголосити результат РАНІШЕ, ніж 1m бачить вхід
    # (KAITO 05.10: «результат» 04.10 22:38, а ENTRY 00:16, SL 04:33). Якщо ENTRY є, а SL/TP/EXPIRED ще немає — ідея ще в позиції, не завершена.
    lc: Dict[Tuple[Any, Any], set] = {}
    for e in trk._events(db, trk.EV_MILESTONE):
        lc.setdefault((e["p"].get("scenario_id"), e["p"].get("confirmed_ts")), set()).add(str(e["p"].get("level") or ""))
    out = []
    for ev in trk._events(db, trk.EV_PLAN):
        p = ev["p"]
        k = (p.get("scenario_id"), p.get("confirmed_ts"))
        lv = lc.get(k, set())
        lifecycle_open = "ENTRY" in lv and not (lv & {"SL", "TP1", "TP2", "TP3", "EXPIRED"})
        if p.get("rejected") or (k in done and not lifecycle_open):
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


def story_for(*, symbol: str, direction: str, confirm: Optional[Dict[str, Any]], gate: Optional[Dict[str, Any]], entry: Any, zone_lo: Any, zone_hi: Any, tf: str = "H1") -> Dict[str, Any]:
    """Назва сетапу й причини для Telegram І Mini App з одного місця: лише з реально збережених підстав (gate.confirm) + цифри зони входу."""
    import office_setup_story as su
    from office_price_format import format_px

    conf = confirm or {}
    zt = ""
    lo, hi = _f(zone_lo), _f(zone_hi)
    if lo is not None and hi is not None:
        a, b = (lo, hi) if lo <= hi else (hi, lo)
        zt = f"{format_px(a, symbol)}–{format_px(b, symbol)}".replace(".", ",")
    et = format_px(entry, symbol).replace(".", ",") if _f(entry) is not None else ""
    g = gate or {}
    return su.build(conf.get("tags") or [], conf.get("mode"), direction, rr_net=g.get("rr_net"), rr_weighted=g.get("rr_weighted"),
                    tf="M5" if str(tf or "").upper() in ("M15", "M5") else "M15", entry_txt=et, zone_txt=zt)


def repeat_context(db: str, *, symbol: str, direction: str, entry: Any, sl: Any, tags: Any = None, zone: Any = None, now: Optional[float] = None) -> Dict[str, Any]:
    """ІНСТРУМЕНТАЦІЯ для shadow-визначення structural reset (05.10). НЕ впливає на gate/READY: лише зберігає у знімку, що змінилось
    порівняно з попередньою READY тієї ж пари symbol+direction. Заповнюється з журналу подій; збій → порожній результат.
    Структурні події після SL (новий sweep/BOS/CHoCH, зміна HTF-контексту) тут ще не обчислюються — окреме поле в наступному кроці."""
    import office_signal_track as trk

    now = time.time() if now is None else now
    sym, d = str(symbol or "").upper(), str(direction or "").upper()
    prevs = [e["p"] for e in trk._events(db, trk.EV_PLAN)
             if not e["p"].get("rejected") and str(e["p"].get("symbol") or "").upper() == sym and str(e["p"].get("direction") or "").upper() == d
             and (_f(e["p"].get("confirmed_ts")) or 0.0) < now]
    prevs.sort(key=lambda p: _f(p.get("confirmed_ts")) or 0.0)
    out: Dict[str, Any] = {"v": 1, "has_prev": bool(prevs), "n_prev_24h": sum(1 for p in prevs if now - (_f(p.get("confirmed_ts")) or 0.0) <= 86400), "n_prev_total": len(prevs)}
    if not prevs:
        return out
    prev = prevs[-1]
    ct = _f(prev.get("confirmed_ts")) or 0.0
    k = (prev.get("scenario_id"), prev.get("confirmed_ts"))
    res = next((e["p"] for e in trk._events(db, trk.EV_RESULT) if (e["p"].get("scenario_id"), e["p"].get("confirmed_ts")) == k), None)
    lv: Dict[str, Optional[float]] = {}
    for e in trk._events(db, trk.EV_MILESTONE):
        if (e["p"].get("scenario_id"), e["p"].get("confirmed_ts")) == k:
            lv[str(e["p"].get("level") or "")] = _f(e["p"].get("touched_ts"))
    sl_ts = lv.get("SL") if lv.get("SL") else (ct + (_f(res.get("time_to_result_sec")) or 0.0) if res and res.get("outcome") == "STOP" else None)
    if "SL" in lv or (res and res.get("outcome") == "STOP"):
        state = "sl"
    elif lv.keys() & {"TP1", "TP2", "TP3"} or (res and str(res.get("outcome") or "").startswith("TP")):
        state = "tp"
    elif "ENTRY" in lv:
        state = "open"
    else:
        state = "unresolved"
    e0, s0 = _f(entry), _f(sl)
    pe, ps = _f(prev.get("entry")), _f(prev.get("sl"))
    pz = ((prev.get("gate") or {}).get("zone")) or None
    overlap = None
    try:
        if pz and zone:
            overlap = max(float(pz[0]), float(zone[0])) <= min(float(pz[1]), float(zone[1]))
    except (TypeError, ValueError, IndexError):
        overlap = None
    ptags = ((prev.get("gate") or {}).get("confirm") or {}).get("tags")
    out.update({"prev_scenario_id": prev.get("scenario_id"), "prev_confirmed_ts": ct, "prev_age_min": round((now - ct) / 60.0, 1), "prev_state": state,
                "since_prev_sl_min": round((now - sl_ts) / 60.0, 1) if sl_ts and state == "sl" else None,
                "sl_diff_pct": round(abs(s0 - ps) / s0 * 100.0, 4) if s0 and ps is not None else None,
                "entry_diff_pct": round(abs(e0 - pe) / e0 * 100.0, 4) if e0 and pe is not None else None,
                "zone_overlap": overlap, "prev_tags": ptags, "tags": [str(x) for x in (tags or [])] or None,
                "same_tags": (sorted(ptags) == sorted(str(x) for x in tags)) if ptags and tags else None})
    return out
