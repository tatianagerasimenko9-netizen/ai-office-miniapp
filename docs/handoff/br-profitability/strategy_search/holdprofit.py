"""READ-ONLY. Купи сигналів в один бік: чи допомагає обмеження одночасних угод в один бік (A) або відбір найкращих за оцінкою моделі в межах одного H1-бару й напряму (B).
Ті самі угоди TD-V1 (12 монет, фіксований поріг, вхід M15), $10 ризику, SL-first. Використання: holdprofit.py CANDLES_DIR TRAIN COST"""
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
    sel = pd.concat(parts); cache = {}; trades = []
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
            rs, fin, kind = path(a, j, side, ent, sl, tp)
            trades.append((float(a["open_time"][j] + 900), int(pd.to_datetime(x.t, unit="s").year), np.array(rs), fin, kind, sp)); break
    print(f"Угод {len(trades)}; комісія {C*100:.2f}%; $10 ризику; забираємо прибуток, якщо угода відкрита ≥ T годин і на закритті M15 у плюсі ≥ X R (до цілі/стопа)")
    def evaluate(T, Xr):
        out = []
        for t_in, yr, rs, fin, kind, sp in trades:
            r = fin; took = False
            if Xr is not None:
                k0 = int(T * 4)
                for k in range(k0, len(rs)):
                    if rs[k] >= Xr: r = rs[k]; took = True; break
            out.append((t_in, yr, r - C / sp, took))
        d = pd.DataFrame(out, columns=["t", "year", "r", "took"]); d["usd"] = 10 * d.r; return d
    def stat(d):
        z = d.sort_values("t"); cum = z.usd.cumsum(); dd = (cum - cum.cummax()).min()
        mo = z.groupby(pd.to_datetime(z.t, unit="s").dt.to_period("M")).usd.sum()
        return z.usd.sum(), [z[z.year == y].usd.sum() for y in (2024, 2025, 2026)], dd, mo.min(), int((mo < 0).sum()), 100 * z.took.mean(), 100 * (z.usd > 0).mean()
    print("\n| правило | усього $ | 2024 | 2025 | 2026 | найглибша просадка $ | найгірший місяць $ | місяців у мінусі | частка угод, де забрали | плюсових угод |\n|--|--|--|--|--|--|--|--|--|--|")
    def line(nm, d):
        tot, ys, dd, wm, nm_, tk, wr = stat(d)
        print(f"| {nm} | {tot:+,.0f} | " + " | ".join(f"{v:+,.0f}" for v in ys) + f" | {dd:,.0f} | {wm:+,.0f} | {nm_} | {tk:.0f}% | {wr:.0f}% |")
    line("0. Як зараз: тримати до цілі, стопа або 48 год", evaluate(0, None))
    for T in (4, 8, 12, 24):
        for Xr in (0.5, 1.0, 2.0, 3.0):
            line(f"Після {T} год, якщо плюс ≥ +{Xr:g}R: забрати", evaluate(T, Xr))
    print("\nПримітка: 16 правил = кратне порівняння; корисним вважається те, що не знижує підсумок у всі роки й за обох комісій.\n##### ПІДСУМОК holdprofit завершено")
if __name__ == "__main__": main()
