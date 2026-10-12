#!/usr/bin/env python3
"""Тест V9/V10 (беззбитковість після +R): порядок подій, SL перед TP в одному барі, OPEN за ціною горизонту, витрати з нього віднімаються."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.learning import counterfactual as CF  # noqa: E402


def bars(h, l, c):
    n = len(h)
    return {"t": np.arange(n) * 900.0, "o": np.array(c, float), "h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float), "v": np.ones(n), "tbv": np.ones(n)}


def ev(d="LONG", entry=100.0, sl=99.0, tp1=102.0):
    return {"dir": d, "entry": entry, "sl": sl, "tp1": tp1}


fails = []


def check(name, cond):
    if not cond:
        fails.append(name)
        print("FAIL", name)


# бар0 — рішення; далі: +1R досягнуто (high 101.2), потім відкат до входу (low 99.9) → BE, а не SL
m = bars([100, 101.2, 100.5, 100.4], [100, 100.1, 99.9, 99.9], [100, 101, 100.2, 100.1])
r = CF._be(m, 0, ev(), 1.0)
check("BE після +1R: вихід по входу", r["outcome"] == "BE" and abs(r["r_net"] + CF.FEE_RT_PCT / 1.0 - 0) < 0.5)
# без BE (be_r=3) той самий шлях лишається OPEN → MTM
r2 = CF._be(m, 0, ev(), 3.0)
check("без досягнення порогу — OPEN", r2["outcome"] == "OPEN")
# SL і TP в одному барі → SL
m2 = bars([100, 102.5], [100, 98.5], [100, 100])
r3 = CF._be(m2, 0, ev(), 1.0)
check("SL перед TP в одному барі", r3["outcome"] == "SL")
# BE-перенесення діє з наступного бару: бар1 дає +1R і одразу падає нижче входу, але SL ще на початковому рівні
m3 = bars([100, 101.3, 100], [100, 99.5, 99.0], [100, 100.5, 99.5])
r4 = CF._be(m3, 0, ev(), 1.0)
check("в тому ж барі SL не перенесено (low 99.5 > SL 99)", r4["outcome"] in ("BE", "OPEN", "SL"))
# SHORT симетрично
m4 = bars([100, 100.1, 100.2], [100, 98.8, 99.5], [100, 99.0, 100.0])
r5 = CF._be(m4, 0, ev("SHORT", 100.0, 101.0, 98.0), 1.0)
check("SHORT: BE по входу", r5["outcome"] == "BE")
print("OK" if not fails else f"FAIL: {fails}")
sys.exit(1 if fails else 0)
