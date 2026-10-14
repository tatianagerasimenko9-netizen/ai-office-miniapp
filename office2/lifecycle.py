"""Життєвий цикл торгового задуму Office2: один задум — одна історія.

Сутності:
  сценарій    — доставлений READY (scenario_id, №, повідомлення Telegram, заморожений план);
  сетап       — теза Brain (th["id"] = стабільний id ідеї по монеті; той самий id = та сама ідея);
  подія       — супровід (ENTRY/TP/SL …, `office_events` SCENARIO_MILESTONE);
  ДУБЛІКАТ      — та сама ідея (той самий id або та сама структурна подія), що вже в роботі: нічого не надсилаємо;
  ПРОДОВЖЕННЯ   — інша ідея, але її структурна подія НЕ новіша за початковий сценарій (той самий рух), поки він ще в роботі (немає SL/TP3/EXPIRED/INVALIDATED): НЕ новий READY, а подія в гілці початкового №;
  НЕЗАЛЕЖНИЙ    — структурна подія сформувалася ПІСЛЯ видачі початкового сценарію (нова структура, власне скасування): окремий №, лише з поясненням відмінності й після звичайних ризик-обмежень;
  ПОВТОРНИЙ ВХІД — новий підтверджений сетап після того, як попередній сценарій завершився: окремий №, з посиланням на попередній.
(Критерії — ГІПОТЕЗА щодо класифікації без числових порогів; перевіряються на історії, режим OFFICE2_LIFECYCLE=annotate/off — відкат.)

Система ВМІЄ пропонувати нові цілі (наступний структурний рівень за початковими цілями), але лише як окрему ПРОПОЗИЦІЮ зі статусом «НЕ ЗАСТОСОВАНО»:
початкові TP1/TP2/TP3 і SL не змінюються, стоп не пересувається, часткових закриттів і ордерів немає (торкання ціни ≠ виконання ордера).
Режим OFFICE2_LIFECYCLE: merge (за замовчуванням: продовження → подія в гілці) | annotate (лише позначка, READY як раніше) | off.
Відкат: OFFICE2_LIFECYCLE=off.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

TERMINAL = ("SL", "TP3", "EXPIRED", "INVALIDATED")
LIFECYCLE_SEC = 48 * 3600          # те саме вікно, що в opposite_lifecycle (CONFLICT_LIFECYCLE_SEC)
CLAIM_TTL_SEC = 180
MAX_TRIES = 3
VERSION = "lifecycle-1"

DDL = ("""CREATE TABLE IF NOT EXISTS office2_lifecycle_event (
    event_id TEXT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL, relation TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
    parent_scenario_id TEXT NOT NULL, parent_seq INTEGER, parent_msg_id BIGINT, child_scenario_id TEXT, child_thesis_id TEXT, payload_json TEXT,
    tg_status TEXT DEFAULT 'NEW', tg_tries INTEGER DEFAULT 0, claim TEXT, claim_ts DOUBLE PRECISION, msg_id BIGINT, sent_ts DOUBLE PRECISION, last_error TEXT, version TEXT)""",)
_READY: set = set()


def mode() -> str:
    v = os.getenv("OFFICE2_LIFECYCLE", "merge").strip().lower()
    return v if v in ("off", "annotate", "merge") else "merge"


def _ensure(db: str) -> None:
    if db in _READY:
        return
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)
    _READY.add(db)


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _milestones(db: str, sid: str) -> set:
    from office_bridge import _fetchall

    lv = set()
    try:
        for (pj,) in _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id = ?", (sid,)):
            try:
                lv.add(json.loads(pj or "{}").get("level"))
            except ValueError:
                pass
    except Exception:  # noqa: BLE001
        pass
    return {x for x in lv if x}


def _plan_of(snap: Dict[str, Any]) -> Dict[str, Any]:
    th = snap.get("thesis") or {}
    return {"entry": _f(th.get("entry")), "sl": _f((th.get("sl") or {}).get("price") if isinstance(th.get("sl"), dict) else th.get("sl")),
            "targets": [{"kind": t.get("kind"), "p": _f(t.get("p")), "r": _f(t.get("r"))} for t in (th.get("targets") or []) if _f(t.get("p")) is not None],
            "zone": th.get("entry_zone") or th.get("zone"), "thesis_id": th.get("id"), "invalidation": _f((th.get("invalidation") or {}).get("price")),
            "event": {"src": (th.get("event") or {}).get("src"), "class": (th.get("event") or {}).get("class"), "level": (th.get("event") or {}).get("level"), "ts": (th.get("event") or {}).get("ts")}}


def parents(db: str, sym: str, direction: str, now: float, exclude: str = "") -> List[Dict[str, Any]]:
    """Доставлені READY цієї монети й напряму за останні 48 год (нові першими) зі станом життя."""
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT scenario_id, created_ts, valid_until_ts, msg_id, snapshot_json FROM office2_live_signal "
                         "WHERE symbol = ? AND direction = ? AND status = 'DELIVERED' AND created_ts > ? AND scenario_id <> ? ORDER BY created_ts DESC", (sym, direction, now - LIFECYCLE_SEC, exclude))
    out = []
    for sid, ct, vu, mid, sj in rows:
        try:
            snap = json.loads(sj or "{}")
        except ValueError:
            snap = {}
        lv = _milestones(db, sid)
        try:
            import office_ready_seq as _rs

            seq = _rs.number_of(db, sid)
        except Exception:  # noqa: BLE001
            seq = None
        out.append({"scenario_id": sid, "created_ts": float(ct), "valid_until_ts": float(vu), "msg_id": int(mid) if mid else None, "seq": seq, "milestones": sorted(lv),
                    "entered": "ENTRY" in lv, "terminal": sorted(lv & set(TERMINAL)), "live": not (lv & set(TERMINAL)), "plan": _plan_of(snap)})
    return out


def relate(db: str, sym: str, direction: str, th: Dict[str, Any], now: float) -> Dict[str, Any]:
    """NEW | DUPLICATE | CONTINUATION | INDEPENDENT | REENTRY (див. докстрінг модуля)."""
    ps = parents(db, sym, direction, now, exclude=str(th.get("scenario_id") or ""))
    live = [p for p in ps if p["live"]]
    if live:
        p = live[0]
        ev = th.get("event") or {}
        c_ts, p_ts = _f(ev.get("ts")), _f((p["plan"].get("event") or {}).get("ts"))
        same_id = bool(p["plan"].get("thesis_id") and p["plan"]["thesis_id"] == th.get("id"))
        same_event = bool(c_ts is not None and p_ts is not None and c_ts == p_ts)
        if same_id or same_event:
            return {"relation": "DUPLICATE", "parent": p, "same_idea": True}
        if c_ts is not None and c_ts > p["created_ts"]:
            return {"relation": "INDEPENDENT", "parent": p, "same_idea": False, "difference": difference(p, th)}
        return {"relation": "CONTINUATION", "parent": p, "same_idea": False}
    if ps:
        return {"relation": "REENTRY", "parent": ps[0], "same_idea": False}
    return {"relation": "NEW", "parent": None, "same_idea": False}


def difference(parent: Dict[str, Any], th: Dict[str, Any]) -> Dict[str, Any]:
    """Що відрізняє новий сетап від початкового сценарію (лише обчислені факти)."""
    ev = th.get("event") or {}
    lvl = ev.get("level") or th.get("level") or {}
    pl = parent["plan"]
    return {"new_event": {"class": ev.get("class"), "src": ev.get("src"), "kind": lvl.get("kind"), "level": _f(lvl.get("p")), "ts": _f(ev.get("ts"))},
            "new_invalidation": _f((th.get("invalidation") or {}).get("price")), "parent_invalidation": pl.get("invalidation"), "parent_event": pl.get("event")}


def compact(rel: Dict[str, Any]) -> Dict[str, Any]:
    """Те, що потрапляє в заморожений знімок READY (повторний вхід): без важких полів."""
    p = rel.get("parent") or {}
    return {"relation": rel.get("relation"), "parent_scenario_id": p.get("scenario_id"), "parent_seq": p.get("seq"), "parent_msg_id": p.get("msg_id"),
            "parent_milestones": p.get("milestones"), "parent_terminal": p.get("terminal"), "difference": rel.get("difference"), "version": VERSION}


def new_targets_beyond(parent_plan: Dict[str, Any], th: Dict[str, Any], long_: bool) -> List[Dict[str, Any]]:
    """Цілі нового сетапу, що лежать ДАЛІ за найдальшу початкову ціль (реальні рівні тези)."""
    old = [t["p"] for t in parent_plan.get("targets") or [] if t.get("p") is not None]
    if not old:
        return []
    far = max(old) if long_ else min(old)
    return [{"kind": t.get("kind"), "p": _f(t.get("p"))} for t in th.get("targets") or [] if _f(t.get("p")) is not None and ((_f(t.get("p")) > far) if long_ else (_f(t.get("p")) < far))]


def propose_targets(parent_plan: Dict[str, Any], levels: List[Dict[str, Any]], long_: bool, limit: int = 2) -> List[Dict[str, Any]]:
    """ПРОПОЗИЦІЯ (не застосовується): найближчі ще не зняті структурні рівні ЗА найдальшою початковою ціллю в напрямі угоди; R — від початкового входу/SL батьківського плану.
    Рівнів немає → порожньо (нічого не вигадуємо). Початкові цілі й стоп не змінюються."""
    tps = [t["p"] for t in parent_plan.get("targets") or [] if t.get("p") is not None]
    e, sl = parent_plan.get("entry"), parent_plan.get("sl")
    if not tps or e is None or sl is None or e == sl:
        return []
    far = max(tps) if long_ else min(tps)
    risk = abs(e - sl)
    want = "high" if long_ else "low"
    cand = sorted([x for x in levels if x.get("taken_ts") is None and x.get("side") == want and ((x["p"] > far) if long_ else (x["p"] < far))], key=lambda x: x["p"] if long_ else -x["p"])
    out: List[Dict[str, Any]] = []
    for x in cand:
        if out and abs(x["p"] - out[-1]["p"]) < 0.5 * risk:       # як у Brain.targets_for: наступна ціль — не ближче 0,5 R від попередньої
            continue
        out.append({"kind": x.get("kind"), "p": float(x["p"]), "r_from_original": round(abs(x["p"] - e) / risk, 2), "strength": int(x.get("strength", 1))})
        if len(out) >= limit:
            break
    return out


def continuation_text(rel: Dict[str, Any], th: Dict[str, Any], symbol: str, direction: str, fmt: Callable[[Any], str], ticker: str, proposals: Optional[List[Dict[str, Any]]] = None) -> str:
    p = rel["parent"]
    plan = p["plan"]
    long_ = str(direction).upper() != "SHORT"
    no = f"№{int(p['seq'])}" if p.get("seq") else "№?"
    reached = [m for m in ("TP1", "TP2", "TP3") if m in p.get("milestones", [])]
    status = f"{reached[-1]} досягнуто (за ринковою ціною)" if reached else ("Сценарій у роботі" if p.get("entered") else "Сценарій у роботі, вхід ще не торкнуто")
    L = ["AI OFFICE · СУПРОВІД СЦЕНАРІЮ", f"{no} · {ticker} {direction}", "", status, "Продовження руху", "",
         f"Початковий сценарій {no} залишається головним. Новий {direction}-сетап підтверджує продовження руху."]
    for i, t in enumerate(plan.get("targets") or [], 1):
        L.append(f"Початковий TP{i}  {fmt(t['p'])}" + ("  (досягнуто)" if f"TP{i}" in p.get("milestones", []) else ""))
    if plan.get("sl") is not None:
        L.append(f"Початковий SL  {fmt(plan['sl'])}  (без змін)")
    z = th.get("entry_zone") or th.get("zone")
    inv = _f((th.get("invalidation") or {}).get("price"))
    ev = th.get("event") or {}
    lvl = (ev.get("level") or th.get("level") or {})
    bits = []
    if isinstance(z, (list, tuple)) and len(z) == 2:
        bits.append(f"зона входу {fmt(min(z))}–{fmt(max(z))}")
    if inv is not None:
        bits.append(f"скасування {fmt(inv)}")
    if ev.get("class") or lvl.get("kind"):
        bits.append(f"подія {ev.get('class') or ''} {lvl.get('kind') or ''} {fmt(lvl['p']) if _f(lvl.get('p')) is not None else ''}".strip())
    if bits:
        L.append("Новий сетап: " + " · ".join(bits))
    L += ["", "ПРОПОЗИЦІЯ · НЕ ЗАСТОСОВАНО"]
    if proposals:
        for i, x in enumerate(proposals, 4):
            L.append(f"Можливий TP{i}  {fmt(x['p'])}  ({x.get('kind') or 'рівень'}, {x['r_from_original']:.2f}R від початкового входу)")
        steps = [f"{x.get('step')}: {x.get('value')}" for x in (th.get("sequence") or []) if isinstance(x, dict) and x.get("ok") and x.get("value")]
        if steps:
            L.append("Підтвердження: " + "; ".join(steps[:5]))
        L.append("Ризики: рівень лежить за початковими цілями — ціна має пройти шлях до нього; R рахується від початкового входу/SL, не від ціни зараз.")
    else:
        L.append("Наступного структурного рівня за початковими цілями не знайдено — пропозиції немає.")
    cond = f"закриття M15 {'нижче' if long_ else 'вище'} {fmt(inv)}" if inv is not None else "умова скасування нового сетапу не задана"
    L.append(f"Умови скасування: {cond}; початковий SL {fmt(plan['sl']) if plan.get('sl') is not None else '—'} лишається чинним.")
    L.append("")
    L.append("Пропозиція не змінює початковий сигнал: TP1–TP3 і SL ті самі. Пересування стопа, часткове закриття, додавання до позиції й нові ордери — лише окреме рішення; автоматично нічого не застосовується. Торкання ціни — не виконання ордера.")
    return "\n".join(L)


def event_id(parent_sid: str, thesis_id: str, kind: str = "CONTINUATION") -> str:
    return f"LC|{kind}|{hashlib.sha256(f'{parent_sid}|{thesis_id}'.encode()).hexdigest()[:14]}"


def record_continuation(db: str, rel: Dict[str, Any], th: Dict[str, Any], sym: str, direction: str, child_sid: str, text: str, now: float, proposals: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Один запис на пару (початковий сценарій, id ідеї нового сетапу): паралельні цикли й повтори не дублюють. True — створено щойно."""
    from office_bridge import _execute, _fetchall

    _ensure(db)
    p = rel["parent"]
    eid = event_id(p["scenario_id"], str(th.get("id") or child_sid))
    if _fetchall(db, "SELECT 1 FROM office2_lifecycle_event WHERE event_id = ?", (eid,)):
        return False
    payload = {"text": text, "parent": {k: p.get(k) for k in ("scenario_id", "seq", "milestones", "plan")}, "child_targets": th.get("targets"), "child_zone": th.get("entry_zone") or th.get("zone"),
               "child_invalidation": (th.get("invalidation") or {}).get("price"), "proposal": {"status": "ПРОПОЗИЦІЯ · НЕ ЗАСТОСОВАНО", "applied": False, "targets": proposals or []}}
    _execute(db, "INSERT INTO office2_lifecycle_event(event_id, ts, relation, symbol, direction, parent_scenario_id, parent_seq, parent_msg_id, child_scenario_id, child_thesis_id, payload_json, tg_status, version) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (event_id) DO NOTHING",
             (eid, float(now), "CONTINUATION", sym, direction, p["scenario_id"], p.get("seq"), p.get("msg_id"), child_sid, th.get("id"), json.dumps(payload, ensure_ascii=False, default=str), "NEW", VERSION))
    return True


def claim(db: str, eid: str, token: str, now: float) -> bool:
    """Атомарне «беру на відправку»: лише один виконавець; застарілий claim (збій) перехоплюється."""
    from office_bridge import _execute, _fetchall

    _ensure(db)
    _execute(db, "UPDATE office2_lifecycle_event SET claim = ?, claim_ts = ?, tg_tries = COALESCE(tg_tries,0) + 1 WHERE event_id = ? AND tg_status = 'NEW' AND (claim IS NULL OR claim_ts < ?)",
             (token, float(now), eid, float(now) - CLAIM_TTL_SEC))
    r = _fetchall(db, "SELECT claim FROM office2_lifecycle_event WHERE event_id = ?", (eid,))
    return bool(r and r[0][0] == token)


def pending(db: str, now: float) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    _ensure(db)
    rows = _fetchall(db, "SELECT event_id, symbol, direction, parent_scenario_id, parent_seq, parent_msg_id, payload_json, tg_tries FROM office2_lifecycle_event "
                         "WHERE tg_status = 'NEW' AND COALESCE(tg_tries,0) < ? AND ts > ? ORDER BY ts", (MAX_TRIES, now - 6 * 3600))
    out = []
    for eid, sym, d, psid, pseq, pmid, pj, tries in rows:
        try:
            pl = json.loads(pj or "{}")
        except ValueError:
            pl = {}
        out.append({"event_id": eid, "symbol": sym, "direction": d, "parent_scenario_id": psid, "parent_seq": pseq, "parent_msg_id": pmid, "text": pl.get("text") or "", "tries": tries})
    return out


def mark_sent(db: str, eid: str, msg_id: Any, now: float) -> None:
    from office_bridge import _execute

    _execute(db, "UPDATE office2_lifecycle_event SET tg_status = 'SENT', msg_id = ?, sent_ts = ?, last_error = NULL WHERE event_id = ?", (int(msg_id) if msg_id else None, float(now), eid))


def mark_failed(db: str, eid: str, err: str) -> None:
    from office_bridge import _execute

    _execute(db, "UPDATE office2_lifecycle_event SET last_error = ?, claim = NULL, tg_status = CASE WHEN COALESCE(tg_tries,0) >= ? THEN 'FAILED' ELSE 'NEW' END WHERE event_id = ?", (err[:200], MAX_TRIES, eid))


async def deliver(db: str, send: Callable[..., Any], event_type: str, now: Optional[float] = None) -> int:
    """Надсилає події ПРОДОВЖЕННЯ відповіддю на повідомлення початкового READY (тим самим каналом, що TP/SL-події сценарію). Один раз на подію."""
    import asyncio
    import uuid

    t = time.time() if now is None else now
    n = 0
    for ev in await asyncio.to_thread(pending, db, t):
        token = uuid.uuid4().hex
        if not await asyncio.to_thread(claim, db, ev["event_id"], token, t):
            continue
        try:
            mid = await send(event_type, ev["text"], reply_to_message_id=ev["parent_msg_id"], symbol=ev["symbol"], direction=ev["direction"], kind="SCENARIO_EVENT", intent="SCENARIO_EVENT",
                             canonical_id=ev["event_id"], scenario_event="CONTINUATION", link_scenario_id=ev["parent_scenario_id"])
        except Exception as exc:  # noqa: BLE001
            await asyncio.to_thread(mark_failed, db, ev["event_id"], f"{type(exc).__name__}: {exc}")
            continue
        if mid:
            await asyncio.to_thread(mark_sent, db, ev["event_id"], mid, time.time())
            n += 1
        else:
            await asyncio.to_thread(mark_failed, db, ev["event_id"], "Telegram не підтвердив доставку")
    return n
