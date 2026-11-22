"""READ-ONLY. «Пошук закономірності» (22.11.2026): чи є в стані ринку ПЕРЕД входом ознаки, що відрізняють виграшні угоди СВІНГу від програшних? Берутся всі 18 810 угод СВІНГу (3 правила, 42 монети, 2022–2026; durations_sw_60.csv).
Ознаки на закритій H4-свічці перед входом (усе «у бік угоди»: плюс = ринок уже йшов у бік угоди): зміна ціни за 1 добу/3/7/30 діб, ATR у % ціни, відстань до MA200 в ATR, RSI14, об'єм відносно 20 свічок, позиція в діапазоні 50 свічок, зміна BTC за 7 діб у бік угоди, відстань BTC до MA200, година, день тижня, ризик (стоп у %), правило входу.
Навчання HistGradientBoosting на угодах ≤2023, перевірка на НЕБАЧЕНИХ 2024–2026 (чесний тест, без підгонки): $ і частка виграшних по п'ятьох групах за прогнозом моделі; ЗНАЧУЩІСТЬ ознак (permutation importance на тесті); прості одновимірні зрізи (квінтилі) з результатом по двох половинах.
Використання: sw_features.py CANDLES_DIR SYMS TRADES_CSV OUT_PREFIX"""
import os, sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
CD, SYMS, TCSV, OUT = sys.argv[1], sys.argv[2].split(","), sys.argv[3], sys.argv[4]
PER = 14400

def bars(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close", "volume")}
def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))); return pd.Series(tr).rolling(14).mean().to_numpy()
def rsi14(c):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / 14, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / 14, adjust=False).mean(); return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
B = {}
def prep(sym):
    b = bars(sym); c = b["close"]; b["A"] = atr14(b["high"], b["low"], c); b["m200"] = pd.Series(c).rolling(200).mean().to_numpy(); b["rsi"] = rsi14(c)
    b["vol20"] = pd.Series(b["volume"]).rolling(20).mean().shift(1).to_numpy(); b["mx50"] = pd.Series(b["high"]).rolling(50).max().to_numpy(); b["mn50"] = pd.Series(b["low"]).rolling(50).min().to_numpy(); return b
for s in set(SYMS) | {"BTCUSDT"}: B[s] = prep(s)
T = pd.read_csv(TCSV); T["usd"] = 10 * T.r
rows = []
for _, r in T.iterrows():
    b = B.get(r.sym)
    if b is None: continue
    idx = int(np.searchsorted(b["open_time"], r.ts)); i = idx - 1
    if i < 200 or idx >= len(b["close"]): continue
    c = b["close"]; s = int(r.side); a = b["A"][i]; bt = B["BTCUSDT"]; j = int(np.searchsorted(bt["open_time"], r.ts)) - 1
    if not a > 0 or j < 50: continue
    ret = lambda k: s * (c[i] / c[i - k] - 1)
    rg = b["mx50"][i] - b["mn50"][i]
    rows.append(dict(ret6=ret(6), ret18=ret(18), ret42=ret(42), ret180=ret(180), atr_pct=a / c[i], dist200=s * (c[i] - b["m200"][i]) / a, rsi=b["rsi"][i] if s > 0 else 100 - b["rsi"][i],
                     volx=b["volume"][i] / b["vol20"][i] if b["vol20"][i] > 0 else np.nan, rpos=((c[i] - b["mn50"][i]) / rg if s > 0 else (b["mx50"][i] - c[i]) / rg) if rg > 0 else np.nan,
                     btc7=s * (bt["close"][j] / bt["close"][j - 42] - 1), btcd=s * (bt["close"][j] - bt["m200"][j]) / bt["A"][j], hour=(int(r.ts) % 86400) // 3600, dow=pd.Timestamp(r.ts, unit="s").day_of_week,
                     risk=r.risk_pct, sig=["donchian", "rsi2", "boll"].index("donchian" if r.sig.startswith("donchian") else ("rsi2" if r.sig.startswith("RSI2") else "boll")), side=s, y=int(r.y), usd=r.usd, win=int(r.usd > 0), ts=r.ts))
D = pd.DataFrame(rows).dropna(); X = [c for c in D.columns if c not in ("y", "usd", "win", "ts")]
D.to_csv(OUT + "_features.csv", index=False)
print(f"ПОШУК ЗАКОНОМІРНОСТІ: угод СВІНГу з ознаками {len(D)} (усього {len(T)}); сума ${D.usd.sum():+.0f}, на угоду ${D.usd.mean():+.2f}, виграшних {100*D.win.mean():.0f}%")
SPLIT = int(os.environ.get('SPLIT_Y', 2023)); tr, te = D[D.y <= SPLIT], D[D.y > SPLIT].copy()
print(f"навчання ≤2023: {len(tr)} угод; перевірка 2024–2026: {len(te)} угод (на угоду ${te.usd.mean():+.2f}, виграшних {100*te.win.mean():.0f}%)")
m = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=400, l2_regularization=5.0, random_state=7).fit(tr[X], tr.usd.clip(-12, 60))
te["pred"] = m.predict(te[X]); te["q"] = pd.qcut(te.pred.rank(method="first"), 5, labels=False)
print("\n== Пятірки за прогнозом моделі (на НЕБАЧЕНИХ 2024–2026; q0 = найгірші за прогнозом, q4 = найкращі):")
for q, g in te.groupby("q"): print(f"  q{int(q)}: {len(g):5d} угод, на угоду ${g.usd.mean():+6.2f}, виграшних {100*g.win.mean():3.0f}%, сума ${g.usd.sum():+7.0f}")
top = te[te.q >= 3]; print(f"  якщо брати лише найкращі 40% за моделлю: {len(top)} угод, на угоду ${top.usd.mean():+.2f} (усі: ${te.usd.mean():+.2f}), виграшних {100*top.win.mean():.0f}%, сума ${top.usd.sum():+.0f} (усі ${te.usd.sum():+.0f})")
pi = permutation_importance(m, te[X], te.usd.clip(-12, 60), n_repeats=5, random_state=3, n_jobs=1)
print("\n== Що модель реально використовує (чим більше, тим важливіше; ~0 = нічого не додає):")
for nm, v in sorted(zip(X, pi.importances_mean), key=lambda z: -z[1]): print(f"   {nm:9s} {v:+.3f}")
print("\n== Прості зрізи по ознаках (квінтилі за ВСІМА роками; на угоду $ у 2022–2023 і 2024–2026):")
for f in X:
    if D[f].nunique() < 6: continue
    qs = pd.qcut(D[f].rank(method="first"), 5, labels=False); out = []
    for q in range(5):
        g = D[qs == q]; a_ = g[g.y <= 2023].usd.mean(); b_ = g[g.y >= 2024].usd.mean(); out.append(f"q{q}: {g.usd.mean():+.1f} ({a_:+.1f}|{b_:+.1f})")
    print(f"   {f:9s} " + "  ".join(out))
