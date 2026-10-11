#!/usr/bin/env python3
"""Офлайн-перевірка ознак зі свічок: немає заглядання в майбутнє, мало історії → UNKNOWN, геометрія/дедуп."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from office2.learning import history_features as HF  # noqa: E402
import history_study as HS  # noqa: E402

t0 = 1790000000 // 900 * 900
n = 1200
t = t0 + np.arange(n) * 900.0
c = 100 + np.cumsum(np.sin(np.arange(n) / 20.0))
a = {"t": t, "o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "v": np.ones(n)}
ts = float(t[900]) + 100
p = {"dir": "LONG", "tf": "H1", "entry": float(c[899]), "sl": float(c[899]) - 1.0, "tp1": float(c[899]) + 2.0, "ts": ts, "rej": False}
f1 = HF.extract(p, a, None, a)
a2 = {k: v.copy() for k, v in a.items()}
a2["c"][905:] += 50.0; a2["h"][905:] += 50.0; a2["l"][905:] += 50.0     # змінюємо ЛИШЕ майбутнє
f2 = HF.extract(p, a2, None, a2)
assert f1 == f2, (f1, f2)
print("OK ознаки не залежать від майбутніх свічок")
early = HF.extract({**p, "ts": float(t[10])}, a, None, None)
assert early["trend_h4"] == "UNKNOWN" and early["btc_h4"] == "UNKNOWN" and early["pd_24h"] == "UNKNOWN", early
print("OK мало історії → UNKNOWN")
assert HS.usable({"sym": "X", "dir": "LONG", "entry": 1, "sl": 2, "tp1": 3, "ts": 1, "valid": 2}) == "BAD_GEOMETRY"
assert HS.usable({"sym": "X", "dir": "SHORT", "entry": 2, "sl": 3, "tp1": 1, "ts": 1, "valid": 2}) == "OK"
assert HS.usable({"sym": "X", "dir": "SHORT", "entry": 2, "sl": None, "tp1": 1, "ts": 1, "valid": 2}) == "NO_LEVELS"
pl = HS.dedup([{"sym": "A", "dir": "LONG", "ts": 1000.0, "sid": "1"}, {"sym": "A", "dir": "LONG", "ts": 2000.0, "sid": "2"}, {"sym": "A", "dir": "SHORT", "ts": 2000.0, "sid": "3"}])
assert [x["dup"] for x in pl] == [False, True, False]
import office_signal_track as T  # noqa: E402
e0 = float(t[10]); base = 100.0
cl = [{"ts": e0 + 900 * k, "high": base + 0.2, "low": base - 0.2} for k in range(0, 700)]
cl[300]["low"] = 98.9        # SL=99 зачеплено через ~75 год після входу? ні: 300*900 c = 75 год
pl = {"direction": "LONG", "entry": 100.0, "sl": 99.0, "tp1": 102.0, "confirmed_ts": e0, "valid_until_ts": e0 + 3600}
r = HS.run_sim(T, pl, cl, e0 + 900 * 700)
assert r["status"] == "OPEN_TIMEOUT", r          # SL після 72 год → тайм-аут, як у трекері
cl[100]["low"] = 98.9; cl[300]["low"] = 99.8     # SL через ~25 год
r = HS.run_sim(T, pl, cl, e0 + 900 * 700)
assert r["status"] == "STOP", r
print("OK симуляція: STOP до 72 год, тайм-аут після (без хибного OPEN_TIMEOUT)\nALL OK")
