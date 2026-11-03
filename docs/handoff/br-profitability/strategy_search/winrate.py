"""READ-ONLY. Розбивка угод TD-V1 (12 монет): скільки плюсових/мінусових, середні, серії, просадка. Використання: winrate.py CANDLES_DIR TRAIN COST"""
import os, sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, HG = nc.md, nc.HistGradientBoostingRegressor

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = HG(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy(); z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
    res = nc.m15_stage(pd.concat(parts)); df = pd.DataFrame(res, columns=["r", "t", "sym"]).sort_values("t").reset_index(drop=True)
    df["usd"] = 10 * df.r; df["year"] = pd.to_datetime(df.t, unit="s").dt.year
    t0, t1 = pd.to_datetime(df.t.min(), unit="s"), pd.to_datetime(df.t.max(), unit="s")
    print(f"Період угод: {t0:%Y-%m-%d} .. {t1:%Y-%m-%d}; монет: {df.sym.nunique()}; комісія {float(COST)*100:.2f}%; $10 ризику на угоду")
    def block(d, name):
        w, l = d[d.usd > 0], d[d.usd <= 0]; stop = d[d.r <= -0.99]; tp = d[d.r > 2]; tm = d[(d.r > -0.99) & (d.r <= 2)]
        print(f"{name}: угод {len(d)}; ПЛЮС {len(w)} ({100*len(w)/len(d):.1f}%), МІНУС {len(l)} ({100*len(l)/len(d):.1f}%); сума ${d.usd.sum():+,.0f}")
        print(f"   сер. плюсова ${w.usd.mean():+.1f}, сер. мінусова ${l.usd.mean():+.1f}; найбільша плюсова ${d.usd.max():+.0f}, найбільша мінусова ${d.usd.min():+.0f}")
        print(f"   валові: плюси ${w.usd.sum():+,.0f}, мінуси ${l.usd.sum():+,.0f}")
        print(f"   за стопом: {len(stop)} (${stop.usd.sum():+,.0f}); за ціллю (>2R): {len(tp)} (${tp.usd.sum():+,.0f}); закриті за часом/інше: {len(tm)} (${tm.usd.sum():+,.0f}; з них плюс {int((tm.usd>0).sum())})")
    block(df, "УСЬОГО")
    for y in (2024, 2025, 2026): block(df[df.year == y], f"  {y}")
    s = (df.usd <= 0).to_numpy(); best = cur = 0
    for v in s: cur = cur + 1 if v else 0; best = max(best, cur)
    cum = df.usd.cumsum(); dd = (cum - cum.cummax()).min()
    print(f"Найдовша серія мінусів поспіль: {best}; найглибша просадка кривої: ${dd:,.0f}; кінцевий результат ${cum.iloc[-1]:+,.0f}")
    print("Місяці з мінусом:", int((df.groupby(pd.to_datetime(df.t, unit='s').dt.to_period('M')).usd.sum() < 0).sum()), "із", df.groupby(pd.to_datetime(df.t, unit='s').dt.to_period('M')).ngroups)
    print("\n##### ПІДСУМОК winrate завершено")
if __name__ == "__main__": main()
