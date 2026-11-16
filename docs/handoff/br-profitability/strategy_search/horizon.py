"""READ-ONLY. Чи варто тримати угоди довше за 48 год? Модель TD-V1 (12 монет, 2024-2026, вхід M15 як у живому скані): той самий стоп і ціль плану H1, змінюється лише час виходу.
Горизонти: 24 год, 48 (поточний), 72, 96, 7 діб, 14 діб. $10 ризику, комісія COST. SL-першим. Використання: horizon.py CANDLES_DIR TRAIN_SYMS COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], float(sys.argv[3])
sys.argv = ["x", CD, TRAIN, TRAIN, str(COST)]
import newcoins as nc
md, td = nc.md, nc.td
HZ = [("24 год", 96), ("48 год (зараз)", 192), ("72 год", 288), ("96 год", 384), ("7 діб", 672), ("14 діб", 1344)]

def walk(a, j, side, ent, sl, tp, hz):
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl)
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): return None
        if (l[q] <= sl) if side > 0 else (h[q] >= sl): return -1.0, "SL"
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return side * (tp - ent) / risk, "TP"
    return side * (c[j + hz] - ent) / risk, "TIME"

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = nc.HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy(); z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
    sel = pd.concat(parts); cache = {}; out = {n: [] for n, _ in HZ}
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"]))
        a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
        for k in range(16):
            j = i0 + k
            if j < 9 or j >= len(c_) - 1400: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            for n, hz in HZ:
                w = walk(a, j, side, ent, sl, tp, hz)
                if w: out[n].append((w[0] - COST / sp, w[1], pd.Timestamp(x.t, unit="s").year))
            break
    print(f"Комісія {COST*100:.2f}% за круг; $10 ризику; 12 монет; одні й ті самі {len(out['48 год (зараз)'])} угод; змінюється тільки час виходу")
    print("| тримати до | угод | ціль | стоп | за часом | виграшних | усього $ | 2024 | 2025 | 2026 | $/угоду |\n|--|--|--|--|--|--|--|--|--|--|--|")
    for n, _ in HZ:
        d = pd.DataFrame(out[n], columns=["r", "o", "y"]); u = 10 * d.r
        print(f"| {n} | {len(d)} | {(d.o=='TP').sum()} | {(d.o=='SL').sum()} | {(d.o=='TIME').sum()} | {100*(d.r>0).mean():.0f}% | {u.sum():+,.0f} | " + " | ".join(f"{u[d.y==y].sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {u.mean():+.2f} |")
    print("\n##### ПІДСУМОК horizon завершено")
if __name__ == "__main__": main()
