"""СКАЛЬП-версія: стоп за найближчим підтвердженим swing на M15/M30/H1 (НЕ D1), стоп у діапазоні [min%, max%], цілі = N×R від нового стопу.
Вхід — сигнальний (як зараз). Свічки: M1 → ресемпл 15m/30m/60m (лише закриті на момент сигналу). Комісія 0.04%/0.10% round-trip.
Показ у доларах при ризику $10/угоду за 18 діб. Фільтр дня: використано ≥50% добового ATR(5д) (опційно). Кластерний CI, ранні/пізні."""
import glob, sys, bisect, csv, random, collections, statistics as st
from pathlib import Path
random.seed(7); PL, CD = sys.argv[1], Path(sys.argv[2]); C = {}; R = {}
def m1(s):
    if s not in C:
        try: b = [dict(t=int(r["open_time"]), o=float(r["open"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"])) for r in csv.DictReader(open(CD / s / "1m.csv"))]
        except FileNotFoundError: b = []
        C[s] = (b, [x["t"] for x in b])
    return C[s]
def rs(s, tf):
    k = (s, tf)
    if k not in R:
        b, _ = m1(s); sec = tf * 60; g = collections.OrderedDict()
        for x in b:
            key = x["t"] - x["t"] % sec; y = g.get(key)
            if y is None: g[key] = dict(t=key, o=x["o"], h=x["h"], l=x["l"], c=x["c"], n=1)
            else: y["h"] = max(y["h"], x["h"]); y["l"] = min(y["l"], x["l"]); y["c"] = x["c"]; y["n"] += 1
        bars = [v for v in g.values() if v["n"] == tf]  # лише повні бари
        R[k] = (bars, [v["t"] for v in bars])
    return R[k]
def daily(s):
    k = (s, "d")
    if k not in R:
        try: b = [dict(t=int(r["open_time"]), h=float(r["high"]), l=float(r["low"])) for r in csv.DictReader(open(CD / s / "1d.csv"))]
        except FileNotFoundError: b = []
        R[k] = (b, [x["t"] for x in b])
    return R[k]
def swing_stop(s, tf, ts, d, ent, mn, mx, kk=2):
    bars, t = rs(s, tf); sec = tf * 60; i = bisect.bisect_right(t, ts - sec)  # бари, закриті до ts
    cl = bars[max(0, i - 120):i]; best = None
    for n in range(kk, len(cl) - kk):
        x = cl[n]
        if d == "L":
            if all(x["l"] < cl[j]["l"] for j in range(n - kk, n + kk + 1) if j != n):
                dist = (ent - x["l"]) / ent * 100
                if mn <= dist <= mx and (best is None or x["l"] > best): best = x["l"]
        else:
            if all(x["h"] > cl[j]["h"] for j in range(n - kk, n + kk + 1) if j != n):
                dist = (x["h"] - ent) / ent * 100
                if mn <= dist <= mx and (best is None or x["h"] < best): best = x["h"]
    atr = st.mean([x["h"] - x["l"] for x in cl[-14:]]) if len(cl) >= 14 else None
    return best, atr
def day_used(s, ts):
    b, t = daily(s); i = bisect.bisect_right(t, ts - 86400); d5 = b[max(0, i - 5):i]
    if len(d5) < 5: return None
    atr5 = sum(x["h"] - x["l"] for x in d5) / 5; h1, th = rs(s, 60); j = bisect.bisect_right(th, ts - 3600)
    day = [x for x in h1[max(0, j - 24):j] if x["t"] >= ts - ts % 86400]
    return (max(x["h"] for x in day) - min(x["l"] for x in day)) / atr5 if day and atr5 > 0 else None
plans = []
for f in sorted(glob.glob(PL)):
    for ln in open(f):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [e.split("@")[0] for e in p[7].split(",")]
        if "E" not in ev or "AMB" in ev: continue
        plans.append(dict(sym=p[1] + "USDT", d=p[2], ts=int(p[3]), ent=float(p[4])))
cut = sorted(p["ts"] for p in plans)[int(len(plans) * .6)]
def follow(s, d, ts, ent, stop, tp):
    b, t = m1(s); i = bisect.bisect_left(t, ts); j = bisect.bisect_right(t, ts + 24 * 3600); st_ = False
    for x in b[i:j]:
        if not st_:
            if not (x["l"] <= ent <= x["h"]): continue
            st_ = True
        if (x["l"] <= stop) if d == "L" else (x["h"] >= stop): return "SL"
        if (x["h"] >= tp) if d == "L" else (x["l"] <= tp): return "TP"
    return None
def ci(items):
    cl = collections.defaultdict(list)
    for k, v in items: cl[k].append(v)
    ks = list(cl)
    if len(ks) < 5: return (float("nan"),) * 2
    ms = []
    for _ in range(500):
        a = c = 0
        for _ in ks: v = cl[random.choice(ks)]; a += sum(v); c += len(v)
        ms.append(a / c)
    ms.sort(); return ms[12], ms[487]
res = collections.defaultdict(list); days = 18.0
for p in plans:
    s, d, ts, ent = p["sym"], p["d"], p["ts"], p["ent"]; du = day_used(s, ts)
    for tf in (15, 30, 60):
        for mn in (0.3, 0.5):
            for buf in (0.0, 0.1):
                sw, atr = swing_stop(s, tf, ts, d, ent, mn, 1.5)
                if sw is None or atr is None: continue
                stop = sw - buf * atr if d == "L" else sw + buf * atr; risk = abs(ent - stop); sp = risk / ent * 100
                if not (mn <= sp <= 1.6): continue
                for m in (1.0, 1.5, 2.0):
                    tp = ent + (1 if d == "L" else -1) * m * risk; r = follow(s, d, ts, ent, stop, tp)
                    if r is None: continue
                    gross = m if r == "TP" else -1.0
                    for filt in ("без", "день≥50%"):
                        if filt != "без" and not (du is not None and du >= .5): continue
                        res[(tf, mn, buf, m, filt)].append(((ts // 900, d), gross, sp, ts >= cut, r == "TP"))
print(f"планів {len(plans)}; \n\n| ТФ структури | мін стоп % | буфер ATR | ціль | фільтр | комісія | угод | частка виграшів | сер. стоп % | R/угоду | CI95 | рано | пізно | $ за 18 діб ($10/угоду) | $/добу |\n|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|")
rows = []
for k, v in res.items():
    if len(v) < 60: continue
    for cost in (0.04, 0.10):
        xs = [(a[0], a[1] - cost / a[2], a[3]) for a in v]; m = sum(x[1] for x in xs) / len(xs); lo, hi = ci([(x[0], x[1]) for x in xs])
        e = [x[1] for x in xs if not x[2]]; l = [x[1] for x in xs if x[2]]
        rows.append((m, k, cost, len(v), sum(a[4] for a in v) / len(v), sum(a[2] for a in v) / len(v), lo, hi, sum(e) / max(1, len(e)), sum(l) / max(1, len(l)), sum(x[1] for x in xs) * 10))
for m, k, cost, n, wr, sp, lo, hi, me, ml, usd in sorted(rows, reverse=True)[:30]:
    flag = " ✅" if lo > 0 and me > 0 and ml > 0 else ""
    print(f"| M{k[0]} | {k[1]} | {k[2]} | {k[3]}R | {k[4]} | {cost:.2f}% | {n} | {wr:.0%} | {sp:.2f} | {m:+.3f} | [{lo:+.3f}; {hi:+.3f}] | {me:+.2f} | {ml:+.2f} | {usd:+,.0f} | {usd/days:+,.0f} |{flag}")
print("\n✅ = CI>0 і рано>0 і пізно>0. Показано топ-30 з багатьох конфігурацій (кратне порівняння, відбір по найкращих) — без підтвердження на нових даних це НЕ доказ.")
