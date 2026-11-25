"""READ-ONLY. «Куди доходять угоди СВІНГу» (23.11.2026, запит власниці):
1) який у середньому МАКСИМУМ (найбільший плюс у R за час угоди) мають угоди, що НЕ дійшли до цілі 6R за 10 діб;
2) після досягнення +1R/+2R/+3R/+4R/+5R: скільки угод потім розвернулося (стоп), скільки закрилося в плюсі — основа для нагадування на картці;
3) що об'єднує угоди, які ДІЙШЛИ до цілі (TP) або дали ≥+3R: ознаки ПЕРЕД входом (як у sw_features: рух за 1/3/7/30 діб у бік угоди, ATR, відстань до MA200, RSI, об'єм, позиція у 50-свічковому діапазоні, BTC) та РАННІ ознаки шляху (R наприкінці 1-ї, 2-ї, 3-ї доби).
СВІНГ ідентичний backtest (discover.py): H4, 3 рукави (Donchian20+MA200, RSI2+MA200, Bollinger+MA200), стоп 3×ATR14, ціль 6R, утримання ≤60 H4-барів (10 діб), вхід на відкритті наступного бару, SL-першим, ОДНА позиція на монету (перший за порядком рукавів, суперечливі пропускаємо), комісія FEE за круг.
Максимум у R = найбільше (high−вхід)/ризик для LONG (для SHORT — (вхід−low)/ризик) на барах ДО виходу; на барі стопа максимум не рахується (порядок всередині бару невідомий → консервативно).
Використання: sw_mfe.py CANDLES_DIR SYMS FEE OUT_PREFIX"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, FEE, OUT = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]), sys.argv[4]
PER = 14400; H = 60; K = 6.0; S = 3.0
def bars(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    if "volume" not in d: d["volume"] = 1.0
    g = d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close", "volume")}
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return pd.Series(tr).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
B = {s: bars(s) for s in set(SYMS) | {"BTCUSDT"}}
for s, b in B.items():
    c = b["close"]; b["A"] = atr(b["high"], b["low"], c); b["m200"] = sma(c, 200); b["rsi14"] = rsi(c, 14)
    b["vol20"] = pd.Series(b["volume"]).rolling(20).mean().shift(1).to_numpy(); b["mx50"] = pd.Series(b["high"]).rolling(50).max().to_numpy(); b["mn50"] = pd.Series(b["low"]).rolling(50).min().to_numpy()
rows = []
for sym in SYMS:
    b = B[sym]; o, h, l, c, A, m200, t = b["open"], b["high"], b["low"], b["close"], b["A"], b["m200"], b["open_time"]; n = len(c)
    up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
    rules = [("donchian", ev(c > hi20) & up, ev(c < lo20) & dn), ("rsi2", ev((r2 < 10) & up), ev((r2 > 90) & dn)), ("boll", ev((c < lb) & up), ev((c > ub) & dn))]
    bt = B["BTCUSDT"]; i = 201
    while i < n - 2:
        shorts = any(rl[2][i] for rl in rules); longs = any(rl[1][i] for rl in rules)
        if longs == shorts or not A[i] > 0: i += 1; continue                # немає сигналу або суперечливі
        side = 1 if longs else -1; key = next(k for k, L_, S_ in rules if (L_[i] if side > 0 else S_[i]))
        e = o[i + 1]; risk = S * A[i]
        if risk <= 0 or risk / e < 0.0005: i += 1; continue
        sl = e - side * risk; tp = e + side * K * risk; mfe = 0.0; mfe_bar = 0; why = "TIME"; j = i + 1; snaps = {}; done = False
        while j < n and j <= i + H:
            hs = (l[j] <= sl) if side > 0 else (h[j] >= sl)
            if hs: why = "SL"; res = -1.0; done = True; break
            fav = ((h[j] - e) if side > 0 else (e - l[j])) / risk
            if fav > mfe: mfe = fav; mfe_bar = j - (i + 1)
            if (j - (i + 1) + 1) % 6 == 0 and (j - (i + 1) + 1) // 6 <= 10: snaps[(j - (i + 1) + 1) // 6] = (c[j] - e) * side / risk
            if (h[j] >= tp) if side > 0 else (l[j] <= tp): why = "TP"; res = K; done = True; break
            j += 1
        if not done: jj = min(j, n - 1); res = (c[jj] - e) * side / risk
        net = res - FEE / (risk / e)
        k = lambda q: side * (c[i] / c[i - q] - 1); rg = b["mx50"][i] - b["mn50"][i]; jb = int(np.searchsorted(bt["open_time"], t[i + 1])) - 1
        rows.append(dict(sym=sym, sig=key, side=side, ts=float(t[i + 1]), y=int(pd.Timestamp(t[i + 1], unit="s").year), why=why, r=net, mfe=mfe, mfe_day=mfe_bar / 6.0, risk_pct=risk / e, hold=j - (i + 1),
                         d1=snaps.get(1, np.nan), d2=snaps.get(2, np.nan), d3=snaps.get(3, np.nan), d5=snaps.get(5, np.nan), d4=snaps.get(4, np.nan), d6=snaps.get(6, np.nan), d7=snaps.get(7, np.nan), d8=snaps.get(8, np.nan), d9=snaps.get(9, np.nan), d10=snaps.get(10, np.nan),
                         ret6=k(6), ret18=k(18), ret42=k(42), ret180=k(180) if i >= 180 else np.nan, atr_pct=A[i] / c[i], dist200=side * (c[i] - m200[i]) / A[i],
                         rsi=b["rsi14"][i] if side > 0 else 100 - b["rsi14"][i], volx=b["volume"][i] / b["vol20"][i] if b["vol20"][i] > 0 else np.nan,
                         rpos=((c[i] - b["mn50"][i]) / rg if side > 0 else (b["mx50"][i] - c[i]) / rg) if rg > 0 else np.nan,
                         btc7=side * (bt["close"][jb] / bt["close"][jb - 42] - 1) if jb >= 50 else np.nan, btcd=side * (bt["close"][jb] - bt["m200"][jb]) / bt["A"][jb] if jb >= 50 and bt["A"][jb] > 0 else np.nan,
                         hour=int(t[i + 1] % 86400 // 3600), dow=int(pd.Timestamp(t[i + 1], unit="s").day_of_week)))
        i = max(j, i + 1)
W = pd.DataFrame(rows); W["usd"] = 10 * W.r; W.to_csv(OUT + "_trades.csv", index=False)
n = len(W); P = lambda x: f"{100 * x:.0f}%"
print(f"СВІНГ: максимум угод і що об'єднує дійшлих до цілі. Угод {n} (42 монети, 2022–2026, одна позиція на монету, комісія {FEE*100:.2f}%), сума ${W.usd.sum():+.0f}, на угоду ${W.usd.mean():+.2f}\n")
print("== 1. Чим закінчились і який у них МАКСИМУМ за час угоди (у R; 1R = $10)")
for w, g in W.groupby("why"):
    print(f"   {w:5s}: {len(g):5d} ({P(len(g)/n)}); максимум у середньому +{g.mfe.mean():.2f}R (${10*g.mfe.mean():.0f}), медіана +{g.mfe.median():.2f}R; результат на угоду ${g.usd.mean():+.1f}")
nt = W[W.why != "TP"]
print(f"   УСІ, що НЕ дійшли до цілі: {len(nt)}; максимум у середньому +{nt.mfe.mean():.2f}R (${10*nt.mfe.mean():.0f}), медіана +{nt.mfe.median():.2f}R, 90-й процентиль +{nt.mfe.quantile(.9):.2f}R")
print("   частка не-дійшлих, що колись були у плюсі ≥ +1R / 2R / 3R / 4R / 5R: " + " / ".join(P((nt.mfe >= q).mean()) for q in (1, 2, 3, 4, 5)))
print("   день, коли був максимум (медіана, діб):", round(nt.mfe_day.median(), 1))
print("\n== 2. Після досягнення +kR (на будь-якому барі): що було далі")
print("   k    угод  стоп(−1R)  закрито за часом  із них у плюсі  дійшло до цілі  у середньому на угоду")
for q in (1, 2, 3, 4, 5):
    g = W[W.mfe >= q]
    if len(g): print(f"   {q}R {len(g):5d}   {P((g.why=='SL').mean()):>6s}    {P((g.why=='TIME').mean()):>6s}      {P(((g.why=='TIME')&(g.r>0)).sum()/max(1,(g.why=='TIME').sum())):>6s}        {P((g.why=='TP').mean()):>6s}      ${g.usd.mean():+.1f}")
print("   (стоп після +kR означає, що угоду вибило за початковим стопом, тобто плюс повністю віддано)")
print("\n== 3. Що об'єднує угоди, які ДІЙШЛИ до цілі (TP) та дали ≥+3R (BIG)")
W["tp"] = (W.why == "TP").astype(int); W["big"] = ((W.why == "TP") | (W.r >= 3)).astype(int)
print(f"   TP: {W.tp.sum()} ({P(W.tp.mean())}); BIG (≥+3R або ціль): {W.big.sum()} ({P(W.big.mean())})")
feats = ["ret6", "ret18", "ret42", "ret180", "atr_pct", "dist200", "rsi", "volx", "rpos", "btc7", "btcd", "risk_pct", "hour", "dow"]
print("   частка BIG за п'ятірками ознаки (q0 найнижча … q4 найвища) | ПО РОКАХ 2022–23 / 2024–26; базова:", P(W.big.mean()))
for f in feats:
    d = W.dropna(subset=[f]);
    if d[f].nunique() < 6: continue
    q = pd.qcut(d[f], 5, labels=False, duplicates="drop"); out = []
    for k_ in sorted(q.unique()):
        g = d[q == k_]; a = g[g.y <= 2023]; z = g[g.y >= 2024]
        out.append(f"q{k_}:{P(g.big.mean())}({P(a.big.mean()) if len(a) else '-'}|{P(z.big.mean()) if len(z) else '-'})")
    print(f"   {f:9s} " + "  ".join(out))
print("   за рукавом / боком / роком:")
for col in ("sig", "side", "y"):
    print("   " + col + ": " + ", ".join(f"{k_}: {P(g.big.mean())} (n={len(g)})" for k_, g in W.groupby(col)))
print("   за монетою (топ-8 за часткою BIG, n≥150): " + ", ".join(f"{s.replace('USDT','')} {P(g.big.mean())}" for s, g in sorted(((s, g) for s, g in W.groupby('sym') if len(g) >= 150), key=lambda x: -x[1].big.mean())[:8]))
print("\n== 4. РАННІ ознаки шляху: яка частка BIG залежно від R наприкінці 1-ї / 2-ї / 3-ї доби (серед тих, хто ще живий)")
for col, lab in (("d1", "1-ша доба"), ("d2", "2-га доба"), ("d3", "3-тя доба")):
    d = W.dropna(subset=[col])
    bins = [(-9, -0.5), (-0.5, 0), (0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 99)]
    print(f"   {lab}: " + "  ".join(f"[{a:+.1f}..{b_:+.1f}R]: {P(g.big.mean())} BIG, стоп {P((g.why=='SL').mean())} (n={len(g)})" for a, b_ in bins for g in [d[(d[col] > a) & (d[col] <= b_)]] if len(g) >= 30))
