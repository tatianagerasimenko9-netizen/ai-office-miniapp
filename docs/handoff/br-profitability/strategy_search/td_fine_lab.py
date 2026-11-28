"""READ-ONLY. ІНТРАДЕЙ: чи покращує історію вхід на 5-хвилинках або хвилинках замість 15-хвилинок (28.11.2026, питання власниці).
Записано ДО запуску. ГІПОТЕЗА (наша автоматизація). Нічого не вмикає.
Відбір сигналів БЕЗ ЗМІН: модель на H1 (навчена ≤2023, поріг 2024), 12 монет, 2024–2026 — як у td_pairs.py. Ціль — та сама ЦІНА (3R від плану H1). Міняється лише графік, на якому шукаємо вхід.
ПРАВИЛО ВХОДУ те саме, що зараз на M15: протягом 4 годин після сигналу H1 — перша свічка в бік угоди, що закрилась за максимумом/мінімумом попередньої; вхід на її закритті.
ВАРІАНТИ:
  M15 (як зараз)      свічки 15 хв; стоп за екстремумом останніх 8 свічок (2 год) − 0,1 ATR
  M5 · свій стоп      свічки 5 хв;  стоп за екстремумом останніх 8 свічок (40 хв) − 0,1 ATR(M5)   → стоп коротший
  M5 · стоп як M15    свічки 5 хв;  стоп за екстремумом останніх 24 свічок (2 год) − 0,1 ATR(M15) → лише точніший момент входу
  M1 · свій стоп      свічки 1 хв;  стоп за екстремумом останніх 8 свічок (8 хв) − 0,1 ATR(M1)
  M1 · стоп як M15    свічки 1 хв;  стоп за екстремумом останніх 120 свічок (2 год) − 0,1 ATR(M15)
Умови як зараз: стоп від 0,15% до 3% ціни; до цілі не менше, ніж до стопа; інакше сигнал пропущено. Результат рахується на ХВИЛИННИХ свічках для всіх варіантів (точно видно, що було раніше — стоп чи ціль),
утримання до 48 год від входу, у спірній хвилині стоп першим. Ризик $10, комісія 0,10% за круг.
«КРАЩЕ» = сума $ більша за M15 у КОЖНОМУ з років 2024, 2025, 2026.
Використання (з каталогу strategy_search): td_fine_lab.py CANDLES_DIR TRAIN"""
import sys
import numpy as np, pandas as pd
CD, TRAIN = sys.argv[1], sys.argv[2]
sys.argv = ["x", CD, TRAIN, TRAIN, "0.0010"]
import newcoins as nc
from sklearn.ensemble import HistGradientBoostingRegressor
md, td = nc.md, nc.td
FEE = 0.001
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
sel = md.dedupe(pd.concat(parts))
def load(sym, tf):
    d = pd.read_csv(f"{CD}/{sym}/{tf}.csv").drop_duplicates("open_time").sort_values("open_time")
    a = {k: d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}; a["atr"] = td.atr_arr(a["high"], a["low"], a["close"]); return a
VARS = [("M15 (як зараз)", "15m", 900, 16, 8, "own"), ("M5 · свій стоп", "5m", 300, 48, 8, "own"), ("M5 · стоп як M15", "5m", 300, 48, 24, "m15"), ("M1 · свій стоп", "1m", 60, 240, 8, "own"), ("M1 · стоп як M15", "1m", 60, 240, 120, "m15")]
cache = {}; rows = []
for _, x in sel.iterrows():
    sym = x.sym
    if sym not in cache:
        try: cache[sym] = {tf: load(sym, tf) for tf in ("15m", "5m", "1m")}
        except Exception as exc: print("нема даних", sym, exc); cache[sym] = None
    C = cache[sym]
    if C is None: continue
    side = int(x.side); tp = x.ent + side * 3 * abs(x.ent - x.sl); m1 = C["1m"]; a15 = C["15m"]
    for name, tf, per, win, lb, stopmode in VARS:
        a = C[tf]; o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]; i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); got = None
        for k in range(win):
            j = i0 + k
            if j < lb + 1 or j >= len(c_) - 2: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            if stopmode == "own": at = a["atr"][j]
            else:
                q = int(np.searchsorted(a15["open_time"], a["open_time"][j] + per, side="right")) - 1; at = a15["atr"][q] if q >= 0 else np.nan
            if not at == at: break
            ext = l_[j - lb + 1:j + 1].min() if side > 0 else h_[j - lb + 1:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            got = (float(a["open_time"][j]) + per, ent, sl, sp); break
        if got is None: rows.append((sym, x.t, name, 0, 0.0, np.nan)); continue
        te, ent, sl, sp = got; s0 = int(np.searchsorted(m1["open_time"], te)); e1 = min(len(m1["close"]), s0 + 2880); res = None; risk = abs(ent - sl)
        H1_, L1_ = m1["high"][s0:e1], m1["low"][s0:e1]
        hs = (L1_ <= sl) if side > 0 else (H1_ >= sl); ht = (H1_ >= tp) if side > 0 else (L1_ <= tp)
        isl = int(np.argmax(hs)) if hs.any() else 10 ** 9; itp = int(np.argmax(ht)) if ht.any() else 10 ** 9
        if e1 - s0 < 10: continue
        res = -1.0 if isl <= itp and isl < 10 ** 9 else (side * (tp - ent) / risk if itp < 10 ** 9 else side * (m1["close"][e1 - 1] - ent) / risk)
        rows.append((sym, x.t, name, 1, 10 * (res - FEE / sp), 100 * sp))
T = pd.DataFrame(rows, columns=["sym", "t", "v", "in", "usd", "sp"]); T["y"] = pd.to_datetime(T.t, unit="s").dt.year; N = sel.shape[0]; YS = (2024, 2025, 2026)
base = T[T.v == VARS[0][0]].groupby("y").usd.sum().reindex(YS).fillna(0)
print(f"ІНТРАДЕЙ, вхід на різних графіках: сигналів H1 {N}, монет {sel.sym.nunique()}, 2024–2026; ризик $10, комісія 0,10%, результат на хвилинних свічках")
print(f"{'варіант':20s} {'узято':>6s} {'сума $':>8s} {'на угоду':>8s} {'вигр.%':>6s} {'стопів%':>7s} {'стоп, % ціни':>12s} {'комісія на угоду':>16s} | " + " ".join(f"{y:>8d}" for y in YS) + " | краще за M15 в усі роки")
for name, *_ in VARS:
    x = T[T.v == name]; e = x[x["in"] == 1]; by = x.groupby("y").usd.sum().reindex(YS).fillna(0); ok = name != VARS[0][0] and all(by[y] > base[y] for y in YS)
    print(f"{name:20s} {100*len(e)/N:5.0f}% {e.usd.sum():+8.0f} {e.usd.mean():+8.2f} {100*(e.usd>0).mean():6.0f} {100*(e.usd<=-9.9).mean():7.0f} {e.sp.median():12.2f} {(10*FEE/(e.sp/100)).mean():16.2f} | " + " ".join(f"{by[y]:+8.0f}" for y in YS) + (" | ТАК" if ok else " |"))
