"""READ-ONLY. БОТ-ЕТАЛОН: чим сигнали, що дійшли до TP1 / TP2 / TP3, відрізняються від тих, що пішли в стоп (28.11.2026, прохання власниці: «побачити систему; порівняти з нашими умовами відскоку, свінгу, інтрадею»).
Монети й сигнали — саме бота. Підсумок сигналу — з незалежної перевірки (etalon_replay.csv, вхід за ринком). Ознаки рахуються на свічках ДО хвилини сигналу (без заглядання вперед).
ОЗНАКИ І МЕЖІ ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА):
 З картки бота: клас, бал, таймфрейм, сесія, режим, kill zone, «проти денного тренду», RSI, ADX, ATR%, стоп%, R/R до TP1.
 Тренд монети (як у нашому СВІНГУ): ціна відносно середньої за 200 свічок на 4 год і на 1 год → сигнал ЗА трендом / ПРОТИ.   Спокійна монета (ATR 4 год < 2,3% ціни).
 Рух перед сигналом: за 1 год, 4 год і 24 год у бік сигналу (сигнал «навздогін» чи «проти руху»).   Місце ціни в діапазоні 7 діб (0 = дно, 1 = верх).
 Умови нашого ВІДСКОКУ, дзеркально для SHORT: відстань від 7-денного максимуму (для LONG) / від 7-денного мінімуму (для SHORT): <10% / 10–20% / >20%;
   скільки разів за 7 діб уже тестували цю ж крайню точку (±1 ATR 1 год): 0 / 1 / 2+;   чи був за останні 6 год «злив і повернення» (LONG) або «виліт і повернення» (SHORT) за правилами bounce_lab.
 Ринок: BTC відносно середньої за 200 свічок 4 год (ЗА сигналом / ПРОТИ); рух BTC за 24 год у бік сигналу; рух BTC за 1 год; те саме для ETH за 24 год.
 Обсяг: обсяг останньої години до середнього за 24 год: <1 / 1–2 / 2–4 / 4+.   Розмах монети за 24 год, %.
 Пачка: скільки сигналів бота в той самий бік було за попередні 6 год: 0 / 1–2 / 3+.   Попередній сигнал бота по цій монеті: не було / був стоп / був тейк.
 Монета: акція чи метал / крипто;   «нова» (історії менше 60 діб) / стара.   День тижня, година.
Для кожної групи: скільки сигналів, частка стопів, частка «TP1 і далі», «TP2 і далі», TP3, $ на угоду («як бот»), окремо SHORT і LONG, і стійкість: перша половина (травень–серпень) проти другої (вересень–листопад).
Позначка <<< — група краща за середнє в ОБОХ половинах і плюсова в обох; >>> — гірша за середнє і мінусова в обох.
Використання: etalon_feat.py REPLAY_CSV DIR OUT_CSV"""
import os, sys
import numpy as np, pandas as pd
REP, DIR, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
S = pd.read_csv(REP); S = S[S.E0X1.notna()].copy(); S["dt"] = pd.to_datetime(S.ts, unit="s")
STOCK = {"AMD","INTC","NVDA","TSLA","AAPL","MSFT","PLTR","HOOD","TSM","WDC","ASTS","IREN","SOXL","EWY","NOK","MU","COIN","MSTR","GOOGL","META","AMZN","XAG","XAU","RKLB","MRVL","CRCL","ARM","LLY","NFLX","APP","SPCX","CL","BZ","NG","QQQ","SPY","AVGO","ORCL","BABA","UNH","SMCI","RIOT","MARA","CLSK","HIMS","SOFI","OKLO","IONQ","RGTI","QBTS","NBIS","CRWV"}
def load(sym):
    f = f"{DIR}/{sym}.csv"
    if not os.path.exists(f): return None
    d = pd.read_csv(f)
    if "v" not in d: d["v"] = 0.0
    return d
def agg(d, per):
    g = d.groupby(d.t // per * per).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum")).reset_index(); return {k: g[k].to_numpy(float) for k in ("t", "o", "h", "l", "c", "v")}
def atr_(b, n=14):
    pc = np.r_[b["c"][0], b["c"][:-1]]; return pd.Series(np.maximum(b["h"] - b["l"], np.maximum(abs(b["h"] - pc), abs(b["l"] - pc)))).rolling(n).mean().to_numpy()
ctx = {}
for s in ("BTCUSDT", "ETHUSDT"):
    d = load(s)
    if d is not None: ctx[s] = (agg(d, 3600), agg(d, 14400))
def ret(b, i, n): return (b["c"][i] / b["c"][i - n] - 1) * 100 if i - n >= 0 else np.nan
rows = []
for sym, g in S.groupby("sym"):
    d = load(sym)
    if d is None: continue
    h1, h4 = agg(d, 3600), agg(d, 14400); A1 = atr_(h1); A4 = atr_(h4); first_t = d.t.iloc[0]
    lo72 = pd.Series(h1["l"]).rolling(72).min().to_numpy(); hi72 = pd.Series(h1["h"]).rolling(72).max().to_numpy(); hi24 = pd.Series(h1["h"]).rolling(24).max().to_numpy(); lo24 = pd.Series(h1["l"]).rolling(24).min().to_numpy()
    FL = {1: np.flatnonzero((h1["l"] == lo72) & (hi24 - h1["l"] >= 3 * A1)), -1: np.flatnonzero((h1["h"] == hi72) & (h1["h"] - lo24 >= 3 * A1))}
    for r in g.itertuples():
        side = 1 if r.dir == "LONG" else -1; f = dict(ts=r.ts, sym=sym)
        i = int(np.searchsorted(h1["t"], r.ts - 3600, side="right")) - 1                      # останній ЗАКРИТИЙ бар 1 год
        j = int(np.searchsorted(h4["t"], r.ts - 14400, side="right")) - 1
        if i < 30: rows.append(f); continue
        px = r.p0
        if j >= 200: f["тренд 4 год"] = "ЗА трендом" if side * (px - h4["c"][j - 199:j + 1].mean()) > 0 else "ПРОТИ тренду"
        if i >= 200: f["тренд 1 год"] = "ЗА трендом" if side * (px - h1["c"][i - 199:i + 1].mean()) > 0 else "ПРОТИ тренду"
        if j >= 15 and A4[j] > 0: f["спокійна монета"] = "так" if A4[j] / px < 0.023 else "ні"
        for n_, nm in ((1, "рух монети за 1 год"), (4, "рух монети за 4 год"), (24, "рух монети за 24 год")):
            v = side * ret(h1, i, n_)
            if v == v: f[nm] = pd.cut([v], [-1e9, -5, -1.5, 1.5, 5, 1e9], labels=["сильно ПРОТИ (>5%)", "проти 1,5–5%", "без руху", "у бік 1,5–5%", "сильно У БІК (>5%)"])[0]
        if i >= 168:
            H7, L7 = h1["h"][i - 167:i + 1].max(), h1["l"][i - 167:i + 1].min()
            if H7 > L7: f["місце в діапазоні 7 діб"] = pd.cut([(px - L7) / (H7 - L7)], [-9, 0.2, 0.4, 0.6, 0.8, 9], labels=["біля дна", "нижня частина", "середина", "верхня частина", "біля верху"])[0]
            dist = (H7 - px) / H7 * 100 if side > 0 else (px - L7) / L7 * 100
            f["відскок: відстань від 7-ден. екстремуму"] = "<10%" if dist < 10 else ("10–20%" if dist < 20 else ">20%")
            fl = FL[side]; fl6 = fl[(fl <= i) & (fl >= i - 6)]; f["відскок: злив/виліт за 6 год"] = "так" if len(fl6) else "ні"
            ext = h1["l"] if side > 0 else h1["h"]; e_now = ext[i - 5:i + 1].min() if side > 0 else ext[i - 5:i + 1].max(); pf = fl[(fl >= i - 168) & (fl <= i - 12)]
            k = int(sum(abs(ext[q] - e_now) <= A1[i] for q in pf)) if A1[i] > 0 else 0; f["відскок: тестів тієї ж точки"] = "0" if k == 0 else ("1" if k == 1 else "2+")
            f["розмах монети за 24 год"] = pd.cut([(h1["h"][i - 23:i + 1].max() / h1["l"][i - 23:i + 1].min() - 1) * 100], [0, 5, 10, 20, 1e9], labels=["<5%", "5–10%", "10–20%", ">20%"])[0]
        if i >= 25 and h1["v"][i - 24:i].mean() > 0: f["обсяг години до середнього"] = pd.cut([h1["v"][i] / h1["v"][i - 24:i].mean()], [-1, 1, 2, 4, 1e9], labels=["<1×", "1–2×", "2–4×", "4×+"])[0]
        for s_, nm in (("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")):
            if s_ not in ctx: continue
            b1, b4 = ctx[s_]; bi = int(np.searchsorted(b1["t"], r.ts - 3600, side="right")) - 1; bj = int(np.searchsorted(b4["t"], r.ts - 14400, side="right")) - 1
            if bi >= 25:
                v = side * ret(b1, bi, 24); f[f"{nm} за 24 год"] = pd.cut([v], [-1e9, -3, -1, 1, 3, 1e9], labels=["сильно ПРОТИ (>3%)", "проти 1–3%", "без руху", "у бік 1–3%", "сильно У БІК (>3%)"])[0]
                if nm == "BTC": v1 = side * ret(b1, bi, 1); f["BTC за 1 год"] = pd.cut([v1], [-1e9, -0.5, 0.5, 1e9], labels=["проти (>0,5%)", "без руху", "у бік (>0,5%)"])[0]
            if nm == "BTC" and bj >= 200: f["BTC тренд 4 год"] = "ЗА сигналом" if side * (b4["c"][bj] - b4["c"][bj - 199:bj + 1].mean()) > 0 else "ПРОТИ сигналу"
        f["монета"] = "акція/метал" if sym[:-4] in STOCK else "крипто"; f["вік монети"] = "нова (<60 діб)" if r.ts - first_t < 60 * 86400 and r.ts - first_t > 0 and (S.dt.min().timestamp() - first_t) < 30 * 86400 else "стара"
        rows.append(f)
Fm = pd.DataFrame(rows); X = S.merge(Fm, on=["ts", "sym"], how="left").sort_values("ts").reset_index(drop=True)
ts = X.ts.to_numpy(); dr = X.dir.to_numpy(); cl = []
for a in range(len(X)):
    lo = np.searchsorted(ts, ts[a] - 6 * 3600); n_ = int((dr[lo:a] == dr[a]).sum()); cl.append("0" if n_ == 0 else ("1–2" if n_ <= 2 else "3+"))
X["пачка: сигналів у той самий бік за 6 год"] = cl; prev = {}; pv = []
for r in X.itertuples():
    pv.append(prev.get(r.sym, "не було")); prev[r.sym] = "був стоп" if r.E0_st == "SL" else "був тейк"
X["попередній сигнал по монеті"] = pv
X["день тижня"] = X.dt.dt.day_name(); X["година (Київ)"] = ((X.dt.dt.hour + 2) % 24 // 3 * 3).astype(str) + ":00"
X["бал"] = pd.cut(X.score, [-2, 11, 15, 17, 19, 20]).astype(str); X["стоп %"] = pd.cut(X.E0_sp, [0, 2, 3, 4, 6, 50]).astype(str); X["R/R до TP1 за карткою"] = pd.cut(X.rr1, [0, 1.2, 1.5, 2, 3, 99]).astype(str)
X["RSI картки"] = pd.cut(X.rsi, [-2, 30, 45, 55, 70, 101]).astype(str); X["ADX картки"] = pd.cut(X.adx, [-2, 25, 40, 101]).astype(str); X["ATR% картки"] = pd.cut(X.atr, [-2, 1, 2, 3, 50]).astype(str)
X = X.rename(columns={"tier": "клас", "tf": "таймфрейм", "ses": "сесія", "regime": "режим ринку (бот)", "kz": "kill zone", "against": "проти денного тренду (бот)"})
X["u"] = 10 * X.E0X1; X["half"] = np.where(X.dt.dt.month <= 8, "A", "B"); X["t1"] = X.E0_st.isin(["TP1", "TP2", "TP3"]); X["t2"] = X.E0_st.isin(["TP2", "TP3"]); X["t3"] = X.E0_st == "TP3"; X["sl_"] = X.E0_st == "SL"
X.to_csv(OUT, index=False)
FEATS = ["тренд 4 год", "тренд 1 год", "BTC тренд 4 год", "BTC за 24 год", "BTC за 1 год", "ETH за 24 год", "рух монети за 1 год", "рух монети за 4 год", "рух монети за 24 год", "місце в діапазоні 7 діб", "відскок: відстань від 7-ден. екстремуму", "відскок: злив/виліт за 6 год",
         "відскок: тестів тієї ж точки", "спокійна монета", "розмах монети за 24 год", "обсяг години до середнього", "пачка: сигналів у той самий бік за 6 год", "попередній сигнал по монеті", "монета", "вік монети", "клас", "бал", "таймфрейм", "сесія", "режим ринку (бот)",
         "kill zone", "проти денного тренду (бот)", "RSI картки", "ADX картки", "ATR% картки", "стоп %", "R/R до TP1 за карткою", "день тижня", "година (Київ)"]
print(f"сигналів з підсумком: {len(X)}; з ознаками зі свічок: {int(X['тренд 1 год'].notna().sum())}")
FOUND = []
for dn, Z in (("SHORT", X[X.dir == "SHORT"]), ("LONG", X[X.dir == "LONG"]), ("УСІ", X)):
    ba, bb = Z[Z.half == "A"].u.mean(), Z[Z.half == "B"].u.mean()
    print(f"\n################ {dn}: {len(Z)} сигналів; стоп {100*Z.sl_.mean():.0f}%, TP1+ {100*Z.t1.mean():.0f}%, TP2+ {100*Z.t2.mean():.0f}%, TP3 {100*Z.t3.mean():.0f}%; $ на угоду {Z.u.mean():+.2f} (трав–серп {ba:+.2f}, вер–лист {bb:+.2f})")
    print(f"{'':44s} {'n':>4s} {'стоп':>5s} {'TP1+':>5s} {'TP2+':>5s} {'TP3':>4s} {'$/угоду':>8s} | {'трав–серп':>12s} | {'вер–лист':>12s}")
    for ft in FEATS:
        if ft not in Z: continue
        print(f" {ft}")
        for v, g in Z.groupby(ft, observed=True):
            if len(g) < 15: continue
            a, b = g[g.half == "A"], g[g.half == "B"]; ma, mb = (a.u.mean() if len(a) >= 8 else np.nan), (b.u.mean() if len(b) >= 8 else np.nan)
            mark = "   <<<" if (ma > ba and mb > bb and ma > 0 and mb > 0) else ("   >>>" if (ma < ba and mb < bb and ma < 0 and mb < 0) else "")
            print(f"    {str(v):40s} {len(g):4d} {100*g.sl_.mean():4.0f}% {100*g.t1.mean():4.0f}% {100*g.t2.mean():4.0f}% {100*g.t3.mean():3.0f}% {g.u.mean():+8.2f} | {ma:+6.2f} ({len(a):3d}) | {mb:+6.2f} ({len(b):3d}){mark}")
            if mark.strip() == "<<<": FOUND.append((dn, ft, str(v), len(g), g.u.mean(), ma, mb, g.u.sum()))
print("\n################ ПІДСУМОК: групи, плюсові й кращі за середнє в обох половинах"); 
for x in sorted(FOUND, key=lambda z: -z[7]): print(f"  {x[0]:5s} · {x[1]}: {x[2]} — {x[3]} сигналів, {x[4]:+.2f}$ на угоду (трав–серп {x[5]:+.2f}, вер–лист {x[6]:+.2f}), разом {x[7]:+.0f}$")
print("\n################ ЗБІГ ІЗ НАШИМИ СИСТЕМАМИ")
for dn, Z in (("SHORT", X[X.dir == "SHORT"]), ("LONG", X[X.dir == "LONG"])):
    if "тренд 4 год" in Z:
        a = Z[Z["тренд 4 год"] == "ЗА трендом"]; b = Z[Z["тренд 4 год"] == "ПРОТИ тренду"]; print(f" {dn}: як у СВІНГУ (за трендом 4 год): {len(a)} сигналів, {a.u.mean():+.2f}$; проти тренду: {len(b)}, {b.u.mean():+.2f}$")
    if "відскок: злив/виліт за 6 год" in Z:
        m = (Z["відскок: злив/виліт за 6 год"] == "так") & (Z["відскок: відстань від 7-ден. екстремуму"] == ">20%") & (Z["відскок: тестів тієї ж точки"] != "0"); a = Z[m]
        print(f" {dn}: умови ВІДСКОКУ (злив/виліт + >20% + точку тестували): {len(a)} сигналів" + (f", {a.u.mean():+.2f}$, TP1+ {100*a.t1.mean():.0f}%" if len(a) else ""))
        m2 = (Z["відскок: відстань від 7-ден. екстремуму"] == ">20%"); a = Z[m2]; print(f" {dn}: лише «>20% від 7-денного екстремуму»: {len(a)} сигналів" + (f", {a.u.mean():+.2f}$, TP1+ {100*a.t1.mean():.0f}%, TP3 {100*a.t3.mean():.0f}%" if len(a) else ""))
