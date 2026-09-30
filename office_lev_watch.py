"""Лев відстежує умову, яку сам оголосив: чекаємо → в зоні → підтверджено / скасовано / час минув / дані застаріли.

Стан зберігається в office_events (LEV_WATCH — версії стану, LEV_WATCH_EVENT — що вже повідомлено), тож
переживає рестарт worker і не дублює повідомлення: одна подія на одну зміну ситуації, мовчання, якщо нічого
не змінилось. Розрахунок на закритих свічках. Ордерів немає. Надсилання — лише за OFFICE_LEV_WATCH_NOTIFY=1;
без прапорця події все одно записуються (видно в Mini App), але в Telegram не йдуть.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from office_user_messages import render

EVENT_WATCH = "LEV_WATCH"
EVENT_NOTE = "LEV_WATCH_EVENT"
TERMINAL = ("CANCELLED", "EXPIRED", "REJECTED", "HANDOFF")
MAX_ATTEMPTS = 3
CARD_STATUSES = ("ACTIVE", "CONFIRMED", "HIT_ENTRY")
TTL_SEC = 12 * 3600
M15, H1 = 900, 3600
STALE_AFTER_SEC = int(M15 * 2.5)
STALE_TICKS_TO_NOTIFY = 3
STALE_REPEAT_SEC = 6 * 3600
_STALE_TICKS: Dict[str, int] = {}


def notify_enabled() -> bool:
    return os.getenv("OFFICE_LEV_WATCH_NOTIFY", "").strip().lower() in ("1", "true", "yes", "on")


def _dt(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def watch_id(symbol: str, direction: str, lo: Any, hi: Any) -> str:
    raw = f"{str(symbol).upper()}|{str(direction).upper()}|{_f(lo):.8g}|{_f(hi):.8g}"
    return "W-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ storage
def _save(db: str, rec: Dict[str, Any]) -> None:
    from office_bridge import log_event

    log_event(db, EVENT_WATCH, rec, rec["watch_id"])


def _latest(db: str, limit: int = 600) -> Dict[str, Dict[str, Any]]:
    from office_bridge import _fetchall

    out: Dict[str, Dict[str, Any]] = {}
    try:
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT ?", (EVENT_WATCH, limit))
    except Exception:  # noqa: BLE001
        return out
    for (pj,) in rows or []:
        try:
            rec = json.loads(pj)
        except Exception:  # noqa: BLE001
            continue
        out.setdefault(str(rec.get("watch_id")), rec)
    return out


def active_watches(db: str) -> List[Dict[str, Any]]:
    return [w for w in _latest(db).values() if str(w.get("state")) not in TERMINAL]


def recent_notes(db: str, *, symbol: str = "", limit: int = 12) -> List[Dict[str, Any]]:
    """Події повідомлень (остання версія кожної пари «умова + подія»): що сталося і чи доставлено."""
    from office_bridge import _fetchall

    try:
        rows = _fetchall(db, "SELECT ts_utc, payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT ?", (EVENT_NOTE, 300))
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for ts, pj in rows or []:
        try:
            p = json.loads(pj)
        except Exception:  # noqa: BLE001
            continue
        k = (p.get("watch_id"), p.get("event"))
        if k in seen:
            continue
        seen.add(k)
        if symbol and str(p.get("symbol", "")).upper() != symbol.upper():
            continue
        out.append({**p, "ts": ts})
        if len(out) >= limit:
            break
    return out


def _last_note(db: str, wid: str, event: str) -> Optional[Dict[str, Any]]:
    for n in recent_notes(db, limit=300):
        if n.get("watch_id") == wid and n.get("event") == event:
            return n
    return None


def _noted(db: str, wid: str, event: str) -> Optional[str]:
    """ts_utc останньої відповідної події або None."""
    n = _last_note(db, wid, event)
    return str(n.get("ts")) if n else None


def _note(db: str, watch: Dict[str, Any], event: str, text: str, sent: bool, why: str = "", *, status: str = "", attempts: int = 0,
          message_id: Any = None) -> None:
    from office_bridge import log_event

    st = status or ("pending" if sent else "disabled")
    log_event(db, EVENT_NOTE, {"watch_id": watch["watch_id"], "symbol": watch["symbol"], "direction": watch.get("direction"), "event": event,
                               "text": text, "sent": st == "sent", "status": st, "attempts": attempts, "message_id": message_id, "why": why},
              watch["watch_id"])


def mark_result(db: str, watch_id: str, event: str, ok: bool, message_id: Any = None, error: str = "") -> None:
    """Результат доставки: sent або failed (з лічильником спроб). Записується завжди — помилки видно, а не мовчки губляться."""
    n = _last_note(db, watch_id, event)
    if not n:
        return
    attempts = int(n.get("attempts") or 0) + 1
    _note(db, {"watch_id": watch_id, "symbol": n.get("symbol"), "direction": n.get("direction")}, event, str(n.get("text") or ""), ok,
          why="" if ok else (error or "не доставлено (заблоковано політикою або помилка Telegram)"), status="sent" if ok else "failed",
          attempts=attempts, message_id=message_id)


def find_card(db: str, symbol: str, direction: str, lo: float, hi: float) -> Optional[Dict[str, Any]]:
    """Уже відправлена картка Лева (ACTIVE/CONFIRMED) для тієї ж зони: її веде основний трекер worker — двічі не стежимо й не сповіщаємо."""
    from office_bridge import _fetchall

    try:
        rows = _fetchall(db, "SELECT signal_id, entry_low, entry_high, status FROM office_signals WHERE symbol = ? AND direction = ? AND status IN (?, ?, ?)",
                         (str(symbol).upper(), str(direction).upper(), *CARD_STATUSES))
    except Exception:  # noqa: BLE001
        return None
    for sid, elo, ehi, st in rows or []:
        a, b = _f(elo), _f(ehi)
        if a is not None and b is not None and _overlap(lo, hi, min(a, b), max(a, b)):
            return {"signal_id": sid, "status": st}
    return None


# ------------------------------------------------------------------ registration
def register(db: str, *, symbol: str, direction: str, zone_lo: Any, zone_hi: Any, invalidation: Any, wait_tf: str = "M15",
             scenario_tf: str = "H1", state: str = "WAIT", plan: Optional[Dict[str, Any]] = None, scenario_id: str = "",
             now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Зберігає умову для відстеження. Без зони/напряму/рівня скасування — не реєструє (обіцяти нічого)."""
    lo, hi, inv = _f(zone_lo), _f(zone_hi), _f(invalidation)
    side = str(direction or "").upper()
    if lo is None or hi is None or inv is None or side not in ("LONG", "SHORT"):
        return None
    if lo > hi:
        lo, hi = hi, lo
    t = now or datetime.now(timezone.utc)
    if find_card(db, symbol, side, lo, hi):
        return None  # картку вже веде основний трекер (follow_setup) — дубля стеження немає
    wid = watch_id(symbol, side, lo, hi)
    cur = _latest(db).get(wid)
    if cur and str(cur.get("state")) not in TERMINAL and _dt(cur.get("expires_at")) and _dt(cur["expires_at"]) > t:
        return cur  # той самий сценарій уже відстежується — не дублюємо
    rec = {"watch_id": wid, "symbol": str(symbol).upper(), "direction": side, "zone_lo": lo, "zone_hi": hi, "invalidation": inv,
           "wait_tf": wait_tf, "scenario_tf": scenario_tf, "state": state, "plan": plan, "scenario_id": scenario_id,
           "touched_zone": False, "created_at": t.isoformat(), "expires_at": datetime.fromtimestamp(__import__("office_scenario_ttl").deadline(t.timestamp(), scenario_tf or "H1"), tz=timezone.utc).isoformat()}
    _save(db, rec)
    return rec


# ------------------------------------------------------------------ evaluation (pure)
def _closed(candles: Any, sec: int, now: datetime) -> List[Dict[str, Any]]:
    out = []
    for c in candles or []:
        d = _dt((c or {}).get("ts"))
        if d and d + timedelta(seconds=sec) <= now:
            out.append({**c, "_open": d})
    return out


def _overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> bool:
    ov = min(a_hi, b_hi) - max(a_lo, b_lo)
    return ov > 0 and ov >= 0.5 * min(a_hi - a_lo, b_hi - b_lo)


def is_stale(m15: Any, now: datetime) -> bool:
    last = None
    for c in m15 or []:
        d = _dt((c or {}).get("ts"))
        if d and (last is None or d > last):
            last = d
    return last is None or (now - last).total_seconds() > STALE_AFTER_SEC


def needs_cycle(watch: Dict[str, Any], m15: Any) -> bool:
    """Повний цикл Лева потрібен лише поблизу зони (економимо запити)."""
    if watch.get("state") == "CONFIRMED":
        return False
    try:
        px = float((m15 or [])[-1]["close"])
    except Exception:  # noqa: BLE001
        return False
    lo, hi = float(watch["zone_lo"]), float(watch["zone_hi"])
    pad = (hi - lo) * 0.5 + px * 0.002
    return lo - pad <= px <= hi + pad or bool(watch.get("touched_zone"))


def plan_from_cycle(cycle: Dict[str, Any]) -> Dict[str, Any]:
    draft = (cycle or {}).get("draft") or {}
    return {"entry": cycle.get("entry"), "sl": cycle.get("sl"), "tp1": cycle.get("tp1"), "tp2": cycle.get("tp2") or draft.get("tp2")}


def check_plan(symbol: str, direction: str, plan: Dict[str, Any], zone_lo: Any, zone_hi: Any) -> Optional[str]:
    """None — план повний і проходить ті самі перевірки, що й SEND у worker; інакше — пояснення людською мовою."""
    from office_alert_gate import validate_trade_geometry
    from office_desk_card import min_tp1_pct
    from office_telegram_filter import move_pct_to_tp

    if any(_f(plan.get(k)) is None for k in ("entry", "sl", "tp1")):
        return "План неповний: немає входу, стопа або цілі."
    from office_calendar import entry_block   # важлива новина: нові плани не відкриваємо (вікно 30 хв до / 15 хв після)

    news = entry_block()
    if news:
        return news
    g = validate_trade_geometry(direction=direction, sl=plan["sl"], tp1=plan["tp1"], entry=plan["entry"], entry_low=zone_lo, entry_high=zone_hi, tp2=plan.get("tp2"))
    if not g.get("ok"):
        reason = str(g.get("reason") or "")
        if "RR" in reason and g.get("rr") is not None:
            from office_alert_gate import _ua_num

            if g.get("rr_weighted") is not None:
                return _ua_num(f"Потенціал замалий порівняно з ризиком (за краями зони: до цілі 1 — {float(g['rr']):.2f}, зважений RR — {float(g['rr_weighted']):.2f}; "
                               "потрібно: зважений не менше 1,5 і до цілі 1 не менше 1,0).")
            return _ua_num(f"Потенціал до цілі замалий порівняно з ризиком (співвідношення {float(g['rr']):.2f}, потрібно не менше 1,5).")
        return "План не пройшов перевірку рівнів: стоп або ціль стоять не на своєму боці від входу."
    # RR від фактичного входу з комісіями (геометрія вище рахує за краями зони — так LSK з RR 1,40 пройшов би); правило — office_alert_gate.rr_gate
    from office_alert_gate import rr_gate

    g2 = rr_gate(plan["entry"], plan["sl"], plan["tp1"], plan.get("tp2"))
    if not g2["ok"]:
        return g2["reason"]
    need = min_tp1_pct(symbol)
    mv = move_pct_to_tp(entry=_f(plan["entry"]), tp=_f(plan["tp1"]))
    if mv is None or mv + 1e-12 < need:
        return f"Ціль надто близько до входу (менше {need:g}%) — такий план ми не пропонуємо."
    return None


def evaluate(watch: Dict[str, Any], *, now: datetime, m15: Any, h1: Any, cycle: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Наступна подія для умови або None (нічого не змінилось → мовчимо). Порядок: час → дані → скасування → підтвердження → зона."""
    state = str(watch.get("state"))
    exp = _dt(watch.get("expires_at"))
    if exp and now >= exp:
        return {"event": "EXPIRED", "state": "EXPIRED"}
    if is_stale(m15, now):
        return {"event": "STALE", "state": state}
    created = _dt(watch.get("created_at")) or now
    lo, hi, inv = float(watch["zone_lo"]), float(watch["zone_hi"]), float(watch["invalidation"])
    long_ = str(watch["direction"]).upper() != "SHORT"
    for c in _closed(h1, H1, now):
        if c["_open"] + timedelta(seconds=H1) <= created:
            continue
        cl = _f(c.get("close"))
        if cl is not None and ((long_ and cl < inv) or ((not long_) and cl > inv)):
            return {"event": "CANCELLED", "state": "CANCELLED"}
    if state == "CONFIRMED":
        return None
    if cycle and cycle.get("send") and str(cycle.get("direction") or "").upper() == str(watch["direction"]).upper():
        d = cycle.get("draft") or {}
        zlo, zhi = _f(d.get("zone_lo")), _f(d.get("zone_hi"))
        same = (zlo is not None and zhi is not None and _overlap(lo, hi, min(zlo, zhi), max(zlo, zhi)))
        if same:
            plan = plan_from_cycle(cycle)
            bad = check_plan(watch["symbol"], watch["direction"], plan, zlo, zhi)
            if bad:
                return {"event": "REJECTED", "state": "REJECTED", "reason": bad}
            return {"event": "CONFIRMED", "state": "CONFIRMED", "plan": plan}
    if not watch.get("touched_zone"):
        for c in m15 or []:
            d0 = _dt((c or {}).get("ts"))
            if d0 and d0 + timedelta(seconds=M15) > created:
                if _f(c.get("low")) is not None and _f(c.get("high")) is not None and float(c["low"]) <= hi and float(c["high"]) >= lo:
                    return {"event": "IN_ZONE", "state": "IN_ZONE", "touched_zone": True}
    return None


def view_of(watch: Dict[str, Any], *, price: Any, tracking: bool, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    v = {k: watch.get(k) for k in ("symbol", "direction", "zone_lo", "zone_hi", "invalidation", "wait_tf", "scenario_tf", "plan", "expires_at", "touched_zone")}
    v.update({"price": price, "tracking": tracking, "state": watch.get("state")})
    v.update(extra or {})
    return v


# ------------------------------------------------------------------ worker tick
def tick(db: str, *, now: Optional[datetime] = None, fetch: Optional[Callable[[str, str, int], Any]] = None,
         cycle_fn: Optional[Callable[[str, str], Dict[str, Any]]] = None, send_enabled: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Один прохід по активних умовах. Повертає повідомлення, які ТРЕБА надіслати (вже записані як події)."""
    t = now or datetime.now(timezone.utc)
    send_ok = notify_enabled() if send_enabled is None else send_enabled
    if fetch is None:
        from office_market_data import fetch_candles as fetch  # type: ignore[assignment]
    if cycle_fn is None:
        from office_legacy_guard import lev_cycle_for_symbol

        cycle_fn = lambda d, s: lev_cycle_for_symbol(d, s, None, record=False)  # noqa: E731
    out: List[Dict[str, Any]] = []
    # повтор доставки: події, які не дійшли (до MAX_ATTEMPTS спроб), не губимо
    if send_ok:
        for n in recent_notes(db, limit=100):
            if n.get("status") == "failed" and int(n.get("attempts") or 0) < MAX_ATTEMPTS:
                out.append({"watch_id": n["watch_id"], "symbol": n["symbol"], "direction": n.get("direction"), "event": n["event"],
                            "text": n.get("text") or "", "retry": True})
    for w in active_watches(db):
        wid, sym = w["watch_id"], w["symbol"]
        card = find_card(db, sym, w["direction"], float(w["zone_lo"]), float(w["zone_hi"]))
        if card:  # з'явилась картка Лева для цієї зони — далі її веде основний трекер; тихо передаємо
            _save(db, {**w, "state": "HANDOFF", "handoff_to": card["signal_id"]})
            continue
        try:
            m15, h1 = fetch(sym, "15m", 96), fetch(sym, "1h", 48)
        except Exception:  # noqa: BLE001
            m15, h1 = None, None
        cyc = None
        if needs_cycle(w, m15):
            try:
                cyc = cycle_fn(db, sym)
            except Exception:  # noqa: BLE001
                cyc = None
        ev = evaluate(w, now=t, m15=m15, h1=h1, cycle=cyc)
        if not ev:
            _STALE_TICKS.pop(wid, None)
            continue
        kind = ev["event"]
        try:
            px = float(m15[-1]["close"]) if m15 else None
        except Exception:  # noqa: BLE001
            px = None
        if kind == "STALE":
            n = _STALE_TICKS.get(wid, 0) + 1
            _STALE_TICKS[wid] = n
            last = _noted(db, wid, "STALE")
            last_dt = _dt(last) if last else None
            if n < STALE_TICKS_TO_NOTIFY or (last_dt and (t - last_dt).total_seconds() < STALE_REPEAT_SEC):
                continue
        else:
            _STALE_TICKS.pop(wid, None)
            if _noted(db, wid, kind):
                continue  # ця зміна вже записана — без дублів
        new = {**w, "state": ev["state"], **({"touched_zone": True} if ev.get("touched_zone") else {}), **({"plan": ev["plan"]} if ev.get("plan") else {})}
        if kind != "STALE":
            _save(db, new)
        text = render(view_of(new, price=px, tracking=send_ok, extra={"state": {"IN_ZONE": "IN_ZONE"}.get(kind, ev["state"]) if kind != "STALE" else "STALE",
                                                                    "reason": ev.get("reason")}))
        _note(db, w, kind, text, sent=send_ok, why="" if send_ok else "notify_disabled")
        if send_ok:
            out.append({"watch_id": wid, "symbol": sym, "direction": w["direction"], "event": kind, "text": text})
    return out
