"""A5: кластерний bootstrap, погодинна/сесійна таблиця, purged holdout, пермутаційний контроль. stdlib, seed=7.
Модель = baseline.py (TP1-варіант A, комісія 0.15%/угоду, AMB виключено). Кластер = (15-хв бар, напрям). ГІПОТЕЗА-рівень, не підтвердження."""
import glob, os, random, datetime, statistics as st
random.seed(7)
D = os.path.join(os.path.dirname(__file__), "..", "data"); OFF = 1790000000
plans = []
for f in sorted(glob.glob(os.path.join(D, "br_plans_*.psv"))):
    for ln in open(f, encoding="utf-8"):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [(e.split("@")[0], int(e.split("@")[1]) + OFF) for e in p[7].split(",")]
        k = [a for a, _ in ev]
        if "E" not in k or "AMB" in k: continue
        seen = [(a, t) for a, t in ev if a != "E"]
        if not seen or seen[0][0] not in ("T1", "SL"): continue
        ent, sl, ts = float(p[4]), float(p[5]), int(p[3])
        risk = abs(ent - sl); sp = risk / ent * 100
        t1 = float(p[6].split(",")[0].split(":")[0])
        r = (abs(t1 - ent) / risk if seen[0][0] == "T1" else -1.0) - 0.15 / sp
        plans.append(dict(ts=ts, end=ev[-1][1], dir=p[2], h=datetime.datetime.utcfromtimestamp(ts).hour, sp=sp, r=r, cl=(ts // 900, p[2])))
plans.sort(key=lambda x: x["ts"])
print("n plans:", len(plans))

def boot(items, B=2000, alpha=0.05):
    cl = {}
    for x in items: cl.setdefault(x["cl"], []).append(x["r"])
    keys = list(cl); n = len(keys)
    if n < 2: return None
    means = []
    for _ in range(B):
        tot = cnt = 0
        for _ in range(n):
            v = cl[random.choice(keys)]; tot += sum(v); cnt += len(v)
        means.append(tot / cnt)
    means.sort()
    return means[int(B * alpha / 2)], means[int(B * (1 - alpha / 2)) - 1], n
def row(name, items, alpha=0.05):
    if not items: return f"| {name} | 0 | | | |"
    m = sum(x["r"] for x in items) / len(items); b = boot(items, alpha=alpha)
    ci = f"[{b[0]:+.2f}; {b[1]:+.2f}]" if b else "-"
    return f"| {name} | {len(items)} | {b[2] if b else 1} | {m:+.3f} | {ci} |"

print("\n## Всі: ", row("ALL", plans))
print("\n## Година UTC (99.8% CI ≈ поправка Бонферроні на 24 тести)\n| год | n | кластерів | net R | CI |\n|--|--|--|--|--|")
for h in range(24): print(row(f"{h:02d}", [x for x in plans if x["h"] == h], alpha=0.05 / 24))
print("\n## Сесії UTC (фіксовані вікна)\n| вікно | n | кластерів | net R | CI95 |\n|--|--|--|--|--|")
for nm, a, b in (("00-07", 0, 7), ("07-13", 7, 13), ("13-17", 13, 17), ("17-21", 17, 21), ("21-24", 21, 24)):
    print(row(nm, [x for x in plans if a <= x["h"] < b]))
print("\n## Розмір стопу\n| стоп | n | кластерів | net R | CI95 |\n|--|--|--|--|--|")
for lo, hi in ((0, .3), (.3, .5), (.5, .8), (.8, 1.2), (1.2, 99)):
    print(row(f"{lo}-{hi}%", [x for x in plans if lo <= x["sp"] < hi]))

# purged holdout: перші 60% за часом = train, останні 40% = test; train-угоди, що закінчуються після межі, видалено; embargo 24 год
split = plans[int(len(plans) * 0.6)]["ts"]; emb = 24 * 3600
train = [x for x in plans if x["ts"] < split and x["end"] < split]
test = [x for x in plans if x["ts"] >= split + emb]
print(f"\n## Purged holdout: межа {datetime.datetime.utcfromtimestamp(split):%Y-%m-%d %H:%M} UTC; train n={len(train)} (purged від {sum(1 for x in plans if x['ts']<split)}), test n={len(test)}")
def hourstats(items):
    return {h: (sum(x['r'] for x in items if x['h'] == h) / n, n) for h in range(24) if (n := sum(1 for x in items if x['h'] == h)) >= 12}
hs = hourstats(train)
best = sorted(hs, key=lambda h: -hs[h][0])[:5]
print("Топ-5 годин на train:", [(h, round(hs[h][0], 3), hs[h][1]) for h in best])
tb = [x for x in test if x["h"] in best]
print(row("test: обрані години", tb)); print(row("test: усі", test))
# пермутаційний контроль: випадкові 5 годин із train-набору, середнє на test
vals = []
pool = list(hs)
for _ in range(2000):
    pick = random.sample(pool, min(5, len(pool))); sel = [x for x in test if x["h"] in pick]
    if sel: vals.append(sum(x["r"] for x in sel) / len(sel))
vals.sort(); obs = sum(x["r"] for x in tb) / len(tb) if tb else float("nan")
print(f"Контроль (випадкові 5 годин): медіана {vals[len(vals)//2]:+.3f}, 95%-й квантиль {vals[int(len(vals)*.95)]:+.3f}; спостережено {obs:+.3f}; частка контролю ≥ спостереженого: {sum(v>=obs for v in vals)/len(vals):.2f}")
# стоп ≥ 0.5% на train/test
for nm, items in (("train", train), ("test", test)):
    a = [x for x in items if x["sp"] >= .5]; b = [x for x in items if x["sp"] < .5]
    print(f"{nm}: стоп≥0.5% n={len(a)} netR={sum(x['r'] for x in a)/max(1,len(a)):+.3f} | <0.5% n={len(b)} netR={sum(x['r'] for x in b)/max(1,len(b)):+.3f}")
