"""READ-ONLY. ІНТРАДЕЙ (TD-V1): чи «спокійні» монети кращі й тут? (25.11.2026, питання власниці). Ті самі угоди, що в newcoins.py/bemanage.py (12 монет, модель навчена ≤2023, поріг 2024, вхід M15, 2024–2026), $10 ризику.
«Спокійна» = ATR(14) на 4-годинних свічках < 2,3% ціни на момент сигналу (те саме визначення, що в СВІНГу; поріг НЕ підбирався під ІНТРАДЕЙ). Додатково — п'ятірки за ATR% для контролю.
Зберігає угоди (t, sym, r, atr_pct) для об'єднання систем. Використання: td_calm.py CANDLES_DIR TRAIN COST OUT_CSV"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST, OUTCSV = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
from sklearn.ensemble import HistGradientBoostingRegressor
md, td = nc.md, nc.td
b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
tr = A[A.year <= 2023]; va = A[A.year == 2024]
m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
for y in (2024, 2025, 2026):
    z = A[A.year == y].copy()
    if len(z): z["s"] = m.predict(z[X]); parts.append(z[z.s >= thr])
sel = md.dedupe(pd.concat(parts)); res = nc.m15_stage(sel)
H4 = {}
def atr_pct(sym, t):
    if sym not in H4:
        a = td.load15(sym); d = pd.DataFrame({"t": a["open_time"], "h": a["high"], "l": a["low"], "c": a["close"]}); g = d.groupby(d.t // 14400 * 14400).agg(h=("h", "max"), l=("l", "min"), c=("c", "last"))
        pc = g.c.shift(1); trr = np.maximum(g.h - g.l, np.maximum((g.h - pc).abs(), (g.l - pc).abs())); H4[sym] = (g.index.to_numpy(float), (trr.rolling(14).mean() / g.c).to_numpy())
    tt, v = H4[sym]; i = int(np.searchsorted(tt, t // 14400 * 14400)) - 1        # останній ЗАКРИТИЙ H4-бар
    return float(v[i]) if i >= 14 else np.nan
T = pd.DataFrame([(t, s, r, atr_pct(s, t)) for r, t, s in res], columns=["t", "sym", "r", "atr_pct"]).dropna(); T["usd"] = 10 * T.r; T["y"] = pd.to_datetime(T.t, unit="s").dt.year
T.to_csv(OUTCSV, index=False)
def line(lab, g):
    if not len(g): return
    eq = g.sort_values("t").usd.cumsum(); dd = (eq - eq.cummax()).min()
    print(f"  {lab:34s}: угод {len(g):4d}, ${g.usd.sum():+7.0f}, на угоду ${g.usd.mean():+.2f}, виграшних {100*(g.usd>0).mean():.0f}%, просадка ${dd:.0f} | " + " ".join(f"{y}:{x.usd.sum():+.0f}" for y, x in g.groupby("y")))
print(f"ІНТРАДЕЙ і «спокійні» монети: комісія {float(COST)*100:.2f}%, угод {len(T)}, 2024–2026, $10 ризику")
line("усі угоди", T); line("спокійні (ATR H4 < 2,3%)", T[T.atr_pct < 0.023]); line("рухливі (ATR H4 ≥ 2,3%)", T[T.atr_pct >= 0.023])
print(" п'ятірки за ATR% (q0 найспокійніші):"); T["q"] = pd.qcut(T.atr_pct, 5, labels=False)
for q, g in T.groupby("q"): line(f"q{q} ATR {100*g.atr_pct.min():.1f}–{100*g.atr_pct.max():.1f}%", g)
