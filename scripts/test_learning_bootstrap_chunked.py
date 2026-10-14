#!/usr/bin/env python3
"""Learning: бутстреп довірчих інтервалів порціями рядків дає ТОЙ САМИЙ результат, що й одна велика матриця, але пам'ять обмежена (раніше reps×n×16 Б: HWM 430 МБ на 16 тис. угод)."""
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.learning import compare as CP  # noqa: E402

bad = 0


def check(name, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f" :: {info}"))
    bad += 0 if ok else 1


def ref(a, b, reps=2000, seed=7):
    rnd = np.random.default_rng(seed)
    xa, xb = np.asarray(a, float), np.asarray(b, float)
    ma = xa[rnd.integers(0, len(xa), size=(reps, len(xa)))].mean(axis=1)
    mb = xb[rnd.integers(0, len(xb), size=(reps, len(xb)))].mean(axis=1)
    d = np.sort(ma - mb)
    return [round(float(d[int(0.025 * reps)]), 3), round(float(d[int(0.975 * reps) - 1]), 3)]


r = random.Random(5)
for na, nb in ((2, 2), (3, 5), (40, 60), (500, 900), (1500, 2500)):
    a, b = [r.gauss(0.1, 1) for _ in range(na)], [r.gauss(0, 1) for _ in range(nb)]
    check(f"той самий інтервал, що й еталон (n={na}/{nb})", CP.boot_diff(a, b) == ref(a, b), (CP.boot_diff(a, b), ref(a, b)))
check("<2 спостережень → None", CP.boot_diff([1.0], [1.0, 2.0]) is None)

sizes = []
orig = np.random.Generator.integers


class Spy:
    def __init__(self, g):
        self.g = g

    def integers(self, lo, hi, size=None):
        sizes.append(int(size[0]) * int(size[1]))
        return self.g.integers(lo, hi, size=size)


m = CP._boot_means(np.asarray([r.gauss(0, 1) for _ in range(5000)], float), 2000, Spy(np.random.default_rng(1)))
check("пам'ять обмежена: жодна порція не більша за 2 млн елементів (раніше 2000×5000 = 10 млн за раз)", len(m) == 2000 and max(sizes) <= 2_000_000 and len(sizes) > 1, (max(sizes), len(sizes)))
print("ALL OK" if not bad else f"FAILED {bad}")
sys.exit(1 if bad else 0)
