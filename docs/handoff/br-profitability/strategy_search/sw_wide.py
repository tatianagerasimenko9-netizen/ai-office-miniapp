"""READ-ONLY. СВІНГ НА ВСІХ Ф'ЮЧЕРСАХ BINANCE (включно зі знятими з торгів) + ДЕНЬ ТИЖНЯ (28.11.2026, питання власниці: «розширити монети, але брати лише прибуткові дні»).
Записано ДО запуску. Правила СВІНГу без змін (як sw_exitlab.py BASE): H4, 3 рукави + MA200, стоп 3×ATR, ціль 6R, до 60 барів, одна позиція на монету, комісія 0,10%, ризик $10.
Монети: усі USDT-ф'ючерси з архіву data.binance.vision, яких немає в наших 42 (жодного відбору «по факту»); результат порівнюється з 42.
Гіпотеза для перевірки (взята з 42 монет, тут — незалежна перевірка): сигнали середи, четверга, п'ятниці (київський час) кращі за решту.
Цей скрипт лише пише угоди: sym, side, ts (час сигналу), r. Підсумки рахуються окремо (sw_wide_report.py).
Використання: sw_wide.py CANDLES_DIR SYMS OUT_CSV"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, OUT = sys.argv[1], sys.argv[2].split(","), sys.argv[3]
PER = 14400; H = 60; K = 6.0; S = 3.0; FEE = 0.001
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
rows = []
for sym in SYMS:
    f = f"{CD}/{sym}/15m.csv"
    if not os.path.exists(f): continue
    d = pd.read_csv(f).drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    t, o, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
    if n < 260: continue
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); m200 = sma(c, 200)
    up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
    L = (ev(c > hi20) & up) | ev((r2 < 10) & up) | ev((c < lb) & up); Sx = (ev(c < lo20) & dn) | ev((r2 > 90) & dn) | ev((c > ub) & dn)
    i = 201; k0 = len(rows)
    while i < n - 2:
        if L[i] == Sx[i] or not A[i] > 0: i += 1; continue
        side = 1 if L[i] else -1; e = o[i + 1]; risk = S * A[i]
        if risk <= 0 or risk / e < 0.0005: i += 1; continue
        res = None; j = i + 1
        while j < n and j <= i + H:
            adv = side * ((l[j] if side > 0 else h[j]) - e) / risk; fav = side * ((h[j] if side > 0 else l[j]) - e) / risk
            if adv <= -1: res = -1.0; break
            if fav >= K: res = K; break
            j += 1
        if res is None: res = side * (c[min(j, n - 1)] - e) / risk
        rows.append((sym, side, t[i + 1], res - FEE / (risk / e), A[i] / c[i])); i = max(j, i + 1)
    print(sym, len(rows) - k0, flush=True)
pd.DataFrame(rows, columns=["sym", "side", "ts", "r", "atr_pct"]).to_csv(OUT, index=False)
