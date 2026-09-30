#!/usr/bin/env python3
"""Фігури Булковскі як правила: голова і плечі (обидві), трикутники, прямокутник, клини, прапор — підтвердження лише закриттям за межею; шум не дає фігур."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_bulkowski as B  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = (T0 + timedelta(days=5)).timestamp()


def walk(vertices, legs, pad=0.15):
    """Ламана з вершин vertices (ціни); legs[i] — кількість свічок на відрізку i → i+1."""
    closes = [vertices[0]]
    for (a, b), n in zip(zip(vertices, vertices[1:]), legs):
        for k in range(1, n + 1):
            closes.append(a + (b - a) * k / n)
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        rows.append({"ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": prev, "high": c + pad, "low": c - pad, "close": c})
        prev = c
    return rows


def kinds(rows, side=None, conf=None):
    return [(p["kind"], p["side"], p["confirmed"]) for p in B.detect_all(rows, now_ts=NOW) if (side is None or p["side"] == side) and (conf is None or p["confirmed"] == conf)]


# голова і плечі: три піки 110/116/110,2, шия ≈104,3; закриття під шиєю → SHORT
hs = walk([100, 110, 104, 116, 104.5, 110.2, 100], [6, 4, 6, 6, 4, 6])
res = [p for p in B.detect_all(hs, now_ts=NOW) if p["kind"] == "head_shoulders"]
assert res and res[0]["confirmed"] and res[0]["side"] == "SHORT" and res[0]["target"] < 100, res
hs_wait = walk([100, 110, 104, 116, 104.5, 110.2, 106], [6, 4, 6, 6, 4, 3])   # ще не закрились під шиєю
assert ("head_shoulders", "SHORT", False) in kinds(hs_wait), kinds(hs_wait)
# перевернута: дзеркало → LONG
ihs = walk([116, 106, 112, 100, 111.5, 105.8, 116], [6, 4, 6, 6, 4, 6])
assert ("inverse_head_shoulders", "LONG", True) in kinds(ihs), kinds(ihs)
# голова не вища за плечі → фігури немає
flat = walk([100, 110, 104, 110.2, 104.5, 110.1, 100], [6, 4, 6, 6, 4, 6])
assert not [k for k in kinds(flat) if k[0] == "head_shoulders"], kinds(flat)

# трикутники
asc = walk([100, 110, 102, 110, 105, 110, 107.5, 114], [5, 5, 5, 5, 5, 4, 6])
assert ("ascending_triangle", "LONG", True) in kinds(asc), kinds(asc)
assert ("ascending_triangle", "LONG", True) not in kinds(walk([100, 110, 102, 110, 105, 110, 107.5, 109.4], [5, 5, 5, 5, 5, 4, 3])), "без закриття за опором — не підтверджено"
desc = walk([120, 110, 118, 110, 115, 110, 112.5, 106], [5, 5, 5, 5, 5, 4, 6])
assert ("descending_triangle", "SHORT", True) in kinds(desc), kinds(desc)
sym = walk([100, 110, 102, 108, 103.5, 106.5, 104.6, 111], [5, 5, 5, 5, 5, 4, 6])
assert ("symmetrical_triangle", "LONG", True) in kinds(sym), kinds(sym)
# прямокутник
rect = walk([100, 110, 100.1, 110.1, 99.9, 109.9, 100.05, 113], [5, 5, 5, 5, 5, 5, 7])
assert ("rectangle", "LONG", True) in kinds(rect), kinds(rect)
# клини
rw = walk([100, 110, 104.5, 112, 108.5, 113, 111.5, 105], [5, 5, 5, 5, 5, 4, 8])
assert ("rising_wedge", "SHORT", True) in kinds(rw), kinds(rw)
fw = walk([120, 110, 115.5, 108, 111.5, 106.5, 108.5, 116], [5, 5, 5, 5, 5, 4, 8])
assert ("falling_wedge", "LONG", True) in kinds(fw), kinds(fw)
# прапор: імпульс 100→112, відкат ≤50%, пробій вгору
fl = walk([100, 112, 109.5, 112.8], [6, 8, 4])
fl2 = fl[:]
res = [p for p in B.detect_all(fl2, now_ts=NOW) if p["kind"] in ("flag", "pennant")]
assert res and res[0]["side"] == "LONG", res
# тиха бокова «каша» без форми → нічого підтвердженого
import random  # noqa: E402

random.seed(7)
noise = walk([100 + random.uniform(-0.2, 0.2) for _ in range(40)], [1] * 39)
assert not [p for p in B.detect_all(noise, now_ts=NOW) if p["confirmed"]], B.detect_all(noise, now_ts=NOW)
# перелік бібліотеки: що реалізовано, а чого немає — чесно
assert set(B.KINDS_IMPLEMENTED) >= {"head_shoulders", "ascending_triangle", "rectangle", "falling_wedge", "flag"}
print("OK bulkowski: H&S (both), triangles, rectangle, wedges, flag/pennant — close beyond the boundary, targets by measure rule, noise → nothing")

# інтеграція: підтверджена фігура в зоні → тег у підтвердженнях картки; поза зоною — ні
from office_confluence import detect_ltf_confirms  # noqa: E402

zone_lo, zone_hi = 109.6, 110.6     # опір висхідного трикутника ≈110
hits = detect_ltf_confirms(direction="LONG", candles_ltf=asc, zone_lo=zone_lo, zone_hi=zone_hi, now_ts=NOW)
assert "ascending_triangle" in hits, hits
hits2 = detect_ltf_confirms(direction="LONG", candles_ltf=asc, zone_lo=150, zone_hi=151, now_ts=NOW)
assert "ascending_triangle" not in hits2, "фігура далеко від зони не рахується"
print("OK bulkowski → confirms integration")
