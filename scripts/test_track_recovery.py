#!/usr/bin/env python3
"""P0 супровід: BTC №4-подібний SHORT (вхід 83663.5, SL 84163.7, TP1 83127), FIL №6/SEI №7-подібні LONG зі стопом.
1) Ціна наблизилась до TP1, але не торкнулась → TP1 НЕ фіксується (78% шляху ≠ подія).
2) Тінь торкнулась TP1 під час «простою» Worker → після рестарту (порожні кеші процесу) подія відновлюється з ФАКТИЧНИМ часом свічки, один раз.
3) Після запису віхи повтор не дублюється; 4) heartbeat: час перевірки, помилка fetch → «застарів», завершений сценарій не позначається застарілим."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_signal_track as T  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
BASE = T.milestone_since(db) + 100
bad = 0


def check(n, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + n + ("" if ok else f" :: {info}"))
    bad += 0 if ok else 1


def plan(sid, sym, side, entry, sl, tps, msg):
    T.record_plan(db, scenario_id=sid, symbol=sym, direction=side, tf="M15", entry=entry, sl=sl, tp1=tps[0], tp2=tps[1], tp3=tps[2], confirmed_ts=BASE, valid_until_ts=BASE + 21600, confirm_msg_id=msg)


def c5(specs, step=300):
    return [{"ts": BASE + i * step, "open": o, "high": h, "low": l, "close": c, "volume": 1, "src": "binance_futures"} for i, (o, h, l, c) in enumerate(specs)]


def fresh_process():
    T._MS_LAST.clear(); T._MS_DONE.clear()


plan("O2|btc4|1", "BTCUSDT", "SHORT", 83663.5, 84163.7, (83127.0, 80985.0, 80344.8), 10579)
NOW = BASE + 9 * 3600   # >6 год → 5m
flat = [(83650, 83700, 83300, 83400)] * 20 + [(83400, 83450, 83176, 83250)] + [(83250, 83400, 83200, 83300)] * 10
bars = c5([(83660, 83670, 83655, 83660)] + flat)
fetch = lambda sym, tf, lim: bars
fresh_process()
ms = T.pending_milestones(db, fetch, now_ts=NOW)
lv = [m["level"] for m in ms]
check("мінімум 83176 вище TP1 83127: TP1 не фіксується", "TP1" not in lv, lv)
check("ENTRY є", "ENTRY" in lv, lv)
for m in ms:
    T.record_milestone(db, m, msg_id=1)

# 2) тінь торкнулась TP1 о 06:00 (за «простою» Worker)
touch_i = 72
bars2 = list(bars) + [{"ts": BASE + (len(bars) + touch_i) * 300, "open": 83300, "high": 83320, "low": 83126.5, "close": 83200, "volume": 1, "src": "binance_futures"}]
fetch2 = lambda sym, tf, lim: bars2
fresh_process()      # рестарт Worker: кеші процесу порожні
ms2 = T.pending_milestones(db, fetch2, now_ts=NOW + 3600 * 3)
tp = [m for m in ms2 if m["level"] == "TP1"]
check("після рестарту TP1 відновлено", len(tp) == 1, ms2)
check("час події — фактична свічка, а не час відновлення", tp and abs(float(tp[0]["touched_ts"]) - bars2[-1]["ts"]) < 301, tp and tp[0].get("touched_ts"))
for m in ms2:
    T.record_milestone(db, m, msg_id=2)
fresh_process()
check("повторно подія не віддається", [m for m in T.pending_milestones(db, fetch2, now_ts=NOW + 3600 * 3) if m["level"] == "TP1"] == [])

# 3) FIL/SEI-подібні LONG: SL торкнуто → один SL, не дубль
plan("O2|fil6|1", "FILUSDT", "LONG", 1.1681, 1.1443, (1.2, 1.25, 1.3), 10582)
sl_bars = c5([(1.1681, 1.169, 1.166, 1.168), (1.168, 1.169, 1.144, 1.145), (1.145, 1.15, 1.14, 1.146)])
fetch3 = lambda sym, tf, lim: sl_bars if sym == "FILUSDT" else bars2
fresh_process()
m3 = [m for m in T.pending_milestones(db, fetch3, now_ts=BASE + 3000) if m["symbol"] == "FILUSDT"]
check("FIL: ENTRY і SL по одному разу", [m["level"] for m in m3].count("SL") == 1 and [m["level"] for m in m3].count("ENTRY") == 1, m3)

# 4) heartbeat
fresh_process()
T.pending_milestones(db, fetch2, now_ts=NOW + 3600 * 3 + 30)
hb = T.heartbeat_for(db, "O2|btc4|1", now=NOW + 3600 * 3 + 60, active=True)
check("heartbeat записано після перевірки", hb["known"] and not hb["stale"], hb)
check("давня перевірка → застарів", T.heartbeat_for(db, "O2|btc4|1", now=NOW + 3600 * 3 + 5000, active=True)["stale"])
check("завершений сценарій не позначається застарілим", not T.heartbeat_for(db, "O2|btc4|1", now=NOW + 99999, active=False)["stale"])
check("немає перевірок у активного → stale", T.heartbeat_for(db, "O2|none|1", active=True)["stale"])
def boom(sym, tf, lim): raise RuntimeError("429")
fresh_process()
T.pending_milestones(db, boom, now_ts=NOW + 3600 * 3 + 200)
hb2 = T.heartbeat_for(db, "O2|btc4|1", now=NOW + 3600 * 3 + 210, active=True)
check("помилка Binance → stale і лічильник помилок", hb2["stale"] and hb2["fails"] >= 1, hb2)
sys.exit(1 if bad else 0)
