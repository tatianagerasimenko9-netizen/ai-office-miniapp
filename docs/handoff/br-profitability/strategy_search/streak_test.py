"""READ-ONLY. «Серії днів» (23.11.2026, прохання власниці, випадок ALGO): якщо монета росла k днів підряд — що далі за 1/2/3/5 діб? Дзеркально для падіння. ГІПОТЕЗА (правило записано ДО запуску): після серії з k зростаючих закриттів (close>close попереднього дня) ціна в середньому продовжує рух ще кілька днів.
Денні свічки Binance USDT-M (архів), 2020–2026, до 60 монет. Серія рахується на закритті k-го дня; результат — зміна ціни від цього закриття до закриття через h днів. Комісія за угоду враховується у «чистому» результаті (LONG після росту / SHORT після падіння).
Показуємо: n, середня зміна у б.п. (100 б.п. = 1%), надлишок над безумовним середнім (дрейф ринку), частка вгору, t за ДЕННИМИ кластерами (монети корелюють), окремо 2020–21 і 2022–26, по роках, і розріз за стороною MA200 (як у ALGO — нижче MA200).
Використання: streak_test.py DLY_DIR EXTRA_DIR SYMS FEE FOCUS_SYM"""
import os, sys
import numpy as np, pandas as pd
DLY, EX, SYMS, FEE, FOCUS = sys.argv[1], sys.argv[2], sys.argv[3].split(","), float(sys.argv[4]), sys.argv[5]
def load(s):
    parts = []
    p = f"{DLY}/{s}.csv"
    if os.path.exists(p): d = pd.read_csv(p); parts.append(pd.DataFrame({"day": d.t // 86400, "close": d.close, "qv": d.qvol}))
    q = f"{EX}/{s}/1d.csv"
    if os.path.exists(q): d = pd.read_csv(q); parts.append(pd.DataFrame({"day": (d.open_time // 86400).astype(int), "close": d.close, "qv": d.volume * d.close}))
    if not parts: return None
    g = pd.concat(parts).drop_duplicates("day", keep="last").sort_values("day").set_index("day")
    return g
C, Q = {}, {}
for s in SYMS:
    g = load(s)
    if g is not None and len(g) > 250: C[s] = g.close; Q[s] = g.qv
C = pd.DataFrame(C).sort_index(); idx = pd.to_datetime(C.index * 86400, unit="s")
up = (C > C.shift(1)).astype(int); dn = (C < C.shift(1)).astype(int)
def streak(x):                       # довжина поточної серії 1-ок
    s = np.zeros_like(x.to_numpy(float)); v = x.to_numpy(); out = np.zeros(len(v), dtype=int); c = 0
    for i in range(len(v)): c = c + 1 if v[i] == 1 else 0; out[i] = c
    return pd.Series(out, index=x.index)
SU = up.apply(streak); SD = dn.apply(streak)
M200 = C.rolling(200).mean(); below = C < M200
yrs = pd.Series(idx.year, index=C.index)
print(f"СЕРІЇ ДНІВ: монет {C.shape[1]}, днів {len(C)}, {idx[0]:%Y-%m-%d} — {idx[-1]:%Y-%m-%d}; комісія {FEE*100:.2f}% за угоду")
if FOCUS in C:
    f = C[FOCUS].dropna().tail(12); print(f"\n== {FOCUS}: останні дні (закриття за день)")
    last = None
    for d_, v in f.items():
        ch = v / C[FOCUS].shift(1)[d_] - 1; print(f"   {pd.Timestamp(d_*86400, unit='s'):%Y-%m-%d}  {v:.5f}  {100*ch:+.2f}%  серія зростання {int(SU[FOCUS][d_])}, спадання {int(SD[FOCUS][d_])}, {'нижче' if below[FOCUS][d_] else 'вище'} MA200")
    lastd = C[FOCUS].dropna().index[-1]; r30 = C[FOCUS][lastd] / C[FOCUS].shift(30)[lastd] - 1; r7 = C[FOCUS][lastd] / C[FOCUS].shift(7)[lastd] - 1; r3 = C[FOCUS][lastd] / C[FOCUS].shift(3)[lastd] - 1
    print(f"   за 3 дні {100*r3:+.1f}%, за 7 днів {100*r7:+.1f}%, за 30 днів {100*r30:+.1f}%")
HS = (1, 2, 3, 5)
FW = {h: C.shift(-h) / C - 1 for h in HS}
base = {h: FW[h].stack().dropna().mean() for h in HS}
def tstat(df):                          # t за кластерами = днями
    d = df.groupby(level=0).mean()
    return d.mean() / (d.std() / np.sqrt(len(d))) if len(d) > 5 and d.std() > 0 else np.nan
def report(name, S, side, mask=None):
    print(f"\n== {name}: після k днів підряд ({'LONG' if side > 0 else 'SHORT'} у напрямі серії)")
    for k in (1, 2, 3, 4, 5):
        sel = (S == k) if k < 5 else (S >= 5)
        if mask is not None: sel = sel & mask
        for per, lo, hi in (("2020–21", 2020, 2021), ("2022–26", 2022, 2026)):
            m = sel & ((yrs >= lo) & (yrs <= hi)).to_numpy()[:, None]
            cells = []
            for h in HS:
                x = FW[h].where(m).stack().dropna()
                if len(x) < 100: cells.append(f"h{h}: n<100"); continue
                net = side * x - FEE
                cells.append(f"h{h}: n={len(x)}, {1e4*x.mean():+.0f}б.п. (надл. {1e4*(x.mean()-base[h]):+.0f}), вгору {100*(x>0).mean():.0f}%, чистий {1e4*net.mean():+.0f}б.п., t={tstat(net):+.1f}")
            print(f"   k={k}{'+' if k == 5 else ' '} {per}: " + " | ".join(cells))
print(f"\nБазові середні (усі дні): " + ", ".join(f"h{h}: {1e4*base[h]:+.0f}б.п." for h in HS))
report("СЕРІЇ ЗРОСТАННЯ, усі монети", SU, +1)
report("СЕРІЇ ЗРОСТАННЯ, коли монета НИЖЧЕ MA200 (як ALGO зараз)", SU, +1, below.to_numpy())
report("СЕРІЇ ЗРОСТАННЯ, коли монета ВИЩЕ MA200", SU, +1, (~below).to_numpy())
report("СЕРІЇ ПАДІННЯ, усі монети (SHORT у напрямі серії)", SD, -1)
print("\nпо роках (k=3, LONG після 3 днів зростання, h=2; чистий результат у б.п., n):")
sel = (SU == 3)
for y in sorted(set(yrs)):
    x = FW[2].where(sel & (yrs == y).to_numpy()[:, None]).stack().dropna()
    if len(x) > 30: print(f"   {y}: {1e4*(x.mean()-FEE):+.0f}б.п., n={len(x)}, вгору {100*(x>0).mean():.0f}%")
