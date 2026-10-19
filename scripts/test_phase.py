#!/usr/bin/env python3
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_language as lang  # noqa: E402
import office_phase as ph  # noqa: E402

# ряд 5m: випадкове блукання з σ≈0.2%, потім різкий рух вгору
import random

random.seed(3)
px = [100.0]
for _ in range(400):
    px.append(px[-1] * (1 + random.gauss(0, 0.002)))
base = list(px)
up = base + [base[-1] * (1 + 0.004 * k) for k in range(1, 7)]   # +2,4% за 30 хв ≈ 5σ
a_long = ph.sigma_extension(up, "LONG")
a_short = ph.sigma_extension(up, "SHORT")
assert a_long > 3 and abs(a_short + a_long) < 1e-9, (a_long, a_short)
assert ph.phase_of(a_long, "LONG")["name"] == "дуже пізно", ph.phase_of(a_long, "LONG")
assert ph.phase_of(a_short, "SHORT")["name"] == "ще рано", "SHORT після зростання = проти імпульсу"
assert ph.sigma_extension(base[:100], "LONG") is None, "замало даних — не вигадуємо"
assert ph.phase_of(None, "LONG") is None and ph.line(None) == ""
t = ph.line(ph.phase_of(a_long, "LONG"))
assert "Фаза руху: дуже пізно" in t and "у бік угоди" in t and not lang.problems(t), (t, lang.problems(t))
assert ph.phase_of(0.0, "SHORT")["name"] == "формується"
assert ph.phase_of(1.2, "SHORT")["name"] == "рух пішов" and ph.phase_of(2.5, "LONG")["name"] == "пізно"
print("OK phase: σ-розширення, фази, рядок, чесне None")
