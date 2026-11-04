"""READ-ONLY. Скільки угод відкрито одночасно і який потрібен депозит (TD-V1, 12 монет, фіксований поріг). $10 ризику на угоду; позиція = 10/стоп. Використання: exposure.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, COST]
import duration as du
md, nc, HG = du.md, du.nc, du.HG

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
    d = du.stage(pd.concat(parts)); d["entry"] = d.t + 3600 + d.wait_min * 60; d["exit"] = d.entry + d.hours * 3600; d["notional"] = 10.0 / d.sp; d["usd"] = 10 * d.r
    print(f"Угод {len(d)}; комісія {float(COST)*100:.2f}%; $10 ризику; позиція = $10/стоп")
    print(f"Позиція на 1 угоду ($): сер. {d.notional.mean():,.0f}; медіана {d.notional.median():,.0f}; 90% {d.notional.quantile(.9):,.0f}; макс {d.notional.max():,.0f}")
    ev = sorted([(e, 1, n) for e, n in zip(d.entry, d.notional)] + [(x, -1, n) for x, n in zip(d["exit"], d.notional)], key=lambda z: (z[0], z[1]))
    cnt = 0; notl = 0.0; c_ = []; n_ = []; last = ev[0][0]; wc = []; wn = []; peakc = 0; peakn = 0
    for t, k, n in ev:
        wc.append((t - last, cnt)); wn.append((t - last, notl)); last = t
        cnt += k; notl += k * n; peakc = max(peakc, cnt); peakn = max(peakn, notl)
    tot = sum(w for w, _ in wc); avgc = sum(w * c for w, c in wc) / tot; avgn = sum(w * c for w, c in wn) / tot
    def pct(vals, q):
        vs = sorted(vals, key=lambda z: z[1]); acc = 0
        for w, v in vs:
            acc += w
            if acc >= q * tot: return v
    print(f"Одночасно відкритих угод: у середньому {avgc:.1f}; 95% часу ≤ {pct(wc,.95):.0f}; 99% часу ≤ {pct(wc,.99):.0f}; максимум {peakc}")
    print(f"Сума відкритих позицій ($): у середньому {avgn:,.0f}; 95% часу ≤ {pct(wn,.95):,.0f}; 99% часу ≤ {pct(wn,.99):,.0f}; максимум {peakn:,.0f}")
    z = d.sort_values("exit"); cum = z.usd.cumsum(); dd = (cum - cum.cummax()).min()
    print(f"Просадка за закритими угодами (за часом закриття): ${dd:,.0f}; кінцевий результат ${cum.iloc[-1]:+,.0f}; пік прибутку ${cum.max():+,.0f}")
    for y in (2024, 2025, 2026):
        q = z[z.year == y] if "year" in z else None
    print(f"Найгірший місяць: ${z.groupby(pd.to_datetime(z['exit'], unit='s').dt.to_period('M')).usd.sum().min():,.0f}")
    print("\n##### ПІДСУМОК exposure завершено")
if __name__ == "__main__": main()
