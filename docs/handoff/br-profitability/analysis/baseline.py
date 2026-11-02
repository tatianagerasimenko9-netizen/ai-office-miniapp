"""Базова перевірка даних і проста модель R (стандартна бібліотека). Запуск: python3 analysis/baseline.py
Модель (ГІПОТЕЗА, лише для порівняння): вхід у entry; SL = -1R; варіант A: повний вихід на TP1; варіант B: 1/3 на TP1,TP2,TP3 (решта до SL, без переносу в беззбиток);
витрати 0.15% ціни на угоду (round-trip) -> у R = 0.15/stop%. AMB і плани без події E виключено. Порядок подій береться з файлу."""
import glob, math, os, sys, collections, datetime
D = os.path.join(os.path.dirname(__file__), "..", "data")
OFF = 1790000000
rows = []
for f in sorted(glob.glob(os.path.join(D, "br_plans_*.psv"))):
    for ln in open(f, encoding="utf-8"):
        p = ln.rstrip("\n").split("|")
        if len(p) < 7: continue
        seq, sym, d, ts, ent, sl, tg = int(p[0]), p[1], p[2], int(p[3]), float(p[4]), float(p[5]), p[6]
        ev = [(e.split("@")[0], int(e.split("@")[1]) + OFF) for e in p[7].split(",")] if len(p) > 7 and p[7] else []
        tps = [(float(x.split(":")[0]), x.split(":")[1]) for x in tg.split(",")]
        rows.append(dict(seq=seq, sym=sym, dir=d, ts=ts, entry=ent, sl=sl, tps=tps, ev=ev))
print("планів:", len(rows), "| з входом E:", sum(any(k == "E" for k, _ in r["ev"]) for r in rows),
      "| без жодної події:", sum(not r["ev"] for r in rows), "| AMB:", sum(any(k == "AMB" for k, _ in r["ev"]) for r in rows))

def outcome(r):
    kinds = [k for k, _ in r["ev"]]
    if "E" not in kinds or "AMB" in kinds: return None
    risk = abs(r["entry"] - r["sl"]); stop_pct = risk / r["entry"] * 100
    cost = 0.15 / stop_pct
    rk = [abs(t - r["entry"]) / risk for t, _ in r["tps"]]
    seen = [k for k in kinds if k != "E"]
    if not seen: return None
    first = seen[0]
    a = (rk[0] if first == "T1" else -1.0) - cost if first in ("T1", "SL") else None
    hit = [k for k in seen if k.startswith("T")]
    b = None
    if seen:
        sl_after = "SL" in seen
        part = 0.0
        for i, k in enumerate(("T1", "T2", "T3")):
            if k in seen and (not sl_after or seen.index(k) < seen.index("SL")): part += rk[i] / 3
            else: part += -1.0 / 3
        b = part - cost
    return a, b, stop_pct, first

res = [(r, outcome(r)) for r in rows]
res = [(r, o) for r, o in res if o and o[0] is not None]
def summ(items, name):
    if not items: print(name, "n=0"); return
    A = [o[0] for _, o in items]; B = [o[1] for _, o in items]
    print(f"{name:14s} n={len(items):4d}  A(TP1) netR={sum(A)/len(A):+.3f}  B(1/3х3) netR={sum(B)/len(B):+.3f}  частка першим SL={sum(o[3]=='SL' for _, o in items)/len(items):.0%}")
summ(res, "ВСІ")
print("\nза годиною UTC:")
for h in range(24):
    summ([(r, o) for r, o in res if datetime.datetime.utcfromtimestamp(r["ts"]).hour == h], f"h={h:02d}")
print("\nза розміром стопу:")
for lo, hi in ((0, .3), (.3, .5), (.5, .8), (.8, 1.2), (1.2, 99)):
    summ([(r, o) for r, o in res if lo <= o[2] < hi], f"{lo}-{hi}%")
print("\nУВАГА: це описова статистика без кластерної поправки; сигнали йдуть пачками по багатьох монетах в одну свічку (не незалежні). Висновків про 'гарні години' з цього робити не можна без holdout.")
