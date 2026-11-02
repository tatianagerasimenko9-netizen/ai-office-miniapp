"""Агрегація виходу htf_stop_replay.py: чи покращує стоп за HTF-swing net R проти поточного; частка stop-hunt. Кластерний bootstrap (15-хв бар+напрям), seed 7.
Порівняння лише на тих планах, де варіант розв'язаний (парно). ГІПОТЕЗА."""
import json, random, sys, collections
random.seed(7)
rows = [r for r in json.load(open(sys.argv[1]))["rows"] if "original" in r]
print("планів з свічками та розв'язаним оригіналом:", len(rows))
hunt = [r for r in rows if r["original"]["stop_at"] is not None]
print(f"оригінальних SL: {len(hunt)}; з них після SL ціна дійшла до TP1 за ≤24 год (stop-hunt): {sum(1 for r in hunt if r.get('stop_hunt'))} ({sum(1 for r in hunt if r.get('stop_hunt'))/max(1,len(hunt)):.0%})")
def ci(pairs):
    cl = collections.defaultdict(list)
    for key, d in pairs: cl[key].append(d)
    ks = list(cl); ms = []
    for _ in range(2000):
        t = c = 0
        for _ in ks:
            v = cl[random.choice(ks)]; t += sum(v); c += len(v)
        ms.append(t / c)
    ms.sort(); return ms[50], ms[1949]
groups = collections.defaultdict(list)
for r in rows:
    key = (r["ts"] // 900, r["direction"])
    for v in r["variants"]:
        if v.get("net_r") is None: continue
        groups[(v["timeframe"], v["buffer_ratio"])].append((key, v["net_r"] - r["original_net_r"], v["net_r"], r["original_net_r"]))
print("\n| ТФ | буфер | n | netR варіант | netR оригінал | Δ (варіант−оригінал) | CI95 Δ |\n|--|--|--|--|--|--|--|")
for k in sorted(groups):
    g = groups[k]; n = len(g)
    lo, hi = ci([(a, d) for a, d, _, _ in g])
    print(f"| {k[0]} | {k[1]} | {n} | {sum(x[2] for x in g)/n:+.3f} | {sum(x[3] for x in g)/n:+.3f} | {sum(x[1] for x in g)/n:+.3f} | [{lo:+.3f}; {hi:+.3f}] |")
print("\nВисновок можливий лише якщо CI Δ не містить 0 І підтверджено на пізнішій вибірці; інакше НЕ ПІДТВЕРДЖЕНО.")
