"""READ-ONLY. Чи пов'язана глибина стакана Binance (±1/2/3% від ціни, bookDepth, знімок на годину сигналу) з результатом TD-V1? Ті самі угоди (12 монет, фіксований поріг, M15), $10 ризику.
ОБМЕЖЕННЯ: bookDepth = сумарні заявки в межах % від ціни, НЕ окремі стіни на конкретній ціні. Це груба перевірка. Використання: bookdepth_test.py CANDLES_DIR TRAIN COST BOOK_DIR"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST, BD = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST)

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
    sel = pd.concat(parts); cache = {}; BK = {}; rows = []
    import os
    def book(s):
        if s not in BK:
            p = f"{BD}/{s}.csv"; BK[s] = pd.read_csv(p) if os.path.exists(p) else None
            if BK[s] is not None:
                B = BK[s]; B["tot2"] = B["n-2"] + B["n2"]; B["med"] = B.tot2.rolling(24 * 7, min_periods=24).median()
        return BK[s]
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
            B = book(x.sym); feat = {}
            if B is not None:
                ti = int(np.searchsorted(B.ts.to_numpy(), a["open_time"][j], side="right")) - 1       # останній знімок на момент входу
                if ti >= 0 and a["open_time"][j] - B.ts.iloc[ti] < 7200:
                    rw = B.iloc[ti]; bid = lambda p: rw[f"n-{p}"]; ask = lambda p: rw[f"n{p}"]
                    behind = (lambda p: bid(p)) if side > 0 else (lambda p: ask(p)); ahead = (lambda p: ask(p)) if side > 0 else (lambda p: bid(p))
                    for p in (1, 2, 3):
                        feat[f"imb{p}"] = (behind(p) - ahead(p)) / (behind(p) + ahead(p))       # >0: з боку стопа заявок більше, ніж на шляху до цілі
                    feat["thin"] = rw["tot2"] / rw["med"] if rw["med"] == rw["med"] else np.nan   # загальна глибина ±2% відносно медіани тижня
            rows.append(dict(t=x.t, sym=x.sym, side=side, r=r, **feat)); break
    d = pd.DataFrame(rows); d["year"] = pd.to_datetime(d.t, unit="s").dt.year; d["usd"] = 10 * d.r
    have = d.dropna(subset=["imb2"]) if "imb2" in d else d.iloc[0:0]
    print(f"Угод {len(d)}; зі знімком стакана {len(have)} ({100*len(have)/len(d):.0f}%); по роках: " + ", ".join(f"{y}: {int((have.year==y).sum())}" for y in (2024, 2025, 2026)) + f"; комісія {C*100:.2f}%; $10 ризику")
    if len(have) < 200: print("Замало даних."); return
    print(f"База на цих угодах: R {have.r.mean():+.3f}, $ {have.usd.sum():+,.0f}")
    for col, nm in (("imb1", "дисбаланс ±1% (позитивно = більше заявок З БОКУ СТОПА, ніж на шляху до цілі)"), ("imb2", "дисбаланс ±2%"), ("imb3", "дисбаланс ±3%"), ("thin", "загальна глибина ±2% відносно тижневої медіани (малі = тонкий стакан)")):
        z = have.dropna(subset=[col]).copy(); z["q"] = pd.qcut(z[col], 3, labels=["нижня третина", "середня", "верхня третина"])
        print(f"\n{nm}")
        print("| група | угод | R/угоду | усього $ | 2024 | 2025 | 2026 | плюсових |\n|--|--|--|--|--|--|--|--|")
        for q, g in z.groupby("q", observed=True):
            print(f"| {q} | {len(g)} | {g.r.mean():+.3f} | {g.usd.sum():+,.0f} | " + " | ".join(f"{g[g.year==y].usd.sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {100*(g.r>0).mean():.0f}% |")
        print(f"   кореляція (Spearman) із R: {z[col].corr(z.r, method='spearman'):+.3f}")
    print("\nПримітка: 4 ознаки × 3 групи — кратне порівняння; ефект має бути однаковим у всі роки, щоб йому вірити.\n##### ПІДСУМОК bookdepth завершено")
if __name__ == "__main__": main()
