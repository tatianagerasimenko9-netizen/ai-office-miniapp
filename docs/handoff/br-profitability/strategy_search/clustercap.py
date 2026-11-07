"""READ-ONLY. Купи сигналів в один бік: чи допомагає обмеження одночасних угод в один бік (A) або відбір найкращих за оцінкою моделі в межах одного H1-бару й напряму (B).
Ті самі угоди TD-V1 (12 монет, фіксований поріг, вхід M15), $10 ризику, SL-first. Використання: clustercap.py CANDLES_DIR TRAIN COST"""
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
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
        for k in range(16):
            j = i0 + k
            if j < 9 or j >= len(c_) - 2: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            r, q = run(a, j, side, ent, sl, tp)
            rows.append(dict(sym=x.sym, side=side, score=float(x.s), h1=float(x.t), t_in=float(a["open_time"][j] + 900), t_out=float(a["open_time"][q] + 900), r=r - C / sp)); break
    d = pd.DataFrame(rows).sort_values("t_in").reset_index(drop=True); d["year"] = pd.to_datetime(d.t_in, unit="s").dt.year; d["usd"] = 10 * d.r
    print(f"Угод {len(d)}; комісія {C*100:.2f}%; $10 ризику; період {pd.to_datetime(d.t_in.min(), unit='s'):%Y-%m-%d}..{pd.to_datetime(d.t_in.max(), unit='s'):%Y-%m-%d}")
    # скільки одночасно відкрито в один бік (без обмежень)
    ev = []
    for _, x in d.iterrows(): ev += [(x.t_in, 1, x.side), (x.t_out, -1, x.side)]
    ev.sort(key=lambda z: (z[0], z[1])); cur = {1: 0, -1: 0}; tot = 0; mx = {1: 0, -1: 0}; span = 0; hist = {}; last = ev[0][0]
    for t, k, s in ev:
        span += t - last; hist.setdefault(max(cur.values()), 0); hist[max(cur.values())] += t - last; last = t; cur[s] += k; mx[s] = max(mx[s], cur[s])
    print("Макс. одночасно відкритих в один бік: LONG", mx[1], "SHORT", mx[-1])
    print("Частка часу з N відкритими в один бік (макс. з двох боків): " + ", ".join(f"{n}: {100*v/span:.0f}%" for n, v in sorted(hist.items()) if n <= 10))
    def stats(z):
        z = z.sort_values("t_out"); cum = z.usd.cumsum(); dd = (cum - cum.cummax()).min() if len(z) else 0
        mo = z.groupby(pd.to_datetime(z.t_out, unit="s").dt.to_period("M")).usd.sum()
        s = (z.usd <= 0).to_numpy(); best = cur_ = 0
        for v in s: cur_ = cur_ + 1 if v else 0; best = max(best, cur_)
        return len(z), z.usd.sum(), z.usd.mean(), [z[z.year == y].usd.sum() for y in (2024, 2025, 2026)], dd, mo.min(), int((mo < 0).sum()), best
    print("\n| правило | угод | усього $ | $ на угоду | 2024 | 2025 | 2026 | найглибша просадка $ | найгірший місяць $ | місяців у мінусі | найдовша серія мінусів |\n|--|--|--|--|--|--|--|--|--|--|--|")
    def line(nm, z):
        n, tot, avg, ys, dd, wm, nm_, best = stats(z)
        print(f"| {nm} | {n} | {tot:+,.0f} | {avg:+.2f} | " + " | ".join(f"{v:+,.0f}" for v in ys) + f" | {dd:,.0f} | {wm:+,.0f} | {nm_} | {best} |")
    line("0. Без обмежень (як зараз)", d)
    for N in (1, 2, 3, 4, 6):                           # A: не більше N відкритих в один бік одночасно
        keep = []; opens = []                           # (t_out, side)
        for i, x in d.iterrows():
            opens = [o for o in opens if o[0] > x.t_in]
            if sum(1 for o in opens if o[1] == x.side) < N: keep.append(i); opens.append((x.t_out, x.side))
        line(f"A. Не більше {N} відкритих в один бік одночасно", d.loc[keep])
    for N in (2, 4):                                    # A2: не більше N відкритих усього
        keep = []; opens = []
        for i, x in d.iterrows():
            opens = [o for o in opens if o > x.t_in]
            if len(opens) < N: keep.append(i); opens.append(x.t_out)
        line(f"A2. Не більше {N} відкритих усього одночасно", d.loc[keep])
    for K in (1, 2, 3):                                 # B: у межах одного H1-бару й напряму лишати K кращих за оцінкою
        z = d.sort_values(["h1", "side", "score"], ascending=[True, True, False]); z = z.groupby(["h1", "side"]).head(K)
        line(f"B. Лишати {K} найкращих за оцінкою на H1-бар і напрям", z)
    print("\nПримітка: кілька правил = кратне порівняння; обмеження справжнє, якщо воно зменшує просадку, не вбиваючи прибуток, у всі роки.\n##### ПІДСУМОК clustercap завершено")
if __name__ == "__main__": main()
