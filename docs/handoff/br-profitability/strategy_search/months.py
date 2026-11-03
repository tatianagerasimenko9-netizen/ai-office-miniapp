"""READ-ONLY. Місяці по черзі (чи йшли мінуси підряд) і симуляція депозиту $1000: фіксований ризик проти ризику у % від поточного депозиту (складний відсоток). TD-V1, 12 монет, фіксований поріг.
Використання: months.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, COST]
import duration as du
md, nc, HG = du.md, du.nc, du.HG

def sim(d, dep, mode, val):
    """mode 'fix': ризик val $ на угоду; 'pct': ризик val*депозит (на момент входу). Закриті угоди, хронологічно."""
    ev = sorted([(e, 1, i) for i, e in enumerate(d.entry)] + [(x, 0, i) for i, x in enumerate(d["exit"])], key=lambda z: (z[0], z[1]))
    eq = dep; risk = {}; peak = dep; mdd = 0.0; mn = dep; mdd_usd = 0.0
    for t, k, i in ev:
        if k == 1: risk[i] = val if mode == "fix" else val * eq
        else:
            eq += risk[i] * d.r.iloc[i]; peak = max(peak, eq); mn = min(mn, eq)
            mdd = min(mdd, eq / peak - 1); mdd_usd = min(mdd_usd, eq - peak)
    return eq, mdd, mn, mdd_usd

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
    d = du.stage(pd.concat(parts)).reset_index(drop=True); d["entry"] = d.t + 3600 + d.wait_min * 60; d["exit"] = d.entry + d.hours * 3600
    print(f"Угод {len(d)}; комісія {float(COST)*100:.2f}%")
    d["mon"] = pd.to_datetime(d["exit"], unit="s").dt.to_period("M"); mm = d.groupby("mon").agg(n=("r", "size"), usd=("r", lambda s: 10 * s.sum()))
    print("\nМІСЯЦІ (за місяцем закриття угод), $ при ризику $10 на угоду:")
    streak = best = 0; cur_s = []; worst_runs = []
    for p, row in mm.iterrows():
        neg = row.usd < 0; print(f"  {p}: угод {int(row.n):3d}  {row.usd:+8,.0f}  {'МІНУС' if neg else ''}")
        if neg: streak += 1; cur_s.append(str(p))
        else:
            if streak: worst_runs.append(list(cur_s))
            streak = 0; cur_s = []
        best = max(best, streak)
    if streak: worst_runs.append(list(cur_s))
    print(f"Місяців {len(mm)}; у мінусі {int((mm.usd<0).sum())}; найдовша серія мінусових місяців підряд: {max([len(r) for r in worst_runs] or [0])}; серії: {[ (r[0], len(r)) for r in worst_runs]}")
    print(f"Найкращий місяць ${mm.usd.max():+,.0f}; найгірший ${mm.usd.min():+,.0f}; медіана ${mm.usd.median():+,.0f}")
    rolling = mm.usd.rolling(3).sum().dropna(); print(f"Найгірші 3 місяці підряд: ${rolling.min():+,.0f}; 6 місяців: ${mm.usd.rolling(6).sum().min():+,.0f}")
    print("\nДЕПОЗИТ $1000 (закриті угоди, без проковзування/плаваючих збитків/маржі):")
    print("| схема | кінцевий депозит | прибуток | найглибша просадка | мін. депозит |\n|--|--|--|--|--|")
    for dep in (1000,):
        for mode, val, nm in (("fix", 1, "фіксований ризик $1 (0,1%)"), ("fix", 2, "фіксований ризик $2 (0,2%)"), ("fix", 5, "фіксований ризик $5 (0,5%)"), ("pct", .001, "складний % : 0,1% депозиту на угоду"), ("pct", .002, "складний % : 0,2% на угоду"), ("pct", .005, "складний % : 0,5% на угоду")):
            eq, mdd, mn, mdd_usd = sim(d, dep, mode, val)
            print(f"| {nm} | ${eq:,.0f} | {eq-dep:+,.0f} ({(eq/dep-1)*100:+.0f}%) | {mdd*100:.1f}% (${mdd_usd:,.0f}) | ${mn:,.0f} |")
    print("\n##### ПІДСУМОК months завершено")
if __name__ == "__main__": main()
