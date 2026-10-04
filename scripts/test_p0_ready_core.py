#!/usr/bin/env python3
"""P0: ідентичність ідеї/дедуп, заморожений READY, повідомлення = гейт, точний список мажорів, події TP/SL без manual-open,
дата в «Діє до», пошук сценарію за id (історія). Прод-кейси — лише фікстури; ті самі перевірки на довільних символах. Офлайн."""
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "p0.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_desk_card as DC  # noqa: E402
import office_ready_core as RC  # noqa: E402
import office_signal_track as T  # noqa: E402
import office_user_messages as M  # noqa: E402
from office_bridge import init_office_db, signal_refresh_scenario, signal_update, signal_upsert, _fetchall  # noqa: E402

init_office_db(db)
NOW = time.time()

# 4) мажори — точний список
for s in ("BTCUSDT", "ETHUSDT", "XAUUSDT", "PAXGUSDT", "BTC/USDT", "ETHUSDC"):
    assert DC.is_major_symbol(s), s
for s in ("ETHFIUSDT", "BTCDOMUSDT", "ETHWUSDT", "XAUTUSDT", "SOLUSDT", "SUIUSDT", "ZROUSDT", "BTCSTUSDT", "XXXUSDT"):
    assert not DC.is_major_symbol(s), s
assert DC.min_tp1_pct("ETHFIUSDT") == DC.ALTS_TP1_PCT and DC.min_tp1_pct("ETHUSDT") == DC.MAJORS_TP1_PCT

# 3) повідомлення = гейт: тільки записаний TP2; TP3 лише разом із TP2; ніколи TP1+TP3 без TP2
assert RC.message_targets(direction="LONG", entry=100, tp1=104, tp2=None, tp3_structural=110) == (None, None)
assert RC.message_targets(direction="LONG", entry=100, tp1=104, tp2=107, tp3_structural=110) == (107.0, 110.0)
assert RC.message_targets(direction="LONG", entry=100, tp1=104, tp2=107, tp3_structural=105) == (107.0, None)
assert RC.message_targets(direction="SHORT", entry=100, tp1=96, tp2=93, tp3_structural=90) == (93.0, 90.0)
assert RC.message_targets(direction="SHORT", entry=100, tp1=96, tp2=98, tp3_structural=90) == (None, None)   # TP2 «ближче» за TP1 — не показуємо
txt = M.ready_signal(symbol="AAAUSDT", direction="LONG", entry=100, sl=98, tp1=104, tp2=None, tp3=None, valid_until=RC.kyiv_stamp(NOW + 86400))
assert "TP2" not in txt and "TP3" not in txt
snap = RC.gate_snapshot(direction="LONG", entry=100, sl=98, tp1=104, tp2=107, tp3=110, max_entry=101, min_tp1_pct=3.0)
assert snap["shown_tps"] == [104.0, 107.0, 110.0] and snap["rr_weighted"] and snap["risk_pct"] == 2.0 and snap["rr_rule"]

# 6) «Діє до» із датою
import re  # noqa: E402
assert re.fullmatch(r"\d\d\.\d\d \d\d:\d\d", RC.kyiv_stamp(NOW + 86400)), RC.kyiv_stamp(NOW)
assert RC.is_expired(NOW - 1, NOW) and not RC.is_expired(NOW + 60, NOW) and not RC.is_expired(None, NOW)


def plan(sid, sym, d, e, sl, t1, t2=None, ts=NOW, msg=1, rejected=False, valid=None):
    T.record_plan(db, scenario_id=sid, symbol=sym, direction=d, tf="H1", entry=e, sl=sl, tp1=t1, tp2=t2, confirmed_ts=ts,
                  valid_until_ts=valid or ts + 86400, rejected=rejected, confirm_msg_id=msg)


# 1) дедуп: один незавершений READY на ідею; різні scenario_id/basis ідею не змінюють — для довільних символів
rnd = random.Random(7)
for k in range(40):
    sym = "".join(rnd.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(rnd.randint(2, 6))) + "USDT"
    p0 = rnd.choice([0.0123, 1.7, 48.0, 3100.0])
    long_ = rnd.random() < 0.5
    d = "LONG" if long_ else "SHORT"
    sg = 1 if long_ else -1
    e, sl, t1, t2 = p0, p0 * (1 - sg * 0.02), p0 * (1 + sg * 0.04), p0 * (1 + sg * 0.07)
    plan(f"SCN|{sym}|{d}|H1|a{k}", sym, d, e, sl, t1, t2)
    # той самий інструмент+напрямок, вхід у діапазоні, інший scenario_id → дубль
    dup = RC.find_duplicate(db, symbol=sym, direction=d, entry=p0 * (1 + sg * 0.005), scenario_id=f"SCN|{sym}|{d}|H1|b{k}")
    assert dup and dup["scenario_id"].endswith(f"a{k}"), (sym, dup)
    # протилежний напрямок / інший символ / вхід далеко за ціллю — НЕ дубль (нова ідея)
    assert not RC.find_duplicate(db, symbol=sym, direction="SHORT" if long_ else "LONG", entry=e)
    assert not RC.find_duplicate(db, symbol="Q" + sym, direction=d, entry=e)
    assert not RC.find_duplicate(db, symbol=sym, direction=d, entry=p0 * (1 + sg * 0.20))
    assert not RC.find_duplicate(db, symbol=sym, direction=d, entry=p0 * (1 - sg * 0.10))
    # той самий scenario_id → дубль навіть поза діапазоном
    assert RC.find_duplicate(db, symbol=sym, direction=d, entry=p0 * 3, scenario_id=f"SCN|{sym}|{d}|H1|a{k}")

# завершена ідея не блокує нову (без «охолодження після стопа»): SIGNAL_RESULT → нова ідея того ж символу проходить
sym = "ZZZUSDT"
plan("SCN|ZZZ|LONG|H1|x", sym, "LONG", 10.0, 9.8, 10.4, 10.7)
assert RC.find_duplicate(db, symbol=sym, direction="LONG", entry=10.05)
from office_bridge import log_event  # noqa: E402
ev = [e for e in T._events(db, T.EV_PLAN) if e["p"]["scenario_id"] == "SCN|ZZZ|LONG|H1|x"][0]["p"]
log_event(db, T.EV_RESULT, {"scenario_id": ev["scenario_id"], "confirmed_ts": ev["confirmed_ts"], "outcome": "STOP"}, ev["scenario_id"])
assert not RC.find_duplicate(db, symbol=sym, direction="LONG", entry=10.05)
# відхилений план і недоставлений не рахуються
plan("SCN|RJ|LONG|H1|r", "RJUSDT", "LONG", 5.0, 4.9, 5.2, 5.3, rejected=True)
assert not RC.find_duplicate(db, symbol="RJUSDT", direction="LONG", entry=5.0)
# давній план без підсумку (минуло вікно + запобіжник) вважається завершеним
plan("SCN|OLD|LONG|H1|o", "OLDUSDT", "LONG", 5.0, 4.9, 5.2, 5.3, ts=NOW - 10 * 86400)
assert not RC.find_duplicate(db, symbol="OLDUSDT", direction="LONG", entry=5.0)

# 2) заморожений READY: наступний скан не перезаписує вхід/стоп/цілі й не скидає статус
signal_upsert(db, signal_id="SCN|F|LONG|H1|1", symbol="FUSDT", direction="LONG", entry_low=1.0, entry_high=1.1, sl=0.9, tp1=1.3, tp2=1.5, rr=2.0,
              status="WATCHING", analysis_note="a")
signal_update(db, signal_id="SCN|F|LONG|H1|1", status="CONFIRMED")
signal_upsert(db, signal_id="SCN|F|LONG|H1|1", symbol="FUSDT", direction="LONG", entry_low=2.0, entry_high=2.1, sl=1.9, tp1=2.3, tp2=None, rr=None,
              status="WATCHING", analysis_note="b")
signal_refresh_scenario(db, signal_id="SCN|F|LONG|H1|1", entry_low=3.0, entry_high=3.1)
r = _fetchall(db, "SELECT entry_low, sl, tp1, tp2, status FROM office_signals WHERE signal_id = ?", ("SCN|F|LONG|H1|1",))[0]
assert tuple(r) == (1.0, 0.9, 1.3, 1.5, "CONFIRMED"), r
signal_upsert(db, signal_id="SCN|G|LONG|H1|1", symbol="GUSDT", direction="LONG", entry_low=1.0, entry_high=1.1, sl=0.9, tp1=1.3, tp2=None, rr=None,
              status="WATCHING", analysis_note="a")
signal_upsert(db, signal_id="SCN|G|LONG|H1|1", symbol="GUSDT", direction="LONG", entry_low=2.0, entry_high=2.1, sl=1.9, tp1=2.3, tp2=None, rr=None,
              status="WATCHING", analysis_note="b")
assert _fetchall(db, "SELECT entry_low FROM office_signals WHERE signal_id = ?", ("SCN|G|LONG|H1|1",))[0][0] == 2.0   # до READY — звичайне оновлення

# 5) події TP/SL без manual-open: свічки M15, по одному разу, SL після TP1 теж
db2 = str(Path(tempfile.mkdtemp()) / "m.db")
os.environ["OFFICE_DB_PATH"] = db2
init_office_db(db2)
T0 = NOW - 6 * 3600
T.record_plan(db2, scenario_id="SCN|MS|LONG|H1|1", symbol="MSUSDT", direction="LONG", tf="H1", entry=100, sl=98, tp1=104, tp2=107, tp3=110,
              confirmed_ts=T0, valid_until_ts=T0 + 86400, confirm_msg_id=555)
# історичний план (до запуску відстеження) — без подій
T.record_plan(db2, scenario_id="SCN|HIST|LONG|H1|1", symbol="HISTUSDT", direction="LONG", entry=100, sl=98, tp1=104, tf="H1",
              confirmed_ts=NOW - 5 * 3600, valid_until_ts=NOW + 3600, confirm_msg_id=1)
since = T.milestone_since(db2)
assert since > NOW - 5
T.record_plan(db2, scenario_id="SCN|MS|LONG|H1|1b", symbol="MSUSDT", direction="LONG", tf="H1", entry=100, sl=98, tp1=104, tp2=107, tp3=110,
              confirmed_ts=since + 1, valid_until_ts=since + 86400, confirm_msg_id=556)
T.record_plan(db2, scenario_id="SCN|GR|LONG|H1|1", symbol="GRUSDT", direction="LONG", tf="H1", entry=100, sl=98, tp1=104, confirmed_ts=since - 300,
              valid_until_ts=since + 86400, confirm_msg_id=557)   # доставка затрималась: підтверджено за 5 хв до запуску відстеження — теж відстежуємо
c0 = since + 1


def cd(i, lo, hi):
    return {"ts": c0 + 900 * i, "open": (lo + hi) / 2, "high": hi, "low": lo, "close": (lo + hi) / 2}


candles = [cd(1, 99.5, 100.5), cd(2, 100, 104.5), cd(3, 101, 108), cd(4, 97, 103)]   # вхід, TP1, TP2, потім стоп
fetch = lambda s, tf, n: candles  # noqa: E731
got = T.pending_milestones(db2, fetch, now_ts=c0 + 900 * 6)
lv = [(m["symbol"], m["level"], m["confirm_msg_id"]) for m in got if m["symbol"] == "MSUSDT"]
assert lv == [("MSUSDT", "ENTRY", 556), ("MSUSDT", "TP1", 556), ("MSUSDT", "TP2", 556), ("MSUSDT", "SL", 556)], lv
assert [m["silent"] for m in got if m["symbol"] == "MSUSDT"] == [True, False, False, False]   # ENTRY лише в БД
assert not [m for m in got if m["symbol"] == "HISTUSDT"] and {m["symbol"] for m in got} <= {"MSUSDT", "GRUSDT"}
for m in got:
    T.record_milestone(db2, m, 1)
assert T.pending_milestones(db2, fetch, now_ts=c0 + 900 * 6) == []   # вдруге нічого
msg = M.scenario_event(symbol="MSUSDT", direction="LONG", level="SL", price=98)
assert "СТОП" in msg and "Сценарій не спрацював" in msg and "закрит" not in msg.lower() and "MS" in msg
assert "ЦІЛЬ 1" in M.scenario_event(symbol="MSUSDT", direction="LONG", level="TP1", price=104)
import office_alert_gate as G  # noqa: E402
from office_telegram_policy import outbound_allowed  # noqa: E402
assert G.gate_outbound_telegram(intent="SCENARIO_EVENT", text=msg, event_type="TRADE_UPDATE", db_path=db2, symbol="MSUSDT", direction="LONG")["send"]
os.environ["OFFICE_TG_STRICT"] = "1"
assert outbound_allowed(event_type="TRADE_UPDATE", kind="SCENARIO_EVENT", intent="SCENARIO_EVENT")
# стоп без TP: тільки SL
db3 = str(Path(tempfile.mkdtemp()) / "s.db")
os.environ["OFFICE_DB_PATH"] = db3
init_office_db(db3)
s3 = T.milestone_since(db3)
T.record_plan(db3, scenario_id="SCN|SS|SHORT|H1|1", symbol="SSUSDT", direction="SHORT", tf="H1", entry=50, sl=51, tp1=48, tp2=47, confirmed_ts=s3 + 1,
              valid_until_ts=s3 + 86400, confirm_msg_id=9)
cs = [{"ts": s3 + 1 + 900 * i, "open": 50, "high": h, "low": l, "close": 50} for i, (h, l) in enumerate([(50.2, 49.8), (50.5, 49.9), (51.5, 50)], start=1)]
g3 = T.pending_milestones(db3, lambda *a: cs, now_ts=s3 + 1 + 900 * 6)
assert [m["level"] for m in g3] == ["ENTRY", "SL"], g3

# deep-link: сценарій знаходиться за id і коли він за межею «останніх 200»
db4 = str(Path(tempfile.mkdtemp()) / "d.db")
os.environ["OFFICE_DB_PATH"] = db4
init_office_db(db4)
import office_mini_v2 as MV  # noqa: E402
signal_upsert(db4, signal_id="SCN|OLDDL|LONG|H1|abc", symbol="OLDDLUSDT", direction="LONG", entry_low=1.0, entry_high=1.1, sl=0.9, tp1=1.3, tp2=None, rr=None,
              status="CONFIRMED", analysis_note="scenario_id=SCN|OLDDL|LONG|H1|abc origin=desk tf=H1")
for i in range(260):
    signal_upsert(db4, signal_id=f"lev-watch-X{i}USDT-{i}", symbol=f"X{i}USDT", direction="LONG", entry_low=1, entry_high=1.1, sl=0.9, tp1=1.3, tp2=None,
                  rr=None, status="WATCHING", analysis_note="w")
row = MV._signal_row_by_id("SCN|OLDDL|LONG|H1|abc")
assert row and row["symbol"] == "OLDDLUSDT" and row["status"] == "CONFIRMED"
assert MV._signal_row_by_id("SCN|NOPE") is None
print("test_p0_ready_core: OK")
