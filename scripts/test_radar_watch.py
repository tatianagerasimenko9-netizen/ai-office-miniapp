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

# --- 3. вибір для Telegram: RETRACE+ARMED+BLOCKED, plan_ok, антиспам
pk = RW.pick_for_tg(db, NOW + 100)
check("у Telegram усі планово готові RETRACE/ARMED/BLOCKED (але не plan_ok=0), BLOCKED першим", [x["card_id"] for x in pk] == ["B|O2|b1", "W|O2|a1", "W|O2|a2"], str([x["card_id"] for x in pk]))
txt = RW.format_card(pk[1])
check("коротка картка: є напрям, зона, стоп, цілі, прямий лінк і <1024 символів", all(piece in txt for piece in ("СПОСТЕРІГАЄМО", "Очікуємо зростання", "НЕ ВХОДИТИ", "Зона:", "Стоп:", "Цілі:", "tab=radar&card=")) and len(txt) <= 1024, txt)
JARGON = ("READY", "WATCH", "PAPER", "LONG", "SHORT", "SL:", "TP1", "M15", "paper", "ЗАБЛОКОВАНО")
check("у головному тексті немає жаргону (технічний код лише в останньому рядку «Технічно»)", not any(j in txt.split("Технічно:")[0] for j in JARGON), txt)
txtb = RW.format_card(pk[0])
check("навчальна картка коротка, без технічного коду та з конкретним deep link",
      "ЗАБЛОКОВАНО" not in txtb and "НАВЧАЛЬНА УГОДА" in txtb and "Очікуємо падіння" in txtb and "tab=radar&card=" in txtb and len(txtb) <= 1024, txtb)
RW.mark_sent(db, "W|O2|a1", 111, NOW + 100)
RW.mark_sent(db, "B|O2|b1", 112, NOW + 101)
RW.mark_sent(db, "W|O2|a2", 113, NOW + 102)
check("після відправки картка не вибирається повторно", RW.pick_for_tg(db, NOW + 200) == [])
for i in range(RW.TG_PER_HOUR + 4):
    put_scenario(db, f"O2|n{i}", f"N{i}USDT", "LONG", "WAIT", "WAIT 3/3 · ARMED", thesis_wait(), upd=NOW + 300)
RW.sync(db, NOW + 310)
check("антиспам: не більше TG_PER_HOUR карток за годину (вже 3 відправлено)", len(RW.pick_for_tg(db, NOW + 320)) == RW.TG_PER_HOUR - 3)
os.environ["OFFICE2_RADAR_TG"] = "0"
check("OFFICE2_RADAR_TG=0 повністю вимикає Telegram-потік", RW.pick_for_tg(db, NOW + 320) == [])
os.environ.pop("OFFICE2_RADAR_TG")

# --- 4. paper-супровід за свічками після появи картки
def cds(bars, t0):
    return [{"ts": t0 + 900 * i, "high": h, "low": l} for i, (h, l) in enumerate(bars)]


card = dict(zip(RW._COLS, OB._fetchall(db, "SELECT " + ",".join(RW._COLS) + " FROM office2_radar_card WHERE card_id = 'W|O2|a1'")[0]))
t0 = card["sent_ts"]
tb = (t0 // 900 + 1) * 900          # перший бар, що почався після появи картки
pre = cds([(100.5, 99.9)], tb - 900)                                 # свічка ДО появи картки (торкається входу) не рахується
ev = RW.evaluate_card(card, pre + cds([(101.0, 100.6), (101.1, 100.7)], tb + 900), tb + 3 * 900)
check("свічка до картки і бар її появи не дають входу; ціна не дійшла до входу → чекаємо", ev["paper_status"] == "WAITING_ENTRY" and ev["entry_ts"] is None, str(ev))
ev = RW.evaluate_card(card, cds([(101.0, 100.6), (100.5, 100.1), (101.5, 100.3)], tb), tb + 4 * 900)
check("вхід лімітом, потім TP1 → результат моделі A додатний, уже з витратами", ev["paper_status"] in ("ENTERED", "TP1") and "TP1" in (ev["reached"] or "") and ev["r_net"] is not None and ev["r_net"] > 0, str(ev))
ev = RW.evaluate_card(card, cds([(100.5, 100.1), (100.3, 98.9)], tb + 900), tb + 4 * 900)
check("вхід, далі SL першим → SL, від'ємний результат", ev["paper_status"] == "SL" and ev["r_net"] < -1.0, str(ev))
ev = RW.evaluate_card(card, cds([(100.5, 100.1), (102.0, 98.9)], tb + 900), tb + 4 * 900)
check("свічка зі стопом і ціллю разом → SL (консервативно)", ev["paper_status"] == "SL" and ev["r_net"] < -1.0, str(ev))
ev = RW.evaluate_card(card, cds([(101.0, 100.6)] * 20, tb + 900), card["expires_ts"] + 5 * 900)
check("вхід так і не відбувся до кінця строку → NO_ENTRY", ev["paper_status"] == "NO_ENTRY", str(ev))

# --- 5. track + follow-up (віхи один раз)
state = {"bars": cds([(100.5, 100.1), (101.5, 100.3)], tb + 900)}
n = RW.track(db, lambda s, tf, k: state["bars"] if s == "AAAUSDT" else [], NOW + 5000)
fu = RW.pending_followups(db)
check("track пише paper-стан, follow-up містить вхід і TP1", n >= 1 and any(x["card_id"] == "W|O2|a1" and "TP1" in x["_new"] and "ENTERED" in x["_new"] for x in fu), str(fu)[:300])
c1 = [x for x in fu if x["card_id"] == "W|O2|a1"][0]
RW.mark_notified(db, c1["card_id"], c1["_new"], c1.get("notified"))
check("після повідомлення віхи не повторюються", not [x for x in RW.pending_followups(db) if x["card_id"] == "W|O2|a1"])
check("текст follow-up: навчальна угода, не ордер", "Навчальна угода, не ордер" in RW.followup_text(c1))

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


# --- 8. вимоги власниці 11.10 (Issue #199): навчальні сигнали після 3 стопів, deep link, зона входу, далекі цілі, дедуплікація
from office2 import radar_text as RT  # noqa: E402

db4 = new_db()
HEX = "687671d4c162"
put_scenario(db4, f"O2|{HEX}", "DOTUSDT", "SHORT", "NO_TRADE", "ємність сценаріїв: денний ліміт: 3 стопи за добу UTC",
             {"id": "d", "dir": "SHORT", "entry": 1.2337, "sl": 1.246, "risk_pct": 1.0, "targets": [{"p": 1.2, "kind": "PDL", "r": 3.0}, {"p": 1.15, "kind": "D1L", "r": 7.0}, {"p": 1.0075, "kind": "W1L", "r": 18.0}],
              "entry_zone": [1.2338, 1.2399], "level": {"p": 1.2434, "kind": "D1H"}})
RW.sync(db4, NOW + 10)
row = dict(zip(RW._COLS, OB._fetchall(db4, "SELECT " + ",".join(RW._COLS) + f" FROM office2_radar_card WHERE card_id = 'B|O2|{HEX}'")[0]))
check("після 3 стопів навчальна картка створюється й іде в Telegram (обмеження ризику її не гасить)", row["plan_ok"] == 1 and [x["card_id"] for x in RW.pick_for_tg(db4, NOW + 20)] == [f"B|O2|{HEX}"])
check("структурна перевірка: вхід (1.2337) лежить поза зоною 1.2338–1.2399 → зсунуто на межу зони з приміткою", row["entry"] == 1.2338 and "поза зоною" in (row["entry_note"] or ""), str(row))
far = json.loads(row["far_targets"] or "[]")
check("далекі цілі (≈+18 %, понад 8 %) не входять у paper-результат і позначені як далекі", row["tp3"] is None and far and far[0]["n"] == 3 and row["tp1"] == 1.2, str(row["far_targets"]))
tx = RW.format_card(row)
check("далека ціль і примітка про вхід збережені в деталях Mini App, а Telegram стислий", "далека" in str(RT.present(row)["targets"]) or any(not x["active"] for x in RT.present(row)["targets"]))
check("примітка про вхід у деталях, короткий текст має дві близькі цілі", "поза зоною" in str(RT.present(row)["entry_note"]) and "Цілі:" in tx and len(tx) <= 1024, tx)
check("1000PEPE пояснюється, тикер не перейменовується", RT.coin("1000PEPEUSDT") == "1000PEPE (контракт на 1000 токенів PEPE)" and RT.coin("DOTUSDT") == "DOT")
lid = RT.link_id(f"B|O2|{HEX}")
check("посилання без «|» і «%»; розпізнається нове, старе й подвійно закодоване", lid == f"B-{HEX}" and f"B|O2|{HEX}" in RT.parse_link_id(lid) and f"B|O2|{HEX}" in RT.parse_link_id(f"B%257CO2%257C{HEX}") and f"B|O2|{HEX}" in RT.parse_link_id(f"B%7CO2%7C{HEX}") and f"B|O2|{HEX}" in RT.parse_link_id(f"O2|{HEX}"))
for tok in (lid, f"B|O2|{HEX}", f"B%7CO2%7C{HEX}", f"B%257CO2%257C{HEX}", HEX):
    got = RW.summary(db4, NOW + 30, card_id=tok).get("card")
    check(f"картку знайдено за посиланням «{tok[:28]}»", bool(got) and got["card_id"] == f"B|O2|{HEX}" and got["h"]["title"].startswith("🎓"), str(got)[:120])
check("текст у посиланні картки Telegram — короткий ідентифікатор", f"card={lid}" in tx, tx)
put_scenario(db4, "O2|aaaaaaaaaaaa", "DOTUSDT", "SHORT", "NO_TRADE", "ємність сценаріїв: ємність сценаріїв Office2: 50$ > 40$", thesis_blocked() | {"dir": "SHORT"})
RW.sync(db4, NOW + 40)
check("дедуплікація: одна активна ідея на монету й напрям", OB._fetchall(db4, "SELECT COUNT(*) FROM office2_radar_card WHERE symbol='DOTUSDT' AND kind='BLOCKED'")[0][0] == 1)
put_scenario(db4, "O2|bbbbbbbbbbbb", "XRPUSDT", "SHORT", "NO_TRADE", "ємність сценаріїв: по цій монеті вже є живий сигнал Office2", thesis_blocked())
RW.sync(db4, NOW + 50)
check("«по монеті вже є живий сигнал» — не навчальна ідея (дубль справжнього)", not OB._fetchall(db4, "SELECT 1 FROM office2_radar_card WHERE symbol='XRPUSDT'"))
fl = RT.followup_text(dict(row, _new=["SL"], r_net=-1.12, paper_status="SL"))
check("follow-up простою мовою без жаргону", "стоп спрацював" in fl and "Навчальна угода, не ордер" in fl and not any(j in fl for j in ("SL", "paper", "PAPER", "R ")), fl)
sm4 = RW.summary(db4, NOW + 60)
check("summary: пояснення «чому немає дозволених входів» і навчальні картки з готовим текстом", "Навчальні сигнали" in sm4["why_no_ready"]["message"] and all("h" in x for x in sm4["cards"]) and "today" in sm4["stats"], str(sm4["why_no_ready"]))
pl = RW.plan_of({"dir": "LONG", "entry": 100.0, "sl": 99.0, "targets": [{"p": 99.5, "kind": "X", "r": 0.5}], "entry_zone": [99.9, 100.1]})
check("некоректна геометрія (ціль нижче входу для LONG) → план відхилено", pl["plan_ok"] == 0 and "геометрія" in pl["reject"], str(pl))
pl = RW.plan_of({"dir": "LONG", "entry": 100.0, "sl": 99.0, "targets": [{"p": 112.0, "kind": "X", "r": 12.0}], "entry_zone": [99.9, 100.1]})
check("перша ціль далі за 8 % → план відхилено з поясненням", pl["plan_ok"] == 0 and "8%" in pl["reject"], str(pl))

# --- 7. summary: порожній стан чесний, причина «чому немає READY» є
db3 = new_db()
sm = RW.summary(db3, NOW)
check("summary на порожній БД: ok, 0 карток, блок «чому немає READY»", sm["ok"] and sm["cards"] == [] and "why_no_ready" in sm, str(sm)[:300])
sm = RW.summary(db, NOW + 400)
check("summary: картки зі статусом, статистика WATCH/BLOCKED окремо", len(sm["cards"]) >= 4 and "watch" in sm["stats"] and "blocked" in sm["stats"] and all("status_ua" in x for x in sm["cards"]))

# --- 8. контрольний перерахунок стопів для карток без stops_json (створені до #207)
from office2 import stops as SVx
db8 = new_db()
put_scenario(db8, "O2|cccccccccccc", "DOTUSDT", "LONG", "WAIT", "WAIT 2/3 · зсув структури: sweep", thesis_wait())
RW.sync(db8, NOW + 5)
c0 = OB._fetchall(db8, "SELECT entry, sl, tp1, plan_ok, stops_json FROM office2_radar_card WHERE symbol='DOTUSDT'")[0]
check("картка створена без stops_json (старий формат)", c0[3] == 1 and c0[4] is None, str(c0))
th8 = thesis_wait(); th8["preview"]["stops"] = SVx.variants("LONG", 99.2, 0.2, 0.5, [], entry=100.2)
OB._execute(db8, "UPDATE office2_live_scenario SET thesis_json = ? WHERE scenario_id = ?", (json.dumps(th8), "O2|cccccccccccc"))
n8 = RW.backfill_stops(db8, NOW + 10)
c1 = OB._fetchall(db8, "SELECT entry, sl, tp1, stops_json FROM office2_radar_card WHERE symbol='DOTUSDT'")[0]
st8 = json.loads(c1[3] or "null") or {}
check("backfill: 3 варіанти записані, Стоп 1 = фактичний стоп картки, backfill-позначка є", n8 == 1 and abs(st8["v1"]["sl"] - c0[1]) < 1e-9 and "v2" in st8 and "v3" in st8 and "backfill" in st8, str(st8)[:200])
check("backfill не змінює план картки (вхід/SL/ціль)", c1[:3] == c0[:3])
check("backfill ідемпотентний", RW.backfill_stops(db8, NOW + 20) == 0)

# --- кнопка Telegram веде на конкретну картку (регресія: у #211 регулярний вираз не збігався з "/v2?tab=radar", кнопка лишалась загальною «Графік»)
import office_telegram_policy as TP
btn = TP.radar_card_button("Відкрити картку:\nhttps://ai-office-miniapp.onrender.com/v2?tab=radar&card=B-dbcd04afd7a2", "https://ai-office-miniapp.onrender.com")
check("кнопка Telegram містить посилання на конкретну картку", btn and btn["inline_keyboard"][0][0]["url"] == "https://ai-office-miniapp.onrender.com/v2?tab=radar&card=B-dbcd04afd7a2", str(btn))
check("без посилання на картку кнопка не підміняється", TP.radar_card_button("звичайний текст", "https://x") is None)

sdb = RW.summary(db, NOW + 400)
check("summary показує джерело даних (backend + відбиток) для звірки Mini App ↔ воркер", (sdb.get("db") or {}).get("backend") == "sqlite" and len((sdb["db"].get("fingerprint") or "")) == 16, str(sdb.get("db")))

sd = RW.summary(db, NOW + 400)["why_no_ready"].get("scanner") or {}
check("діагностика сканера: лічильники й причина відсутності нових карток", {"wait_total", "with_card", "without_card", "no_structure", "message"} <= set(sd) and isinstance(sd["message"], str) and sd["message"], str(sd))

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
