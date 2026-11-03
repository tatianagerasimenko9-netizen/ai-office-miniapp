"""READ-ONLY. Чому липень-грудень 2025 був у мінусі? Розріз TD-V1 (12 монет, фіксований поріг, вхід M15) по місяцях: напрям, тренд BTC/монети. Далі ГІПОТЕЗА-фільтри «лише за трендом».
$10 ризику, комісія COST. Використання: regime.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST)

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float); bt = b.open_time.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=bt)
    A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = HG(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy(); z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
    sel = pd.concat(parts); cache = {}; H = {}; rows = []
    def h1(s):
        if s not in H:
            d = md.load_h1(s); H[s] = (d.open_time.to_numpy(float), d.close.to_numpy(float))
        return H[s]
    def trend(s, t, n):
        ts, cl = h1(s); i = int(np.searchsorted(ts, t)); 
        return cl[i] / cl[i - n] - 1 if i >= n else np.nan
    def vs_sma(s, t, n):
        ts, cl = h1(s); i = int(np.searchsorted(ts, t))
        return cl[i] / cl[i - n + 1:i + 1].mean() - 1 if i >= n else np.nan
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"]))
        a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
        for k in range(16):
            j = i0 + k
            if j < 9 or j >= len(c_) - 2: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            r = td.sim(a, j, side, ent, sl, tp) - C / sp
            rows.append(dict(t=x.t, sym=x.sym, side=side, r=r, c30=trend(x.sym, x.t, 720), b30=trend("BTCUSDT", x.t, 720), c7=trend(x.sym, x.t, 168), sma100=vs_sma(x.sym, x.t, 2400), b7=trend("BTCUSDT", x.t, 168))); break
    d = pd.DataFrame(rows); d["mon"] = pd.to_datetime(d.t, unit="s").dt.to_period("M"); d["year"] = pd.to_datetime(d.t, unit="s").dt.year; d["usd"] = 10 * d.r
    print(f"Угод {len(d)}; комісія {C*100:.2f}%; $10 ризику; місяць = місяць сигналу")
    print("\nПО МІСЯЦЯХ: n | % лонгів | $ лонги | $ шорти | % плюсових | зміна BTC за місяць")
    bm = pd.Series(bc, index=pd.to_datetime(bt, unit="s")).resample("ME").last().pct_change()
    for p, g in d.groupby("mon"):
        lg, sh = g[g.side > 0], g[g.side < 0]; bmr = bm.loc[bm.index.to_period("M") == p]
        print(f"  {p}: n={len(g):3d} | лонг {100*len(lg)/len(g):3.0f}% | ${lg.usd.sum():+6,.0f} | ${sh.usd.sum():+6,.0f} | плюс {100*(g.r>0).mean():2.0f}% | BTC {100*bmr.iloc[0] if len(bmr) else float('nan'):+5.1f}%")
    for nm, g in (("УСІ", d), ("липень-грудень 2025", d[(d.t >= pd.Timestamp('2025-07-01').timestamp()) & (d.t < pd.Timestamp('2026-01-01').timestamp())]), ("решта періоду", d[~((d.t >= pd.Timestamp('2025-07-01').timestamp()) & (d.t < pd.Timestamp('2026-01-01').timestamp()))])):
        lg, sh = g[g.side > 0], g[g.side < 0]
        print(f"{nm}: n={len(g)}; лонги n={len(lg)} ${lg.usd.sum():+,.0f} (R {lg.r.mean():+.3f}); шорти n={len(sh)} ${sh.usd.sum():+,.0f} (R {sh.r.mean():+.3f}); сер. тренд монети за 30д у момент сигналу: лонги {100*lg.c30.mean():+.1f}%, шорти {100*sh.c30.mean():+.1f}%")
    ws = (d.t >= pd.Timestamp('2025-07-01').timestamp()) & (d.t < pd.Timestamp('2026-01-01').timestamp())
    print("\nФІЛЬТРИ «лише за трендом» (ГІПОТЕЗА; перебір кількох = кратне порівняння):")
    print("| фільтр | угод | усього $ | 2024 | 2025 | 2026 | з них лип-грудень 2025 |\n|--|--|--|--|--|--|--|")
    F = {"0. Без фільтра": pd.Series(True, index=d.index),
         "1. Напрям збігається з трендом монети за 30 днів": (d.side * d.c30 > 0),
         "2. Напрям збігається з трендом BTC за 30 днів": (d.side * d.b30 > 0),
         "3. Напрям збігається: ціна монети вище/нижче середньої 100 днів": (d.side * d.sma100 > 0),
         "4. Напрям збігається з трендом монети за 7 днів": (d.side * d.c7 > 0),
         "5. Напрям ПРОТИ тренду монети за 30 днів (контроль)": (d.side * d.c30 < 0)}
    for nm, f in F.items():
        z = d[f.fillna(False)]; w = z[(z.t >= pd.Timestamp('2025-07-01').timestamp()) & (z.t < pd.Timestamp('2026-01-01').timestamp())]
        print(f"| {nm} | {len(z)} | {z.usd.sum():+,.0f} | " + " | ".join(f"{z[z.year==y].usd.sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {w.usd.sum():+,.0f} (n={len(w)}) |")
    print("\n##### ПІДСУМОК regime завершено")
if __name__ == "__main__": main()
