"""READ-ONLY. РІВНІ НА ІСТОРІЇ: що частіше відбувалось після закриття дня за рівнем (28.11.2026, прохання власниці: «щоб аналітик казав вірогідніший варіант — як було на історії»).
Рівні — ті самі, що показує апка (office_levels.find_levels, лише автоматичні, без рівнів автора), перераховані НА КОЖЕН ДЕНЬ лише за минулими свічками (останні 800 діб). ПРАВИЛА ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА):
 ПРОБІЙ ВНИЗ : учора закриття було не нижче низу зони, сьогодні закриття нижче низу зони.   Далі за 30 діб що раніше: ціна торкнулась НАСТУПНОГО рівня знизу («дійшла») чи день закрився вище верху зони («повернулась»).
 ПРОБІЙ ВГОРУ: дзеркально (закриття вище верху зони; далі — торкання наступного рівня зверху чи закриття нижче низу зони).
 ПОВЕРНЕННЯ  : за останні 5 діб мінімум був нижче низу зони, а сьогодні — перше закриття вище верху зони (правило Герчика «повернення вище рівня — сигнал на купівлю»). Далі: дійшла до наступного рівня зверху чи закрилась нижче низу зони.
 Показуємо: скільки випадків, частка «дійшла», «повернулась», «нічого за 30 діб»; медіана днів; окремо за відстанню до наступного рівня (<5% / 5–10% / >10%) і за тим, чи ціна вище середньої за 200 діб.
 Також рух у «простих грошах»: вхід на закритті дня пробою в бік пробою, стоп — закриття за протилежний край зони (вихід на тому закритті), ціль — наступний рівень; результат у R (R = відстань від входу до протилежного краю зони), комісія 0,10%.
Використання: levels_hist.py OUT_CSV DAILY_CSV[:NAME] ...   (DAILY_CSV: open_time,high,low,close)  |  levels_hist.py OUT_CSV --dir CANDLES_DIR (15m.csv → денні)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
import numpy as np, pandas as pd
import office_levels as ol
OUT = sys.argv[1]; SRC = []
if sys.argv[2] == "--dir":
    for s in sorted(os.listdir(sys.argv[3])):
        f = f"{sys.argv[3]}/{s}/15m.csv"
        if os.path.exists(f):
            d = pd.read_csv(f, usecols=["open_time", "high", "low", "close"]); g = d.groupby(d.open_time // 86400 * 86400).agg(n=("close", "size"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g = g[g.n >= 90]
            SRC.append((s, [{"t": float(a), "h": float(b), "l": float(c), "c": float(e)} for a, b, c, e in zip(g.open_time, g.high, g.low, g.close)]))
else:
    for a in sys.argv[2:]:
        f, _, nm = a.partition(":"); d = pd.read_csv(f).sort_values("open_time"); SRC.append((nm or os.path.basename(f), [{"t": float(r.open_time), "h": float(r.high), "l": float(r.low), "c": float(r.close)} for r in d.itertuples()]))
rows = []
for name, days in SRC:
    n = len(days)
    if n < 460: continue
    c = np.array([d["c"] for d in days]); h = np.array([d["h"] for d in days]); l = np.array([d["l"] for d in days]); ma = pd.Series(c).rolling(200).mean().to_numpy()
    for i in range(400, n - 1):
        lv = ol.find_levels(days[max(0, i - 800):i])                                    # рівні, відомі ДО сьогоднішнього дня
        if not lv: continue
        for z in lv:
            ev = None
            if c[i - 1] >= z["lo"] and c[i] < z["lo"]: ev = "DOWN"
            elif c[i - 1] <= z["hi"] and c[i] > z["hi"]: ev = "RECLAIM" if l[max(0, i - 4):i + 1].min() < z["lo"] else "UP"
            if not ev: continue
            side = -1 if ev == "DOWN" else 1
            nx = [q for q in lv if q["hi"] < z["lo"]][-1:] if side < 0 else [q for q in lv if q["lo"] > z["hi"]][:1]
            if not nx: continue
            tgt = nx[0]["hi"] if side < 0 else nx[0]["lo"]; back = z["hi"] if side < 0 else z["lo"]; e = c[i]; risk = abs(e - back); dist = abs(tgt - e) / e * 100
            if risk <= 0 or dist < 0.3: continue
            res = "NONE"; dn = np.nan; r = np.nan
            for j in range(i + 1, min(n, i + 31)):
                if (l[j] <= tgt) if side < 0 else (h[j] >= tgt): res = "REACH"; dn = j - i; r = abs(tgt - e) / risk; break
                if (c[j] > back) if side < 0 else (c[j] < back): res = "BACK"; dn = j - i; r = side * (c[j] - e) / risk; break
            if res == "NONE":
                if i + 30 >= n: continue
                r = side * (c[i + 30] - e) / risk
            rows.append((name, days[i]["t"], ev, round(dist, 2), res, dn, round(r - 0.001 * e / risk, 3), int(c[i] > ma[i]) if ma[i] == ma[i] else -1, z["touch"], z["n"], round(100 * risk / e, 2)))
            break                                                                       # одна подія на день (найближча зона знизу вгору)
    print(name, n, flush=True)
E = pd.DataFrame(rows, columns=["sym", "t", "ev", "dist", "res", "days", "r", "above200", "touch", "n", "risk_pct"]); E.to_csv(OUT, index=False)
E["y"] = pd.to_datetime(E.t, unit="s").dt.year; E["db"] = pd.cut(E.dist, [0, 5, 10, 1000], labels=["<5%", "5–10%", ">10%"]); E["half"] = np.where(E.y <= E.y.median(), "A", "B")
NM = {"DOWN": "ДЕНЬ ЗАКРИВСЯ НИЖЧЕ РІВНЯ", "UP": "ДЕНЬ ЗАКРИВСЯ ВИЩЕ РІВНЯ", "RECLAIM": "ПОВЕРНЕННЯ ВИЩЕ РІВНЯ ПІСЛЯ ПРОКОЛУ"}
def line(lab, x):
    if len(x) < 8: return f"   {lab:34s} n={len(x):4d} — замало"
    return f"   {lab:34s} n={len(x):4d}: дійшла до наступного рівня {100*(x.res=='REACH').mean():3.0f}% | повернулась {100*(x.res=='BACK').mean():3.0f}% | нічого {100*(x.res=='NONE').mean():3.0f}% | днів до розв'язки {x.days.median():.0f} | у грошах {10*x.r.mean():+.2f}$ на $10 ризику"
print(f"\nподій: {len(E)}; інструментів: {E.sym.nunique()}")
for ev in ("DOWN", "UP", "RECLAIM"):
    x = E[E.ev == ev]; print(f"\n######## {NM[ev]}"); print(line("усі", x))
    for v in ("<5%", "5–10%", ">10%"): print(line(f"до наступного рівня {v}", x[x.db == v]))
    print(line("ціна вище 200-денної", x[x.above200 == 1])); print(line("ціна нижче 200-денної", x[x.above200 == 0]))
    print(line("рівень, на який спирались 10+ дн.", x[x.touch >= 10])); print(line("рівень слабший (<10 дн.)", x[x.touch < 10]))
    print(line("перша половина історії", x[x.half == "A"])); print(line("друга половина історії", x[x.half == "B"]))
    if E.sym.nunique() > 3:
        print(line("BTC і ETH", x[x.sym.isin(["BTCUSDT", "ETHUSDT"])]))
