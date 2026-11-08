"""READ-ONLY. Купи сигналів в один бік: чи допомагає обмеження одночасних угод в один бік (A) або відбір найкращих за оцінкою моделі в межах одного H1-бару й напряму (B).
Ті самі угоди TD-V1 (12 монет, фіксований поріг, вхід M15), $10 ризику, SL-first. Використання: bestscore.py CANDLES_DIR TRAIN COST"""
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
    z = D.sort_values(["h1", "side", "score"], ascending=[True, True, False])
    for K in (1, 2, 3):                                   # Б: відбір ДО підтвердження; не підтвердився — угоди немає
        line(f"Б. Лишати {K} найкращих за оцінкою ДО підтвердження (не підтвердився — угоди немає)", z.groupby(["h1", "side"]).head(K).query("conf"))
    line("В. (для порівняння, як у попередньому тесті) 1 найкращий СЕРЕД ПІДТВЕРДЖЕНИХ", d.sort_values(["h1", "side", "score"], ascending=[True, True, False]).groupby(["h1", "side"]).head(1))
    ch = z.groupby(["h1", "side"]).head(1); print(f"\nКращий кандидат у купі підтверджується у {100*ch.conf.mean():.0f}% випадків (усі кандидати: {100*D.conf.mean():.0f}%)")
    multi = D.groupby(["h1", "side"]).filter(lambda g: len(g) >= 2); cm = multi.sort_values("score", ascending=False).groupby(["h1", "side"]).head(1)
    print(f"Лише в купах з 2+ кандидатами: найкращий підтверджується у {100*cm.conf.mean():.0f}%; середній $ найкращого (підтверджених) {cm[cm.conf].usd.mean():+.2f}; середній $ решти підтверджених {multi.drop(cm.index)[multi.drop(cm.index).conf].usd.mean():+.2f}")
    print("\nПримітка: кілька правил = кратне порівняння; ефект має повторюватись у всі роки й за обох комісій.\n##### ПІДСУМОК bestscore завершено")
if __name__ == "__main__": main()
