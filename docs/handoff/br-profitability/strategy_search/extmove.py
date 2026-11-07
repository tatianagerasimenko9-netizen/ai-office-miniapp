"""READ-ONLY. Чому липень-грудень 2025 був у мінусі? Розріз TD-V1 (12 монет, фіксований поріг, вхід M15) по місяцях: напрям, тренд BTC/монети. Далі ГІПОТЕЗА-фільтри «лише за трендом».
$10 ризику, комісія COST. Використання: extmove.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST)

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float); bt = b.open_time.to_numpy(float); bh = b.high.to_numpy(float); bl = b.low.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=bt)
    A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = HG(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy(); z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
    sel = pd.concat(parts); cache = {}; H = {}; rows = []
    def h1(s):
        if s not in H:
            d = md.load_h1(s); H[s] = (d.open_time.to_numpy(float), d.close.to_numpy(float), d.high.to_numpy(float), d.low.to_numpy(float))
        return H[s]
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
            ts_, cl, hi, lo = h1(x.sym); i = int(np.searchsorted(ts_, x.t)); c24 = side * (cl[i] / cl[i - 24] - 1) * 100 if i >= 24 else np.nan
            rng_c = (hi[i - 23:i + 1].max() / lo[i - 23:i + 1].min() - 1) * 100 if i >= 24 else np.nan
            bi = int(np.searchsorted(bt, x.t)); brng = (bh[bi - 23:bi + 1].max() / bl[bi - 23:bi + 1].min() - 1) * 100 if bi >= 24 else np.nan
            pos = (ent - lo[i - 95:i + 1].min()) / (hi[i - 95:i + 1].max() - lo[i - 95:i + 1].min()) if i >= 96 else np.nan
            rows.append(dict(t=x.t, side=side, r=r, c24=c24, rng_c=rng_c, brng=brng, sp=sp, pos=pos)); break
    d = pd.DataFrame(rows); d["year"] = pd.to_datetime(d.t, unit="s").dt.year; d["usd"] = 10 * d.r
    print(f"Угод {len(d)}; комісія {C*100:.2f}%; $10 ризику; база R {d.r.mean():+.3f}, $ {d.usd.sum():+,.0f}")
    def tab(title, groups):
        print(f"\n{title}\n| група | угод | R/угоду | усього $ | 2024 | 2025 | 2026 | плюсових |\n|--|--|--|--|--|--|--|--|")
        for nm, g in groups:
            if len(g) == 0: continue
            print(f"| {nm} | {len(g)} | {g.r.mean():+.3f} | {g.usd.sum():+,.0f} | " + " | ".join(f"{g[g.year==y].usd.sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {100*(g.r>0).mean():.0f}% |")
    c = d.c24
    tab("А. РУХ МОНЕТИ ЗА 24 ГОД ДО ВХОДУ У БІК УГОДИ (позитивно = вхід ПІСЛЯ руху в той самий бік, «доганяння»)", [("рух проти угоди (< 0%)", d[c < 0]), ("0..2%", d[(c >= 0) & (c < 2)]), ("2..5%", d[(c >= 2) & (c < 5)]), ("5..8%", d[(c >= 5) & (c < 8)]), ("8% і більше", d[c >= 8])])
    b = d.brng
    tab("Б. ДІАПАЗОН BTC ЗА ОСТАННІ 24 ГОД (висока/низька волатильність ринку)", [("тихо (< 2,5%)", d[b < 2.5]), ("2,5..4%", d[(b >= 2.5) & (b < 4)]), ("4..6%", d[(b >= 4) & (b < 6)]), ("6% і більше", d[b >= 6])])
    pos = d.pos
    tab("В. ПОЛОЖЕННЯ ВХОДУ В 4-ДОБОВОМУ ДІАПАЗОНІ (0 = біля мінімуму, 1 = біля максимуму) ДЛЯ ШОРТІВ І ЛОНГІВ ОКРЕМО", [("SHORT біля мінімуму (< 0,25)", d[(d.side < 0) & (pos < .25)]), ("SHORT посередині (0,25..0,75)", d[(d.side < 0) & (pos >= .25) & (pos < .75)]), ("SHORT біля максимуму (≥ 0,75)", d[(d.side < 0) & (pos >= .75)]), ("LONG біля мінімуму (< 0,25)", d[(d.side > 0) & (pos < .25)]), ("LONG посередині", d[(d.side > 0) & (pos >= .25) & (pos < .75)]), ("LONG біля максимуму (≥ 0,75)", d[(d.side > 0) & (pos >= .75)])])
    tab("Г. ПОЄДНАННЯ: вхід після руху 5%+ в той самий бік І тихий BTC (< 4%)", [("так", d[(c >= 5) & (b < 4)]), ("ні", d[~((c >= 5) & (b < 4))])])
    print("\nПримітка: кілька розрізів = кратне порівняння; ефект має бути однаковим у всі роки.\n##### ПІДСУМОК extmove завершено")
if __name__ == "__main__": main()
