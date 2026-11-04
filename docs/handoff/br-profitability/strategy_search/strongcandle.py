"""READ-ONLY. ГІПОТЕЗА (користувацька вимога «сильна свічка старшого ТФ -> відкат -> вхід»; числа НЕ з методичок).
Чи покращує сильна свічка H1 (тіло >= BODY*ATR(H1), закриття у верхніх/нижніх 25%) + вхід у її відкаті стоп і результат? Ті самі сигнали TD-V1 (12 монет, фіксований поріг), $10 ризику на 1-шу одиницю.
Використання: strongcandle.py CANDLES_DIR TRAIN COST BODY"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST, BODY = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
sys.argv = ["x", CD, TRAIN, TRAIN, str(COST)]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
LOOK = 8

def run(a, j, side, ent, sl, tp, add=None, hz=192):
    """повертає (R1 до комісії, R2 до комісії або None). SL-first. Добір виконується на барі q, якщо ціна торкнулась add до виходу."""
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl); filled = None; r1 = None
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): break
        stop_hit = (l[q] <= sl) if side > 0 else (h[q] >= sl); tp_hit = (h[q] >= tp) if side > 0 else (l[q] <= tp)
        if add is not None and filled is None:
            if (l[q] <= add) if side > 0 else (h[q] >= add): filled = add
        if stop_hit: r1 = -1.0; ex = sl; break
        if tp_hit: r1 = side * (tp - ent) / risk; ex = tp; break
    else:
        q = min(j + hz, len(c) - 1); ex = c[q]; r1 = side * (ex - ent) / risk
    if r1 is None: ex = c[-1]; r1 = side * (ex - ent) / risk
    r2 = None
    if filled is not None:
        rk2 = abs(filled - sl); r2 = side * (ex - filled) / rk2 if rk2 > 0 else None
    return r1, r2

def strong(h1, t0, side, atr):
    """останнiй сильний свiчник у бiк угоди серед LOOK барiв H1 до сигналу включно; повертає (low, high) або None"""
    i = int(np.searchsorted(h1["open_time"], t0)); 
    if i >= len(h1["open_time"]) or h1["open_time"][i] != t0: return None
    for k in range(i, i - LOOK, -1):
        o, c, hh, ll = h1["open"][k], h1["close"][k], h1["high"][k], h1["low"][k]; rng = hh - ll; at = atr[k]
        if k < 20 or rng <= 0 or not at == at: continue
        pos = (c - ll) / rng
        if side > 0 and c > o and (c - o) >= BODY * at and pos >= .75: return ll, hh
        if side < 0 and c < o and (o - c) >= BODY * at and pos <= .25: return ll, hh
    return None

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
    sel = pd.concat(parts)
    H1 = {}; M15 = {}; AT15 = {}; rows = []
    for _, x in sel.iterrows():
        s = x.sym
        if s not in M15:
            M15[s] = td.load15(s); AT15[s] = td.atr_arr(M15[s]["high"], M15[s]["low"], M15[s]["close"])
            d = md.load_h1(s); H1[s] = {k: d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}
            pc = np.r_[H1[s]["close"][0], H1[s]["close"][:-1]]; tr_ = np.maximum(H1[s]["high"] - H1[s]["low"], np.maximum(abs(H1[s]["high"] - pc), abs(H1[s]["low"] - pc)))
            H1[s]["atr"] = pd.Series(tr_).rolling(14).mean().shift(1).to_numpy()
        a, at_ = M15[s], AT15[s]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
        sc = strong(H1[s], x.t, side, H1[s]["atr"])
        # базовий вхід M15
        base = None
        for k in range(16):
            j = i0 + k
            if j < 9 or j >= len(c_) - 2: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            base = (j, ent, sl, sp); break
        rec = dict(sym=s, t=x.t, year=int(x.year), strong=sc is not None)
        if base:
            j, ent, sl, sp = base; r1, _ = run(a, j, side, ent, sl, tp)
            rec.update(b_r=r1 - COST / sp, b_sp=sp, b_planR=(tp - ent) * side / abs(ent - sl))
            if sc:
                lo, hi = sc; mid = (lo + hi) / 2; deep = hi - .618 * (hi - lo) if side > 0 else lo + .618 * (hi - lo)
                lvl50 = mid
                touched = any(((l_[q] <= lvl50) if side > 0 else (h_[q] >= lvl50)) for q in range(i0 - 1, j + 1) if q >= 0)
                rec["pullback"] = touched
                # добір: друга одиниця на 50% / 61.8% сильної свічки, лише якщо рівень між входом і стопом
                for nm, lv in (("add50", lvl50), ("add618", deep)):
                    if (ent - lv) * side > 0 and (lv - sl) * side > 0:
                        r1b, r2 = run(a, j, side, ent, sl, tp, add=lv)
                        rec[nm] = (r1b - COST / sp) + ((r2 - COST / (abs(lv - sl) / lv)) if r2 is not None else 0.0); rec[nm + "_filled"] = r2 is not None
                    else: rec[nm] = rec["b_r"]; rec[nm + "_filled"] = False
        # вхід лімітом у відкаті сильної свічки (50%), стоп за екстремумом сильної свічки
        if sc:
            lo, hi = sc; lvl = (lo + hi) / 2
            for k in range(16):
                j = i0 + k
                if j < 9 or j >= len(c_) - 2: break
                if not ((l_[j] <= lvl) if side > 0 else (h_[j] >= lvl)): continue
                at = at_[j]
                if not at == at: break
                sl2 = (lo if side > 0 else hi) - side * 0.1 * at; sp2 = abs(lvl - sl2) / lvl
                if (lvl - sl2) * side <= 0 or not (0.0015 <= sp2 <= 0.05) or (tp - lvl) * side < abs(lvl - sl2): break
                if (l_[j] <= sl2) if side > 0 else (h_[j] >= sl2): rr = -1.0
                else: rr, _ = run(a, j, side, lvl, sl2, tp)
                rec.update(l_r=rr - COST / sp2, l_sp=sp2, l_planR=(tp - lvl) * side / abs(lvl - sl2)); break
        rows.append(rec)
    d = pd.DataFrame(rows); print(f"Сигналів H1 {len(d)}; сильна свічка (тіло>={BODY}ATR, закриття 25% краю, {LOOK} барів) є у {int(d.strong.sum())} ({100*d.strong.mean():.0f}%); комісія {COST*100:.2f}%; $10 ризику на 1-шу одиницю")
    def line(nm, r, sp=None, pl=None, extra=""):
        r = r.dropna()
        if len(r) == 0: print(f"{nm}: немає угод"); return
        yrs = " | ".join(f"{y}: n={int((dd.year==y).sum())} ${10*r[dd.year==y].sum():+,.0f}" for y in (2024, 2025, 2026) for dd in [d.loc[r.index]])
        print(f"{nm}: n={len(r)}; R/угоду {r.mean():+.3f}; усього ${10*r.sum():+,.0f}; плюсових {100*(r>0).mean():.0f}%" + (f"; сер. стоп {100*sp.loc[r.index].mean():.2f}%" if sp is not None else "") + (f"; план {pl.loc[r.index].median():.1f}R" if pl is not None else "") + extra + "\n     " + yrs)
    line("0. БАЗА (усі, вхід M15 як зараз)", d.b_r, d.b_sp, d.b_planR)
    s = d[d.strong & d.b_r.notna()]
    line("1. Є сильна свічка H1 (фільтр)", d.b_r[s.index], d.b_sp, d.b_planR)
    ns = d[~d.strong & d.b_r.notna()]
    line("   немає сильної свічки", d.b_r[ns.index], d.b_sp, d.b_planR)
    if "pullback" in d:
        p = d[d.strong & (d.pullback == True) & d.b_r.notna()]; np_ = d[d.strong & (d.pullback == False) & d.b_r.notna()]
        line("2. Сильна свічка + був відкат до її 50% до входу", d.b_r[p.index], d.b_sp, d.b_planR)
        line("   сильна свічка, але відкату до 50% не було", d.b_r[np_.index], d.b_sp, d.b_planR)
    if "l_r" in d:
        line("3. ЛІМІТ-вхід на 50% сильної свічки, стоп за її екстремумом", d.l_r, d.l_sp, d.l_planR)
        both = d[d.l_r.notna() & d.b_r.notna()]
        line("   ті самі сигнали, вхід M15 як зараз (порівняння)", d.b_r[both.index], d.b_sp, d.b_planR)
    for nm, tx in (("add50", "50%"), ("add618", "61.8%")):
        if nm in d:
            z = d[d[nm].notna()]; fl = z[z[nm + "_filled"] == True]
            line(f"4. ДОБІР 2-ї одиниці на {tx} сильної свічки (разом 2 одиниці; добір спрацював у {len(fl)} із {len(z)})", z[nm], None, None)
            line("   ті самі угоди без добору", z.b_r, None, None)
    print("\n##### ПІДСУМОК strongcandle завершено")
if __name__ == "__main__": main()
