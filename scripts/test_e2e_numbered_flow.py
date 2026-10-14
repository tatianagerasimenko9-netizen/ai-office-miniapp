#!/usr/bin/env python3
"""Наскрізно (контрольовані свічки, без мережі/Telegram): нумерований Office2 READY → ENTRY (тихо) → TP1/TP2/SL у Telegram відповіддю на початкове повідомлення;
ненумерований/legacy — лише БД; збій доставки → повтор без втрати; рестарт → без дублів; збій читання номера → повтор."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "e.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_ready_seq as RS  # noqa: E402
import office_signal_track as T  # noqa: E402
from office2.milestone_policy import dispatch  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
BASE = int(T.milestone_since(db)) + 100


def plan(sid, sym, side, entry, sl, tps, msg):
    t1, t2, t3 = (list(tps) + [None, None, None])[:3]
    T.record_plan(db, scenario_id=sid, symbol=sym, direction=side, tf="H1", entry=entry, sl=sl, tp1=t1, tp2=t2, tp3=t3, confirmed_ts=BASE, valid_until_ts=BASE + 86400, confirm_msg_id=msg)


def c1(specs, t0=BASE):
    return [{"ts": t0 + i * 60, "open": o, "high": h, "low": l, "close": c, "volume": 1} for i, (o, h, l, c) in enumerate(specs)]


ok = True


def check(name, cond, info=""):
    global ok
    print(("OK   " if cond else "FAIL ") + name, "" if cond else info)
    ok &= bool(cond)


# LONG: вхід 100, SL 95, TP1 105, TP2 110. 3 хв: вхід; далі TP1; далі TP2.
plan("O2|num1|1", "AAAUSDT", "LONG", 100, 95, [105, 110, 115], 5001)
plan("O2|old1|1", "BBBUSDT", "LONG", 100, 95, [105, 110, 115], 5002)       # без номера (beta до нумерації)
plan("O2|sl1|1", "CCCUSDT", "SHORT", 100, 105, [95, 90, 85], 5003)
RS.assign(db, "O2|num1|1")
RS.assign(db, "O2|sl1|1")
check("номери присвоєно окремо", RS.number_of(db, "O2|num1|1") == 1 and RS.number_of(db, "O2|sl1|1") == 2 and RS.number_of(db, "O2|old1|1") is None)

candles = {
    "AAAUSDT": c1([(100, 100.5, 99.8, 100.2), (100.2, 101, 100, 100.8), (101, 105.5, 100.9, 105), (105, 110.5, 104.9, 110)]),
    "BBBUSDT": c1([(100, 100.5, 99.8, 100.2), (100.2, 101, 100, 100.8), (101, 105.5, 100.9, 105)]),
    "CCCUSDT": c1([(100, 100.5, 99.8, 100.2), (100.2, 105.5, 100, 105.2)]),
}
fetch = lambda sym, tf, lim: candles.get(sym, [])  # noqa: E731
NOW = BASE + 600


class Tg:
    def __init__(self, fail_first=False):
        self.calls, self.fail_first, self.n = [], fail_first, 0

    async def send(self, m, no):
        self.calls.append((m["symbol"], m["level"], no, m.get("confirm_msg_id")))
        if self.fail_first and len(self.calls) == 1:
            return None
        self.n += 1
        return 9000 + self.n


async def number_of(sid):
    return RS.number_of(db, sid)


async def record(m, mid):
    T.record_milestone(db, m, mid)


def cycle(tg, number=number_of):
    ms = T.pending_milestones(db, fetch, now_ts=NOW, scope="o2", use_mirror=False)
    return ms, asyncio.run(dispatch(ms, "o2", number, tg.send, record, False, lambda s: None))


# 1) перший цикл, перша відправка падає (Telegram недоступний): подія НЕ записується, буде повтор
tg = Tg(fail_first=True)
ms, r = cycle(tg)
check("є події ENTRY/TP/SL по трьох планах", {m["level"] for m in ms} >= {"ENTRY", "TP1", "TP2", "SL"}, [m["level"] for m in ms])
check("збій доставки: undelivered=1, нічого не втрачено", r["undelivered"] == 1, r)
# 2) повторний цикл: недоставлена подія повертається, решта не дублюється
tg2 = Tg()
ms2, r2 = cycle(tg2)
sent_levels = [(s, l) for s, l, _, _ in tg.calls + tg2.calls]
check("кожен рівень нумерованих планів надіслано рівно один раз (з урахуванням повтору)", len({(s, l) for s, l in sent_levels if s in ("AAAUSDT", "CCCUSDT") and l != "ENTRY"}) == 3 and len(sent_levels) - len(set(sent_levels)) == 1 and
      sum(1 for s, l, _, _ in tg2.calls) >= 1, (tg.calls, tg2.calls))
check("відповідь на початкове повідомлення (reply_to=confirm_msg_id)", all(c[3] == {"AAAUSDT": 5001, "CCCUSDT": 5003}[c[0]] for c in tg.calls + tg2.calls if c[0] in ("AAAUSDT", "CCCUSDT")))
check("legacy/ненумерований BBB: у Telegram нічого", all(s != "BBBUSDT" for s, _, _, _ in tg.calls + tg2.calls))
check("ENTRY нумерованого плану йде відповіддю (OFFICE_TG_ENTRY_REPLY=1 за замовчуванням), EXPIRED — тихий", any(l == "ENTRY" for s_, l, _, _ in tg.calls + tg2.calls if s_ == "AAAUSDT") and all(l != "EXPIRED" for _, l, _, _ in tg.calls + tg2.calls))
check("в Telegram передано № READY", {c[2] for c in tg.calls + tg2.calls if c[0] == "AAAUSDT"} == {1} and {c[2] for c in tg.calls + tg2.calls if c[0] == "CCCUSDT"} == {2})
# 3) «рестарт»: новий цикл, нічого нового → нічого не надсилається
tg3 = Tg()
ms3, r3 = cycle(tg3)
check("після рестарту дублів немає", not tg3.calls and ms3 == [], (ms3, tg3.calls))
# 4) збій читання номера: подія не губиться
plan("O2|num2|1", "DDDUSDT", "LONG", 100, 95, [105, 110, 115], 5004)
RS.assign(db, "O2|num2|1")
candles["DDDUSDT"] = c1([(100, 100.5, 99.8, 100.2), (100.2, 100.4, 94, 95)])


async def broken(_sid):
    raise RuntimeError("db busy")


tg4 = Tg()
ms4, r4 = cycle(tg4, broken)
check("збій номера: retry, нічого не надіслано й не записано як sent", r4["retry"] >= 1 and not [c for c in tg4.calls if c[0] == "DDDUSDT"], (r4, tg4.calls))
tg5 = Tg()
ms5, r5 = cycle(tg5)
check("наступний цикл доставляє SL нумерованого плану", any(c[0] == "DDDUSDT" and c[1] == "SL" and c[2] == 3 for c in tg5.calls), tg5.calls)
print("ALL OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
