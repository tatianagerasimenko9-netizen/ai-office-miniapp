"""Сітка рішень: стоп за HTF-swing (H4/D1) × ціль (TP1/TP2/TP3) × мін. R до цілі. Net R з комісією 0.15%, кластерний bootstrap, ранні 60% / пізні 40%.
Свічки: candles/{SYM}/{1m,4h,1d}.csv. Потрібен analysis/htf_stop_replay.py (structural_stop, load_bars). ГІПОТЕЗА-рівень: лише порівняння, не live."""
import glob, sys, random, collections, bisect
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[0])); sys.path.insert(0, "analysis"); sys.path.insert(0, ".")
from analysis.htf_stop_replay import load_bars, structural_stop
random.seed(7); OFF = 1790000000
PL = sys.argv[1]; CD = Path(sys.argv[2])
plans = []
for f in sorted(glob.glob(PL)):
    for ln in open(f):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[0].isdigit(): continue
        ev = [e.split("@")[0] for e in p[7].split(",")] if p[7] else []
        if "E" not in ev or "AMB" in ev: continue
        plans.append(dict(sym=p[1] + "USDT", d=p[2], ts=int(p[3]), ent=float(p[4]), sl=float(p[5]), tps=[float(x.split(":")[0]) for x in p[6].split(",")]))
cache = {}
def bars(sym):
    if sym not in cache:
        r = CD / sym
        try: cache[sym] = {tf: load_bars(r / f"{tf}.csv") for tf in ("1m", "4h", "1d")}
        except FileNotFoundError: cache[sym] = None
    return cache[sym]
def follow(b1, times, ts, d, ent, stop, tp):
    i = bisect.bisect_left(times, ts); j = bisect.bisect_right(times, ts + 48 * 3600); started = False
    for x in b1[i:j]:
        if not started:
            if not (x["l"] <= ent <= x["h"]): continue
            started = True
        hs = x["l"] <= stop if d == "L" else x["h"] >= stop
        ht = x["h"] >= tp if d == "L" else x["l"] <= tp
        if hs: return "SL"
        if ht: return "TP"
    return None
CFG = [(tf, buf, k, mr) for tf in ("4h", "1d") for buf in (0.0, 0.2) for k in (1, 2, 3) for mr in (0.0, 1.0, 2.0)]
rows = collections.defaultdict(list)
cut = sorted(p["ts"] for p in plans)[int(len(plans) * 0.6)]
for p in plans:
    B = bars(p["sym"])
    if not B: continue
    b1 = B["1m"]; times = [x["t"] for x in b1]; risk0 = abs(p["ent"] - p["sl"])
    for tf in ("4h", "1d"):
        sw = structural_stop(B[tf], p["ts"], 14400 if tf == "4h" else 86400, p["d"], p["sl"])
        if sw is None: continue
        for buf in (0.0, 0.2):
            stop = sw - buf * risk0 if p["d"] == "L" else sw + buf * risk0
            risk = abs(p["ent"] - stop)
            if risk <= 0: continue
            for k in (1, 2, 3):
                tp = p["tps"][k - 1]; rr = abs(tp - p["ent"]) / risk
                res = follow(b1, times, p["ts"], p["d"], p["ent"], stop, tp)
                if res is None: continue
                net = (rr if res == "TP" else -1.0) - 0.15 / (risk / p["ent"] * 100)
                for mr in (0.0, 1.0, 2.0):
                    if rr >= mr: rows[(tf, buf, k, mr)].append(((p["ts"] // 900, p["d"]), net, p["ts"] >= cut, risk / p["ent"] * 100))
def ci(items):
    cl = collections.defaultdict(list)
    for key, v in items: cl[key].append(v)
    ks = list(cl); ms = []
    for _ in range(1000):
        t = c = 0
        for _ in ks:
            v = cl[random.choice(ks)]; t += sum(v); c += len(v)
        ms.append(t / c)
    ms.sort(); return ms[25], ms[974]
print(f"планів {len(plans)}; межа часу ts={cut}\n\n| ТФ стопу | буфер | ціль | мін R | n | net R | CI95 | рано n/netR | пізно n/netR | сер. стоп % |\n|--|--|--|--|--|--|--|--|--|--|")
out = []
for cfg in CFG:
    r = rows.get(cfg, [])
    if len(r) < 40: continue
    m = sum(x[1] for x in r) / len(r); lo, hi = ci([(x[0], x[1]) for x in r])
    e = [x for x in r if not x[2]]; l = [x for x in r if x[2]]
    me = sum(x[1] for x in e) / max(1, len(e)); ml = sum(x[1] for x in l) / max(1, len(l))
    out.append((m, cfg, len(r), lo, hi, len(e), me, len(l), ml, sum(x[3] for x in r) / len(r)))
for m, cfg, n, lo, hi, ne, me, nl, ml, sp in sorted(out, reverse=True):
    flag = " ✅" if lo > 0 and me > 0 and ml > 0 else ""
    print(f"| {cfg[0]} | {cfg[1]} | TP{cfg[2]} | {cfg[3]} | {n} | {m:+.3f} | [{lo:+.3f}; {hi:+.3f}] | {ne}/{me:+.3f} | {nl}/{ml:+.3f} | {sp:.2f} |{flag}")
print("\n✅ = CI>0 І рано>0 І пізно>0. Це 36 конфігурацій (кратне порівняння): навіть ✅ потребує підтвердження на нових даних (shadow) — не live.")
