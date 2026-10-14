#!/usr/bin/env python3
"""Життєвий цикл сигналів: FIL №3 (TP1 досягнуто) → нова ідея FIL LONG 11:15 = ПРОДОВЖЕННЯ в гілці №3, а не незалежний №6.
Реальні значення production 14.10.2026 (FIL №3 і №6); ізольована БД, без мережі й Telegram."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_bridge as OB  # noqa: E402
import office_ready_seq as RS  # noqa: E402
from office2 import engine as E  # noqa: E402
from office2 import lifecycle as LC  # noqa: E402

bad = 0


def check(name, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f" :: {info}"))
    bad += 0 if ok else 1


FMT = lambda x: f"{x:.6g}".replace(".", ",")  # noqa: E731
NOW0 = 1791941400.0     # FIL №3: READY 14.10 01:30 UTC
P_ID, P_SID = "O2|7196896c7b11", "O2|7196896c7b11|1791941400"
C_ID = "O2|d713ff646d97"   # FIL №6: 08:15 UTC, інша подія (LATE_SWEEP ASIA_L)


def parent_snap():
    return {"thesis": {"id": P_ID, "entry": 1.1616, "sl": 1.13295, "entry_zone": [1.1483, 1.1646], "invalidation": {"price": 1.1367},
                       "targets": [{"kind": "NEW_YORK_H", "p": 1.1931, "r": 1.1}, {"kind": "H4SW", "p": 1.264, "r": 3.57}, {"kind": "W1H", "p": 1.293, "r": 4.59}],
                       "event": {"src": "SWEEP", "class": "FRESH_RAID", "ts": 1791913500, "level": {"kind": "LONDON_L", "p": 1.1394}}}}


def child_th(targets=None):
    return {"id": C_ID, "dir": "LONG", "entry": 1.1681, "sl": 1.1443, "entry_zone": [1.162429, 1.173462], "invalidation": {"price": 1.1488},
            "targets": targets or [{"kind": "H4SW", "p": 1.2137, "r": 1.9}, {"kind": "H4SW", "p": 1.264, "r": 4.0}, {"kind": "H1SW", "p": 1.2766, "r": 4.5}],
            "event": {"src": "SWEEP", "class": "LATE_SWEEP", "ts": 1791933300, "level": {"kind": "ASIA_L", "p": 1.1532}}, "sequence": [{"step": "зсув структури (MSS/BOS)", "ok": True, "value": "закриття вище 1.1768"}, {"step": "тригер M15", "ok": True, "value": "закриття 1.1681 ≥ середини зони 1.16794"}]}


def mk_db(td, milestones=("ENTRY", "TP1"), sym="FILUSDT", direction="LONG", sid=P_SID, seq=True):
    db = os.path.join(td, "t.db")
    os.environ["OFFICE_DB_PATH"] = db
    OB.init_office_db(db)
    for d in E.DDL:
        OB._execute(db, d)
    OB._execute(db, "INSERT INTO office2_live_signal(scenario_id,symbol,direction,created_ts,valid_until_ts,status,snapshot_json,version,delivered_ts,msg_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, sym, direction, NOW0, NOW0 + 6 * 3600, "DELIVERED", json.dumps(parent_snap()), "v", NOW0 + 37, 10575))
    if seq:
        RS.assign(db, sid, NOW0)
        for _ in range(2):   # №1, №2 вже зайняті іншими: у FIL — №3
            pass
    for lv in milestones:
        OB._execute(db, "INSERT INTO office_events(ts_utc, event_type, signal_id, payload_json) VALUES (?,?,?,?)", ("2026-10-14T04:38:00+00:00", "SCENARIO_MILESTONE", sid, json.dumps({"level": lv})))
    return db


class Sent:
    def __init__(self):
        self.calls = []

    async def __call__(self, ev, text, **kw):
        self.calls.append((text, kw))
        return 10600 + len(self.calls)


with tempfile.TemporaryDirectory() as td:
    db = mk_db(td)
    # нумерація вигляду №3: підставляємо seq=3 для батьківського сценарію
    OB._execute(db, "UPDATE office_ready_seq SET seq = 3 WHERE scenario_id = ?", (P_SID,))
    t8 = NOW0 + 7 * 3600 + 15 * 60          # 08:15 UTC: вікно входу №3 (до 07:30) уже минуло, але сценарій у роботі (TP1 був, SL/TP3 ні)
    rel = LC.relate(db, "FILUSDT", "LONG", child_th(), t8)
    check("FIL №6: батьківський №3 ще в роботі → ПРОДОВЖЕННЯ (раніше проходило як незалежний сигнал)", rel["relation"] == "CONTINUATION" and rel["parent"]["seq"] == 3, rel)
    check("це інша ідея (інша подія), а не повтор тієї самої", rel["same_idea"] is False)
    LEVELS = [{"kind": "D1H", "p": 1.31, "side": "high", "taken_ts": None, "strength": 2}, {"kind": "H1SW", "p": 1.3105, "side": "high", "taken_ts": None}, {"kind": "W1H", "p": 1.36, "side": "high", "taken_ts": None},
              {"kind": "H4SW", "p": 1.27, "side": "high", "taken_ts": None}, {"kind": "OLD", "p": 1.33, "side": "high", "taken_ts": 1790000000}, {"kind": "LOW", "p": 1.4, "side": "low", "taken_ts": None}]
    props = LC.propose_targets(rel["parent"]["plan"], LEVELS, True)
    check("пропозиція TP4/TP5: лише ще не зняті структурні рівні ЗА початковою TP3 (1,293) у напрямі угоди, крок ≥0,5R; без вигаданих рівнів",
          [x["kind"] for x in props] == ["D1H", "W1H"] and abs(props[0]["r_from_original"] - (1.31 - 1.1616) / (1.1616 - 1.13295)) < 0.01, props)
    check("рівнів за TP3 немає → пропозицій немає (нічого не вигадуємо)", LC.propose_targets(rel["parent"]["plan"], [x for x in LEVELS if x["p"] < 1.293], True) == [])
    txt = LC.continuation_text(rel, child_th(), "FILUSDT", "LONG", FMT, "FIL", props)
    check("текст: №3, TP1 досягнуто, початкові TP1/TP2/TP3 і SL без змін", "№3 · FIL LONG" in txt and "TP1 досягнуто" in txt and "Початковий TP1  1,1931  (досягнуто)" in txt and "Початковий TP3  1,293" in txt and "Початковий SL  1,13295  (без змін)" in txt, txt)
    check("текст: окрема ПРОПОЗИЦІЯ · НЕ ЗАСТОСОВАНО з конкретними можливими TP4/TP5, підтвердженнями, ризиками й умовами скасування",
          "ПРОПОЗИЦІЯ · НЕ ЗАСТОСОВАНО" in txt and "Можливий TP4  1,31  (D1H" in txt and "Можливий TP5  1,36  (W1H" in txt and "Підтвердження: зсув структури (MSS/BOS): закриття вище 1.1768" in txt
          and "Ризики:" in txt and "Умови скасування: закриття M15 нижче 1,1488; початковий SL 1,13295 лишається чинним" in txt, txt)
    check("текст: пропозиція не застосовується; стоп/часткові закриття/ордери — лише окреме рішення", "автоматично нічого не застосовується" in txt and "Новий захисний стоп" not in txt)
    check("без рівнів за цілями: «пропозиції немає»", "пропозиції немає" in LC.continuation_text(rel, child_th(), "FILUSDT", "LONG", FMT, "FIL", []))
    check("текст: без вигаданих фіксацій/прибутку", "зафіксовано" not in txt.lower() and "прибуток" not in txt.lower())
    dup = LC.relate(db, "FILUSDT", "LONG", dict(child_th(), id=P_ID), t8)
    check("той самий id ідеї → ДУБЛІКАТ (не надсилати)", dup["relation"] == "DUPLICATE")
    dup2 = LC.relate(db, "FILUSDT", "LONG", dict(child_th(), event=dict(child_th()["event"], ts=1791913500)), t8)
    check("та сама структурна подія під іншим id → ДУБЛІКАТ", dup2["relation"] == "DUPLICATE")
    ind = LC.relate(db, "FILUSDT", "LONG", dict(child_th(), event=dict(child_th()["event"], ts=NOW0 + 3600)), t8)
    check("структурна подія ПІСЛЯ видачі №3 (нова структура, своє скасування) → НЕЗАЛЕЖНИЙ сетап з поясненням відмінності",
          ind["relation"] == "INDEPENDENT" and ind["difference"]["new_invalidation"] == 1.1488 and ind["difference"]["parent_invalidation"] == 1.1367 and LC.compact(ind)["difference"]["new_event"]["kind"] == "ASIA_L", ind)
    snap_before = OB._fetchone(db, "SELECT snapshot_json FROM office2_live_signal WHERE scenario_id = ?", (P_SID,))[0]
    # запис: один раз на (початковий сценарій, ідея); повтори й паралельні цикли не дублюють
    a = LC.record_continuation(db, rel, child_th(), "FILUSDT", "LONG", f"{C_ID}|{int(t8)}", txt, t8, props)
    b = LC.record_continuation(db, rel, child_th(), "FILUSDT", "LONG", f"{C_ID}|{int(t8) + 900}", txt, t8 + 900, props)
    pl = json.loads(OB._fetchone(db, "SELECT payload_json FROM office2_lifecycle_event")[0])
    check("у БД пропозиція зі статусом «НЕ ЗАСТОСОВАНО», applied=False; початковий план №3 у БД не змінено",
          pl["proposal"]["applied"] is False and pl["proposal"]["status"] == "ПРОПОЗИЦІЯ · НЕ ЗАСТОСОВАНО" and OB._fetchone(db, "SELECT snapshot_json FROM office2_live_signal WHERE scenario_id = ?", (P_SID,))[0] == snap_before)
    check("атомарна дедуплікація: друга спроба тієї самої ідеї не створює другої події", a is True and b is False and OB._fetchone(db, "SELECT COUNT(*) FROM office2_lifecycle_event")[0] == 1)
    ev = LC.pending(db, t8)[0]
    check("claim атомарний: лише один виконавець бере подію", LC.claim(db, ev["event_id"], "A", t8) is True and LC.claim(db, ev["event_id"], "B", t8) is False)
    OB._execute(db, "UPDATE office2_lifecycle_event SET claim = NULL")
    OB._execute(db, "UPDATE office2_lifecycle_event SET tg_tries = 0")
    s = Sent()
    async def _both():
        return await asyncio.gather(LC.deliver(db, s, "TRADE_UPDATE", now=t8), LC.deliver(db, s, "TRADE_UPDATE", now=t8))

    n1, n2 = asyncio.run(_both())
    check("паралельні проходи доставки: рівно одне повідомлення", len(s.calls) == 1 and n1 + n2 == 1, (len(s.calls), n1, n2))
    check("продовження — ВІДПОВІДЬ на початкове повідомлення №3 (id 10575), канал SCENARIO_EVENT", s.calls[0][1]["reply_to_message_id"] == 10575 and s.calls[0][1]["intent"] == "SCENARIO_EVENT" and s.calls[0][1]["kind"] == "SCENARIO_EVENT")
    asyncio.run(LC.deliver(db, s, "TRADE_UPDATE", now=t8 + 60))
    check("повторна доставка не шле вдруге", len(s.calls) == 1)
    # Telegram не підтвердив → подія лишається для повтору, але не більше MAX_TRIES
    OB._execute(db, "UPDATE office2_lifecycle_event SET tg_status = 'NEW', claim = NULL, tg_tries = 0")

    async def fail(*a, **k):
        return None

    for i in range(LC.MAX_TRIES + 1):
        asyncio.run(LC.deliver(db, fail, "TRADE_UPDATE", now=t8 + 1000 * (i + 1)))
        OB._execute(db, "UPDATE office2_lifecycle_event SET claim_ts = 0 WHERE tg_status = 'NEW'")
    check("збій Telegram: після MAX_TRIES подія FAILED (без нескінченних повторів)", OB._fetchone(db, "SELECT tg_status FROM office2_lifecycle_event")[0] == "FAILED")

    # та сама ідея (той самий id) — повтор, а не «нова»
    same = dict(child_th(), id=P_ID)
    check("повторний READY тієї самої ідеї: same_idea (подію не створюємо)", LC.relate(db, "FILUSDT", "LONG", same, t8)["same_idea"] is True)
    # протилежний напрям і інша монета — незалежні
    check("протилежний напрям: окремий сценарій (не продовження)", LC.relate(db, "FILUSDT", "SHORT", child_th(), t8)["relation"] == "NEW")
    check("інша монета: окремий сценарій", LC.relate(db, "SUIUSDT", "LONG", child_th(), t8)["relation"] == "NEW")
    # завершення початкового сценарію → ПОВТОРНИЙ ВХІД
    for term in ("SL", "TP3"):
        OB._execute(db, "INSERT INTO office_events(ts_utc, event_type, signal_id, payload_json) VALUES (?,?,?,?)", ("2026-10-14T09:00:00+00:00", "SCENARIO_MILESTONE", P_SID, json.dumps({"level": term})))
        r2 = LC.relate(db, "FILUSDT", "LONG", child_th(), t8 + 3 * 3600)
        check(f"після {term}: новий підтверджений сетап = ПОВТОРНИЙ ВХІД з посиланням на №3", r2["relation"] == "REENTRY" and LC.compact(r2)["parent_seq"] == 3 and LC.compact(r2)["parent_msg_id"] == 10575, r2)
        OB._execute(db, "DELETE FROM office_events WHERE signal_id = ? AND payload_json LIKE ?", (P_SID, f'%"{term}"%'))
    # вікно 48 год: давній сценарій не зв'язується
    check("сценарій старше 48 год не зв'язується", LC.relate(db, "FILUSDT", "LONG", child_th(), NOW0 + 49 * 3600)["relation"] == "NEW")

# нумерація без нулів, внутрішні id не змінено
check("нумерація без нулів: №1, №2, №3, №15, №345", [RS.label(x) for x in (1, 2, 3, 15, 345)] == ["№1", "№2", "№3", "№15", "№345"])
import office_user_messages as M  # noqa: E402
check("TP/SL-події теж без нулів", M.scenario_event(symbol="FILUSDT", direction="LONG", level="TP1", price=1.1931, number=3).startswith("🎯 FIL · TP1 · №3\n"))
check("режим off вимикає життєвий цикл", (os.environ.__setitem__("OFFICE2_LIFECYCLE", "off") or LC.mode() == "off") and (os.environ.pop("OFFICE2_LIFECYCLE") is not None))
print("ALL OK" if not bad else f"FAILED {bad}")
sys.exit(1 if bad else 0)
