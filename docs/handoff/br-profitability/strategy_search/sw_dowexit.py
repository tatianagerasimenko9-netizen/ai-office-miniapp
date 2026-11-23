"""READ-ONLY. СВІНГ: чи допомагає закриття в «день/час піків» (23.11.2026, згода власниці «Так, перевір»). ПРАВИЛО ЗАПИСАНО ДО ЗАПУСКУ:
 «якщо на закритті H4-бару в заданий день тижня (UTC) угода має ≥ +k·R (за ціною закриття) — закрити за цією ціною». Інакше все як у СВІНГу (стоп 3×ATR, ціль 6R, ≤60 барів, SL-першим, одна позиція на монету, комісія FEE).
 Сітка (показуємо ВСЮ): день ∈ {Пн, Пт, Сб, Нд(контроль), будь-який} × k ∈ {1, 2, 3}; окремо «азійська сесія» (бари 00–08 UTC) × k. Ранній вихід звільняє монету для нових сигналів — це враховано (повна пересимуляція).
 Критерій «допомагає»: сума $ більша за базу і в 2022–23, і в 2024–26. Гіпотеза з розд. AE (піки частіше в Пн): основний варіант — Пн, k=2.
Використання: sw_dowexit.py CANDLES_DIR SYMS FEE"""
import sys
import numpy as np, pandas as pd
CD, SYMS, FEE = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3])
PER = 14400; H = 60; K = 6.0; S = 3.0
def bars(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return pd.Series(tr).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
PREP = {}
for sym in SYMS:
    b = bars(sym); o, h, l, c, t = b["open"], b["high"], b["low"], b["close"], b["open_time"]; A = atr(h, l, c); m200 = sma(c, 200)
    up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
    L_ = (ev(c > hi20) & up) | ev((r2 < 10) & up) | ev((c < lb) & up); S_ = (ev(c < lo20) & dn) | ev((r2 > 90) & dn) | ev((c > ub) & dn)
    dow = ((t // 86400 + 3) % 7).astype(int); hr = (t % 86400 // 3600).astype(int)          # день і година ВІДКРИТТЯ бару (UTC); пн=0
    PREP[sym] = (o, h, l, c, t, A, L_, S_, dow, hr)
def run(days, hours, k):
    out = []
    for sym in SYMS:
        o, h, l, c, t, A, L_, S_, dow, hr = PREP[sym]; n = len(c); i = 201
        while i < n - 2:
            if L_[i] == S_[i] or not A[i] > 0: i += 1; continue
            side = 1 if L_[i] else -1; e = o[i + 1]; risk = S * A[i]
            if risk <= 0 or risk / e < 0.0005: i += 1; continue
            sl = e - side * risk; tp = e + side * K * risk; j = i + 1; res = None; why = "TIME"
            while j < n and j <= i + H:
                if (l[j] <= sl) if side > 0 else (h[j] >= sl): res = -1.0; why = "SL"; break
                if (h[j] >= tp) if side > 0 else (l[j] <= tp): res = K; why = "TP"; break
                if days is not None or hours is not None:
                    rr = (c[j] - e) * side / risk
                    if rr >= k and (days is None or dow[j] in days) and (hours is None or hr[j] in hours): res = rr; why = "RULE"; break
                j += 1
            if res is None: jj = min(j, n - 1); res = (c[jj] - e) * side / risk
            out.append((int(pd.Timestamp(t[i + 1], unit="s").year), res - FEE / (risk / e), why)); i = max(j, i + 1)
    return pd.DataFrame(out, columns=["y", "r", "why"])
def line(name, W, base=None):
    a = 10 * W[W.y <= 2023].r.sum(); b = 10 * W[W.y >= 2024].r.sum(); tot = a + b
    extra = "" if base is None else f" | проти бази: {tot-base[0]:+.0f} (2022–23 {a-base[1]:+.0f}, 2024–26 {b-base[2]:+.0f}) {'КРАЩЕ в обох' if a > base[1] and b > base[2] else ('гірше в обох' if a < base[1] and b < base[2] else 'змішано')}"
    print(f" {name:34s}: угод {len(W):5d}, ${tot:+7.0f} (2022–23 ${a:+.0f}, 2024–26 ${b:+.0f}), на угоду ${10*W.r.mean():+.2f}, закрито правилом {100*(W.why=='RULE').mean():.0f}%, стоп {100*(W.why=='SL').mean():.0f}%{extra}")
    return tot, a, b
print(f"СВІНГ: закриття у «день/час піків» — правило записано до запуску. Монет {len(SYMS)}, 2022–2026, комісія {FEE*100:.2f}%, ризик $10")
B = line("БАЗА (тримати до стопа/цілі/10 діб)", run(None, None, 0))
DN = {"Пн": {0}, "Пт": {4}, "Сб": {5}, "Нд (контроль)": {6}, "будь-який день": None}
for nm, ds in DN.items():
    for k in (1, 2, 3):
        line(f"{nm}, якщо ≥ +{k}R (+${10*k})", run(ds if ds is not None else set(range(7)), None, k), B)
for k in (1, 2, 3):
    line(f"азійська сесія 00–08 UTC, ≥ +{k}R", run(None, {0, 4}, k), B)
for k in (2, 3):
    line(f"Пн + азійська сесія, ≥ +{k}R", run({0}, {0, 4}, k), B)
