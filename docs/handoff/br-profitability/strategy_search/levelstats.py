"""READ-ONLY. Мислення Герчика, виміряне на історії: скільки разів ціна підходить до денного рівня, що відбувається (відбій чи пробій) і НА СКІЛЬКИ вона йде далі.
Для 12 монет 2022-2026. Підхід N-й за рахунком (1,2,3,4+); результат протягом 5 днів: ВІДБІЙ (ціна відійшла ≥1 ATR D1 від рівня до пробою), ПРОБІЙ (закриття дня за рівнем >0,25 ATR), НЕЯСНО.
Далі — наскільки далеко пішла ціна за 7 днів (в ATR D1) після відбою / після пробою. Параметри (N=3, допуск 0,25 ATR) — ГІПОТЕЗА. Використання: levelstats.py CANDLES_DIR SYMS"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import d1lv
CD, SYMS = sys.argv[1], sys.argv[2].split(",")
rows = []
for s in SYMS:
    d = pd.read_csv(f"{CD}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time"); a = {k: d[k].to_numpy(float) for k in ("open_time", "high", "low", "close")}
    D = d1lv.build(a); hi, lo, cl, atr = D["hi"], D["lo"], D["cl"], D["atr"]; n = len(hi)
    for L in d1lv.levels(D):
        for k, e in enumerate(L["eps"], 1):
            if e + 8 >= n or not atr[e] == atr[e]: continue
            p, A = L["p"], atr[e]; res = "неясно"; resd = None
            for d_ in range(e, e + 6):
                brk = (cl[d_] > p + .25 * A) if L["t"] == "H" else (cl[d_] < p - .25 * A)
                away = (p - lo[d_] >= A) if L["t"] == "H" else (hi[d_] - p >= A)
                if brk: res, resd = "пробій", d_; break
                if away: res, resd = "відбій", d_; break
            if resd is None: continue
            end = min(n, resd + 8)
            if res == "відбій": ext = ((p - lo[e:end].min()) if L["t"] == "H" else (hi[e:end].max() - p)) / A
            else: ext = ((hi[resd:end].max() - p) if L["t"] == "H" else (p - lo[resd:end].min())) / A
            rows.append(dict(sym=s, y=pd.Timestamp(int(D["u"][e]) * 86400, unit="s").year, k=min(k, 4), res=res, ext=ext, t=L["t"]))
R = pd.DataFrame(rows); print(f"Подій: {len(R)}; рівнів: {sum(1 for _ in range(1))}\n")
print("| підхід № | подій | відбій | пробій | далі після відбою (ATR D1): серед. / ≥2 ATR | далі після пробою: серед. / ≥2 ATR |\n|--|--|--|--|--|--|")
for k in (1, 2, 3, 4):
    g = R[R.k == k]; b = g[g.res == "відбій"]; p_ = g[g.res == "пробій"]
    print(f"| {'4+' if k == 4 else k} | {len(g)} | {len(b)/len(g)*100:.0f}% | {len(p_)/len(g)*100:.0f}% | {b.ext.mean():.2f} / {(b.ext>=2).mean()*100:.0f}% | {p_.ext.mean():.2f} / {(p_.ext>=2).mean()*100:.0f}% |")
print("\nПо роках (частка відбоїв серед підходів № 1 / № 3+):")
for y in sorted(R.y.unique()):
    a1 = R[(R.y == y) & (R.k == 1)]; a3 = R[(R.y == y) & (R.k >= 3)]
    print(f"  {y}: №1 {len(a1)} подій, відбій {(a1.res=='відбій').mean()*100:.0f}% | №3+ {len(a3)} подій, відбій {(a3.res=='відбій').mean()*100:.0f}%")
print("\nПідтримка (L) проти опору (H), відбій%:", {t: f"{(R[(R.t==t)].res=='відбій').mean()*100:.0f}%" for t in ('L', 'H')})
print("\n##### ПІДСУМОК levelstats завершено")
