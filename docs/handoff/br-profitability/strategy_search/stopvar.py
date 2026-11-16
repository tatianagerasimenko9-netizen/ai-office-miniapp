"""READ-ONLY. Які стопи підходять НОВИМ інструментам (золото, срібло, нафта WTI/Brent, газ, NVDA, SPCX)? Модель TD-V1 і вхід M15 — як у живому скані (навчена на 12 монетах до 2023, поріг з 2024).
Змінюється ТІЛЬКИ стоп (і ціль у R від стопа). Контроль: ті ж варіанти на 12 крипто-монетах. $10 ризику, комісія COST за круг, SL-першим, таймаут 48 год.
Варіанти стопу: V0 поточний (екстремум 8 барів M15 ∓0,1 ATR); ATR-стопи 1,5/2/3/4 ATR(M15) від входу; HTF = стоп плану H1; EXT24 = екстремум 24 барів M15 (6 год) ∓0,1 ATR.
Ціль: 2R / 3R власного стопа; PLAN = ціль плану H1 (як у живому). ГІПОТЕЗА, не підтверджено. Використання: stopvar.py CANDLES_DIR TRAIN_SYMS NEW_SYMS COST"""
import os, sys
import numpy as np, pandas as pd
CD, TRAIN, NEW, COST = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
sys.argv = ["x", CD, TRAIN, NEW, str(COST)]
import newcoins as nc
md, td = nc.md, nc.td
GROUPS = {"метали (XAU,XAG)": {"XAUUSDT", "XAGUSDT"}, "енергія (CL,BZ,NATGAS)": {"CLUSDT", "BZUSDT", "NATGASUSDT"}, "акції (NVDA,SPCX)": {"NVDAUSDT", "SPCXUSDT"}}
VARS = ["V0 поточний (8 барів)", "EXT24 (24 бари)", "ATR1,5", "ATR2", "ATR3", "ATR4", "HTF стоп H1"]
TPM = ["2R", "3R", "PLAN"]

def stage(sel):
    res = []; cache = {}
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"]))
        a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600))
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]; tp_plan = x.ent + side * 3 * abs(x.ent - x.sl)
        for k in range(16):
            j = i0 + k
            if j < 25 or j >= len(c_) - 2: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ent = c_[j]
            e8 = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); e24 = l_[j - 23:j + 1].min() if side > 0 else h_[j - 23:j + 1].max()
            sls = {VARS[0]: e8 - side * 0.1 * at, VARS[1]: e24 - side * 0.1 * at, VARS[2]: ent - side * 1.5 * at, VARS[3]: ent - side * 2 * at, VARS[4]: ent - side * 3 * at, VARS[5]: ent - side * 4 * at, VARS[6]: x.sl}
            if (ent - sls[VARS[0]]) * side <= 0 or not (0.0015 <= abs(ent - sls[VARS[0]]) / ent <= 0.03): break      # той самий відбір угод, що й у живому скані
            for v, sl in sls.items():
                risk = (ent - sl) * side
                if risk <= 0: continue
                sp = risk / ent
                if not (0.0005 <= sp <= 0.08): continue
                for tm in TPM:
                    tp = tp_plan if tm == "PLAN" else ent + side * (2 if tm == "2R" else 3) * risk
                    if (tp - ent) * side <= 0: continue
                    res.append((x.sym, pd.Timestamp(x.t, unit="s").year, v, tm, td.sim(a, j, side, ent, sl, tp) - COST / sp, sp))
            break
    return pd.DataFrame(res, columns=["sym", "year", "var", "tp", "r", "sp"])

def table(title, d):
    print(f"\n{title}\n| стоп | ціль | угод | серед. стоп | виграшних | усього $ | 2025 | 2026 | $/угоду |\n|--|--|--|--|--|--|--|--|--|")
    for v in VARS:
        for tm in TPM:
            g = d[(d["var"] == v) & (d.tp == tm)]
            if len(g) < 20: continue
            u = 10 * g.r
            print(f"| {v} | {tm} | {len(g)} | {100*g.sp.mean():.2f}% | {100*(g.r>0).mean():.0f}% | {u.sum():+,.0f} | {u[g.year==2025].sum():+,.0f} | {u[g.year==2026].sum():+,.0f} | {u.mean():+.2f} |")

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(TRAIN.split(","), btc); N = nc.rows(NEW.split(","), btc)
    for d_ in (A, N): d_["year"] = pd.to_datetime(d_.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = nc.HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97))
    print(f"Комісія+проковзування {COST*100:.2f}% за круг; $10 ризику; поріг {thr:.3f}; нових інструментів з даними: {N.sym.nunique() if N is not None else 0} ({', '.join(sorted(N.sym.unique())) if N is not None else ''})")
    def pick(D):
        parts = []
        for y in (2024, 2025, 2026):
            z = D[D.year == y].copy()
            if len(z): z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
        return pd.concat(parts)
    rn = stage(pick(N)); ra = stage(pick(A))
    for name, S in GROUPS.items():
        g = rn[rn.sym.isin(S)]
        if len(g): table(f"{name}: сигналів-угод {g[(g['var']==VARS[0]) & (g.tp=='3R')].shape[0]}", g)
    table("ВСІ НОВІ РАЗОМ", rn); table("КОНТРОЛЬ: 12 крипто-монет, ті ж варіанти", ra)
    print("\nПримітка: багато варіантів = кратне порівняння; шукаємо варіант, що в плюсі в КІЛЬКОХ роках і груп, а не одну найкращу цифру.\n##### ПІДСУМОК stopvar завершено")
if __name__ == "__main__": main()
