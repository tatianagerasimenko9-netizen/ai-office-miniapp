"""«Нове мислення» у доларах: фільтр дня (використано ≥50% добового ATR) × блок часу × схема стопу/цілі. Усі 842 угоди, ризик $10/угоду, 18 діб.
Схеми: A = як зараз (стоп/TP1 зі сигналу); B = стоп за D1-swing (буфер 0.2) + TP2. Комісія: 0.04% (лімітний вхід) і 0.10%.
Показ: скільки з програшних A стали виграшними в B / після фільтра, і сума в $. Свічки candles/{SYM}/{1m,1h,1d}.csv."""
import glob, sys, bisect, csv, collections
from pathlib import Path
sys.path.insert(0, "analysis"); sys.path.insert(0, ".")
from analysis.htf_stop_replay import structural_stop
OFF = 1790000000; PL, CD = sys.argv[1], Path(sys.argv[2]); C = {}
def ld(s, tf):
    k = (s, tf)
    if k not in C:
        try: b = [dict(t=int(r["open_time"]), o=float(r["open"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"])) for r in csv.DictReader(open(CD / s / f"{tf}.csv"))]
        except FileNotFoundError: b = []
        C[k] = (b, [x["t"] for x in b])
    return C[k]
def closed(s, tf, ts, sec, n):
    b, t = ld(s, tf); i = bisect.bisect_right(t, ts - sec); return b[max(0, i - n):i]
def follow(s, d, ts, ent, stop, tp):
    b, t = ld(s, "1m"); i = bisect.bisect_left(t, ts); j = bisect.bisect_right(t, ts + 48 * 3600); st = False
    for x in b[i:j]:
        if not st:
            if not (x["l"] <= ent <= x["h"]): continue
            st = True
        if (x["l"] <= stop) if d == "L" else (x["h"] >= stop): return "SL"
        if (x["h"] >= tp) if d == "L" else (x["l"] <= tp): return "TP"
    return None
rows = []
for f in sorted(glob.glob(PL)):
    for ln in open(f):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [(e.split("@")[0]) for e in p[7].split(",")]
        if "E" not in ev or "AMB" in ev: continue
        seen = [a for a in ev if a != "E"]
        if not seen or seen[0] not in ("T1", "SL"): continue
        s = p[1] + "USDT"; d = p[2]; ts = int(p[3]); ent = float(p[4]); sl = float(p[5]); risk = abs(ent - sl)
        tps = [float(x.split(":")[0]) for x in p[6].split(",")]
        rA = (abs(tps[0] - ent) / risk if seen[0] == "T1" else -1.0)
        d1 = closed(s, "1d", ts, 86400, 6); h1 = closed(s, "1h", ts, 3600, 24)
        used = None
        if len(d1) >= 5 and h1:
            atr5 = sum(x["h"] - x["l"] for x in d1[-5:]) / 5; day = [x for x in h1 if x["t"] >= ts - ts % 86400]
            if day and atr5 > 0: used = (max(x["h"] for x in day) - min(x["l"] for x in day)) / atr5
        # B: стоп за D1 swing + TP2
        rB = None; spB = None
        sw = structural_stop(ld(s, "1d")[0], ts, 86400, d, sl)
        if sw is not None:
            stop = sw - 0.2 * risk if d == "L" else sw + 0.2 * risk; rk = abs(ent - stop)
            res = follow(s, d, ts, ent, stop, tps[1])
            if res: rB = (abs(tps[1] - ent) / rk if res == "TP" else -1.0); spB = rk / ent * 100
        rows.append(dict(d=d, ts=ts, rA=rA, spA=risk / ent * 100, rB=rB, spB=spB, used=used, blk=13 <= (ts // 3600) % 24 < 17, win=seen[0] == "T1"))
days = 18.0
def line(nm, S, sch, cost):
    xs = [(x["rA"] - cost / x["spA"]) if sch == "A" else (x["rB"] - cost / x["spB"]) for x in S if (sch == "A" or x["rB"] is not None)]
    n = len(xs)
    if n == 0: return f"| {nm} | {sch} | {cost:.2f}% | 0 | | | |"
    return f"| {nm} | {sch} | {cost:.2f}% | {n} | {sum(xs)/n:+.3f} | {sum(xs)*10:+,.0f} | {sum(xs)*10/days:+,.0f} |"
print(f"угод {len(rows)}\n\n| підмножина | схема | комісія | угод | R/угоду | $ за 18 діб (ризик $10) | $/добу |\n|--|--|--|--|--|--|--|")
sets = [("усі (як зараз)", rows), ("день рухається (≥50% ATR)", [x for x in rows if x["used"] is not None and x["used"] >= .5]),
        ("день рухається + блок 13–17 UTC", [x for x in rows if x["used"] is not None and x["used"] >= .5 and x["blk"]])]
for nm, S in sets:
    for sch in ("A", "B"):
        for c in (0.04, 0.10): print(line(nm, S, sch, c))
L = [x for x in rows if not x["win"]]; flipA = [x for x in L if x["used"] is not None and x["used"] < .5]
Bw = [x for x in L if x["rB"] is not None and x["rB"] > 0]
print(f"\nПрограшних A: {len(L)}. З них: у «день не рухається» (<50% ATR) — {len(flipA)} (їх фільтр прибирає); стали б виграшними зі стопом за D1+TP2 — {len(Bw)} ({len(Bw)/len(L):.0%}).")
Wl = [x for x in rows if x["win"] and x["rB"] is not None and x["rB"] < 0]
print(f"Виграшних A, які за схемою B стали б програшними: {len(Wl)} з {sum(1 for x in rows if x['win'])}. Тобто B рятує {len(Bw)} програшів, але ламає {len(Wl)} виграшів.")
