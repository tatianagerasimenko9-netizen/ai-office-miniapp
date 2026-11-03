"""READ-ONLY. Тривалість угод TD-V1 (12 монет, фіксований поріг, M15-етап). Використання: duration.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor

def sim2(a, j, side, ent, sl, tp, hz=192):
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl)
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): return k - 1, "кінець даних"
        if (l[q] <= sl) if side > 0 else (h[q] >= sl): return k, "стоп"
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return k, "ціль"
    return hz, "час 48г"

def stage(sel):
    out = []; cache = {}
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
            r = td.sim(a, j, side, ent, sl, tp) - float(COST) / sp
            bars, how = sim2(a, j, side, ent, sl, tp)
            out.append((r, bars * 15 / 60.0, how, k * 15, sp, (tp - ent) * side / abs(ent - sl), x.t)); break
    return pd.DataFrame(out, columns=["r", "hours", "how", "wait_min", "sp", "planR", "t"])

def q(s): return f"мін {s.min():.1f} | 25% {s.quantile(.25):.1f} | медіана {s.median():.1f} | середня {s.mean():.1f} | 75% {s.quantile(.75):.1f} | 90% {s.quantile(.9):.1f} | макс {s.max():.1f}"

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
    d = stage(pd.concat(parts)); print(f"Угод {len(d)}; комісія {float(COST)*100:.2f}%")
    print("ТРИВАЛІСТЬ УТРИМАННЯ, години (від входу до виходу):", q(d.hours))
    print("  після сигналу H1 до входу M15, хв: ", q(d.wait_min))
    for how, g in d.groupby("how"): print(f"  вихід «{how}»: {len(g)} угод ({100*len(g)/len(d):.0f}%); години: медіана {g.hours.median():.1f}, середня {g.hours.mean():.1f}, 90% {g.hours.quantile(.9):.1f}")
    for lo, hi, nm in ((0, 1, "до 1 год"), (1, 4, "1-4 год"), (4, 12, "4-12 год"), (12, 24, "12-24 год"), (24, 48.01, "24-48 год")):
        g = d[(d.hours > lo) & (d.hours <= hi)] if lo else d[d.hours <= hi]
        print(f"  {nm}: {len(g)} угод ({100*len(g)/len(d):.0f}%), ${10*g.r.sum():+,.0f}")
    w = d[d.r > 0]; l = d[d.r <= 0]
    print(f"  плюсові: медіана {w.hours.median():.1f} год, середня {w.hours.mean():.1f}; мінусові: медіана {l.hours.median():.1f} год, середня {l.hours.mean():.1f}")
    print(f"Сер. стоп {100*d.sp.mean():.2f}% ціни; сер. ціль {100*(d.sp*d.planR).mean():.2f}% ціни; план ≈ {d.planR.median():.1f}R")
    print("\n##### ПІДСУМОК duration завершено")
if __name__ == "__main__": main()
