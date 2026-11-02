"""READ-ONLY. Правило A (reverse_search) + різні способи ВИХОДУ. Порівняння у R і $ ($10/угоду) на двох періодах.
Припущення: SL-first у барі; після часткового виходу стоп переноситься у беззбиток з НАСТУПНОГО бару; комісія = COST/stop_pct на всю позицію (ГІПОТЕЗА, без доплати за частковий вихід).
Використання: exits_test.py CANDLES_DIR SYMS COST"""
import sys
import numpy as np, pandas as pd
import reverse_search as rs
DAY = 86400; SPLIT = pd.Timestamp("2025-11-01").timestamp()
HZ = 96

def sim(h, l, c, i, side, ent, risk, variant):
    """повертає R до комісії. частки: [(частка, ціль_у_R або None для трейлінгу)]"""
    parts, be_after, trail = variant
    sl = ent - side * risk; pos = 1.0; r = 0.0; hit = [False] * len(parts); best = ent
    for k in range(1, HZ + 1):
        j = i + k
        if j >= len(c): break
        hi, lo = h[j], l[j]
        stop_hit = (lo <= sl) if side > 0 else (hi >= sl)
        if stop_hit:
            r += pos * (side * (sl - ent) / risk); return r
        favorable = (hi - ent) / risk if side > 0 else (ent - lo) / risk
        best = max(best, hi) if side > 0 else min(best, lo)
        moved = False
        for n, (frac, tgt) in enumerate(parts):
            if hit[n] or tgt is None: continue
            if favorable >= tgt:
                r += frac * tgt; pos -= frac; hit[n] = True; moved = True
        if moved and be_after and any(hit): sl = max(sl, ent) if side > 0 else min(sl, ent)
        if trail is not None and favorable >= trail[0]:
            tsl = best - side * trail[1] * risk
            sl = max(sl, tsl) if side > 0 else min(sl, tsl)
        if pos <= 1e-9: return r
    return r + pos * side * (c[min(i + HZ, len(c) - 1)] - ent) / risk

VARS = {
    "V0 все на 3R":                     ([(1.0, 3.0)], False, None),
    "V1 все на 2R":                     ([(1.0, 2.0)], False, None),
    "V2 все на 5R":                     ([(1.0, 5.0)], False, None),
    "V3 50% на 1R + беззбиток, 50% на 3R": ([(0.5, 1.0), (0.5, 3.0)], True, None),
    "V4 50% на 1.5R + беззбиток, 50% трейлінг 1.5R": ([(0.5, 1.5), (0.5, None)], True, (1.5, 1.5)),
    "V5 1/3 на 1R, 1/3 на 3R, 1/3 трейлінг 2R (беззбиток)": ([(1/3, 1.0), (1/3, 3.0), (1/3, None)], True, (3.0, 2.0)),
}

def main():
    btc = rs.load("BTCUSDT"); btc_ret = {}
    if btc is not None:
        bt = btc.open_time.to_numpy(float); bc = btc.close.to_numpy(float)
        for q in range(4, len(bc)): btc_ret[int(bt[q] // 900)] = np.sign(bc[q] - bc[q - 4])
    res = {k: {"old": [], "new": []} for k in VARS}
    for s in rs.SYMS:
        d = rs.load(s)
        if d is None: continue
        rows = pd.DataFrame(rs.build(d, btc_ret))
        if rows.empty: continue
        rows = rows[(rows.pos_range24 > 0.78) & (rows.compress > 0.18) & (rows.asia_pos > 0.49)].sort_values(["side", "t"])
        keep = (rows.side != rows.side.shift()) | (rows.t - rows.t.shift() > 7200)
        y = rows.groupby(keep.cumsum()).head(1)
        h, l, c = d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float)
        for _, x in y.iterrows():
            risk = abs(x.ent - x.sl); period = "old" if x.t < SPLIT else "new"
            for k, v in VARS.items():
                res[k][period].append(sim(h, l, c, int(x.i), int(x.side), x.ent, risk, v) - rs.COST / x.stop_pct)
        print(s, "ok", flush=True)
    print(f"\nПравило A + виходи; комісія {rs.COST*100:.2f}%; $ при $10 ризику на угоду")
    print("| вихід | період | n | R/угоду | $ |\n|--|--|--|--|--|")
    for k in VARS:
        for p, nm in (("old", "2024-01..2025-10"), ("new", "2025-11..2026-10")):
            a = res[k][p]
            if a: print(f"| {k} | {nm} | {len(a)} | {np.mean(a):+.3f} | {10*sum(a):+,.0f} |")
main()
