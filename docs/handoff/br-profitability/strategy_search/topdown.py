"""READ-ONLY. Схема «зверху вниз»: ЕТАП 1 (старші ТФ): модель на H1-ознаках рівнів/магнітів/діапазонів вибирає напрям і момент (топ-q за прогнозом).
ЕТАП 2 (молодший ТФ): вхід на M15 лише після свічкового підтвердження в бік угоди (закриття за екстремумом попередньої свічки), стоп = екстремум останніх 8 M15 свічок ∓0.1 ATR(M15),
ціль = та сама ціна, що в H1-плані (3R від H1-стопа). Порівняння з базовим входом на H1 для тих самих сигналів. TRAIN 2022-23; результат по 2024/2025/2026.
Використання: MODEL=ml_discover2 topdown.py CANDLES_DIR SYMS COST"""
import os, sys, importlib
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
md = importlib.import_module(os.environ.get("MODEL", "ml_discover2"))
CD, SYMS, COST = md.CD, md.SYMS, md.COST
DAY = 86400

def load15(s):
    d = pd.read_csv(CD / s / "15m.csv").drop_duplicates("open_time").sort_values("open_time")
    return {k: d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}

def atr_arr(h, l, c):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return pd.Series(tr).rolling(14).mean().shift(1).to_numpy()

def sim(a, j, side, ent, sl, tp, hz=192):
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl)
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): break
        if (l[q] <= sl) if side > 0 else (h[q] >= sl): return -1.0
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return side * (tp - ent) / risk
    return side * (c[min(j + hz, len(c) - 1)] - ent) / risk

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    parts = []
    for s in SYMS:
        d = md.load_h1(s)
        if d is None: continue
        r = md.rows_for(s, d, btc)
        if r is not None: parts.append(r)
    df = pd.concat(parts).reset_index(drop=True); df["year"] = pd.to_datetime(df.t, unit="s").dt.year
    X = [c for c in df.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = df[df.year <= 2023]
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    M15 = {s: load15(s) for s in SYMS if (CD / s / "15m.csv").exists()}; AT = {s: atr_arr(a["high"], a["low"], a["close"]) for s, a in M15.items()}
    for q in (0.03, 0.10):
        print(f"\n=== Відбір топ {int(q*100)}% (етап 1: H1, старші рівні) ; комісія {COST*100:.2f}% ; $ при $10 ризику на угоду ===")
        print("| рік | сигналів | БАЗА: вхід на H1 R / $ | з підтвердженням M15: входів | R / $ | сер. стоп H1 → M15 | частка сигналів, що підтвердились |\n|--|--|--|--|--|--|--|")
        for y in (2024, 2025, 2026):
            z = df[df.year == y].copy(); z["s"] = m.predict(z[X]); thr = np.quantile(z.s, 1 - q); sel = md.dedupe(z[z.s >= thr])
            rows = []
            for _, x in sel.iterrows():
                a = M15.get(x.sym)
                if a is None: continue
                side = int(x.side); T0 = x.t + 3600; i0 = int(np.searchsorted(a["open_time"], T0)); risk_h1 = abs(x.ent - x.sl); tp = x.ent + side * 3 * risk_h1
                for k in range(0, 16):
                    j = i0 + k
                    if j < 9 or j >= len(a["close"]) - 2: break
                    o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
                    conf = (c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])
                    if not conf: continue
                    at = AT[x.sym][j]
                    if not at == at: break
                    ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]
                    sp = abs(ent - sl) / ent
                    if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
                    rows.append((sim(a, j, side, ent, sl, tp) - COST / sp, sp, x.stop_pct)); break
            base = sel.r.mean() if len(sel) else 0
            if rows:
                rr = np.array([r[0] for r in rows]); spn = np.mean([r[1] for r in rows]); sph = np.mean([r[2] for r in rows])
                print(f"| {y} | {len(sel)} | {base:+.3f} / {10*sel.r.sum():+,.0f} | {len(rows)} | {rr.mean():+.3f} / {10*rr.sum():+,.0f} | {100*sph:.2f}% → {100*spn:.2f}% | {100*len(rows)/len(sel):.0f}% |")
            else: print(f"| {y} | {len(sel)} | {base:+.3f} / {10*sel.r.sum():+,.0f} | 0 | – | – | 0% |")
    print("\n##### ПІДСУМОК topdown завершено")
if __name__ == "__main__": main()
