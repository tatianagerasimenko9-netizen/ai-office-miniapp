"""READ-ONLY. Безіменний пошук умов (без наперед заданої стратегії).
Крок 1: для кожного моменту (кожні 2 бари, обидва напрямки) рахуємо результат входу зі структурним стопом (екстремум 8 барів) і ціллю 3R + ознаки ДО входу.
Крок 2: дерево вчиться ТІЛЬКИ на 2022-2023. Крок 3: кожен листок перевіряється окремо в 2024, 2025, 2026 (дерево цих років не бачило).
✅ = train>0, плюс у КОЖНОМУ з трьох тестових років (n>=50) І нижня межа CI95 по днях на всьому тесті >0. Таймфрейм бару задається 3-м аргументом (хв: 60 або 240).
Використання: discover.py CANDLES_DIR SYMS TF_MIN COST"""
import sys
import numpy as np, pandas as pd
from sklearn.tree import DecisionTreeRegressor, export_text
TF = int(sys.argv[3]); COST = float(sys.argv[4])
sys.argv = [sys.argv[0], sys.argv[1], sys.argv[2], str(COST)]
import reverse_search as rs
_orig = rs.load
def load(s):
    d = _orig(s)
    if d is None or TF == 15: return d
    g = d.groupby(d.open_time // (TF * 60) * (TF * 60)).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return g
rs.load = load
found = []
def main():
    btc = rs.load("BTCUSDT"); btc_ret = {}
    step = TF * 60
    if btc is not None:
        bt = btc.open_time.to_numpy(float); bc = btc.close.to_numpy(float)
        for i in range(4, len(bc)): btc_ret[int(bt[i] // 900)] = np.sign(bc[i] - bc[i - 4])
        # build() шукає btc_ret за int(t//900): для TF>15 ключі кратні TF/15 — заповнимо всі 15-хв слоти бару
        full = {}
        for k, v in btc_ret.items():
            for j in range(TF // 15): full[k + j] = v
        btc_ret = full
    rows = []
    for s in rs.SYMS:
        d = rs.load(s)
        if d is None: continue
        r = rs.build(d, btc_ret)
        for x in r: x["sym"] = s
        rows += r; print(s, len(r), flush=True)
    df = pd.DataFrame(rows); df["year"] = pd.to_datetime(df.t, unit="s").dt.year
    print(f"\nTF={TF} хв; комісія {COST*100:.2f}%; рядків {len(df)}; сер. R усіх входів по роках:", {int(y): round(g.r.mean(), 3) for y, g in df.groupby("year")})
    ev = {int(y): round(100 * (g.mfe >= 3).mean(), 1) for y, g in df.groupby("year")}
    print("частка входів, що дійшли ≥3R до стопа (беззбиток ≈ 27%+):", ev)
    tr = df[df.year <= 2023]; tests = {y: df[df.year == y] for y in (2024, 2025, 2026)}
    global found
    found = []
    for depth, leaf in ((3, 3000), (4, 2000), (5, 1500)):
        m = DecisionTreeRegressor(max_depth=depth, min_samples_leaf=leaf).fit(tr[rs.FEATS], tr.r)
        lf_tr = m.apply(tr[rs.FEATS]); lf_te = {y: m.apply(g[rs.FEATS]) for y, g in tests.items()}
        print(f"\n=== Дерево depth={depth}, мін. листок {leaf} ===\n" + export_text(m, feature_names=rs.FEATS, max_depth=depth))
        print("| листок | train 22-23 n/R | 2024 n/R/$ | 2025 n/R/$ | 2026 n/R/$ | CI95 тест | ✅ |\n|--|--|--|--|--|--|--|")
        for lf in sorted(set(lf_tr)):
            a = tr[lf_tr == lf]; cells = []; ok = a.r.mean() > 0; pool = {}
            for y, g in tests.items():
                q = g[lf_te[y] == lf]
                if len(q) < 50: cells.append(f"{len(q)}/–/–"); ok = False; continue
                cells.append(f"{len(q)}/{q.r.mean():+.3f}/{10*q.r.sum():+,.0f}")
                if q.r.mean() <= 0: ok = False
                for tt, rr in zip(q.t, q.r): pool.setdefault(int(tt // 86400), []).append(rr)
            lo, hi = rs.boot(pool) if pool else (0, 0)
            ok = ok and lo > 0
            if ok: found.append((depth, lf, len(a), a.r.mean(), cells, lo, hi))
            print(f"| {lf} | {len(a)}/{a.r.mean():+.3f} | " + " | ".join(cells) + f" | [{lo:+.3f}; {hi:+.3f}] | {'✅' if ok else ''} |")
main()
print(f"\n##### ПІДСУМОК TF={TF} комісія {COST*100:.2f}%: ✅ листків = {len(found)}")
for f in found: print("   ✅", f)
