#!/usr/bin/env python3
"""Облік стабільності свічок і авто-вмикання стакана: лише 24 повні години поспіль (ф'ючерсні ≥95%, без 429); перезапуск обриває серію."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_data_stability as S  # noqa: E402
import office_market_data as omd  # noqa: E402
from office_bridge import init_office_db, log_event  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


db = os.path.join(tempfile.mkdtemp(), "t.db")
init_office_db(db)
S.reset_for_tests()
S.set_db(db)
H0 = 1_800_000            # довільна «година»
S._STATE["proc_start"] = H0 * 3600 - 10      # процес працює з початку першої години
c = {"futures": 0, "total": 0, "rate_limited": 0}


def step(hour, fut, tot, rl=0):
    c["futures"] += fut
    c["total"] += tot
    c["rate_limited"] += rl
    return S.tick(now=hour * 3600 + 5, db=db, counters=dict(c))


check("перший виклик лише запам'ятовує годину", step(H0, 0, 0) is None)
r = step(H0 + 1, 200, 200)
check("межа години: записано попередню повну годину, частка 100%", r and r["hour"] == H0 and r["share"] == 1.0 and r["rate_limited"] == 0, str(r))
check("година з часткою ≥95% і без 429 — стабільна", S.hour_ok(r))
r2 = step(H0 + 2, 190, 200)
check("частка 95% рівно — ще стабільна", r2 and S.hour_ok(r2), str(r2))
r3 = step(H0 + 3, 150, 200)
check("частка 75% — нестабільна", r3 and not S.hour_ok(r3), str(r3))
r4 = step(H0 + 4, 200, 200, rl=1)
check("один 429 за годину — нестабільна", r4 and not S.hour_ok(r4) and r4["rate_limited"] == 1, str(r4))
r5 = step(H0 + 5, 0, 3)
check("година майже без читань свічок нічого не доводить", r5 and not S.hour_ok(r5), str(r5))

# перезапуск посеред години: неповна година не записується
S.reset_for_tests()
S.set_db(db)
S._STATE["proc_start"] = (H0 + 10) * 3600 + 1800      # старт на 30-й хвилині години H0+10
c.update(futures=0, total=0, rate_limited=0)
S.tick(now=(H0 + 10) * 3600 + 1900, db=db, counters=dict(c))
partial = S.tick(now=(H0 + 11) * 3600 + 5, db=db, counters={"futures": 100, "total": 100, "rate_limited": 0})
check("година, у яку процес стартував, НЕ записується (неповна)", partial is None)

# серія 24 години → стабільно; на 23 — ні
db2 = os.path.join(tempfile.mkdtemp(), "s.db")
init_office_db(db2)
base = 1_900_000
for h in range(base, base + 23):
    log_event(db2, "DATA_STABILITY", {"hour": h, "futures": 300, "total": 300, "share": 1.0, "rate_limited": 0})
now = (base + 23) * 3600 + 120
st = S.status(db2, now=now)
check("23 години поспіль — ще не стабільно", st["stable"] is False and st["streak_hours"] == 23, str(st))
log_event(db2, "DATA_STABILITY", {"hour": base + 23, "futures": 300, "total": 300, "share": 1.0, "rate_limited": 0})
now = (base + 24) * 3600 + 120
st = S.status(db2, now=now)
check("24 години поспіль — стабільно", st["stable"] is True and st["streak_hours"] == 24, str(st))
check("розрив у серії (пропущена година) обриває рахунок", S.status(db2, now=(base + 40) * 3600)["streak_hours"] == 0)
log_event(db2, "DATA_STABILITY", {"hour": base + 24, "futures": 100, "total": 300, "share": 0.33, "rate_limited": 0})
now = (base + 25) * 3600 + 120
check("свіжа погана година — серія 0", S.status(db2, now=now)["streak_hours"] == 0)

# стакан: режими
os.environ.pop("OFFICE_DEPTH_ENABLED", None)
check("за замовчуванням вимкнено", omd.depth_mode() == "off" and omd.depth_enabled() is False)
os.environ["OFFICE_DEPTH_ENABLED"] = "1"
check("1 — примусово увімкнено", omd.depth_enabled() is True)
os.environ["OFFICE_DEPTH_ENABLED"] = "auto"
S.reset_for_tests()
S.set_db(db2)
check("auto: серії 24 год нема → стакан вимкнений", omd.depth_enabled() is False and omd.depth_mode() == "auto")
db3 = os.path.join(tempfile.mkdtemp(), "a.db")
init_office_db(db3)
cur = int(time.time() // 3600)
for h in range(cur - 24, cur):
    log_event(db3, "DATA_STABILITY", {"hour": h, "futures": 400, "total": 400, "share": 1.0, "rate_limited": 0})
S.reset_for_tests()
S.set_db(db3)
check("auto: 24 години стабільно → стакан вмикається сам", omd.depth_enabled() is True, str(S.status(db3)))
check("depth_stats показує режим", omd.depth_stats()["mode"] == "auto")
os.environ["OFFICE_DEPTH_ENABLED"] = "0"
check("0 — вимкнено, навіть за стабільних даних", omd.depth_enabled() is False)

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
