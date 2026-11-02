"""Тест «глибшого входу»: 65% програшів — напрям правильний, але ціна пішла проти входу (медіана 1.44R за стоп). Гіпотеза: вхід зарано.
Лімітний вхід на k×ризику ГЛИБШЕ за сигнальний вхід (k=0 — як зараз), SL той самий, ціль TP1/TP2. Не виконаний ліміт = немає угоди.
Свічки M1. Комісія 0.04% (maker-вхід) / 0.10% / 0.15% round-trip для порівняння. Кластерний CI, ранні/пізні 60/40."""
import glob, sys, bisect, csv, random, collections
from pathlib import Path
random.seed(7); OFF = 1790000000; PL, CD = sys.argv[1], Path(sys.argv[2]); C = {}
def m1(s):
    if s not in C:
        try: b = [dict(t=int(r["open_time"]), h=float(r["high"]), l=float(r["low"])) for r in csv.DictReader(open(CD / s / "1m.csv"))]
        except FileNotFoundError: b = []
        C[s] = (b, [x["t"] for x in b])
    return C[s]
plans = []
for f in sorted(glob.glob(PL)):
    for ln in open(f):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [e.split("@")[0] for e in p[7].split(",")]
        if "E" not in ev or "AMB" in ev: continue
        plans.append(dict(sym=p[1] + "USDT", d=1 if p[2] == "L" else -1, ts=int(p[3]), ent=float(p[4]), sl=float(p[5]), tps=[float(x.split(":")[0]) for x in p[6].split(",")]))
cut = sorted(p["ts"] for p in plans)[int(len(plans) * .6)]
def sim(p, k, tpi, horizon=24 * 3600):
    b, t = m1(p["sym"]); d = p["d"]; risk = abs(p["ent"] - p["sl"]); L = p["ent"] - d * k * risk; tp = p["tps"][tpi]
    i = bisect.bisect_left(t, p["ts"]); j = bisect.bisect_right(t, p["ts"] + 48 * 3600); fill = None
    for n in range(i, j):
        x = b[n]
        if (x["l"] <= L) if d == 1 else (x["h"] >= L): fill = n; break
        if (x["h"] >= tp) if d == 1 else (x["l"] <= tp): return "MISS", None, None   # ціль без входу
    if fill is None: return "NOFILL", None, None
    r2 = abs(L - p["sl"])
    if r2 <= 0: return "NOFILL", None, None
    for x in b[fill: bisect.bisect_right(t, t[fill] + horizon)]:
        if (x["l"] <= p["sl"]) if d == 1 else (x["h"] >= p["sl"]): return "SL", -1.0, r2 / L * 100
        if (x["h"] >= tp) if d == 1 else (x["l"] <= tp): return "TP", abs(tp - L) / r2, r2 / L * 100
    return "OPEN", None, None
def ci(items):
    cl = collections.defaultdict(list)
    for k, v in items: cl[k].append(v)
    ks = list(cl); ms = []
    for _ in range(600):
        s = c = 0
        for _ in ks: v = cl[random.choice(ks)]; s += sum(v); c += len(v)
        ms.append(s / c)
    ms.sort(); return ms[15], ms[584]
print(f"планів {len(plans)}\n\n| глибина входу k×R | ціль | комісія | угод | виконано % | частка виграшів | net R/угоду | CI95 | рано | пізно | сер. стоп % | $/добу при $10 |\n|--|--|--|--|--|--|--|--|--|--|--|--|")
days = 18.0
for tpi in (0, 1):
    for cost in (0.04, 0.10):
        for k in (0.0, 0.25, 0.5, 0.75):
            R = []; fills = 0
            for p in plans:
                st, r, sp = sim(p, k, tpi)
                if st in ("TP", "SL"): fills += 1; R.append(((p["ts"] // 900, p["d"]), r - cost / sp, p["ts"] >= cut, sp, st))
            if len(R) < 30: continue
            m = sum(x[1] for x in R) / len(R); lo, hi = ci([(x[0], x[1]) for x in R])
            e = [x[1] for x in R if not x[2]]; l = [x[1] for x in R if x[2]]
            print(f"| {k} | TP{tpi+1} | {cost:.2f}% | {len(R)} | {fills/len(plans):.0%} | {sum(x[4]=='TP' for x in R)/len(R):.0%} | {m:+.3f} | [{lo:+.3f}; {hi:+.3f}] | {sum(e)/max(1,len(e)):+.2f} | {sum(l)/max(1,len(l)):+.2f} | {sum(x[3] for x in R)/len(R):.2f} | {sum(x[1] for x in R)*10/days:+.0f} |")
print("\nMISS = ціль досягнута без виконання ліміту — упущені перемоги враховані як відсутність угоди (чесно). Це 16 конфігурацій; потрібне підтвердження на нових даних.")
