"""Три дослідження на 4,9 року угод СВІНГ (3 рукави H4, 12 монет, комісія 0,10%, ризик $10): (1) обмеження одночасних угод одного напрямку,
(2) ринкові дані Binance (фандінг, лонг/шорт, taker, зміна OI) як тло входу, (3) сезонність (день тижня, година, місяць).
Лише читання. Усі зрізи — після факту (ГІПОТЕЗА); дивимось, чи знак однаковий в обох половинах (2022–2024 / 2025–2026) і по роках.
Використання: extras.py TRADES_CSV MARKET_DIR"""
import sys, os, glob, math, datetime as dt
import numpy as np, pandas as pd
tr_csv, mdir = sys.argv[1], sys.argv[2]
SL = ("donchian20+MA200", "RSI2 reversion+MA200", "Bollinger reversion+MA200")
d = pd.read_csv(tr_csv); d = d[(d.tf == "H4") & d.sig.isin(SL) & (d.exit == "fix s3 TP6")].copy()
d["usd"] = 10 * d.r; d = d.sort_values("ts").reset_index(drop=True); d["t"] = pd.to_datetime(d.ts, unit="s", utc=True)
d["half"] = np.where(d.y <= 2024, "2022-24", "2025-26")
def summ(x):
    if len(x) == 0: return "n=0"
    eq = x.usd.cumsum(); dd = (eq - eq.cummax()).min()
    return f"n={len(x):5d} сума ${x.usd.sum():+8.0f} на угоду ${x.usd.mean():+6.2f} вин {100*(x.usd>0).mean():3.0f}% просадка ${dd:+.0f}"
def halves(x):
    a, b = x[x.half == "2022-24"], x[x.half == "2025-26"]
    return f"| 2022-24 ${a.usd.mean() if len(a) else float('nan'):+6.2f}/уг (n={len(a)})  2025-26 ${b.usd.mean() if len(b) else float('nan'):+6.2f}/уг (n={len(b)})"
print(f"=== СВІНГ, 3 рукави, {d.t.min():%Y-%m-%d}…{d.t.max():%Y-%m-%d}: {summ(d)} ===\n")
print("## (1) Обмеження: не більше N одночасних угод одного напрямку (вікно утримання 10 діб = консервативно; пропущені = 0)")
for N in (99, 8, 6, 4, 3, 2):
    kept = []; open_ = {1: [], -1: []}
    for i, r in d.iterrows():
        s = int(r.side); open_[s] = [t for t in open_[s] if t > r.ts]
        if len(open_[s]) < N: open_[s].append(r.ts + 240 * 3600); kept.append(i)
    x = d.loc[kept]; print(f"N={N:3d}: {summ(x)}  {halves(x)}")
print("\n## (3) Сезонність (середній $ на угоду; дивимось чи знак однаковий у двох половинах)")
d["dow"] = d.t.dt.dayofweek; d["hr"] = (d.t.dt.hour // 4) * 4; d["mon"] = d.t.dt.month
for col, names in (("dow", "пн вт ср чт пт сб нд".split()), ("hr", None), ("mon", None)):
    print(f"-- {col}")
    for k, x in d.groupby(col):
        a, b = x[x.half == "2022-24"].usd.mean(), x[x.half == "2025-26"].usd.mean()
        same = "ТАК" if np.sign(a) == np.sign(b) else "ні"
        print(f"  {names[k] if names else k:>3}: n={len(x):4d} на угоду ${x.usd.mean():+6.2f} | 22-24 ${a:+6.2f} 25-26 ${b:+6.2f} | знак однаковий: {same}")
# ---- ринкові дані
print("\n## (2) Ринкові дані Binance на момент входу (ознака·напрям: + означає «натовп разом з угодою»)")
feat = {}
for f in glob.glob(f"{mdir}/funding/*.csv"):
    sym = os.path.basename(f)[:-4]; x = pd.read_csv(f); feat.setdefault(sym, {})["fund"] = (x.t.values, x.v.values)
for f in glob.glob(f"{mdir}/metrics/*.csv"):
    sym = os.path.basename(f)[:-4]; x = pd.read_csv(f).sort_values("t"); feat.setdefault(sym, {})["m"] = x
def at(t, ts):
    i = np.searchsorted(t, ts, side="right") - 1
    return i if i >= 0 else None
rows = []
for _, r in d.iterrows():
    f = feat.get(r.sym); 
    if not f: continue
    o = {"i": r.name}
    if "fund" in f:
        i = at(f["fund"][0], r.ts); 
        if i is not None and r.ts - f["fund"][0][i] < 12 * 3600: o["funding"] = f["fund"][1][i] * r.side
    if "m" in f:
        m = f["m"]; i = at(m.t.values, r.ts)
        if i is not None and r.ts - m.t.values[i] < 6 * 3600:
            o["ls_ratio"] = (math.log(m.ls.values[i]) * r.side) if m.ls.values[i] > 0 else np.nan
            o["taker"] = (math.log(m.taker.values[i]) * r.side) if m.taker.values[i] > 0 else np.nan
            j = at(m.t.values, r.ts - 86400)
            if j is not None and m.oi.values[j] > 0: o["oi_chg24"] = (m.oi.values[i] / m.oi.values[j] - 1) * 100
    rows.append(o)
if not rows: print("немає ринкових даних"); sys.exit(0)
F = pd.DataFrame(rows).set_index("i"); D = d.join(F)
print(f"угод із даними: {D.funding.notna().sum()} (фандінг), {D.ls_ratio.notna().sum()} (лонг/шорт), {D.oi_chg24.notna().sum()} (OI)")
for col in ("funding", "ls_ratio", "taker", "oi_chg24"):
    x = D.dropna(subset=[col]).copy()
    if len(x) < 200: print(f"-- {col}: мало даних ({len(x)})"); continue
    x["q"] = pd.qcut(x[col], 5, labels=False, duplicates="drop")
    print(f"-- {col}  (q0 = «проти натовпу» … q4 = «разом з натовпом»)")
    for q, y in x.groupby("q"):
        a, b = y[y.half == "2022-24"].usd.mean(), y[y.half == "2025-26"].usd.mean()
        print(f"  q{int(q)}: діапазон [{y[col].min():+.4g}; {y[col].max():+.4g}]  {summ(y)} | 22-24 ${a:+6.2f}  25-26 ${b:+6.2f}")
