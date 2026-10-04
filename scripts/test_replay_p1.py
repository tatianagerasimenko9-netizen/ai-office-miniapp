#!/usr/bin/env python3
"""Replay P1: логіка без мережі на синтетичних свічках — без lookahead, стоп першим у свічці, цензура, STOP_THEN_DIRECTION, ATR лише з минулого."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import replay_p1 as R  # noqa: E402

T = 1_790_000_000.0 - (1_790_000_000.0 % 3600)
FIVE = 300.0


def mk(start, specs):
    return [(start + i * FIVE, o, h, l, c) for i, (o, h, l, c) in enumerate(specs)]


row = {"t": T, "sym": "AAAUSDT", "dir": "LONG", "entry": 100.0, "sl": 98.0, "tp1": 104.0, "tp2": 107.0, "tp3": None}
flat = (100, 100.5, 99.5, 100)
# заповнення на 2-й свічці, потім TP1, TP2
c = mk(T, [flat, (100, 100.2, 99.9, 100), (100, 105, 100, 104), (104, 108, 104, 107)])
s = R.simulate(row, c, T + 10 * 3600)
assert s["fill"] and s["first"] == "TP1" and s["best"] == "TP2" and s["resolved"], s
# свічка ДО сигналу не використовується (lookahead-захист)
c0 = mk(T - FIVE, [(100, 105, 95, 100)]) + mk(T, [(101, 102, 101, 102)] * 3)
s0 = R.simulate(row, c0, T + 10 * 3600)
assert not s0["fill"], s0
# стоп і ціль в одній свічці → стоп першим
c1 = mk(T, [(100, 100.5, 99.5, 100), (100, 105, 97, 100)])
s1 = R.simulate(row, c1, T + 10 * 3600)
assert s1["first"] == "STOP", s1
# TP1, потім стоп → TP1_THEN_STOP, і STOP_THEN_DIRECTION=False без нового руху
c2 = mk(T, [(100, 100.5, 99.5, 100), (100, 105, 100, 104), (104, 104, 97, 98)] + [(98, 99, 97, 98)] * 400)
s2 = R.simulate(row, c2, T + 100 * 3600)
assert s2["first"] == "TP1_THEN_STOP" and s2["best"] == "TP1" and s2["stop_then_dir"] is False, s2
# стоп, потім рух до TP1 за 24 год → STOP_THEN_DIRECTION=True
c3 = mk(T, [(100, 100.5, 99.5, 100), (100, 100, 97, 98), (98, 99, 98, 99), (99, 105, 99, 105)])
s3 = R.simulate(row, c3, T + 100 * 3600)
assert s3["first"] == "STOP" and s3["stop_then_dir"] is True, s3
# без заповнення за 24 год → NO_FILL; дані скінчились раніше → не розв'язано (цензура)
c4 = mk(T, [(101, 102, 101, 102)] * 400)
assert R.simulate(row, c4, T + 400 * FIVE)["first"] == "NO_FILL"
c5 = mk(T, [(101, 102, 101, 102)] * 10)
s5 = R.simulate(row, c5, T + 10 * FIVE)
assert s5["first"] == "NONE" and not s5["resolved"], s5
# SHORT дзеркально
rs = {"t": T, "sym": "BBBUSDT", "dir": "SHORT", "entry": 100.0, "sl": 102.0, "tp1": 96.0, "tp2": None, "tp3": None}
cs = mk(T, [(100, 100.5, 99.5, 100), (100, 100, 95, 96)])
ss = R.simulate(rs, cs, T + 10 * 3600)
assert ss["first"] == "TP1" and ss["resolved"], ss
# ATR лише зі свічок ДО t: майбутній сплеск не впливає
hist = []
for h in range(30):
    hist += mk(T - (30 - h) * 3600, [(100, 101, 99, 100)] * 12)
a0 = R.atr_h1(hist, T)
future = hist + mk(T, [(100, 150, 50, 100)] * 12)
assert a0 and abs(R.atr_h1(future, T) - a0) < 1e-9 and 1.9 < a0 < 2.1, a0
assert R.bucket(0.4) == "<0.5 ATR" and R.bucket(0.8) == "0.75–1.0" and R.bucket(2.0) == ">1.5 ATR" and R.bucket(None) == "немає ATR"
# горизонт 24 год без цензури: TP1 першим → h24=TP1; стоп першим → STOP; недостатньо даних → None
assert R.simulate(row, c, T + 10 * 3600)["h24"] is None
cc = mk(T, [(100, 100.5, 99.5, 100), (100, 105, 100, 104)] + [(104, 104.5, 103.5, 104)] * 400)
assert R.simulate(row, cc, T + 40 * 3600)["h24"] == "TP1"
cs2 = mk(T, [(100, 100.5, 99.5, 100), (100, 100, 97, 98)] + [(98, 99, 97, 98)] * 400)
assert R.simulate(row, cs2, T + 40 * 3600)["h24"] == "STOP"
# повний прогін на синтетичних даних
rows = [dict(row, t=T + 3600 * 40), dict(rs, t=T + 3600 * 40, sym="AAAUSDT")]
day = lambda sym, d: hist + mk(T, [(100, 100.5, 99.5, 100)] * 2 + [(100, 105, 100, 104)] * 600)  # noqa: E731
out = R.run(rows, day)
assert len(out["rows"]) == 2 and not out["missing"] and R.summarize(out["rows"], "bin")
print("test_replay_p1: OK")
