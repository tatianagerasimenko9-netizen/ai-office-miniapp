"""READ-ONLY. ІНТРАДЕЙ (TD-V1): коли переносити стоп у беззбиток і чи допомагає трейлінг? Ті самі угоди, що й у horizon.py (12 монет, 2024-2026, вхід M15 як у живому скані, ціль плану 3R, 48 год), змінюється ЛИШЕ супровід стопа.
Варіанти: база; беззбиток після +0,5/1/1,5/2R (стоп = вхід, з НАСТУПНОГО M15-бару); трейлінг на 1R або 0,5R позаду найкращого закриття після +1/1,5/2R. SL-першим. $10 ризику, комісія COST за круг. Використання: bemanage.py CANDLES_DIR TRAIN_SYMS COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], float(sys.argv[3])
sys.argv = ["x", CD, TRAIN, TRAIN, str(COST)]
import newcoins as nc
md, td = nc.md, nc.td
HZB = 192
VARS = [("база (стоп/ціль плану)", None), ("БЗ після +0,5R", ("be", .5)), ("БЗ після +1R", ("be", 1.0)), ("БЗ після +1,5R", ("be", 1.5)), ("БЗ після +2R", ("be", 2.0)),
        ("трейлінг 1R після +1R", ("tr", 1.0, 1.0)), ("трейлінг 1R після +1,5R", ("tr", 1.5, 1.0)), ("трейлінг 1R після +2R", ("tr", 2.0, 1.0)), ("трейлінг 0,5R після +1,5R", ("tr", 1.5, .5)), ("трейлінг 0,5R після +2R", ("tr", 2.0, .5))]

def walk(a, j, side, ent, sl, tp, rule):
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl); cur = sl; mfe = 0.0; best = ent
    for k in range(1, HZB + 1):
        q = j + k
        if q >= len(c): return None
        if rule and k >= 2:
            p = q - 1; fav = ((h[p] - ent) if side > 0 else (ent - l[p])) / risk; mfe = max(mfe, fav)
            if rule[0] == "be" and mfe >= rule[1]: cur = max(cur, ent) if side > 0 else min(cur, ent)
            if rule[0] == "tr" and mfe >= rule[1]:
                best = max(best, c[p]) if side > 0 else min(best, c[p]); nsl = best - side * rule[2] * risk; cur = max(cur, nsl) if side > 0 else min(cur, nsl)
        if (l[q] <= cur) if side > 0 else (h[q] >= cur): return side * (cur - ent) / risk, "SL"
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return side * (tp - ent) / risk, "TP"
    return side * (c[j + HZB] - ent) / risk, "TIME"

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = nc.HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy(); z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
    sel = pd.concat(parts); cache = {}; out = {n: [] for n, _ in VARS}
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"]))
        a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
        for k in range(16):
            j = i0 + k
            if j < 9 or j >= len(c_) - 1400: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            for n, rule in VARS:
                w = walk(a, j, side, ent, sl, tp, rule)
                if w: out[n].append((w[0] - COST / sp, w[1], pd.Timestamp(x.t, unit="s").year))
            break
    print(f"Комісія {COST*100:.2f}% за круг; $10 ризику; 12 монет; ті самі {len(out[VARS[0][0]])} угод; змінюється тільки супровід стопа (БЗ = беззбиток)")
    print("| варіант | угод | ціль | стоп/БЗ | за часом | виграшних | усього $ | 2024 | 2025 | 2026 | $/угоду |\n|--|--|--|--|--|--|--|--|--|--|--|")
    for n, _ in VARS:
        d = pd.DataFrame(out[n], columns=["r", "o", "y"]); u = 10 * d.r
        print(f"| {n} | {len(d)} | {(d.o=='TP').sum()} | {(d.o=='SL').sum()} | {(d.o=='TIME').sum()} | {100*(d.r>0).mean():.0f}% | {u.sum():+,.0f} | " + " | ".join(f"{u[d.y==y].sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {u.mean():+.2f} |")
    print("\n##### ПІДСУМОК bemanage завершено")
if __name__ == "__main__": main()
