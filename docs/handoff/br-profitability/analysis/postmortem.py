"""Постмортем: чим відрізняються виграшні й програшні входи B&R (модель TP1 vs SL), і чому програші.
Ознаки рахуються на момент створення плану лише із закритих свічок. Це ОПИСОВА діагностика (ознаки — гіпотези, не правила джерел).
Свічки: candles/{SYM}/{1m,1h,4h,1d}.csv (+BTCUSDT). Запуск: postmortem.py PLANS_GLOB CANDLES_DIR"""
import glob, sys, random, bisect, collections
from pathlib import Path
random.seed(7); OFF = 1790000000
PL, CD = sys.argv[1], Path(sys.argv[2])
def load(p):
    import csv
    try: return [dict(t=int(r["open_time"]), o=float(r["open"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"])) for r in csv.DictReader(open(p))]
    except FileNotFoundError: return None
C = {}
def bars(sym, tf):
    k = (sym, tf)
    if k not in C: C[k] = load(CD / sym / f"{tf}.csv"); C[k + ("t",)] = [x["t"] for x in C[k]] if C[k] else []
    return C[k], C[k + ("t",)]
def closed(sym, tf, ts, sec, n):
    b, t = bars(sym, tf)
    if not b: return []
    i = bisect.bisect_right(t, ts - sec)  # бари, відкриті не пізніше ts-sec → закриті до ts
    return b[max(0, i - n):i]
plans = []
for f in sorted(glob.glob(PL)):
    for ln in open(f):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [(e.split("@")[0], int(e.split("@")[1]) + OFF) for e in p[7].split(",")]
        k = [a for a, _ in ev]
        if "E" not in k or "AMB" in k: continue
        seen = [(a, t) for a, t in ev if a != "E"]
        if not seen or seen[0][0] not in ("T1", "SL"): continue
        ent, sl, ts = float(p[4]), float(p[5]), int(p[3]); risk = abs(ent - sl); d = p[2]
        tps = [float(x.split(":")[0]) for x in p[6].split(",")]
        win = seen[0][0] == "T1"
        plans.append(dict(sym=p[1] + "USDT", d=d, ts=ts, ent=ent, sl=sl, risk=risk, sp=risk / ent * 100, tp1=tps[0], win=win,
                          r=(abs(tps[0] - ent) / risk if win else -1.0), sl_ts=(seen[0][1] if not win else None), cl=(ts // 900, d)))
sgn = lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
def feats(p):
    s, d, ts = p["sym"], 1 if p["d"] == "L" else -1, p["ts"]; F = {}
    d1 = closed(s, "1d", ts, 86400, 21); h4 = closed(s, "4h", ts, 14400, 30); h1 = closed(s, "1h", ts, 3600, 30)
    btc = closed("BTCUSDT", "1h", ts, 3600, 13)
    if len(d1) >= 6: F["D1 тренд (5д) збігається з напрямком"] = "так" if sgn(d1[-1]["c"] - d1[-6]["c"]) == d else "ні"
    if len(h4) >= 7: F["H4 тренд (6 барів) збігається"] = "так" if sgn(h4[-1]["c"] - h4[-7]["c"]) == d else "ні"
    if len(h1) >= 13: F["H1 імпульс (12 барів) збігається"] = "так" if sgn(h1[-1]["c"] - h1[-13]["c"]) == d else "ні"
    if len(btc) >= 13: F["BTC H1 (12 барів) збігається"] = "так" if sgn(btc[-1]["c"] - btc[-13]["c"]) == d else "ні"
    if len(d1) >= 20:
        hi, lo = max(x["h"] for x in d1[-20:]), min(x["l"] for x in d1[-20:])
        if hi > lo:
            pos = (p["ent"] - lo) / (hi - lo)
            F["позиція у діапазоні D1(20д) для напрямку"] = ("біля краю напрямку (≥0.8)" if (pos >= .8 if d == 1 else pos <= .2) else ("біля протилежного краю (≤0.2)" if (pos <= .2 if d == 1 else pos >= .8) else "середина"))
    if len(d1) >= 6 and d1:
        atr5 = sum(x["h"] - x["l"] for x in d1[-5:]) / 5
        day = [x for x in closed(s, "1h", ts, 3600, 24) if x["t"] >= ts - ts % 86400]
        if day and atr5 > 0:
            used = (max(x["h"] for x in day) - min(x["l"] for x in day)) / atr5
            F["добовий ATR використано"] = "≥80%" if used >= .8 else ("50–80%" if used >= .5 else "<50%")
    # перешкода за напрямком між входом і TP1 (swing H1 за 30 барів)
    if len(h1) >= 5:
        tgt = p["tp1"]
        if d == 1: obs = [x["h"] for x in h1[-30:] if p["ent"] < x["h"] <= tgt]
        else: obs = [x["l"] for x in h1[-30:] if tgt <= x["l"] < p["ent"]]
        F["перешкода H1 між входом і TP1"] = "є" if obs else "немає"
    F["стоп ≥0.5%"] = "так" if p["sp"] >= .5 else "ні"
    F["година UTC (блок)"] = ["00–07", "07–13", "13–17", "17–21", "21–24"][[0, 7, 13, 17, 21].index(max(h for h in (0, 7, 13, 17, 21) if h <= (ts // 3600) % 24))]
    return F
def ci(items):
    cl = collections.defaultdict(list)
    for k, v in items: cl[k].append(v)
    ks = list(cl)
    if len(ks) < 3: return None
    ms = []
    for _ in range(800):
        t = c = 0
        for _ in ks:
            v = cl[random.choice(ks)]; t += sum(v); c += len(v)
        ms.append(t / c)
    ms.sort(); return ms[20], ms[779]
rows = collections.defaultdict(list); skipped = 0
cut = sorted(p["ts"] for p in plans)[int(len(plans) * .6)]
for p in plans:
    F = feats(p)
    if not F: skipped += 1; continue
    for k, v in F.items(): rows[(k, v)].append(p)
print(f"угод {len(plans)}, без свічок/ознак {skipped}; виграш = TP1 раніше SL; R TP1-варіант (gross, без комісії)\n")
print("| ознака | значення | n | частка виграшів | сер. R | CI95 R | рано R | пізно R |\n|--|--|--|--|--|--|--|--|")
for (k, v), L in sorted(rows.items()):
    if len(L) < 25: continue
    e = [x["r"] for x in L if x["ts"] < cut]; l = [x["r"] for x in L if x["ts"] >= cut]
    c = ci([(x["cl"], x["r"]) for x in L]); cs = f"[{c[0]:+.2f}; {c[1]:+.2f}]" if c else "-"
    print(f"| {k} | {v} | {len(L)} | {sum(x['win'] for x in L)/len(L):.0%} | {sum(x['r'] for x in L)/len(L):+.3f} | {cs} | {sum(e)/max(1,len(e)):+.2f} | {sum(l)/max(1,len(l)):+.2f} |")
# причини програшів: SL, після якого ціна все ж дійшла до TP1 за 24 год (правильний напрям, поганий стоп/таймінг) vs ні (хибний напрям)
loss = [p for p in plans if not p["win"]]; right = wrong = 0; unk = 0
for p in loss:
    b, t = bars(p["sym"], "1m")
    if not b: unk += 1; continue
    i = bisect.bisect_right(t, p["sl_ts"]); j = bisect.bisect_right(t, p["sl_ts"] + 24 * 3600); hit = False
    for x in b[i:j]:
        if (x["h"] >= p["tp1"]) if p["d"] == "L" else (x["l"] <= p["tp1"]): hit = True; break
    right += hit; wrong += (not hit)
print(f"\nПрограшних {len(loss)}: після SL ціна дійшла до TP1 за 24 год у {right} ({right/max(1,len(loss)):.0%}) — напрям правильний, вибило стоп/таймінг; не дійшла у {wrong} ({wrong/max(1,len(loss)):.0%}) — напрям/аналіз хибний; без свічок {unk}.")
print("\nОБМЕЖЕННЯ: ознаки — описові гіпотези; 25+ значень × без поправки на кратність; висновок лише якщо CI не містить 0 і знак збігається рано/пізно.")
