"""Офлайн-тести DYNAMIC WATCH_ONLY: режими, ізоляція від LIVE, незмінність умовного READY, paper-наслідок на свічках."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)
import numpy as np

from office2 import dynamic_watch as DW

FAILS = []


def check(name, cond):
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def bars(rows):
    t = np.array([r[0] for r in rows], dtype=float)
    return {"t": t, "h": np.array([r[1] for r in rows], dtype=float), "l": np.array([r[2] for r in rows], dtype=float)}


# 1. режими: тільки явне live повертає в основний цикл
for v, exp in (("", "off"), ("0", "off"), ("1", "watch"), ("on", "watch"), ("watch", "watch"), ("true", "watch"), ("live", "live"), ("LIVE", "live"), ("garbage", "off")):
    os.environ["OFFICE2_DYNAMIC_UNIVERSE"] = v
    check(f"mode({v!r})={exp}", DW.mode() == exp)

# 2. paper-наслідок
E, SL, T1, T2 = 100.0, 99.0, 102.0, 104.0
RT0 = 10_000.0
now = RT0 + 20 * 900
o = DW.paper_outcome(bars([(RT0 + 900, 101, 99.5), (RT0 + 1800, 102.5, 100)]), RT0, "LONG", E, SL, T1, T2, 1.0, now)
check("LONG TP1", o and o["outcome"] == "TP1" and abs(o["r_gross"] - 2.0) < 1e-9 and abs(o["r_net"] - 1.85) < 1e-9)
o = DW.paper_outcome(bars([(RT0 + 900, 102.5, 98.5)]), RT0, "LONG", E, SL, T1, T2, 1.0, now)
check("бар зі SL і TP → SL (консервативно)", o and o["outcome"] == "SL" and abs(o["r_net"] + 1.15) < 1e-9)
o = DW.paper_outcome(bars([(RT0, 105, 90)]), RT0, "LONG", E, SL, T1, T2, 1.0, now)
check("бар READY і раніше не рахується (без заднього числа)", o is None)
o = DW.paper_outcome(bars([(RT0 + 900, 101, 99.5)]), RT0, "LONG", E, SL, T1, T2, 1.0, now)
check("без дотику → відкрито", o is None)
o = DW.paper_outcome(bars([(RT0 + 900, 100.5, 97.5)]), RT0, "SHORT", 98.0, 99.0, 96.0, 94.0, 1.0, now)
check("SHORT SL", bool(o) and o["outcome"] == "SL")
o = DW.paper_outcome(bars([(RT0 + 900, 101, 99.5)]), RT0, "LONG", E, SL, T1, T2, 1.0, RT0 + DW.TTL_SEC + 1)
check("EXPIRED після 48 год", o and o["outcome"] == "EXPIRED" and o["r_gross"] == 0.0)
o = DW.paper_outcome(bars([(RT0 + 900, 103, 100)]), RT0, "LONG", E, SL, T1, T2, None, now)
check("без stop_pct r_net=None (не вигадуємо)", o and o["r_net"] is None)
o = DW.paper_outcome(bars([(now - 100, 103, 100)]), RT0, "LONG", E, SL, T1, T2, 1.0, now)
check("незакритий бар не рахується", o is None)

# 3. БД: запис, незмінність READY, резолв
d = tempfile.mkdtemp()
db = os.path.join(d, "t.db")
DW._READY_TABLE["done"] = False
th = {"id": "X|1", "dir": "LONG", "kind": "SWEEP_SEQ", "state": "WAIT", "reason": "чекаю"}
DW.record(db, "XUSDT", th, 1000.0)
th2 = dict(th, state="READY", entry=100.0, sl=99.0, targets=[{"p": 102.0, "r": 2}, {"p": 104.0, "r": 4}], sizing={"stop_pct": 1.0}, reason="готово")
DW.record(db, "XUSDT", th2, 2000.0)
th3 = dict(th2, entry=150.0, sl=140.0, targets=[{"p": 160.0, "r": 1}])
DW.record(db, "XUSDT", th3, 3000.0)
from office_bridge import _fetchall

r = _fetchall(db, "SELECT state, ready_ts, entry, sl, tp1, tp2, first_ts FROM office2_dynamic_candidate")
check("один рядок, READY зафіксовано один раз", len(r) == 1 and r[0][0] == "READY" and r[0][1] == 2000 and r[0][2] == 100.0 and r[0][4] == 102.0 and r[0][6] == 1000)


class Feed:
    def klines(self, sym, tf, now, limit=None, start_ms=None, end_ms=None):
        return bars([(2900.0, 102.5, 100.0)])


n = DW.resolve(db, Feed(), 6000.0)
s = DW.summary(db)
check("resolve закрив TP1", n == 1 and s["stats"]["tp"] == 1 and s["stats"]["open"] == 0)
check("summary: модельний PnL з витратами", abs(s["stats"]["sum_r_net"] - 1.85) < 1e-6 and abs(s["stats"]["model_pnl_usd"] - 18.5) < 1e-6)

# 4. observe не пише в LIVE-таблиці
import office2.brain2 as B2
import office2.brain as B
import office2.engine as EN

B2.thesis = lambda *a, **k: dict(th2, id="X|2")
B.all_levels = lambda ctx, now: []
res = DW.observe(db, "YUSDT", {}, {}, {}, 5000.0)
check("observe → READY лише в dynamic_candidate", res["ready"] >= 1)
try:
    cnt = _fetchall(db, "SELECT COUNT(*) FROM office2_live_signal")[0][0]
except Exception:
    cnt = 0
try:
    cnt2 = _fetchall(db, "SELECT COUNT(*) FROM office2_live_scenario")[0][0]
except Exception:
    cnt2 = 0
check("жодного рядка в outbox/сценаріях LIVE", cnt == 0 and cnt2 == 0)

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
