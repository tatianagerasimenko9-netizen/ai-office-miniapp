#!/usr/bin/env python3
"""office2/entry_quality: класифікація причин SL (передчасний вхід / вибито тінню / хибний напрям / без продовження), рекавері до початкового TP1, альтернативи, відсутність look-ahead у входах."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office2 import entry_quality as EQ

bad = 0
def check(n, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + n + ("" if ok else f" :: {info}"))
    bad += 0 if ok else 1

def mk(bars):
    t = np.arange(len(bars), dtype=float) * 900.0
    o = np.array([b[0] for b in bars]); h = np.array([b[1] for b in bars]); l = np.array([b[2] for b in bars]); c = np.array([b[3] for b in bars])
    return {"t": t, "o": o, "h": h, "l": l, "c": c}

def flat(p, n): return [(p, p + 0.1, p - 0.1, p)] * n

# LONG: entry 100, SL 96, TP1 106, зона 98–100.5 (дальній край 98), екстремум(v2) 96.5
ev = {"dir": "LONG", "entry": 100.0, "sl": 96.0, "tp1": 106.0, "zone": [98.0, 100.5], "sl_v2": 96.5}
# 1) зайшла до 98 (deeper), потім SL, потім TP1 → PREMATURE_ENTRY
b1 = flat(100, 2) + [(100, 100.2, 97.5, 98), (98, 98.5, 95.5, 96)] + flat(97, 8) + [(97, 106.5, 97, 106)] + flat(105, 5)
q1 = EQ.analyze(mk(b1), 1, ev, 1.0)
check("PREMATURE_ENTRY: зона пройдена, TP1 після SL", q1["o"] == "SL" and q1["deeper"] and q1["cls"] == "PREMATURE_ENTRY" and q1["tp1_24h"], q1)
# 2) без заходу в зону (SL тінню одразу), потім TP1 → STOP_WICK
ev2 = dict(ev, zone=[90.0, 100.5])
b2 = flat(100, 2) + [(100, 100.1, 95.8, 99)] + flat(99, 8) + [(99, 106.5, 99, 106)] + flat(105, 5)
q2 = EQ.analyze(mk(b2), 1, ev2, 1.0)
check("STOP_WICK: зону не проходили, TP1 після SL", q2["cls"] == "STOP_WICK" and not q2["deeper"], q2)
# 3) SL і далі падіння ≥1R за SL → WRONG_DIRECTION
b3 = flat(100, 2) + [(100, 100.1, 95.8, 96)] + [(96, 96.1, 91.0, 92)] + flat(92, 14)
q3 = EQ.analyze(mk(b3), 1, ev2, 1.0)
check("WRONG_DIRECTION", q3["cls"] == "WRONG_DIRECTION" and q3["ext_r"] >= 1.0 and not q3["tp1_72h"], q3)
# 4) SL і боковик → NO_FOLLOWTHROUGH
b4 = flat(100, 2) + [(100, 100.1, 95.8, 96)] + flat(95.5, 14)
q4 = EQ.analyze(mk(b4), 1, ev2, 1.0)
check("NO_FOLLOWTHROUGH", q4["cls"] == "NO_FOLLOWTHROUGH", q4)
# 5) SHORT-дзеркало
evs = {"dir": "SHORT", "entry": 100.0, "sl": 104.0, "tp1": 94.0, "zone": [99.5, 102.0], "sl_v2": 103.5}
b5 = flat(100, 2) + [(100, 102.5, 99.9, 102), (102, 104.5, 101.5, 104)] + flat(103, 8) + [(103, 103, 93.5, 94)] + flat(95, 5)
q5 = EQ.analyze(mk(b5), 1, evs, 1.0)
check("SHORT дзеркало: PREMATURE_ENTRY", q5["o"] == "SL" and q5["cls"] == "PREMATURE_ENTRY", q5)
# 6) альтернативи: SG ширший стоп не вибито тінню → результат не SL
check("альтернативи рахуються", set(q1["alt"]) >= {"E2", "SG", "SA"}, q1["alt"])
b6 = flat(100, 2) + [(100, 100.1, 95.85, 99)] + flat(99, 10) + [(99, 106.5, 99, 106)] + flat(105, 5)
q6 = EQ.analyze(mk(b6), 1, ev2, 1.0)
check("SG/SA (ширший стоп) переживають тінь і беруть TP1", q6["alt"]["SG"]["o"] == "TP1" and q6["alt"]["SA"]["o"] == "TP1" and q6["o"] == "SL", q6)
# 7) без look-ahead: зміна барів ПІСЛЯ закінчення горизонту не змінює вхідні поля
b7 = list(b1)
q7 = EQ.analyze(mk(b7 + [(500, 501, 1, 2)] * 400), 1, ev, 1.0)
check("рекавері обмежене 72 год", q7["cls"] == "PREMATURE_ENTRY" and q7["rec_n"] <= EQ.REC_72H, q7)
sys.exit(1 if bad else 0)
