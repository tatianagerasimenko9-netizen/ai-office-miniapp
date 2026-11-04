"""READ-ONLY. «Магніти/перешкоди» зі свічок (відкриті дані, без стакана): чи впливає, що між входом і ціллю є рівень, і чи є рівень між входом і стопом / за стопом.
ГІПОТЕЗА (наше визначення рівнів, не з методичок): попередній день high/low (UTC), попередній тиждень high/low (пн-нд), 4-годинні свінг-піки (3 бари з кожного боку, підтверджені, останні 60 барів H4).
Ті самі угоди TD-V1 (12 монет, фіксований поріг, M15), $10 ризику. Використання: magnets.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST); DAY = 86400

class Lv:
    def __init__(self, a):
        t = a["open_time"]; self.t = t
        def agg(w):
            g = pd.DataFrame({"k": (t // w) * w, "h": a["high"], "l": a["low"]}).groupby("k").agg(h=("h", "max"), l=("l", "min"))
            return g
        self.D = agg(DAY); wk = (t + 3 * DAY) // (7 * DAY) * (7 * DAY) - 3 * DAY      # тиждень з понеділка (UTC)
        self.W = pd.DataFrame({"k": wk, "h": a["high"], "l": a["low"]}).groupby("k").agg(h=("h", "max"), l=("l", "min"))
        g = agg(14400); hh, ll, kk = g.h.to_numpy(), g.l.to_numpy(), g.index.to_numpy(float); n = len(hh); piv = []
        for i in range(3, n - 3):
            if hh[i] == hh[i - 3:i + 4].max(): piv.append((kk[i + 4 - 0] if i + 4 < n else kk[-1] + 14400, hh[i]))
            if ll[i] == ll[i - 3:i + 4].min(): piv.append((kk[i + 4] if i + 4 < n else kk[-1] + 14400, ll[i]))
        self.pc = np.array([p[0] for p in piv]); self.pp = np.array([p[1] for p in piv]); self.kk = kk
    def at(self, te):
        L = []; d0 = (te // DAY) * DAY - DAY; w0 = ((te + 3 * DAY) // (7 * DAY) * (7 * DAY) - 3 * DAY) - 7 * DAY
        for T, k in ((self.D, d0), (self.W, w0)):
            if k in T.index: L += [T.loc[k, "h"], T.loc[k, "l"]]
        m = (self.pc <= te) & (self.pc > te - 60 * 14400)
        L += list(self.pp[m]); return L

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
    sel = pd.concat(parts); cache = {}; LV = {}; rows = []
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"])); LV[x.sym] = Lv(a)
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
            r = td.sim(a, j, side, ent, sl, tp) - C / sp; risk = abs(ent - sl); dtp = (tp - ent) * side
            L = LV[x.sym].at(a["open_time"][j]); ahead = [(p - ent) * side for p in L if (p - ent) * side > 0.05 * risk and (p - ent) * side < dtp]
            frac = min(ahead) / dtp if ahead else None
            zone = any(0.05 * risk < (ent - p) * side < risk for p in L)                    # рівень між входом і стопом
            guard = any(risk <= (ent - p) * side <= 1.5 * risk for p in L)                   # рівень одразу за стопом (до 0.5 ризику)
            rows.append(dict(t=x.t, r=r, frac=frac, zone=zone, guard=guard, nahead=len(ahead))); break
    d = pd.DataFrame(rows); d["year"] = pd.to_datetime(d.t, unit="s").dt.year; d["usd"] = 10 * d.r
    print(f"Угод {len(d)}; комісія {C*100:.2f}%; $10 ризику; база R {d.r.mean():+.3f}, $ {d.usd.sum():+,.0f}")
    def tab(title, groups):
        print(f"\n{title}\n| група | угод | R/угоду | усього $ | 2024 | 2025 | 2026 | плюсових |\n|--|--|--|--|--|--|--|--|")
        for nm, g in groups:
            if len(g) == 0: continue
            print(f"| {nm} | {len(g)} | {g.r.mean():+.3f} | {g.usd.sum():+,.0f} | " + " | ".join(f"{g[g.year==y].usd.sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {100*(g.r>0).mean():.0f}% |")
    f = d.frac
    tab("Б. ПЕРЕШКОДА НА ШЛЯХУ ДО ЦІЛІ (найближчий рівень між входом і ціллю; відстань як частка шляху до цілі)", [("рівень у перших 25% шляху", d[f <= .25]), ("рівень на 25–60% шляху", d[(f > .25) & (f <= .6)]), ("рівень на 60–100% шляху", d[f > .6]), ("жодного рівня на шляху", d[f.isna()])])
    tab("В. РІВЕНЬ БІЛЯ СТОПА", [("рівень МІЖ входом і стопом (стоп глибше за рівень)", d[d.zone]), ("рівень ОДРАЗУ ЗА стопом (до 0,5 ризику), нічого між входом і стопом", d[d.guard & ~d.zone]), ("жодного рівня біля стопа", d[~d.zone & ~d.guard])])
    tab("Г. УСІ УГОДИ ЗА КІЛЬКІСТЮ РІВНІВ НА ШЛЯХУ ДО ЦІЛІ", [("0", d[d.nahead == 0]), ("1", d[d.nahead == 1]), ("2-3", d[(d.nahead >= 2) & (d.nahead <= 3)]), ("4+", d[d.nahead >= 4])])
    print("\nПримітка: кілька розрізів = кратне порівняння; ефект має повторюватись у всі роки.\n##### ПІДСУМОК magnets завершено")
if __name__ == "__main__": main()
