"""READ-ONLY. Купи сигналів в один бік: чи допомагає обмеження одночасних угод в один бік (A) або відбір найкращих за оцінкою моделі в межах одного H1-бару й напряму (B).
Ті самі угоди TD-V1 (12 монет, фіксований поріг, вхід M15), $10 ризику, SL-first. Використання: randomcontrol.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST)

def run(a, j, side, ent, sl, tp, hz=192):
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl)
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): break
        if (l[q] <= sl) if side > 0 else (h[q] >= sl): return -1.0, q
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return side * (tp - ent) / risk, q
    q = min(j + hz, len(c) - 1); return side * (c[q] - ent) / risk, q

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
    sel = pd.concat(parts); cache = {}; rows = []
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"]))
        a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]; rec = dict(sym=x.sym, side=side, score=float(x.s), h1=float(x.t), conf=False, t_in=np.nan, t_out=np.nan, r=np.nan, year=int(pd.to_datetime(x.t, unit="s").year))
        for k in range(16):
            j = i0 + k
            if j < 9 or j >= len(c_) - 2: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            r, q = run(a, j, side, ent, sl, tp)
            rec.update(conf=True, t_in=float(a["open_time"][j] + 900), t_out=float(a["open_time"][q] + 900), r=r - C / sp); break
        rows.append(rec)
    D = pd.DataFrame(rows); D["usd"] = 10 * D.r
    d = D[D.conf].sort_values("t_in").reset_index(drop=True)
    print(f"Кандидатів H1 {len(D)}; з M15-підтвердженням (угод) {len(d)} ({100*len(d)/len(D):.0f}%); комісія {C*100:.2f}%; $10 ризику")
    G = D.groupby(["h1", "side"]).size(); print(f"Купи: годинних барів-напрямів {len(G)}; з 2+ кандидатами {int((G>=2).sum())}; макс. кандидатів в купі {int(G.max())}")
    def stats(z):
        z = z.sort_values("t_out"); cum = z.usd.cumsum(); dd = (cum - cum.cummax()).min() if len(z) else 0
        mo = z.groupby(pd.to_datetime(z.t_out, unit="s").dt.to_period("M")).usd.sum()
        s = (z.usd <= 0).to_numpy(); best = cur_ = 0
        for v in s: cur_ = cur_ + 1 if v else 0; best = max(best, cur_)
        return len(z), z.usd.sum(), z.usd.mean(), [z[z.year == y].usd.sum() for y in (2024, 2025, 2026)], dd, mo.min(), int((mo < 0).sum()), best, 100 * (z.usd > 0).mean()
    print("\n| правило | угод | усього $ | $ на угоду | 2024 | 2025 | 2026 | найглибша просадка $ | найгірший місяць $ | місяців у мінусі | найдовша серія мінусів | плюсових |\n|--|--|--|--|--|--|--|--|--|--|--|--|")
    def line(nm, z):
        n, tot, avg, ys, dd, wm, nm_, best, wr = stats(z)
        print(f"| {nm} | {n} | {tot:+,.0f} | {avg:+.2f} | " + " | ".join(f"{v:+,.0f}" for v in ys) + f" | {dd:,.0f} | {wm:+,.0f} | {nm_} | {best} | {wr:.0f}% |")
    line("0. Без відбору (як зараз)", d)
    zs = D.sort_values(["h1", "side", "score"], ascending=[True, True, False]); best = zs.groupby(["h1", "side"]).head(1).query("conf")
    line("Б. 1 НАЙКРАЩИЙ за оцінкою до підтвердження (реальний)", best)
    rng = np.random.default_rng(7); res = []; keys = D.groupby(["h1", "side"]).indices
    idx_groups = [np.array(v) for v in keys.values()]; Dv = D.reset_index(drop=True)
    for it in range(300):
        pick = [g[rng.integers(len(g))] for g in idx_groups]
        z = Dv.loc[pick]; z = z[z.conf]
        n, tot, avg, ys, dd, wm, nm_, bs, wr = stats(z); res.append((n, tot, avg, dd, bs, nm_, *ys))
    R = np.array(res); nb, totb, avgb, ysb, ddb, wmb, nmb, bsb, wrb = stats(best)
    def q(c): return f"середнє {R[:, c].mean():+,.0f}; 5%..95%: {np.percentile(R[:, c], 5):+,.0f}..{np.percentile(R[:, c], 95):+,.0f}"
    print("\nКОНТРОЛЬ: 300 разів замість найкращого брати ВИПАДКОВОГО кандидата з купи (до підтвердження):")
    print(f"  угод: середнє {R[:,0].mean():.0f}; усього $: {q(1)}  | реальний найкращий: {totb:+,.0f} (серед випадкових він кращий за {100*(R[:,1] < totb).mean():.0f}%)")
    print(f"  $ на угоду: середнє {R[:,2].mean():+.2f}; 5%..95%: {np.percentile(R[:,2],5):+.2f}..{np.percentile(R[:,2],95):+.2f}  | реальний найкращий: {avgb:+.2f} (кращий за {100*(R[:,2] < avgb).mean():.0f}% випадкових)")
    print(f"  найглибша просадка $: середнє {R[:,3].mean():,.0f}; 5%..95%: {np.percentile(R[:,3],5):,.0f}..{np.percentile(R[:,3],95):,.0f}  | реальний найкращий: {ddb:,.0f} (м'якший за {100*(R[:,3] < ddb).mean():.0f}% випадкових; більше = краще)")
    print(f"  найдовша серія мінусів: середнє {R[:,4].mean():.0f}; реальний найкращий: {bsb}")
    print(f"  по роках (2024/2025/2026), $: випадкові {R[:,6].mean():+,.0f} / {R[:,7].mean():+,.0f} / {R[:,8].mean():+,.0f}; реальний найкращий {ysb[0]:+,.0f} / {ysb[1]:+,.0f} / {ysb[2]:+,.0f}")
    print("\n##### ПІДСУМОК randomcontrol завершено")
if __name__ == "__main__": main()
