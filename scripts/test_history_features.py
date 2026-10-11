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
print("OK геометрія/дедуп\nALL OK")
