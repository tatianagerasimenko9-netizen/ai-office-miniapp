"""READ-ONLY. Чи працює модель TD-V1 (навчена на 12 монетах, 2022-2023, поріг із 2024) на ІНШИХ монетах, яких вона не бачила?
Крок 1 H1 + крок 2 M15 — як у topdown. $ при $10 ризику на угоду. Використання: newcoins.py CANDLES_DIR TRAIN_SYMS NEW_SYMS COST"""
import os, sys
import numpy as np, pandas as pd
CD, TRAIN, NEW, COST = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
os.environ["MODEL"] = "ml_discover2"; sys.argv = ["x", CD, TRAIN, COST]
import ml_discover2 as md
import topdown as td
from sklearn.ensemble import HistGradientBoostingRegressor
DAY = 86400

def rows(syms, btc):
    out = []
    for s in syms:
        d = md.load_h1(s)
        if d is None or len(d) < 800: continue
        r = md.rows_for(s, d, btc)
        if r is not None: out.append(r)
    return pd.concat(out).reset_index(drop=True) if out else None

def m15_stage(sel):
    res = []; cache = {}
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
            res.append((td.sim(a, j, side, ent, sl, tp) - float(COST) / sp, x.t, x.sym)); break
    return res

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = rows(TRAIN.split(","), btc); Bn = rows(NEW.split(","), btc)
    for d_ in (A, Bn): d_["year"] = pd.to_datetime(d_.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97))
    print(f"Модель навчена на {len(TRAIN.split(','))} монетах (<=2023), поріг {thr:.3f}; НОВИХ монет із даними: {Bn.sym.nunique()}; комісія {float(COST)*100:.2f}%; $ при $10 ризику на угоду")
    print("| група | рік | сигналів H1 (/добу) | H1 R / $ | вхід M15: угод | R / $ |\n|--|--|--|--|--|--|")
    tot = {"12 монет (навчання)": [], "НОВІ монети": []}
    for name, D in (("12 монет (навчання)", A), ("НОВІ монети", Bn)):
        for y in (2024, 2025, 2026):
            z = D[D.year == y].copy()
            if len(z) == 0: continue
            z["s"] = m.predict(z[X]); sel = md.dedupe(z[z.s >= thr]); r15 = m15_stage(sel); days = 365 if y < 2026 else 300
            rr = np.array([r[0] for r in r15]) if r15 else np.array([])
            tot[name] += list(rr)
            print(f"| {name} | {y} | {len(sel)} ({len(sel)/days:.1f}) | {sel.r.mean() if len(sel) else 0:+.3f} / {10*sel.r.sum():+,.0f} | {len(rr)} | {rr.mean() if len(rr) else 0:+.3f} / {10*rr.sum():+,.0f} |")
    for k, v in tot.items(): print(f"{k}: M15-угод {len(v)}, R/угоду {np.mean(v) if v else 0:+.3f}, $ {10*sum(v):+,.0f}")
    # по монетах (нові), лише M15-етап за 2024-2026
    parts_ = []
    for y in (2024, 2025, 2026):
        z = Bn[Bn.year == y].copy()
        if len(z): z["s"] = m.predict(z[X]); parts_.append(z[z.s >= thr])
    sel_all = md.dedupe(pd.concat(parts_))
    r15 = m15_stage(sel_all); per = {}
    for r, t_, s_ in r15: per.setdefault(s_, []).append(r)
    print("\nНові монети, M15-етап, 2024-2026: R/угоду і $ по кожній монеті (n>=15)")
    for s_, v in sorted(per.items(), key=lambda kv: -sum(kv[1])):
        if len(v) >= 15: print(f"   {s_}: n={len(v)} R={np.mean(v):+.3f} $={10*sum(v):+,.0f}")
    print("\n##### ПІДСУМОК newcoins завершено")
if __name__ == "__main__": main()
