"""READ-ONLY. СПОТ-ЛАБОРАТОРІЯ (25.11.2026, запит власниці: пасивний дохід на споті — зі стопом чи без, «відра»/сітка лімітних купівель, що вигідніше). Денні свічки (OHLC) Binance, 2020–2026, капітал $4 000, комісія 0,10% за угоду. Тільки купівля (спот), без плеча.
Ціни — USDT-M ф'ючерси (архів) як наближення до споту (різниця — частки відсотка). Упередження виживання: у списку лише монети, що існують сьогодні (реальний результат кошиків гірший).
Стратегії (усі параметри записано ДО запуску; показуємо ВСЕ, без відбору найкращого):
 A  КУПИТИ І ТРИМАТИ: BTC; BTC+ETH; кошик великих монет порівну.
 B  DCA: $4 000 рівними частинами щотижня протягом 52 тижнів, далі тримати (BTC; кошик).
 C  ТРЕНД-УТРИМАННЯ (перегляд раз на 7 днів, до 10 монет із найбільшим обсягом, по 1/10 капіталу на монету, решта — в доларах): тримати монету, поки умова істинна:
      C1 зростання за 30 днів > 0;  C2 ціна вище 200-денної середньої;  C3 обидві.  Стоп: немає / −15% від входу / ковзний −20% від максимуму (після стопа повторний вхід лише на наступному перегляді).
 D  «ВІДРА» (сітка лімітних купівель): рівні купівлі на −s, −2s, … −N·s від 90-денного максимуму; кожне «відро» = капітал/N; продаж відра на +tp від його ціни купівлі (tp = s або 2s) або при поверненні до того максимуму (tohigh).
      Купівля — якщо мінімум дня ≤ рівня; продаж — не раніше наступного дня (порядок усередині дня невідомий). BTC, ETH і кошик (капітал порівну між монетами).
 F  ВХІД ЗА ТРЕНДОМ, СТОП ЧИ БЕЗ (окремі угоди по $400, без обмеження капіталу): вхід — закриття вище максимуму 20 днів і вище 200-денної середньої. Вихід:
      F1 стоп 3×ATR + вихід за трендом (закриття нижче мінімуму 20 днів або нижче 200-денної);  F2 без стопа, лише вихід за трендом;  F3 без стопа, тримати рівно 30 днів;  F4 стоп 3×ATR, тримати до 30 днів.
Метрики: підсумок у $, % за весь період і в середньому на рік, найбільша просадка (за денними закриттями), по роках, кількість дій на рік (наскільки «пасивно»). Вікна: 2020-01→кінець і 2022-01→кінець (старт на вершині ринку — чесний стрес-тест).
Використання: spot_lab.py fetch DIR SYMS | spot_lab.py run DIR SYMS"""
import io, os, sys, zipfile, urllib.request
import numpy as np, pandas as pd
mode, D, SYMS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
MONTHS = [f"{y}-{m:02d}" for y in range(2019, 2027) for m in range(1, 13) if (2019, 9) <= (y, m) <= (2026, 10)]
if mode == "fetch":
    os.makedirs(D, exist_ok=True)
    for s in SYMS:
        rows = {}
        for mo in MONTHS:
            u = f"https://data.binance.vision/data/futures/um/monthly/klines/{s}/1d/{s}-1d-{mo}.zip"
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "office-research"}), timeout=60) as r: z = zipfile.ZipFile(io.BytesIO(r.read()))
            except Exception: continue
            for ln in z.read(z.namelist()[0]).decode().splitlines():
                p = ln.split(",")
                if p[0].isdigit():
                    t = int(p[0]); t = t // 1000 if t > 10**11 else t
                    rows[t // 86400] = (float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[7]) if len(p) > 7 else 0.0)
        if rows:
            pd.DataFrame([(k, *v) for k, v in sorted(rows.items())], columns=["day", "o", "h", "l", "c", "qv"]).to_csv(f"{D}/{s}.csv", index=False); print(s, len(rows), end="; ")
    print(); sys.exit(0)
FEE = 0.001; CAP = 4000.0
X = {}
for s in SYMS:
    p = f"{D}/{s}.csv"
    if os.path.exists(p): X[s] = pd.read_csv(p).set_index("day")
O = pd.DataFrame({s: x.o for s, x in X.items()}).sort_index(); H = pd.DataFrame({s: x.h for s, x in X.items()}).reindex(O.index); L = pd.DataFrame({s: x.l for s, x in X.items()}).reindex(O.index)
C = pd.DataFrame({s: x.c for s, x in X.items()}).reindex(O.index); Q = pd.DataFrame({s: x.qv for s, x in X.items()}).reindex(O.index)
DT = pd.to_datetime(O.index * 86400, unit="s"); YR = pd.Series(DT.year, index=O.index)
MAJ = [s for s in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "BCHUSDT", "ETCUSDT", "XLMUSDT", "ATOMUSDT") if s in C]
def day(s): return int(pd.Timestamp(s).timestamp() // 86400)
WIN = [("2020→2026", day("2020-03-01")), ("2022→2026", day("2022-01-01"))]
END = int(O.index[-1])
def rep(name, eq, acts=None, invested=CAP):
    eq = eq.dropna();
    if len(eq) < 30: return
    yrs = (eq.index[-1] - eq.index[0]) / 365.0; tot = eq.iloc[-1] / invested - 1; cagr = (eq.iloc[-1] / invested) ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1
    dd = (eq / eq.cummax() - 1).min(); y = YR.reindex(eq.index); py = []
    for yy in sorted(set(y)):
        e = eq[y == yy]; prev = eq[y < yy]; b = prev.iloc[-1] if len(prev) else invested; py.append(f"{yy}:{100*(e.iloc[-1]/b-1):+.0f}%")
    a = "" if acts is None else f" | дій на рік ≈ {acts/yrs:.0f}"
    print(f"  {name:58s}: ${eq.iloc[-1]:7.0f} ({100*tot:+5.0f}%, {100*cagr:+4.0f}%/рік), просадка {100*dd:4.0f}%{a} | {' '.join(py)}")
def avail(syms, d0): return [s for s in syms if s in C and pd.notna(C[s].get(d0, np.nan))]
def hold(syms, d0):
    ss = avail(syms, d0); c = C.loc[d0:END, ss]; return (CAP * (1 - FEE) / len(ss) * (c / c.iloc[0]).sum(axis=1)), len(ss)
def dca(syms, d0, weeks=52):
    ss = avail(syms, d0); c = C.loc[d0:END, ss]; units = pd.Series(0.0, index=ss); cash = CAP; eq = []; n = 0
    for k, (d, row) in enumerate(c.iterrows()):
        if k % 7 == 0 and k // 7 < weeks:
            amt = CAP / weeks; cash -= amt; units += amt * (1 - FEE) / len(ss) / row; n += len(ss)
        eq.append(cash + float((units * row).sum()))
    return pd.Series(eq, index=c.index), n
def trend(d0, cond, stop=None, trail=None, N=10):
    idx = [d for d in C.index if d0 <= d <= END]; cash = CAP; pos = {}; eq = []; acts = 0
    r30 = C / C.shift(30) - 1; ma = C.rolling(200).mean(); qv = Q.rolling(30).mean()
    for k, d in enumerate(idx):
        for s in list(pos):                                     # денна перевірка стопа
            u, e, pk = pos[s]; lvl = None
            if stop: lvl = e * (1 - stop)
            if trail: lvl = max(lvl or 0, pk * (1 - trail))
            if lvl and pd.notna(L.at[d, s]) and L.at[d, s] <= lvl:
                px = min(O.at[d, s], lvl); cash += u * px * (1 - FEE); del pos[s]; acts += 1
            elif pd.notna(C.at[d, s]): pos[s] = (u, e, max(pk, C.at[d, s]))
        if k % 7 == 0:
            top = qv.loc[d].dropna().nlargest(N).index if d in qv.index else []
            ok = set()
            for s in top:
                a = r30.at[d, s] > 0 if cond in ("C1", "C3") else True; b = C.at[d, s] > ma.at[d, s] if cond in ("C2", "C3") else True
                if a and b and pd.notna(C.at[d, s]): ok.add(s)
            for s in list(pos):
                if s not in ok: cash += pos[s][0] * C.at[d, s] * (1 - FEE); del pos[s]; acts += 1
            e_now = cash + sum(u * C.at[d, s] for s, (u, _, _) in pos.items())
            for s in ok:
                if s not in pos and cash >= e_now / N * 0.99:
                    amt = e_now / N; cash -= amt; pos[s] = (amt * (1 - FEE) / C.at[d, s], C.at[d, s], C.at[d, s]); acts += 1
        eq.append(cash + sum(u * (C.at[d, s] if pd.notna(C.at[d, s]) else e) for s, (u, e, _) in pos.items()))
    return pd.Series(eq, index=idx), acts
def grid(sym, d0, cap, s, N, tp):
    idx = [d for d in C.index if d0 <= d <= END and pd.notna(C.at[d, sym])]; cash = cap; b = {}; eq = []; acts = 0; hi = H[sym].rolling(90, min_periods=20).max().shift(1)
    for d in idx:
        for k in list(b):                                         # продаж відер (куплених у попередні дні)
            u, px, ref, d_in = b[k]; tgt = ref if tp == "tohigh" else px * (1 + tp)
            if d > d_in and H.at[d, sym] >= tgt: cash += u * max(tgt, O.at[d, sym]) * (1 - FEE); del b[k]; acts += 1
        ref = hi.get(d, np.nan)
        if pd.notna(ref):
            for k in range(1, N + 1):
                lvl = ref * (1 - k * s)
                if k not in b and L.at[d, sym] <= lvl and cash >= cap / N * 0.999:
                    px = min(O.at[d, sym], lvl); amt = cap / N; cash -= amt; b[k] = (amt * (1 - FEE) / px, px, ref, d); acts += 1
        eq.append(cash + sum(u * C.at[d, sym] for u, _, _, _ in b.values()))
    return pd.Series(eq, index=idx), acts
print(f"СПОТ-ЛАБОРАТОРІЯ: монет {C.shape[1]}, {DT[0]:%Y-%m-%d} — {DT[-1]:%Y-%m-%d}; капітал ${CAP:.0f}; комісія {FEE*100:.2f}%; великі монети для кошика: {len(MAJ)}")
for wname, d0 in WIN:
    d0 = int(min(d for d in C.index if d >= d0)); print(f"\n################ ВІКНО {wname}")
    print(" A. Купити і тримати")
    for nm, ss in (("BTC", ["BTCUSDT"]), ("BTC+ETH", ["BTCUSDT", "ETHUSDT"]), ("кошик великих монет порівну", MAJ)):
        e, n = hold(ss, d0); rep(f"A тримати {nm} ({n} монет)", e, 1 * n)
    print(" B. DCA: щотижня 52 тижні, далі тримати")
    for nm, ss in (("BTC", ["BTCUSDT"]), ("кошик великих монет", MAJ)):
        e, n = dca(ss, d0); rep(f"B DCA {nm}", e, n)
    print(" C. Тренд-утримання (перегляд раз на 7 днів, до 10 монет)")
    for cnd, cn in (("C1", "росла 30 днів"), ("C2", "вище 200-денної"), ("C3", "обидві умови")):
        for sn, kw in (("без стопа", {}), ("стоп −15%", {"stop": 0.15}), ("ковзний −20%", {"trail": 0.20})):
            e, a = trend(d0, cnd, **kw); rep(f"C {cn}, {sn}", e, a)
    print(" D. «Відра»: сітка лімітних купівель від 90-денного максимуму")
    for nm, ss in (("BTC", ["BTCUSDT"]), ("ETH", ["ETHUSDT"]), ("кошик великих монет", avail(MAJ, d0))):
        for s_, N_ in ((0.05, 10), (0.10, 5), (0.10, 8)):
            for tp in (s_, 2 * s_, "tohigh"):
                parts = [grid(x, d0, CAP / len(ss), s_, N_, tp) for x in ss]; e = sum(p[0].reindex(parts[0][0].index).ffill() for p in parts); a = sum(p[1] for p in parts)
                rep(f"D {nm}: крок {int(100*s_)}%, {N_} відер, продаж {'до максимуму' if tp=='tohigh' else '+'+str(int(100*tp))+'%'}", e, a)
print("\n################ F. Вхід за трендом: стоп чи без (угоди по $400, усі монети, 2020→2026)")
rows = []
for s in C.columns:
    c, h, l, o = C[s].to_numpy(), H[s].to_numpy(), L[s].to_numpy(), O[s].to_numpy(); n = len(c)
    pc = np.r_[np.nan, c[:-1]]; tr = np.fmax(h - l, np.fmax(abs(h - pc), abs(l - pc))); A = pd.Series(tr).rolling(14).mean().to_numpy()
    hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy(); ma = pd.Series(c).rolling(200).mean().to_numpy(); yr = YR.to_numpy()
    for var in ("F1", "F2", "F3", "F4"):
        i = 201
        while i < n - 2:
            if not (c[i] > hi20[i] and c[i] > ma[i] and A[i] > 0): i += 1; continue
            e = o[i + 1]
            if not e > 0: i += 1; continue
            sl = e - 3 * A[i]; j = i + 1; px = None; why = "кінець"
            while j < n:
                if var in ("F1", "F4") and l[j] <= sl: px = min(o[j], sl); why = "стоп"; break
                if var in ("F1", "F2") and (c[j] < lo20[j] or c[j] < ma[j]): px = c[j]; why = "тренд"; break
                if var in ("F3", "F4") and j - (i + 1) >= 29: px = c[j]; why = "30 днів"; break
                j += 1
            if px is None: px = c[min(j, n - 1)]
            rows.append((var, s, int(yr[i + 1]), px / e - 1 - 2 * FEE, why, j - i)); i = max(j, i + 1)
T = pd.DataFrame(rows, columns=["v", "sym", "y", "ret", "why", "days"]); T["usd"] = 400 * T.ret
NM = {"F1": "стоп 3×ATR + вихід за трендом", "F2": "БЕЗ стопа, вихід за трендом", "F3": "БЕЗ стопа, рівно 30 днів", "F4": "стоп 3×ATR, до 30 днів"}
for v, g in T.groupby("v"):
    a = g[g.y <= 2021]; b = g[g.y >= 2022]
    print(f"  {v} {NM[v]:32s}: угод {len(g):5d}, на угоду {100*g.ret.mean():+5.1f}% (${g.usd.mean():+.1f}), виграшних {100*(g.ret>0).mean():.0f}%, тримання {g.days.median():.0f} дн., найгірша {100*g.ret.min():.0f}%, сума ${g.usd.sum():+.0f} | 2020–21: {100*a.ret.mean():+.1f}%/угоду (n={len(a)}), 2022–26: {100*b.ret.mean():+.1f}%/угоду (n={len(b)}) | по роках: " + " ".join(f"{y}:{100*x.ret.mean():+.0f}%" for y, x in g.groupby("y")))
