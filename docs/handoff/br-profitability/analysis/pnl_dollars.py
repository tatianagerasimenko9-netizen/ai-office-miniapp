"""P&L у доларах для поточних сигналів B&R (скальп-налаштування як є: стоп/цілі зі сигналу). Фіксований ризик на угоду $R. 
Схеми виходу: TP1 цілком; TP2 цілком; TP3 цілком; 30/40/30 по TP1/TP2/TP3 (як у картці), SL лишається початковим (без беззбитку).
Модель: події з БД (перша торкнута ціль vs SL у хронології), AMB виключено. Витрати: cost% від ціни на угоду (round-trip) -> у R = cost/stop%. Чутливість: 0 / 0.05 / 0.10 / 0.15%."""
import glob, os, datetime, collections
D = os.path.join(os.path.dirname(__file__), "..", "data")
plans = []
for f in sorted(glob.glob(os.path.join(D, "br_plans_*.psv"))):
    for ln in open(f, encoding="utf-8"):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [(e.split("@")[0], int(e.split("@")[1])) for e in p[7].split(",")]
        k = [a for a, _ in ev]
        if "E" not in k or "AMB" in k: continue
        seen = [a for a, _ in ev if a != "E"]
        if not seen: continue
        ent, sl = float(p[4]), float(p[5]); risk = abs(ent - sl)
        rk = [abs(float(x.split(":")[0]) - ent) / risk for x in p[6].split(",")]
        plans.append(dict(seen=seen, rk=rk, sp=risk / ent * 100, ts=int(p[3])))
def r_scheme(pl, name):
    s, rk = pl["seen"], pl["rk"]
    sl_i = s.index("SL") if "SL" in s else 10**9
    hit = lambda t: t in s and s.index(t) < sl_i
    if name == "TP1": return rk[0] if hit("T1") else (-1 if "SL" in s else None)
    if name == "TP2": return rk[1] if hit("T2") else (-1 if "SL" in s else None)
    if name == "TP3": return rk[2] if hit("T3") else (-1 if "SL" in s else None)
    if name == "30/40/30":
        if not hit("T1") and "SL" not in s: return None
        w = (0.3, 0.4, 0.3); tot = 0.0
        for i, t in enumerate(("T1", "T2", "T3")): tot += w[i] * (rk[i] if hit(t) else -1)
        return tot
days = (max(p["ts"] for p in plans) - min(p["ts"] for p in plans)) / 86400
print(f"угод з результатом: {len(plans)}, період ≈ {days:.1f} діб, ≈ {len(plans)/days:.0f} угод/добу\n")
print("| схема виходу | витрати | сер. R/угоду | усього R | $ при ризику $10 | $100 | $1000 | $/добу при $100 |\n|--|--|--|--|--|--|--|--|")
for sch in ("TP1", "TP2", "TP3", "30/40/30"):
    rr = [(r_scheme(p, sch), p["sp"]) for p in plans]; rr = [(r, sp) for r, sp in rr if r is not None]
    for c in (0.0, 0.05, 0.10, 0.15):
        tot = sum(r - c / sp for r, sp in rr)
        print(f"| {sch} | {c:.2f}% | {tot/len(rr):+.3f} | {tot:+.1f} | {tot*10:+,.0f} | {tot*100:+,.0f} | {tot*1000:+,.0f} | {tot*100/days:+,.0f} |")
print("\nR = частка ризику. $ = R × ризик на угоду. Комісія Binance Futures taker ≈0.04%/бік ≈0.08–0.10% round-trip + ковзання; 0.15% — консервативна модель.")
