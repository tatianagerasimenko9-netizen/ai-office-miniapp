#!/usr/bin/env python3
"""Живий WATCH/PAPER-радар: preview плану в Brain (стан не змінюється), картки WATCH/BLOCKED, антиспам, текст Telegram, paper-супровід без заглядання вперед,
розмежування з READY, чесні порожні стани."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import office_bridge as OB  # noqa: E402
import test_office2_brain2 as TB  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import brain2 as B2  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import radar_watch as RW  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


NOW = 1_800_000_000.0


def new_db():
    td = tempfile.mkdtemp()
    db = os.path.join(td, "r.db")
    OB.init_office_db(db)
    EN.init_db(db)
    return db


def put_scenario(db, sid, sym, d, state, reason, th, upd=NOW):
    OB._execute(db, "INSERT INTO office2_live_scenario VALUES (?,?,?,?,?,?,?,?,?,?,?)", (sid, sym, d, "SWEEP_SEQ", state, upd, upd, None, reason, json.dumps(th), "t"))


def thesis_wait(zone=(100.0, 100.4), entry=100.2, sl=99.0, tps=(101.4, 102.6, 104.0), ok=True):
    pv = {"ok": ok, "entry": entry, "sl": sl, "risk_pct": abs(entry - sl) / entry * 100, "targets": [{"p": p, "kind": "PDH", "r": abs(p - entry) / abs(entry - sl)} for p in tps] if ok else None,
          "reject": None if ok else "до першої реальної цілі PDH лише 0.7 R"}
    return {"id": "x", "dir": "LONG", "state": "WAIT", "entry_zone": list(zone), "zone": list(zone), "level": {"p": 99.5, "kind": "PDL"}, "need": {"px": 100.2, "text": "бичаче закриття M15 вище 100.2"}, "preview": pv}


def thesis_blocked():
    return {"id": "y", "dir": "SHORT", "state": "NO_TRADE", "entry": 50.0, "sl": 50.6, "risk_pct": 1.2, "targets": [{"p": 49.0, "kind": "PDL", "r": 1.67}, {"p": 48.2, "kind": "D1L", "r": 3.0}],
            "entry_zone": [49.9, 50.1], "level": {"p": 50.4, "kind": "ASIA_H"}}


# --- 1. Brain: preview додається лише до WAIT із зоною, стан/причина не змінюються
c, seq = TB.closes_long()
orig = B.all_levels
B.all_levels = lambda ctx, now: TB.LEVELS
try:
    st = {}
    for name in ("sweep", "top", "bear_in_zone"):
        th = TB.run(c, seq[name])
        st[name] = th
    check("WAIT 1/3 (sweep) без preview — структури ще немає", "preview" not in st["sweep"], str(st["sweep"].get("preview")))
    check("WAIT 2/3 має preview з ознакою ok та орієнтиром", st["top"]["state"] == "WAIT" and "preview" in st["top"] and "ok" in st["top"]["preview"], str(st["top"].get("preview")))
    check("WAIT 3/3 має preview", st["bear_in_zone"]["state"] == "WAIT" and "preview" in st["bear_in_zone"])
    pv = st["bear_in_zone"]["preview"]
    check("preview: або повний план (entry/sl/цілі), або чесна причина відмови", (pv["ok"] and pv["entry"] and pv["sl"] and pv["targets"]) or (not pv["ok"] and pv["reject"]), str(pv))
    ready = TB.run(c, seq["trigger"])
    check("READY не містить preview (план справжній)", ready["state"] == "READY" and "preview" not in ready)
finally:
    B.all_levels = orig

# --- 2. sync: WATCH (ARMED/RETRACE), BLOCKED, 1/3 ігнорується
db = new_db()
put_scenario(db, "O2|a1", "AAAUSDT", "LONG", "WAIT", "WAIT 3/3 · ARMED (зона досягнута): ціна в зоні", thesis_wait())
put_scenario(db, "O2|a2", "BBBUSDT", "LONG", "WAIT", "WAIT 2/3 · ретрейс: чекаємо", thesis_wait())
put_scenario(db, "O2|a3", "CCCUSDT", "LONG", "WAIT", "WAIT 1/3 · зсув структури: потрібен", {"id": "z", "state": "WAIT"})
put_scenario(db, "O2|a4", "DDDUSDT", "LONG", "WAIT", "WAIT 3/3 · ARMED", thesis_wait(ok=False))
put_scenario(db, "O2|b1", "EEEUSDT", "SHORT", "NO_TRADE", "ємність сценаріїв: денний ліміт: 3 стопи за добу UTC", thesis_blocked())
put_scenario(db, "O2|b2", "FFFUSDT", "LONG", "NO_TRADE", "до першої реальної цілі PDH лише 0.7 R", {"id": "q"})
r = RW.sync(db, NOW + 60)
rows = {x[0]: x for x in OB._fetchall(db, "SELECT card_id, kind, stage, plan_ok, entry, sl, tp1, tp2, tp3, expires_ts, reject FROM office2_radar_card")}
check("sync: 4 картки (ARMED, RETRACE, ARMED без плану, BLOCKED); 1/3 і відхилений NO_TRADE карток не мають", set(rows) == {"W|O2|a1", "W|O2|a2", "W|O2|a4", "B|O2|b1"}, str(sorted(rows)))
check("ARMED має повний план, TTL 4 год", rows["W|O2|a1"][3] == 1 and rows["W|O2|a1"][6] == 101.4 and abs(rows["W|O2|a1"][9] - (NOW + RW.TTL_SEC)) < 1)
check("план, що не пройшов фільтри, лишається карткою з причиною (plan_ok=0), не прикидається сигналом", rows["W|O2|a4"][3] == 0 and "PDH" in (rows["W|O2|a4"][10] or ""))
check("BLOCKED бере повний READY-рівень відсіченого лімітом сценарію", rows["B|O2|b1"][3] == 1 and rows["B|O2|b1"][4] == 50.0 and rows["B|O2|b1"][7] == 48.2)
RW.sync(db, NOW + 90)
check("повторний sync без дублів", OB._fetchall(db, "SELECT COUNT(*) FROM office2_radar_card")[0][0] == 4)

# --- 3. вибір для Telegram: ARMED+BLOCKED, plan_ok, антиспам
pk = RW.pick_for_tg(db, NOW + 100)
check("у Telegram лише ARMED/BLOCKED із планом (RETRACE і plan_ok=0 — ні), BLOCKED першим", [x["card_id"] for x in pk] == ["B|O2|b1", "W|O2|a1"], str([x["card_id"] for x in pk]))
txt = RW.format_card(pk[1])
check("текст WATCH: не вхід, зона, SL, TP1–TP3, строк, лінк на картку", all(s in txt for s in ("WATCH · не вхід", "Зона входу", "SL:", "TP1:", "TP2:", "TP3:", "актуально до", "не сигнал і не ордер", "tab=radar&card=W%7CO2%7Ca1")), txt)
txtb = RW.format_card(pk[0])
check("текст BLOCKED показує причину ліміту й що це не вхід", "ЗАБЛОКОВАНО · не вхід" in txtb and "денний ліміт" in txtb, txtb)
RW.mark_sent(db, "W|O2|a1", 111, NOW + 100)
RW.mark_sent(db, "B|O2|b1", 112, NOW + 101)
check("після відправки картка не вибирається повторно", RW.pick_for_tg(db, NOW + 200) == [])
for i in range(5):
    put_scenario(db, f"O2|n{i}", f"N{i}USDT", "LONG", "WAIT", "WAIT 3/3 · ARMED", thesis_wait(), upd=NOW + 300)
RW.sync(db, NOW + 310)
check("антиспам: не більше TG_PER_HOUR карток за годину (вже 2 відправлено)", len(RW.pick_for_tg(db, NOW + 320)) == RW.TG_PER_HOUR - 2)
os.environ["OFFICE2_RADAR_TG"] = "0"
check("OFFICE2_RADAR_TG=0 повністю вимикає Telegram-потік", RW.pick_for_tg(db, NOW + 320) == [])
os.environ.pop("OFFICE2_RADAR_TG")

# --- 4. paper-супровід за свічками після появи картки
def cds(bars, t0):
    return [{"ts": t0 + 900 * i, "high": h, "low": l} for i, (h, l) in enumerate(bars)]


card = dict(zip(RW._COLS, OB._fetchall(db, "SELECT " + ",".join(RW._COLS) + " FROM office2_radar_card WHERE card_id = 'W|O2|a1'")[0]))
t0 = card["sent_ts"]
pre = cds([(100.5, 99.9)], t0 - 900)                                 # свічка ДО появи картки (торкається входу) не рахується
ev = RW.evaluate_card(card, pre + cds([(101.0, 100.6), (101.1, 100.7)], t0 + 900), t0 + 3 * 900)
check("свічка до картки не дає входу; ціна не дійшла до входу → чекаємо", ev["paper_status"] == "WAITING_ENTRY" and ev["entry_ts"] is None, str(ev))
ev = RW.evaluate_card(card, cds([(101.0, 100.6), (100.5, 100.1), (101.5, 100.3)], t0), t0 + 4 * 900)
check("вхід лімітом, потім TP1 → результат моделі A додатний, уже з витратами", ev["paper_status"] in ("ENTERED", "TP1") and "TP1" in (ev["reached"] or "") and ev["r_net"] is not None and ev["r_net"] > 0, str(ev))
ev = RW.evaluate_card(card, cds([(100.5, 100.1), (100.3, 98.9)], t0 + 900), t0 + 4 * 900)
check("вхід, далі SL першим → SL, від'ємний результат", ev["paper_status"] == "SL" and ev["r_net"] < -1.0, str(ev))
ev = RW.evaluate_card(card, cds([(100.5, 100.1), (102.0, 98.9)], t0 + 900), t0 + 4 * 900)
check("свічка зі стопом і ціллю разом → SL (консервативно)", ev["paper_status"] == "SL" and ev["r_net"] < -1.0, str(ev))
ev = RW.evaluate_card(card, cds([(101.0, 100.6)] * 20, t0 + 900), card["expires_ts"] + 5 * 900)
check("вхід так і не відбувся до кінця строку → NO_ENTRY", ev["paper_status"] == "NO_ENTRY", str(ev))

# --- 5. track + follow-up (віхи один раз)
state = {"bars": cds([(100.5, 100.1), (101.5, 100.3)], t0 + 900)}
n = RW.track(db, lambda s, tf, k: state["bars"] if s == "AAAUSDT" else [], NOW + 5000)
fu = RW.pending_followups(db)
check("track пише paper-стан, follow-up містить вхід і TP1", n >= 1 and any(x["card_id"] == "W|O2|a1" and "TP1" in x["_new"] and "ENTERED" in x["_new"] for x in fu), str(fu)[:300])
c1 = [x for x in fu if x["card_id"] == "W|O2|a1"][0]
RW.mark_notified(db, c1["card_id"], c1["_new"], c1.get("notified"))
check("після повідомлення віхи не повторюються", not [x for x in RW.pending_followups(db) if x["card_id"] == "W|O2|a1"])
check("текст follow-up: paper, не ордер", "Paper, не ордер" in RW.followup_text(c1))

# --- 6. send_pass (фейковий Telegram): надсилає, фіксує msg_id, помилка не ламає інших
sent = []


async def fake_photo(path, text, symbol="", direction=""):
    sent.append(("photo", symbol))
    return 900 + len(sent)


async def fake_text(text, reply_to=None, symbol="", direction=""):
    sent.append(("text", symbol, reply_to))
    return 700 + len(sent)


db2 = new_db()
put_scenario(db2, "O2|s1", "SSSUSDT", "LONG", "WAIT", "WAIT 3/3 · ARMED", thesis_wait())
put_scenario(db2, "O2|s2", "TTTUSDT", "SHORT", "NO_TRADE", "ємність сценаріїв: ємність сценаріїв Office2: 50$ > 40$", thesis_blocked())
res = asyncio.run(RW.send_pass(db2, fake_photo, fake_text, lambda s, tf, k: [], lambda **kw: {"ok": False, "reason": "no matplotlib in test"}, now=NOW + 60, log=lambda m: None))
check("send_pass: 2 картки відправлено (текстом, бо графік недоступний), msg_id збережено", res["sent"] == 2 and len(sent) == 2 and all(OB._fetchall(db2, "SELECT msg_id FROM office2_radar_card WHERE tg_status='SENT'")[i][0] for i in range(2)), f"{res} {sent}")
res = asyncio.run(RW.send_pass(db2, fake_photo, fake_text, lambda s, tf, k: [], lambda **kw: {"ok": False}, now=NOW + 120, log=lambda m: None))
check("повторний прохід нічого не шле (дедуп)", res["sent"] == 0 and len(sent) == 2)

# --- 7. summary: порожній стан чесний, причина «чому немає READY» є
db3 = new_db()
sm = RW.summary(db3, NOW)
check("summary на порожній БД: ok, 0 карток, блок «чому немає READY»", sm["ok"] and sm["cards"] == [] and "why_no_ready" in sm, str(sm)[:300])
sm = RW.summary(db, NOW + 400)
check("summary: картки зі статусом, статистика WATCH/BLOCKED окремо", len(sm["cards"]) >= 4 and "watch" in sm["stats"] and "blocked" in sm["stats"] and all("status_ua" in x for x in sm["cards"]))

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
