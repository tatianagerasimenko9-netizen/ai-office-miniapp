"""READ-ONLY. «ІМПУЛЬСНИЙ ПРОБІЙ» НА ГОДИННОМУ ГРАФІКУ як доповнення до ІНТРАДЕЮ (28.11.2026, питання власниці: «як використати побічну знахідку»).
Звідки: squeeze_lab (пробій «з ходу» кращий за пробій після стояння) і tvh_lab (швидкий підхід: пробій +$2,44 у всіх 6 клітинках; повільний: мінус у всіх 6).
УВАГА: це ПРОТИЛЕЖНЕ твердженню чек-листа ТВХ про швидкість (там — індекси ES/NQ); на крипті перевіряємо те, що показали дані. Нижче — підтвердна перевірка: правило ФІКСОВАНЕ з tvh_lab,
а навколо нього — сітка сусідніх значень (щоб побачити, чи тримається не на одному числі). ГІПОТЕЗА. Нічого не вмикає.
ПРАВИЛО (основне): H1; рівень = максимум/мінімум за 240 год; бар ЗАКРИВСЯ за рівнем (рівню ≥ 12 год; не частіше 1 пробою на 24 год на монету);
  швидкість = рух за останні 6 год у бік пробою ≥ 4 ATR(14); вхід на закритті; стоп за екстремумом останніх 3 барів − 0,1 ATR (0,3%…5% ціни); ціль 2R; до 72 год; стоп першим; $10; комісія 0,10%.
СІТКА: поріг швидкості 3 / 4 / 5 ATR × ціль 2R / 3R × вікно рівня 120 / 240 / 480 год. Окремо LONG і SHORT; група A (42 наші) і B (30 інших); по роках; просадка; угод на місяць.
«ТРИМАЄТЬСЯ» = основне правило в плюсі в кожному році 2021–2026 (де ≥ 50 угод) і в обох групах, і сусідні клітинки сітки теж у плюсі.
Порівняння з ІНТРАДЕЄМ: якщо є data/td_trades.csv — місячні суми ІНТРАДЕЮ (12 монет, 2024–2026) і цього правила на тих самих 12 монетах, окремо і разом.
Використання: impulse_lab.py CANDLES_DIR SEARCH CONTROL OUT_CSV [TD_TRADES_CSV]"""
import os, sys
import numpy as np, pandas as pd
CD, GA, GB, OUT = sys.argv[1], sys.argv[2].split(","), sys.argv[3].split(","), sys.argv[4]; TDF = sys.argv[5] if len(sys.argv) > 5 else ""
FEE = 0.001; HOR = 72; R = []
def trade(H, L, C, i, e, sl, k):
    risk = e - sl
    for j in range(i + 1, min(len(C), i + HOR + 1)):
        if L[j] <= sl: return -1.0, j
        if H[j] >= e + k * risk: return float(k), j
    j = min(len(C) - 1, i + HOR); return (C[j] - e) / risk, j
def run(sym, grp):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(n=("open", "size"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g = g[g.n == 4]
    t, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "high", "low", "close")); n = len(c)
    if n < 1000: return
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy()
    for LB in (120, 240, 480):
        for side in (1, -1):
            H, L, C = (h, l, c) if side > 0 else (-l, -h, -c)
            lvl = pd.Series(H).rolling(LB).max().shift(1).to_numpy(); set_i = 0; last = -10 ** 9
            for i in range(LB + 20, n - HOR - 2):
                if lvl[i] != lvl[i - 1]: set_i = i - 1
                if not (A[i] > 0 and C[i] > lvl[i]): continue
                ok = i - last >= 24 and i - set_i >= 12; last = i
                if not ok: continue
                sp = (C[i] - C[i - 6]) / A[i]
                if sp < 3: continue
                e = C[i]; sl = L[i - 2:i + 1].min() - 0.1 * A[i]; rp = (e - sl) / abs(e)
                if not (0.003 <= rp <= 0.05): continue
                r2, j2 = trade(H, L, C, i, e, sl, 2); r3, _ = trade(H, L, C, i, e, sl, 3)
                R.append((sym, grp, LB, side, t[i] + 3600, t[j2] + 3600, sp, 100 * rp, 10 * (r2 - FEE / rp), 10 * (r3 - FEE / rp)))
for grp, syms in (("A", GA), ("B", GB)):
    for s in syms:
        if os.path.exists(f"{CD}/{s}/15m.csv"): run(s, grp)
W = pd.DataFrame(R, columns=["sym", "g", "LB", "side", "ts", "tx", "sp", "stop", "u2", "u3"]); k = pd.to_datetime(W.ts, unit="s", utc=True); W["y"] = k.dt.year; W["dow"] = k.dt.tz_convert("Europe/Kyiv").dt.day_of_week
W.to_csv(OUT, index=False); YS = sorted(W.y.unique())
def desc(x, col="u2"):
    z = x.sort_values("ts"); eq = z[col].cumsum(); mo = max(1e-9, (z.ts.max() - z.ts.min()) / 86400 / 30.4); m = z.groupby(pd.to_datetime(z.ts, unit="s").dt.to_period("M"))[col].sum()
    return f"n={len(z):5d} ({len(z)/mo:4.1f}/міс) на угоду {z[col].mean():+.2f} сума {z[col].sum():+7.0f} ({z[col].sum()/mo:+5.0f}/міс) просадка {(eq-eq.cummax()).min():6.0f} виграшних {100*(z[col]>0).mean():.0f}% мінус-місяців {int((m<0).sum())}/{len(m)}"
def years(x, col="u2"): return " ".join(f"{y}:{x[x.y==y][col].sum():+.0f}({int((x.y==y).sum())})" for y in YS)
M = W[(W.LB == 240) & (W.sp >= 4)]
print("ОСНОВНЕ ПРАВИЛО (рівень 240 год, швидкість ≥ 4 ATR, ціль 2R), медіанний стоп %.2f%% ціни" % M.stop.median())
for nm, x in (("усі", M), ("LONG", M[M.side > 0]), ("SHORT", M[M.side < 0]), ("наші 42 (A)", M[M.g == "A"]), ("інші 30 (B)", M[M.g == "B"]), ("A · LONG", M[(M.g == "A") & (M.side > 0)]), ("A · SHORT", M[(M.g == "A") & (M.side < 0)]),
              ("сигнал у ср–пт", M[M.dow.isin([2, 3, 4])]), ("сигнал в інші дні", M[~M.dow.isin([2, 3, 4])])):
    print(f"  {nm:18s} {desc(x)} | {years(x)}")
print("\nСІТКА ($ на угоду; n) — рядки: вікно рівня × швидкість; стовпці: ціль 2R | 3R; окремо A і B")
for LB in (120, 240, 480):
    for s0, s1 in ((3, 4), (4, 5), (5, 99), (4, 99)):
        x = W[(W.LB == LB) & (W.sp >= s0) & (W.sp < s1)]
        print(f"  рівень {LB:3d} год, швидкість {s0}–{s1 if s1 < 99 else '∞'} ATR: " + " | ".join(f"{col[1:]}R: A {x[x.g=='A'][col].mean():+.2f} ({int((x.g=='A').sum())}), B {x[x.g=='B'][col].mean():+.2f} ({int((x.g=='B').sum())}), LONG {x[x.side>0][col].mean():+.2f}, SHORT {x[x.side<0][col].mean():+.2f}" for col in ("u2", "u3")))
if TDF and os.path.exists(TDF):
    T = pd.read_csv(TDF); coins = set(T.sym.unique()); X = M[M.sym.isin(coins) & (M.y >= 2024)]
    tm = T.groupby(pd.to_datetime(T.t, unit="s").dt.to_period("M")).usd.sum(); xm = X.groupby(pd.to_datetime(X.ts, unit="s").dt.to_period("M")).u2.sum(); idx = tm.index.union(xm.index); tm = tm.reindex(idx).fillna(0); xm = xm.reindex(idx).fillna(0); both = tm + xm
    dd = lambda s: (s.cumsum() - s.cumsum().cummax()).min()
    print(f"\nРАЗОМ З ІНТРАДЕЄМ (ті самі {len(coins)} монет, 2024–2026, місячні суми $):")
    for nm, s, n in (("ІНТРАДЕЙ як зараз", tm, len(T)), ("імпульсний пробій", xm, len(X)), ("разом", both, len(T) + len(X))):
        print(f"  {nm:20s}: угод {n:5d}, сума {s.sum():+7.0f}, на місяць {s.mean():+6.0f}, найгірший місяць {s.min():+6.0f}, мінус-місяців {int((s<0).sum())}/{len(s)}, просадка по місяцях {dd(s):6.0f}")
    print(f"  зв'язок місячних результатів (кореляція): {np.corrcoef(tm, xm)[0,1]:+.2f}")
    print("  імпульсний пробій на цих монетах: " + desc(X) + " | " + years(X))
