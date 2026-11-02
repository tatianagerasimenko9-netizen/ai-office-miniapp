"""Теорія власниці: «сильна свічка + великий рівень» покращують точку входу (менший стоп, більший прибуток)?
Ознаки лише з ЗАКРИТИХ свічок на момент сигналу (M15 з M1):
 F1 сильна свічка: серед останніх 4 закритих M15 є свічка у напрямку угоди з діапазоном ≥1.2×ATR14(M15) і об'ємом ≥2×SMA20(об'єм)   [пороги = наша реалізація office2/strongcandle.py, ГІПОТЕЗА щодо джерел]
 F2 великий рівень: вхід (проксі рівня) у межах 0.3×ATR(H1) від підтвердженого swing H4 або D1 (k=2)                                   [пороги ГІПОТЕЗА]
Результат у $ при ризику $10/угоду: (а) стоп/ціль як зараз; (б) стоп за екстремумом сильної свічки (−0.1 ATR M15), у межах 0.3–1.5%, ціль 1.5R та 2R."""
import glob, sys, bisect, csv, random, collections, statistics as st
from pathlib import Path
random.seed(7); PL, CD = sys.argv[1], Path(sys.argv[2]); C = {}; R = {}
def m1(s):
    if s not in C:
        try: b = [dict(t=int(r["open_time"]), o=float(r["open"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"]), v=float(r.get("volume") or 0)) for r in csv.DictReader(open(CD / s / "1m.csv"))]
        except FileNotFoundError: b = []
        C[s] = (b, [x["t"] for x in b])
    return C[s]
def rs(s, tf):
    k = (s, tf)
    if k not in R:
        b, _ = m1(s); sec = tf * 60; g = collections.OrderedDict()
        for x in b:
            key = x["t"] - x["t"] % sec; y = g.get(key)
            if y is None: g[key] = dict(t=key, o=x["o"], h=x["h"], l=x["l"], c=x["c"], v=x["v"], n=1)
            else: y["h"] = max(y["h"], x["h"]); y["l"] = min(y["l"], x["l"]); y["c"] = x["c"]; y["v"] += x["v"]; y["n"] += 1
        bars = [v for v in g.values() if v["n"] == tf]; R[k] = (bars, [v["t"] for v in bars])
    return R[k]
def htf(s, tf):
    k = (s, "h", tf)
    if k not in R:
        try: b = [dict(t=int(r["open_time"]), h=float(r["high"]), l=float(r["low"])) for r in csv.DictReader(open(CD / s / f"{tf}.csv"))]
        except FileNotFoundError: b = []
        R[k] = (b, [x["t"] for x in b])
    return R[k]
def swings(s, tf, ts, sec, kk=2, n=120):
    b, t = htf(s, tf); i = bisect.bisect_right(t, ts - sec); cl = b[max(0, i - n):i]; out = []
    for j in range(kk, len(cl) - kk):
        if all(cl[j]["l"] < cl[q]["l"] for q in range(j - kk, j + kk + 1) if q != j): out.append(cl[j]["l"])
        if all(cl[j]["h"] > cl[q]["h"] for q in range(j - kk, j + kk + 1) if q != j): out.append(cl[j]["h"])
    return out
def follow(s, d, ts, ent, stop, tp, hz=24 * 3600):
    b, t = m1(s); i = bisect.bisect_left(t, ts); j = bisect.bisect_right(t, ts + hz); started = False
    for x in b[i:j]:
        if not started:
            if not (x["l"] <= ent <= x["h"]): continue
            started = True
        if (x["l"] <= stop) if d == "L" else (x["h"] >= stop): return "SL"
        if (x["h"] >= tp) if d == "L" else (x["l"] <= tp): return "TP"
    return None
plans = []
for f in sorted(glob.glob(PL)):
    for ln in open(f):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [e.split("@")[0] for e in p[7].split(",")]
        if "E" not in ev or "AMB" in ev: continue
        seen = [a for a in ev if a != "E"]
        if not seen or seen[0] not in ("T1", "SL"): continue
        ent, sl = float(p[4]), float(p[5]); risk = abs(ent - sl); tp1 = float(p[6].split(",")[0].split(":")[0])
        plans.append(dict(sym=p[1] + "USDT", d=p[2], ts=int(p[3]), ent=ent, sl=sl, risk=risk, sp=risk / ent * 100,
                          rA=(abs(tp1 - ent) / risk if seen[0] == "T1" else -1.0), win=seen[0] == "T1"))
cut = sorted(p["ts"] for p in plans)[int(len(plans) * .6)]
for p in plans:
    s, d, ts, ent = p["sym"], p["d"], p["ts"], p["ent"]; b15, t15 = rs(s, 15); i = bisect.bisect_right(t15, ts - 900)
    cl = b15[max(0, i - 40):i]; p["f1"] = None; p["f2"] = None; p["cstop"] = None
    if len(cl) >= 24:
        atr = st.mean([x["h"] - x["l"] for x in cl[-14:]]); vs = st.mean([x["v"] for x in cl[-20:]])
        strong = None
        for x in cl[-4:]:
            ok_dir = (x["c"] > x["o"]) if d == "L" else (x["c"] < x["o"])
            if ok_dir and (x["h"] - x["l"]) >= 1.2 * atr and x["v"] >= 2 * vs: strong = x
        p["f1"] = strong is not None
        if strong is not None:
            stop = strong["l"] - 0.1 * atr if d == "L" else strong["h"] + 0.1 * atr; sp = abs(ent - stop) / ent * 100
            if 0.3 <= sp <= 1.5 and ((stop < ent) if d == "L" else (stop > ent)): p["cstop"] = (stop, sp)
        h1, th = rs(s, 60); j = bisect.bisect_right(th, ts - 3600); hh = h1[max(0, j - 14):j]
        if len(hh) >= 14:
            atrh = st.mean([x["h"] - x["l"] for x in hh]); lv = swings(s, "4h", ts, 14400) + swings(s, "1d", ts, 86400)
            p["f2"] = any(abs(ent - L) <= 0.3 * atrh for L in lv) if lv else False
def ci(vals):
    cl = collections.defaultdict(list)
    for k, v in vals: cl[k].append(v)
    ks = list(cl)
    if len(ks) < 5: return None
    ms = []
    for _ in range(500):
        a = c = 0
        for _ in ks: v = cl[random.choice(ks)]; a += sum(v); c += len(v)
        ms.append(a / c)
    ms.sort(); return ms[12], ms[487]
days = 18.0
def show(nm, S):
    if len(S) < 15: print(f"| {nm} | {len(S)} | мало | | | | |"); return
    for cost in (0.04, 0.10):
        xs = [(((x["ts"] // 900), x["d"]), x["rA"] - cost / x["sp"], x["ts"] >= cut) for x in S]
        m = sum(v for _, v, _ in xs) / len(xs); c = ci([(k, v) for k, v, _ in xs]); cs = f"[{c[0]:+.2f}; {c[1]:+.2f}]" if c else "-"
        e = [v for _, v, q in xs if not q]; l = [v for _, v, q in xs if q]
        print(f"| {nm} | як зараз | {cost:.2f}% | {len(S)} | {sum(x['win'] for x in S)/len(S):.0%} | {m:+.3f} | {cs} | {sum(e)/max(1,len(e)):+.2f}/{sum(l)/max(1,len(l)):+.2f} | {sum(v for _,v,_ in xs)*10:+,.0f} |")
print(f"угод {len(plans)}; F1 визначено {sum(p['f1'] is not None for p in plans)}, F2 визначено {sum(p['f2'] is not None for p in plans)}\n")
print("| підмножина | стоп/ціль | комісія | угод | частка виграшів | R/угоду | CI95 | рано/пізно | $ за 18 діб ($10/угоду) |\n|--|--|--|--|--|--|--|--|--|")
sets = [("усі", plans), ("F1 сильна свічка", [p for p in plans if p["f1"]]), ("немає F1", [p for p in plans if p["f1"] is False]),
        ("F2 великий рівень", [p for p in plans if p["f2"]]), ("немає F2", [p for p in plans if p["f2"] is False]),
        ("F1 і F2", [p for p in plans if p["f1"] and p["f2"]])]
for nm, S in sets: show(nm, S)
print("\n| стоп за екстремумом сильної свічки | ціль | комісія | угод | частка виграшів | R/угоду | $ за 18 діб | сер. стоп % |\n|--|--|--|--|--|--|--|--|")
for nm, S in (("F1", [p for p in plans if p["f1"] and p["cstop"]]), ("F1 і F2", [p for p in plans if p["f1"] and p["f2"] and p["cstop"]])):
    for m in (1.5, 2.0):
        res = []
        for x in S:
            stop, sp = x["cstop"]; risk = abs(x["ent"] - stop); tp = x["ent"] + (1 if x["d"] == "L" else -1) * m * risk
            r = follow(x["sym"], x["d"], x["ts"], x["ent"], stop, tp)
            if r: res.append(((m if r == "TP" else -1.0), sp))
        for cost in (0.04, 0.10):
            if len(res) < 10: print(f"| {nm} | {m}R | {cost:.2f}% | {len(res)} | мало | | | |"); continue
            net = [g - cost / sp for g, sp in res]
            print(f"| {nm} | {m}R | {cost:.2f}% | {len(res)} | {sum(g > 0 for g, _ in res)/len(res):.0%} | {sum(net)/len(net):+.3f} | {sum(net)*10:+,.0f} | {sum(sp for _, sp in res)/len(res):.2f} |")
print("\nУВАГА: пороги — наша реалізація, не прямі числа з джерел; вибірки малі; без підтвердження на нових даних це гіпотеза.")
