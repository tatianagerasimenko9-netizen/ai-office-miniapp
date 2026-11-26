"""READ-ONLY. ДИВЕРГЕНЦІЇ: ШИРОКА ПЕРЕВІРКА (26.11.2026, прохання власниці: менші таймфрейми, різні монети, метали, акції; де вхід і де стоп).
ПЛАН ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА; означення дивергенцій — ЗОВНІШНЄ, класичний теханаліз). Щоб не «знайти красиве випадково», дані поділено на НЕЗАЛЕЖНІ групи, і правило вважаємо підтвердженим лише якщо воно плюсове в КОЖНІЙ:
  A = 42 монети, 2022–2026 (цю групу на H4 вже бачили);  B = ті самі 42 монети, 2020–2021 (не бачили);  C = інші монети Binance, 2020–2026 (не бачили);
  M = метали Binance (XAU, XAG);  S = акції США, денні 2005–2026 (Yahoo);  G = метали/індекси, денні (Yahoo);  S1 = акції, годинні, останні ~2 роки (Yahoo).
Сигнал: RSI(14); пивот = екстремум серед k барів з обох боків, k ∈ {3,5,8} (видно через k барів); попередній пивот того ж типу не далі 60 барів.
  RB звичайна бичача (ціна нижче, RSI вище → LONG), RS звичайна ведмежа (SHORT), HB прихована бичача (ціна вище, RSI нижче → LONG), HS прихована ведмежа (SHORT).
Вхід: закриття бару підтвердження. Стопи: 1,5 / 2 / 3 × ATR14 від входу, або «за пивот» (за екстремум пивота ∓0,1 ATR). Цілі: 2R / 3R / 6R. Утримання ≤60 барів. Стоп-першим. Ризик $10.
Комісія за круг: крипто 0,10%; акції/метали Yahoo 0,05% (ГІПОТЕЗА). Таймфрейми крипто: M15, H1, H4, D1.
Розрізи: за трендом / проти (MA200 того ж ТФ); зона RSI у пивоті (LONG: RSI<40 чи ≥40; SHORT: RSI>60 чи ≤60).
Частина 2: дивергенція за 12 барів H4 до входу СВІНГ (k=5) — у бік / проти угоди, окремо по групах A, B, C (угоди з sw_mfe.py на тих самих даних).
Використання: div_lab.py fetch DIR SYMS | yf DIR | run DIR SYMS42 SW_TRADES OUT_PREFIX"""
import io, os, sys, zipfile, urllib.request
import numpy as np, pandas as pd
mode, D = sys.argv[1], sys.argv[2]
if mode == "fetch":
    from concurrent.futures import ThreadPoolExecutor
    SY = sys.argv[3].split(","); MONTHS = [f"{y}-{m:02d}" for y in range(2020, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)]
    def one(s):
        rows = []
        for mo in MONTHS:
            u = f"https://data.binance.vision/data/futures/um/monthly/klines/{s}/15m/{s}-15m-{mo}.zip"
            for att in range(3):
                try:
                    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "office-research"}), timeout=90).read()))
                    for ln in z.read(z.namelist()[0]).decode().splitlines():
                        p = ln.split(",")
                        if p[0].isdigit(): rows.append((int(p[0]) // 1000 if int(p[0]) > 10**11 else int(p[0]), p[1], p[2], p[3], p[4]))
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 404: break
                except Exception: pass
        if rows:
            os.makedirs(f"{D}/{s}", exist_ok=True); pd.DataFrame(sorted(set(rows)), columns=["open_time", "open", "high", "low", "close"]).to_csv(f"{D}/{s}/15m.csv", index=False)
        return s, len(rows)
    with ThreadPoolExecutor(6) as ex:
        for s, n in ex.map(one, SY): print(s, n, flush=True)
    sys.exit(0)
YF_S = "AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AMD,NFLX,JPM,XOM,KO,WMT,DIS,BA,INTC,CSCO,PFE,V,MA,UNH,HD,PG,CVX,ORCL,ADBE,CRM,QCOM,MU,GS".split(",")
YF_G = "GC=F,SI=F,PL=F,HG=F,CL=F,SPY,QQQ,GLD,SLV".split(",")
if mode == "yf":
    import yfinance as yf
    os.makedirs(D, exist_ok=True)
    for t in YF_S + YF_G:
        for iv, per, nm in (("1d", "max", "1d"), ("1h", "730d", "1h")):
            try:
                d = yf.download(t, period=per, interval=iv, progress=False, auto_adjust=True)
                if isinstance(d.columns, pd.MultiIndex): d.columns = [c[0] for c in d.columns]
                d = d.dropna(subset=["Close"])
                if len(d) < 300: continue
                ix = pd.DatetimeIndex(d.index); ix = ix.tz_convert("UTC").tz_localize(None) if ix.tz is not None else ix
                pd.DataFrame({"open_time": (ix.astype("int64") // 10**9), "open": d.Open.to_numpy(), "high": d.High.to_numpy(), "low": d.Low.to_numpy(), "close": d.Close.to_numpy()}).to_csv(f"{D}/{t.replace('=', '_')}_{nm}.csv", index=False)
                print(t, nm, len(d), flush=True)
            except Exception as e: print(t, nm, "ERR", str(e)[:80], flush=True)
    sys.exit(0)
SY42 = set(sys.argv[3].split(",")); SWF, OUT = sys.argv[4], sys.argv[5]; YFD = os.environ.get("YFDIR", "yf")
KS = (3, 5, 8); LOOK = 60; HOLD = 60; STOPS = ("A1.5", "A2", "A3", "PIV"); TGS = (2, 3, 6)
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
ROWS = []; EV4 = []; CH = []
COLS = ["g", "tf", "k", "kind", "trend", "zone", "stop", "tg", "y", "wk", "r"]
def flush():
    global ROWS
    if not ROWS: return
    d = pd.DataFrame(ROWS, columns=COLS); ROWS = []
    for c_ in ("g", "tf", "kind", "stop"): d[c_] = d[c_].astype("category")
    for c_ in ("k", "trend", "zone", "tg"): d[c_] = d[c_].astype("int8")
    d["y"] = d.y.astype("int16"); d["wk"] = d.wk.astype("int32"); d["r"] = d.r.astype("float32"); CH.append(d)
def study(group, tf, sym, t, h, l, c, fee, keep_ev=False):
    n = len(c)
    if n < 400: return
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); M = pd.Series(c).rolling(200).mean().to_numpy(); R = rsi(c)
    yr = pd.to_datetime(t, unit="s").year.to_numpy()
    for k in KS:
        w = 2 * k + 1
        isl = (pd.Series(l).rolling(w, center=True).min().to_numpy() == l); ish = (pd.Series(h).rolling(w, center=True).max().to_numpy() == h)
        for typ, mask, x in (("L", isl, l), ("H", ish, h)):
            piv = np.flatnonzero(mask); piv = piv[(piv >= 210) & (piv + k < n)]
            if len(piv) < 2: continue
            prev = piv[:-1]; cur = piv[1:]; ok = (cur - prev <= LOOK) & (cur - prev > k) & (R[cur] > 0) & (R[prev] > 0)
            for q, p in zip(cur[ok], prev[ok]):
                if typ == "L": kind = "RB" if (l[q] < l[p] and R[q] > R[p]) else ("HB" if (l[q] > l[p] and R[q] < R[p]) else None); side = 1
                else: kind = "RS" if (h[q] > h[p] and R[q] < R[p]) else ("HS" if (h[q] < h[p] and R[q] > R[p]) else None); side = -1
                i = q + k
                if not kind or not A[i] > 0 or not M[i] > 0: continue
                if keep_ev and k == 5: EV4.append((sym, t[i] + 14400, kind, side))
                if i + HOLD >= n: continue
                e = c[i]; H_ = h[i + 1:i + 1 + HOLD]; L_ = l[i + 1:i + 1 + HOLD]; last = c[i + HOLD]
                zone = int(R[q] < 40) if side > 0 else int(R[q] > 60); trend = int(side * (e - M[i]) > 0); g = group if group != "X" else ("A" if yr[i] >= 2022 else "B")
                for st in STOPS:
                    risk = (float(st[1:]) * A[i]) if st[0] == "A" else side * (e - (x[q] - side * 0.1 * A[i]))
                    if not risk > 0 or not 0.0005 <= risk / e <= 0.25: continue
                    sl = e - side * risk; hs = (L_ <= sl) if side > 0 else (H_ >= sl); isx = int(np.argmax(hs)) if hs.any() else HOLD + 1; f = fee * e / risk
                    for tg in TGS:
                        tp = e + side * tg * risk; ht = (H_ >= tp) if side > 0 else (L_ <= tp); itx = int(np.argmax(ht)) if ht.any() else HOLD + 1
                        r = -1.0 if (isx <= itx and isx <= HOLD) else (float(tg) if itx <= HOLD else side * (last - e) / risk)
                        ROWS.append((g, tf, k, kind, trend, zone, st, tg, int(yr[i]), int(t[i] // 604800), r - f))
def agg(d, per):
    g = d.groupby(d.open_time // per * per).agg(n=("open", "size"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return g
TFS = (("M15", 900, 1), ("H1", 3600, 4), ("H4", 14400, 16), ("D1", 86400, 96))
syms = sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv"))
for s in syms:
    d = pd.read_csv(f"{D}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    grp = "M" if s in ("XAUUSDT", "XAGUSDT") else ("X" if s in SY42 else "C")
    for tf, per, need in TFS:
        if per == 900: g = d.rename(columns={})
        else: g = agg(d, per); g = g[g.n >= need * 0.9]
        study(grp, tf, s, g.open_time.to_numpy(float), g.high.to_numpy(float), g.low.to_numpy(float), g.close.to_numpy(float), 0.001, keep_ev=(tf == "H4"))
    flush(); print(s, grp, sum(len(x) for x in CH), flush=True)
if os.path.isdir(YFD):
    for fn in sorted(os.listdir(YFD)):
        tk, nm = fn[:-4].rsplit("_", 1); d = pd.read_csv(f"{YFD}/{fn}"); isg = tk.replace("_", "=") in YF_G
        if nm == "1d": d = d[d.open_time >= 1104537600]
        study(("G" if isg else "S") + ("1" if nm == "1h" else ""), "D1" if nm == "1d" else "H1", tk, d.open_time.to_numpy(float), d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float), 0.0005)
    flush(); print("yf", sum(len(x) for x in CH), flush=True)
flush(); W = pd.concat(CH, ignore_index=True); del CH
for c_ in ("g", "tf", "kind", "stop"): W[c_] = W[c_].astype(str).astype("category")
W["usd"] = (10 * W.r).astype("float32")
NAME = {"RB": "звичайна бичача", "RS": "звичайна ведмежа", "HB": "прихована бичача", "HS": "прихована ведмежа"}
GN = {"A": "A: 42 монети 2022–26", "B": "B: ті самі 2020–21", "C": "C: інші монети", "M": "M: метали Binance", "S": "S: акції, день", "G": "G: метали/індекси, день", "S1": "S1: акції, година", "G1": "G1: метали/індекси, година"}
def cell(x):
    if len(x) < 100: return f"n={len(x)}"
    wk = x.groupby("wk").usd.sum(); t = wk.mean() / (wk.std() / np.sqrt(len(wk))) if len(wk) > 5 and wk.std() > 0 else np.nan; py = x.groupby("y").usd.sum()
    return f"n={len(x)}, ${x.usd.mean():+.2f}/угоду, виграшних {100*(x.usd>0).mean():.0f}%, плюсових років {int((py>0).sum())}/{len(py)}, t={t:+.1f}"
print(f"\nДИВЕРГЕНЦІЇ, ШИРОКА ПЕРЕВІРКА: {len(W):,} результатів (усі комбінації); ризик $10")
print("\n== 1) БАЗОВА КОМІРКА (k=5, стоп 3×ATR, ціль 6R) — усі / за трендом / проти тренду")
b = W[(W.k == 5) & (W.stop == "A3") & (W.tg == 6)]
for kind in NAME:
    print(f" {NAME[kind]}")
    for (g, tf), x in b[b.kind == kind].groupby(["g", "tf"], observed=True):
        print(f"   {GN.get(g, g):28s} {tf:3s}: усі [{cell(x)}] | за трендом [{cell(x[x.trend == 1])}] | проти [{cell(x[x.trend == 0])}]")
print("\n== 2) ДЕ СТАВИТИ СТОП І ЦІЛЬ (k=5; $ на угоду; рядки — стоп, стовпці — ціль 2R/3R/6R) — приховані, за трендом")
for kind in ("HB", "HS"):
    for g, tf in (("A", "H4"), ("B", "H4"), ("C", "H4"), ("A", "H1"), ("B", "H1"), ("C", "H1"), ("A", "M15"), ("C", "M15"), ("A", "D1"), ("S", "D1"), ("G", "D1")):
        x = W[(W.k == 5) & (W.kind == kind) & (W.g == g) & (W.tf == tf) & (W.trend == 1)]
        if len(x) < 300: continue
        p = x.pivot_table(index="stop", columns="tg", values="usd", aggfunc="mean", observed=True).round(2); print(f"  {NAME[kind]} · {GN[g]} · {tf} (n≈{len(x)//12}):  " + " | ".join(f"{st}: " + "/".join(f"{p.loc[st, tg]:+.2f}" for tg in TGS) for st in STOPS if st in p.index))
print("\n== 3) ЩО ПЛЮСОВЕ В УСІХ ТРЬОХ НЕЗАЛЕЖНИХ ГРУПАХ КРИПТО (A, B, C; n≥200 у кожній). Показано найкращі 30 за НАЙГІРШОЮ з трьох груп")
cr = W[W.g.isin(["A", "B", "C"])]; res = []
for trn in (None, 1, 0):
    for zn in (None, 1, 0):
        x = cr if trn is None else cr[cr.trend == trn]; x = x if zn is None else x[x.zone == zn]
        a = x.groupby(["tf", "k", "kind", "stop", "tg", "g"], observed=True).usd.agg(["mean", "size"]).unstack("g")
        for idx, row in a.iterrows():
            try: ms = [row[("mean", g)] for g in "ABC"]; ns = [row[("size", g)] for g in "ABC"]
            except KeyError: continue
            if any(pd.isna(ms)) or min(ns) < 200: continue
            res.append((min(ms), idx, trn, zn, ms, ns))
tot = len(res); pos = sum(1 for r in res if r[0] > 0); res.sort(key=lambda r: -r[0])
print(f"  перевірено комбінацій: {tot}; плюсові в усіх трьох групах: {pos} ({100*pos/max(tot,1):.0f}%). Якби дивергенції нічого не давали, випадково плюсових у трьох групах було б ≈12%.")
TR = {None: "усі", 1: "за трендом", 0: "проти тренду"}; ZN = {None: "будь-який RSI", 1: "RSI у крайній зоні", 0: "RSI не в крайній зоні"}
for mn, idx, trn, zn, ms, ns in res[:30]:
    tf, k, kind, st, tg = idx; print(f"   {tf:3s} k={k} {NAME[kind]:18s} {TR[trn]:13s} {ZN[zn]:22s} стоп {st:4s} ціль {tg}R: A ${ms[0]:+.2f} (n={int(ns[0])}), B ${ms[1]:+.2f} (n={int(ns[1])}), C ${ms[2]:+.2f} (n={int(ns[2])})")
print("  найгірші 10 (для чесності):")
for mn, idx, trn, zn, ms, ns in sorted(res, key=lambda r: max(r[4]))[:10]:
    tf, k, kind, st, tg = idx; print(f"   {tf:3s} k={k} {NAME[kind]:18s} {TR[trn]:13s} {ZN[zn]:22s} стоп {st:4s} ціль {tg}R: A ${ms[0]:+.2f}, B ${ms[1]:+.2f}, C ${ms[2]:+.2f}")
print("\n== 4) АКЦІЇ І МЕТАЛИ: найкращі 12 комірок у групі S (акції, день), і та сама комірка в G (метали/індекси) та S1 (акції, година)")
sx = W[W.g == "S"].groupby(["k", "kind", "trend", "stop", "tg"], observed=True).usd.agg(["mean", "size"]); sx = sx[sx["size"] >= 300].sort_values("mean", ascending=False)
print(f"  комбінацій у S: {len(sx)}, плюсових {int((sx['mean']>0).sum())}")
for (k, kind, trn, st, tg), row in sx.head(12).iterrows():
    def other(g, tf):
        y = W[(W.g == g) & (W.tf == tf) & (W.k == k) & (W.kind == kind) & (W.trend == trn) & (W.stop == st) & (W.tg == tg)]; return f"${y.usd.mean():+.2f} (n={len(y)})" if len(y) >= 50 else f"n={len(y)}"
    print(f"   k={k} {NAME[kind]:18s} {TR[trn]:13s} стоп {st:4s} ціль {tg}R: S ${row['mean']:+.2f} (n={int(row['size'])}) | G {other('G', 'D1')} | S1 {other('S1', 'H1')} | крипто D1 A {other('A', 'D1')}")
if os.path.exists(SWF):
    E = pd.DataFrame(EV4, columns=["sym", "t", "kind", "side"]); sw = pd.read_csv(SWF); sw["usd"] = 10 * sw.r; sw["g"] = np.where(~sw.sym.isin(SY42), "C", np.where(sw.y >= 2022, "A", "B")); WIN = 12 * 14400
    def flag(kinds, same):
        out = pd.Series(False, index=sw.index)
        for sym, g in sw.groupby("sym"):
            e = E[(E.sym == sym) & E.kind.isin(kinds)]
            for sd in (1, -1):
                tt = np.sort(e[e.side == (sd if same else -sd)].t.to_numpy()); gi = g[g.side == sd]
                if not len(tt) or not len(gi): continue
                ts = gi.ts.to_numpy() + 14400; kk = np.searchsorted(tt, ts, side="right") - 1; out.loc[gi.index] = (kk >= 0) & (ts - tt[np.clip(kk, 0, len(tt) - 1)] <= WIN)
        return out.to_numpy()
    print(f"\n== 5) ДИВЕРГЕНЦІЯ ЗА 2 ДОБИ ДО ВХОДУ СВІНГ, по групах (з нею / без неї, $ на угоду; n)")
    for lab, kinds, same in (("прихована ПРОТИ угоди", ("HB", "HS"), False), ("звичайна ПРОТИ угоди", ("RB", "RS"), False), ("прихована В БІК угоди", ("HB", "HS"), True), ("звичайна В БІК угоди", ("RB", "RS"), True)):
        f = flag(kinds, same); print(f"  {lab}: " + " | ".join(f"{GN[g][:1]}: {sw[f & (sw.g == g)].usd.mean():+.2f} (n={int((f & (sw.g == g)).sum())}) / {sw[~f & (sw.g == g)].usd.mean():+.2f}" for g in "ABC"))
W.groupby(["g", "tf", "k", "kind", "trend", "zone", "stop", "tg"], observed=True).usd.agg(["mean", "size", "sum"]).round(3).to_csv(OUT + "_cells.csv")
