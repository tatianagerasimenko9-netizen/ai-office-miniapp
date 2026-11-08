"""READ-ONLY. Купи сигналів в один бік: чи допомагає обмеження одночасних угод в один бік (A) або відбір найкращих за оцінкою моделі в межах одного H1-бару й напряму (B).
Ті самі угоди TD-V1 (12 монет, фіксований поріг, вхід M15), $10 ризику, SL-first. Використання: timing.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST)

def path(a, j, side, ent, sl, tp, hz=192):
    """повертає масив R за закриттям кожного бару до виходу за SL/TP/часом і підсумок {'sl'|'tp'|'time'}"""
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl); rs = []
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): break
        if (l[q] <= sl) if side > 0 else (h[q] >= sl): return rs, -1.0, "sl"
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return rs, side * (tp - ent) / risk, "tp"
        rs.append(side * (c[q] - ent) / risk)
    last = rs[-1] if rs else 0.0
    return rs, last, "time"

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X_ = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = HG(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X_], tr.r)
    thr = float(np.quantile(m.predict(va[X_]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy(); z["s"] = m.predict(z[X_]); parts.append(md.dedupe(z[z.s >= thr]))
    sel = pd.concat(parts); cache = {}; T = []
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
            rs, fin, kind = path(a, j, side, ent, sl, tp); T.append((np.array(rs), kind, (tp - ent) * side / abs(ent - sl))); break
    print(f"ІСТОРІЯ 2024-2026: угод {len(T)}. Коли ціна на закритті M15 уперше стає в плюсі >= X R і чим угода закінчилась")
    print("| плюс X | угод досягли X | з них закінчились: ціль / стоп (віддали) / час 48 год | через скільки годин після входу вперше (25% / медіана / 75% / 90%) | досягли за ≤ 2 год | ≤ 4 год | ≤ 8 год |\n|--|--|--|--|--|--|--|")
    for X in (0.5, 1.0, 2.0, 3.0):
        hrs = []; ends = {"tp": 0, "sl": 0, "time": 0}
        for rs, kind, planR in T:
            idx = np.where(rs >= X)[0]
            if len(idx): hrs.append((idx[0] + 1) / 4.0); ends[kind] += 1
        h = np.array(hrs); n = len(h)
        q = np.percentile(h, [25, 50, 75, 90]) if n else [0, 0, 0, 0]
        print(f"| +{X:g}R | {n} ({100*n/len(T):.0f}%) | {100*ends['tp']/n:.0f}% / {100*ends['sl']/n:.0f}% / {100*ends['time']/n:.0f}% | {q[0]:.1f} / {q[1]:.1f} / {q[2]:.1f} / {q[3]:.1f} год | {100*(h<=2).mean():.0f}% | {100*(h<=4).mean():.0f}% | {100*(h<=8).mean():.0f}% |")
    print("\nПО РЕЗУЛЬТАТУ УГОДИ (коли вперше бул +1R): що було далі")
    for kind, nm in (("tp", "дійшли до цілі"), ("sl", "закрились стопом ПІСЛЯ того, як були в +1R"), ("time", "закінчились за часом 48 год")):
        hrs = [((np.where(rs >= 1.0)[0][0] + 1) / 4.0, rs[np.where(rs >= 1.0)[0][0]:].max()) for rs, k_, _ in T if k_ == kind and (rs >= 1.0).any()]
        if hrs:
            h = np.array([a for a, _ in hrs]); mx = np.array([b for _, b in hrs])
            print(f"  {nm}: {len(h)} угод; перший +1R через {np.median(h):.1f} год (медіана); пік після цього в середньому {mx.mean():+.1f}R")
    print("\n##### ПІДСУМОК timing (історія) завершено")
import os
if __name__ == "__main__": main()
