#!/usr/bin/env python3
"""Самоперевірка строгого пересчету READY на синтетичних 1m-свічках (без мережі): порядок SL/TP1, хвилина-нічия, відсутність lookahead, NO_DATA."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import ready_replay_strict as rr  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


T0 = 1_790_000_000 - (1_790_000_000 % 60)


def rows_from(path):
    """path: список (high, low, close) по хвилинах від T0."""
    return [[T0 + 60 * i, c, h, l, c, 1.0] for i, (h, l, c) in enumerate(path)]


def plan(ct, direction="LONG", entry=100.0, sl=98.0, tp1=104.0):
    return {"mid": "1", "direction": direction, "entry": entry, "sl": sl, "tp1": tp1, "tp2": None, "tp3": 110.0, "ct": ct, "vt": ct + 86400}


def run(path, **kw):
    rows = rows_from(path)
    return rr.replay_one(plan(**kw), rows, [r[0] for r in rows])


flat = [(100.5, 99.5, 100.0)] * 10
# a) вхід торкнуто, далі TP1 раніше за SL
r = run(flat + [(105.0, 100.0, 104.5)] + flat, ct=T0 + 5 * 60)
check(r["first"] == "TP1" and "TP1" in (r.get("reached") or []) and not r["tie"], f"TP1 першим (позиція ще відкрита → PENDING): {r['status']} {r['first']} reached={r.get('reached')}")
# b) SL першим
r = run(flat + [(100.0, 97.0, 97.5)] + flat, ct=T0 + 5 * 60)
check(r["status"] == "STOP" and r["first"] == "SL" and not r["tie"], f"SL першим: {r['status']} {r['first']}")
# c) стоп і TP1 в одній хвилині → стоп, tie=True (порядок невідомий)
r = run(flat + [(105.0, 97.0, 100.0)] + flat, ct=T0 + 5 * 60)
check(r["status"] == "STOP" and r["tie"] is True and r["first"] == "SL", f"нічия в одній хвилині: {r['status']} tie={r['tie']}")
# d) lookahead: екстремум стопу ДО моменту READY (хвилини 0–4) не зараховується
pre = [(100.5, 90.0, 100.0)] * 5   # дуже низький low до READY
r = run(pre + [(100.5, 99.5, 100.0)] * 20, ct=T0 + 5 * 60)
check(r["status"] == "PENDING", f"рух до READY ігнорується (PENDING, не STOP): {r['status']}")
# e) без даних
r = rr.replay_one(plan(ct=T0), [], [])
check(r["status"] == "NO_DATA", f"немає свічок = NO_DATA: {r['status']}")
# f) дані закінчились до READY
rows = rows_from(flat)
r = rr.replay_one(plan(ct=T0 + 100 * 60), rows, [x[0] for x in rows])
check(r["status"] == "NO_DATA", f"дані раніше за READY: {r['status']}")
# g) ret_pct бере лише закриті до t свічки
path = [(100.0 + i, 100.0 + i, 100.0 + i) for i in range(400)]
rows = rows_from(path)
times = [x[0] for x in rows]
t = T0 + 300 * 60
v = rr.ret_pct(rows, times, t, 1800)
exp = round((299.0 + 100.0) / (269.0 + 100.0) * 100 - 100, 3)
check(v == exp, f"ret_pct без lookahead: {v} vs {exp}")
check(rr.ret_pct(rows, times, T0 + 10 * 60, 1800) is None, "недостатньо історії = None, а не вигадане число")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
