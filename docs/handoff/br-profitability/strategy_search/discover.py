"""READ-ONLY. Широкий пошук стратегій на історії (власниця 16.11.2026: «застосовуй ті інструменти, які знаєш ти»). Класичні підходи на H1/H4/D1, 12 монет, 2022-2026, комісія за круг (FEE), ризик $10 = 1R = стоп.
Вхід на відкритті наступного бару після сигналу; одна позиція на монету; SL-першим. Виходи: fix (стоп s×ATR, ціль k×стоп, час H) і trail (ATR-стоп, що підтягується).
Чесна оцінка: параметри НЕ підбираються під результат; показуємо ВСІ конфігурації; окремо — що в плюсі в КОЖНОМУ з 2023, 2024, 2025, 2026 і вибір на 2022-2024 → тест 2025-2026. Усе — ГІПОТЕЗА (OUR_IMPLEMENTATION класичних сигналів).
Використання: discover.py CANDLES_DIR SYMS FEE"""
import os, sys, numpy as np, pandas as pd
try:
    from numba import njit
except Exception:
    def njit(*a, **k):
        return (lambda f: f) if not (a and callable(a[0])) else a[0]
CD, SYMS, FEE = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]); ONLY = [x for x in os.environ.get("ONLY", "").split(";") if x]; DETAIL = os.environ.get("DETAIL", "")

def bars(sym, per):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // per * per).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}

def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def std(x, n): return pd.Series(x).rolling(n).std().to_numpy()
def rmax(x, n): return pd.Series(x).rolling(n).max().shift(1).to_numpy()
def rmin(x, n): return pd.Series(x).rolling(n).min().shift(1).to_numpy()
def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return pd.Series(tr).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state):                      # подія: стан щойно став істинним
    s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]

def signals(b):
    o, h, l, c = b["open"], b["high"], b["low"], b["close"]; A = atr(h, l, c); m200 = sma(c, 200); S = {}
    up, dn = c > m200, c < m200
    for N in (20, 50, 100):
        hi, lo = rmax(h, N), rmin(l, N); L_, S_ = ev(c > hi), ev(c < lo)
        S[f"donchian{N}"] = (L_, S_); S[f"donchian{N}+MA200"] = (L_ & up, S_ & dn)
    for f, s in ((10, 30), (20, 50), (50, 200)):
        a, z = sma(c, f), sma(c, s); S[f"MA{f}/{s}cross"] = (ev(a > z), ev(a < z))
    r2 = rsi(c, 2); S["RSI2 reversion+MA200"] = (ev((r2 < 10) & up), ev((r2 > 90) & dn)); S["RSI2 reversion"] = (ev(r2 < 5), ev(r2 > 95))
    r14 = rsi(c, 14); S["RSI14 <30/>70 reversion"] = (ev(r14 < 30), ev(r14 > 70)); S["RSI14 >70/<30 momentum"] = (ev(r14 > 70), ev(r14 < 30))
    mb, sb = sma(c, 20), std(c, 20); ub, lb = mb + 2 * sb, mb - 2 * sb
    S["Bollinger reversion"] = (ev(c < lb), ev(c > ub)); S["Bollinger reversion+MA200"] = (ev((c < lb) & up), ev((c > ub) & dn)); S["Bollinger breakout"] = (ev(c > ub), ev(c < lb))
    w = (ub - lb) / mb; pr = pd.Series(w).rolling(100).rank(pct=True).shift(1).to_numpy(); sq = pr < 0.1
    S["Squeeze breakout"] = (ev(sq & (c > ub)), ev(sq & (c < lb)))
    z = (c - sma(c, 50)) / std(c, 50); S["Z-score reversion 2.5"] = (ev(z < -2.5), ev(z > 2.5))
    rg = h - l; big = rg > 2 * A; pos = (c - l) / np.where(rg == 0, np.nan, rg)
    S["Big bar follow"] = (ev(big & (pos > 0.75)), ev(big & (pos < 0.25))); S["Big bar fade"] = (ev(big & (pos < 0.25)), ev(big & (pos > 0.75)))
    for n in (20, 60):
        roc = c / np.r_[np.full(n, np.nan), c[:-n]] - 1; S[f"Momentum ROC{n}"] = (ev(roc > 0), ev(roc < 0))
    return S, A

@njit(cache=False)
def run(o, h, l, c, A, ls, ss, mode, s, k, t, H, fee, up, dn):
    n = len(c); out_i = []; out_r = []; out_rk = []; out_s = []; out_h = []; out_w = []; out_snap = []; out_ch = []; i = 1; pend = 0; chain = 0
    while i < n - 2:
        side = 0
        if ls[i]: side = 1
        elif ss[i]: side = -1
        if side == 0 and pend != 0 and chain < 3 and ((pend > 0 and up[i]) or (pend < 0 and dn[i])): side = pend      # перезахід після беззбитку (режим 5): той самий напрямок, якщо тренд-фільтр MA200 лишається
        else: chain = 0 if side != 0 else chain
        pend = 0
        if side == 0 or not A[i] > 0: i += 1; continue
        e = o[i + 1]; risk = s * A[i]
        if risk <= 0 or risk / e < 0.0005: i += 1; continue
        sl = e - side * risk; tp = e + side * k * risk; best = e; res = 0.0; j = i + 1; done = False; mfe = 0.0; why = 'TIME'; snap = {}; bk = 0.0; fl = 0; ff = 0.5 if mode == 6 else 0.3333333333333333
        while j < n and j <= i + H:
            if mode >= 2 and j - 1 >= i + 1:          # беззбиток (2) / трейлінг на 1R (3) або 0,5R (4) за ціною ПІСЛЯ того, як попередні бари дали +t·R (SL-першим, активація з наступного бару)
                pj = j - 1; fav = ((h[pj] - e) if side > 0 else (e - l[pj])) / risk; mfe = max(mfe, fav)
                if mfe >= t:
                    if mode == 2 or mode == 5: nsl = e
                    elif mode == 6 or mode == 7:
                        nsl = e
                        if not fl: fl = 1; bk = ff * t        # частковий вихід: фіксуємо ff від позиції на +t·R, решта зі стопом у беззбитку
                    else:
                        best = max(best, c[pj]) if side > 0 else min(best, c[pj]); nsl = best - side * (1.0 if mode == 3 else 0.5) * risk
                    sl = max(sl, nsl) if side > 0 else min(sl, nsl)
            if mode == 1:
                if side > 0: best = max(best, c[j - 1]); sl = max(sl, best - t * A[i])
                else: best = min(best, c[j - 1]); sl = min(sl, best + t * A[i])
            hs = (l[j] <= sl) if side > 0 else (h[j] >= sl)
            if not hs and (j - (i + 1) + 1) in (12, 18, 24, 30, 36): snap[(j - (i + 1) + 1) // 6] = (c[j] - e) * side / risk
            if hs: res = (sl - e) * side / risk; done = True; why = 'SL' if abs(sl - (e - side * risk)) < 1e-12 * max(1, e) else 'SL_BE'; break
            if mode != 1:
                ht = (h[j] >= tp) if side > 0 else (l[j] <= tp)
                if ht: res = k; done = True; why = 'TP'; break
            j += 1
        if not done:
            jj = min(j, n - 1); res = (c[jj] - e) * side / risk
        out_i.append(i + 1); out_r.append((bk + (1 - ff) * res if fl else res) - fee / (risk / e) - (ff * 0.5 * fee / (risk / e) if fl else 0.0)); out_rk.append(risk / e); out_s.append(side); out_h.append(j - (i + 1)); out_w.append(why); out_snap.append(snap); out_ch.append(chain)
        if mode == 5 and why == 'SL_BE': pend = side; chain += 1
        i = max(j, i + 1)
    return out_i, out_r, out_rk, out_s, out_h, out_w, out_snap, out_ch

EXITS = [("fix s1.5 TP2", 0, 1.5, 2.0, 0.0), ("fix s3 TP3", 0, 3.0, 3.0, 0.0), ("fix s3 TP6", 0, 3.0, 6.0, 0.0), ("trail 3 ATR", 1, 3.0, 0.0, 3.0),
         ("fix s3 TP0.3", 0, 3.0, 0.3, 0.0), ("fix s3 TP0.5", 0, 3.0, 0.5, 0.0), ("fix s3 TP1", 0, 3.0, 1.0, 0.0), ("fix s3 TP2", 0, 3.0, 2.0, 0.0),
         ("BE +1R TP6", 2, 3.0, 6.0, 1.0), ("половина +2R і беззбиток TP6", 6, 3.0, 6.0, 2.0), ("третина +2R і беззбиток TP6", 7, 3.0, 6.0, 2.0), ("BE +2R перезахід TP6", 5, 3.0, 6.0, 2.0), ("BE +3R перезахід TP6", 5, 3.0, 6.0, 3.0), ("BE +1.5R TP6", 2, 3.0, 6.0, 1.5), ("BE +2R TP6", 2, 3.0, 6.0, 2.0), ("BE +3R TP6", 2, 3.0, 6.0, 3.0),
         ("trail1R після +1.5R TP6", 3, 3.0, 6.0, 1.5), ("trail1R після +2R TP6", 3, 3.0, 6.0, 2.0), ("trail1R після +3R TP6", 3, 3.0, 6.0, 3.0),
         ("trail0.5R після +2R TP6", 4, 3.0, 6.0, 2.0), ("trail0.5R після +3R TP6", 4, 3.0, 6.0, 3.0)]
HZ = {3600: 72, 14400: int(os.environ.get('H4_BARS', 60)), 86400: 40}; TFN = {3600: "H1", 14400: "H4", 86400: "D1"}
rows = []
for per in (3600, 14400, 86400):
    B = {s: bars(s, per) for s in SYMS}
    SG = {s: signals(B[s]) for s in SYMS}; UPd = {s: B[s]["close"] > sma(B[s]["close"], 200) for s in SYMS}; DNd = {s: B[s]["close"] < sma(B[s]["close"], 200) for s in SYMS}
    for name in SG[SYMS[0]][0]:
        for ename, mode, sm, k, t in EXITS:
            if ONLY and f"{TFN[per]}|{name}|{ename}" not in ONLY: continue
            for sym in SYMS:
                b = B[sym]; S, A = SG[sym]; L_, S_ = S[name]
                idx, rr, rk, sd, hh, ww, ss, chn = run(b["open"], b["high"], b["low"], b["close"], A, L_, S_, mode, sm, k, t, HZ[per] if mode != 1 else HZ[per] * 3, FEE, UPd[sym], DNd[sym])
                for i_, r_, sd_, rk_, h_, w_, sn_, ch_ in zip(idx, rr, sd, rk, hh, ww, ss, chn): rows.append((TFN[per], name, ename, sym, int(pd.Timestamp(b["open_time"][i_], unit="s").year), r_, float(b["open_time"][i_]), int(sd_), float(rk_), int(h_), w_, sn_.get(2, np.nan), sn_.get(3, np.nan), sn_.get(4, np.nan), sn_.get(5, np.nan), sn_.get(6, np.nan), int(ch_)))
R = pd.DataFrame(rows, columns=["tf", "sig", "exit", "sym", "y", "r", "ts", "side", "risk_pct", "hold_bars", "why", "r_d2", "r_d3", "r_d4", "r_d5", "r_d6", "chain"]); R["usd"] = R.r * 10
if DETAIL: R.to_csv(DETAIL, index=False)
G = R.groupby(["tf", "sig", "exit", "y"]).agg(n=("r", "size"), usd=("usd", "sum")).reset_index()
P = G.pivot_table(index=["tf", "sig", "exit"], columns="y", values="usd", fill_value=0).reset_index(); N = G.groupby(["tf", "sig", "exit"]).n.sum().reset_index(name="n"); P = P.merge(N, on=["tf", "sig", "exit"])
yrs = [y for y in (2022, 2023, 2024, 2025, 2026) if y in P.columns]; P["total"] = P[yrs].sum(axis=1)
print(f"Комісія {FEE*100:.2f}% за круг, ризик $10; конфігурацій: {len(P)}; угод у всіх: {int(P.n.sum()):,}")
print(f"Серед конфігурацій у плюсі всього: {(P.total>0).sum()} ({(P.total>0).mean()*100:.0f}%); у плюсі в КОЖНОМУ з 2023-2026: {int((P[[y for y in yrs if y>=2023]]>0).all(axis=1).sum())}")
print("\nУ плюсі в КОЖНОМУ році 2023–2026 (n≥150):")
ok = P[(P[[y for y in yrs if y >= 2023]] > 0).all(axis=1) & (P.n >= 150)].sort_values("total", ascending=False)
print(ok.round(0).to_string(index=False) if len(ok) else "  немає")
sel = P[(P[[y for y in yrs if y <= 2024]].sum(axis=1) > 0)]; oos = sel[[y for y in (2025, 2026) if y in sel.columns]].sum(axis=1)
print(f"\nЧесна перевірка: обрано {len(sel)} конфігурацій, що були в плюсі на 2022–2024; на НЕБАЧЕНИХ 2025–2026 з них у плюсі {(oos>0).sum()} ({(oos>0).mean()*100:.0f}%); сума {oos.sum():+,.0f}$; середня {oos.mean():+,.0f}$")
print("\nТоп-15 за небаченим 2025–2026 серед обраних на 2022–2024:")
sel = sel.assign(oos=oos.values).sort_values("oos", ascending=False).head(15); print(sel.round(0).to_string(index=False))
print("\nНайкращі 10 за загальним результатом (УВАГА: відбір після факту):"); print(P.sort_values("total", ascending=False).head(10).round(0).to_string(index=False))
print("\nУсередненні за сигналом (усі виходи, TF): сума $ і частка конфігурацій у плюсі:"); print(P.groupby("sig").agg(total=("total", "sum"), plus=("total", lambda x: (x > 0).mean())).round(2).sort_values("total", ascending=False).to_string())
P.to_csv("discover_results.csv", index=False)
