"""READ-ONLY. Часткові тейки для TD-V1: чи краще фіксувати частинами, ніж одна ціль? Ті самі угоди (12 монет, фіксований поріг, вхід M15), $10 ризику.
Рівні в R від стопа M15; фінальна ціль = план H1 (як зараз). Комісія COST/стоп на всю позицію. SL-first; беззбиток діє з наступного бару. Використання: partials.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST)
SCHEMES = {
    "A. Одна ціль (як зараз)": ([], False),
    "B. 50% на 1R + 50% ціль": ([(1.0, .5)], False),
    "C. 50% на 1R + 50% ціль, стоп у беззбиток після 1R": ([(1.0, .5)], True),
    "D. 50% на 2R + 50% ціль": ([(2.0, .5)], False),
    "E. 50% на 2R + 50% ціль, беззбиток після 2R": ([(2.0, .5)], True),
    "F. по 1/3 на 1R, 2R і ціль (без беззбитку)": ([(1.0, 1/3), (2.0, 1/3)], False),
    "G. по 1/3 на 1R, 2R і ціль, беззбиток після 1R": ([(1.0, 1/3), (2.0, 1/3)], True),
    "H. 1/3 на 1R, 1/3 на 3R, 1/3 ціль, беззбиток після 1R": ([(1.0, 1/3), (3.0, 1/3)], True),
}

def trade(a, j, side, ent, sl, tp, legs, be, hz=192):
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl); fin = (tp - ent) * side / risk
    legs = [(lv, fr) for lv, fr in legs if lv < fin - 1e-9]; done = [False] * len(legs); pos = 1.0; r = 0.0; stop = sl; moved = False
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): break
        if (l[q] <= stop) if side > 0 else (h[q] >= stop): return r + pos * side * (stop - ent) / risk
        for n, (lv, fr) in enumerate(legs):
            if done[n]: continue
            px = ent + side * lv * risk
            if (h[q] >= px) if side > 0 else (l[q] <= px):
                r += fr * lv; pos -= fr; done[n] = True
                if be and not moved: stop = ent; moved = True
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return r + pos * fin
        if pos <= 1e-9: return r
    return r + pos * side * (c[min(j + hz, len(c) - 1)] - ent) / risk

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
    sel = pd.concat(parts); cache = {}; res = {k: [] for k in SCHEMES}; yrs = []; stops = []; fins = []
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
            for nm, (legs, be) in SCHEMES.items(): res[nm].append(trade(a, j, side, ent, sl, tp, legs, be) - C / sp)
            yrs.append(int(pd.to_datetime(x.t, unit="s").year)); fins.append((tp - ent) * side / abs(ent - sl)); break
    yrs = np.array(yrs); print(f"Угод {len(yrs)}; комісія {C*100:.2f}%; $10 ризику; фінальна ціль у середньому {np.mean(fins):.1f}R (медіана {np.median(fins):.1f}R)")
    print("| схема | усього $ | 2024 | 2025 | 2026 | плюсових угод | сер. $ на угоду | найглибша просадка $ |\n|--|--|--|--|--|--|--|--|")
    for nm, v in res.items():
        v = np.array(v); cum = np.cumsum(10 * v); dd = (cum - np.maximum.accumulate(cum)).min()
        print(f"| {nm} | {10*v.sum():+,.0f} | " + " | ".join(f"{10*v[yrs==y].sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {100*(v>0).mean():.0f}% | {10*v.mean():+.2f} | {dd:,.0f} |")
    print("\n##### ПІДСУМОК partials завершено")
if __name__ == "__main__": main()
