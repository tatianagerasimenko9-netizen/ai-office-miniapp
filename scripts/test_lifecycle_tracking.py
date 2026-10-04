#!/usr/bin/env python3
"""Життя КОЖНОГО виданого READY (контур A, без кнопки «Я відкрила угоду»): ENTRY → TP1/TP2/TP3 | SL | EXPIRED за свічками 1m/5m.
LONG/SHORT, intrabar, SL до входу ≠ SL угоди, expiry, рестарт, захист від дублів, вибір таймфрейму. Офлайн, без Telegram."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "l.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_signal_track as T  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
SINCE = T.milestone_since(db)
BASE = SINCE + 100     # момент READY (після старту відстеження)


def plan(sid, sym, side, entry, sl, tps, ts=BASE, valid=None, msg=1):
    t1, t2, t3 = (list(tps) + [None, None, None])[:3]
    T.record_plan(db, scenario_id=sid, symbol=sym, direction=side, tf="H1", entry=entry, sl=sl, tp1=t1, tp2=t2, tp3=t3, confirmed_ts=ts,
                  valid_until_ts=valid or ts + 86400, confirm_msg_id=msg)


def c1(t0, specs, step=60):
    return [{"ts": t0 + i * step, "open": o, "high": h, "low": l, "close": c, "volume": 1} for i, (o, h, l, c) in enumerate(specs)]


def run(candles, now, tf_seen=None):
    def fetch(sym, tf, lim):
        if tf_seen is not None:
            tf_seen.append((sym, tf, lim))
        return candles.get(sym, [])
    return T.pending_milestones(db, fetch, now_ts=now)


def levels(ms, sym):
    return [m["level"] for m in ms if m["symbol"] == sym]


T0 = BASE   # свічки 1m починаються рівно з моменту READY (кандидат на «свічку підтвердження» відсіяний: відкрита до T → ігнор)
# 1) VVV-подібний SHORT: вхід у першу хвилину, далі проколює SL усередині свічки (intrabar), закриття нижче → SL; затримка ≤ 1 хв
plan("SCN|V|SHORT|H1|1", "VVVUSDT", "SHORT", 27.984, 28.351, [27.134, 26.511])
cv = c1(T0, [(27.98, 27.99, 27.97, 27.98), (27.98, 28.44, 27.98, 28.20), (28.2, 28.3, 28.1, 28.2)])
ms = run({"VVVUSDT": cv}, T0 + 3 * 60 + 1)
assert levels(ms, "VVVUSDT") == ["ENTRY", "SL"], ms     # SL зафіксовано на 3-й хвилині, не через 15 хв
assert [m["silent"] for m in ms if m["symbol"] == "VVVUSDT"] == [True, False]
# ще не закрита свічка не зараховується (усередині 2-ї хвилини SL ще не видно)
assert levels(run({"VVVUSDT": cv}, T0 + 90), "VVVUSDT") == ["ENTRY"], "незакрита свічка SL не дає"

# 2) LONG: вхід → TP1 → TP2 (wick без закриття теж торкання)
plan("SCN|L|LONG|H1|1", "LLLUSDT", "LONG", 100.0, 98.0, [104.0, 107.0])
cl = c1(T0, [(100, 100.4, 99.6, 100), (100, 104.2, 100, 101), (101, 107.5, 100.5, 102)])
assert levels(run({"LLLUSDT": cl}, T0 + 10 * 60), "LLLUSDT") == ["ENTRY", "TP1", "TP2"]

# 3) SL ДО входу — не SL угоди: гэп вниз повз вхід (LONG), вхід так і не торкнуто → ні ENTRY, ні SL
plan("SCN|G|LONG|H1|1", "GAPUSDT", "LONG", 100.0, 98.0, [104.0])
cg = c1(T0, [(97.5, 97.9, 97.0, 97.2), (97.2, 97.9, 96.5, 97.0)])
assert levels(run({"GAPUSDT": cg}, T0 + 5 * 60), "GAPUSDT") == []
# SHORT: ціна пішла вниз і ніколи не торкнулась входу — очікування, подій немає
plan("SCN|W|SHORT|H1|1", "WAITUSDT", "SHORT", 50.0, 51.0, [48.0])
cw = c1(T0, [(49.5, 49.8, 49.2, 49.4)] * 5)
assert levels(run({"WAITUSDT": cw}, T0 + 6 * 60), "WAITUSDT") == []

# 4) вхід + стоп в одній свічці → консервативно SL (після ENTRY)
plan("SCN|S|LONG|H1|1", "SAMEUSDT", "LONG", 100.0, 98.0, [104.0])
cs = c1(T0, [(100, 105, 97, 99)])
assert levels(run({"SAMEUSDT": cs}, T0 + 2 * 60), "SAMEUSDT") == ["ENTRY", "SL"]

# 5) pre-READY wick у свічці, що відкрилась ДО T, ігнорується (інакше хибний ENTRY/SL)
plan("SCN|P|SHORT|H1|1", "PREUSDT", "SHORT", 10.0, 10.3, [9.5])
cp = c1(T0 - 60, [(10.0, 10.5, 9.9, 10.0)]) + c1(T0, [(9.8, 9.9, 9.7, 9.8)] * 3)
assert levels(run({"PREUSDT": cp}, T0 + 5 * 60), "PREUSDT") == [], "свічка до моменту READY не рахується"

# 6) EXPIRED: вхід не торкнуто до кінця строку → один тихий запис
plan("SCN|E|LONG|H1|1", "EXPUSDT", "LONG", 100.0, 98.0, [104.0], valid=T0 + 600)
ce = c1(T0, [(105, 106, 104.5, 105)] * 20)
mx = run({"EXPUSDT": ce}, T0 + 20 * 60 + 1)
assert levels(mx, "EXPUSDT") == ["EXPIRED"] and mx[-1]["silent"], mx

# 7) рестарт воркера: пам'ять процесу стерта, але записані події не дублюються; нові — з'являються
all_ms = run({"VVVUSDT": cv, "LLLUSDT": cl, "SAMEUSDT": cs, "EXPUSDT": ce}, T0 + 20 * 60 + 1)
for m in all_ms:
    T.record_milestone(db, m, 77)
T._MS_DONE.clear()
T._MS_LAST.clear()
assert run({"VVVUSDT": cv, "LLLUSDT": cl, "SAMEUSDT": cs, "EXPUSDT": ce}, T0 + 20 * 60 + 1) == [], "після рестарту повторів немає"
# 8) захист від дублів: повторний виклик без запису нічого нового не додає понад ті самі рівні, а запис фіксує один раз
seen = [(m["scenario_id"], m["level"]) for m in all_ms]
assert len(seen) == len(set(seen))

# 9) вибір таймфрейму: свіжий план — 1m×1500; старший за FRESH_SEC — 5m×1000 і не частіше за OLD_RECHECK_SEC
plan("SCN|N|LONG|H1|1", "NEWUSDT", "LONG", 100.0, 98.0, [104.0], ts=BASE + 5)
tfs = []
run({}, BASE + 120, tfs)
assert ("NEWUSDT", "1m", 1500) in tfs, tfs
T._MS_LAST.clear()
old_fresh = T.FRESH_SEC
T.FRESH_SEC = 60.0
tfs2 = []
run({}, BASE + 3600, tfs2)
assert ("NEWUSDT", "5m", 1000) in tfs2 and ("NEWUSDT", "1m", 1500) not in tfs2, tfs2
tfs3 = []
run({}, BASE + 3600 + 30, tfs3)
assert ("NEWUSDT", "5m", 1000) not in tfs3, "старі плани не частіше за інтервал"
T.FRESH_SEC = old_fresh
print("test_lifecycle_tracking: OK")
