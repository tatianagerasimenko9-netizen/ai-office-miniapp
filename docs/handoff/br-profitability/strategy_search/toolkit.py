"""Бібліотека ознак (READ-ONLY, лише вимірювання): свічковий аналіз, класичний ТА, об'єм/Вайков-подібні, хвильова структура (Еліотт-подібна).
Усі визначення — алгоритмічні наближення ГІПОТЕЗА (Вайков/Еліотт суб'єктивні); пороги не з джерел. Режими вирівнювання за напрямом угоди:
 'bb' = (бичаче, ведмежее): береться бичаче для лонга, ведмежее для шорта; 's' = value*напрям; 'p' = value (шорт: 1-value); 'p100' = (шорт: 100-value); 'n' = без змін."""
import numpy as np, pandas as pd

def rmax(x, n): return pd.Series(x).rolling(n).max().to_numpy()
def rmin(x, n): return pd.Series(x).rolling(n).min().to_numpy()
def pr(a, k=1): return np.r_[np.full(k, np.nan), a[:len(a) - k]]
def ema(x, span): return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()

FAMILY = {"candle": ("engulf", "pin", "doji", "inside", "outside", "star", "streak", "body", "range", "clv", "tail"),
          "classic_TA": ("rsi", "rsidiv", "macd", "bb_", "ema", "stack", "adx", "di_diff", "slope48", "r2_48"),
          "volume_wyckoff": ("obv", "effort", "absorb", "ad24", "spring", "sweep_vol", "sos", "compress", "vol20", "vol168"),
          "waves": ("w_",), "levels_fib": ("D_", "W_", "M_", "H4_", "fib", "leg_", "touch", "flip", "pos", "width", "since_hi"),
          "momentum_vol": ("ret", "atr_r"), "time": ("hsin", "hcos", "dow"), "btc": ("btc",), "stop": ("stop_pct",)}
def family_of(name):
    for f, keys in FAMILY.items():
        if any(name.startswith(k) for k in keys): return f
    return "other"

def waves(h, l, c, atr, K=3):
    n = len(c)
    ph = (pd.Series(h).rolling(2 * K + 1, center=True).max().to_numpy() == h); pl = (pd.Series(l).rolling(2 * K + 1, center=True).min().to_numpy() == l)
    piv = []
    for j in range(K, n - K):
        for typ, ok, px in (("H", ph[j], h[j]), ("L", pl[j], l[j])):
            if not ok: continue
            if piv and piv[-1][1] == typ:
                if (typ == "H" and px > piv[-1][2]) or (typ == "L" and px < piv[-1][2]): piv[-1] = (j, typ, px)
            else:
                if piv and abs(px - piv[-1][2]) < 1.5 * (atr[j] if atr[j] == atr[j] else 1e18): continue   # мінімальний розмір ноги 1.5 ATR (ГІПОТЕЗА)
                piv.append((j, typ, px))
    names = ("w_AB", "w_AC", "w_BC", "w_dir", "w3like", "w_lastP", "w_lastA", "w_lastI")
    arr = {k: np.full(n, np.nan) for k in names}
    for m in range(4, len(piv)):
        cm = piv[m][0] + K
        if cm >= n: break
        P = [piv[m - i][2] for i in range(5)]
        A, B, C = abs(P[0] - P[1]), abs(P[1] - P[2]), abs(P[2] - P[3])
        if min(A, B, C) <= 0: continue
        arr["w_AB"][cm] = A / B; arr["w_AC"][cm] = A / C; arr["w_BC"][cm] = B / C; arr["w_dir"][cm] = 1.0 if P[0] > P[1] else -1.0
        arr["w3like"][cm] = float(A > B and A > C and B < C); arr["w_lastP"][cm] = P[0]; arr["w_lastA"][cm] = A; arr["w_lastI"][cm] = cm
    F = {k: pd.Series(v).ffill().to_numpy() for k, v in arr.items()}
    idx = np.arange(n)
    retr = (F["w_lastP"] - c) * F["w_dir"] / F["w_lastA"]          # частка останньої ноги, яку ціна вже відкотила
    return {"w_AB": (F["w_AB"], "n"), "w_AC": (F["w_AC"], "n"), "w_BC": (F["w_BC"], "n"), "w_dir": (F["w_dir"], "s"), "w3like": (F["w3like"], "n"),
            "w_retr": (retr, "n"), "w_since": ((idx - F["w_lastI"]), "n")}

def extra(t, o, h, l, c, v, atr):
    n = len(c); E = {}; rng = h - l; body = c - o; absb = abs(body); safe = np.where(rng > 0, rng, np.nan)
    # --- свічковий аналіз ---
    E["engulf"] = (((body > 0) & (pr(body) < 0) & (c >= pr(o)) & (o <= pr(c))).astype(float), ((body < 0) & (pr(body) > 0) & (c <= pr(o)) & (o >= pr(c))).astype(float)), "bb"
    E["pin"] = ((((np.minimum(o, c) - l) >= 2 * absb) & ((h - np.maximum(o, c)) <= 0.5 * absb + 1e-12) & (rng > 0.5 * atr)).astype(float),
                (((h - np.maximum(o, c)) >= 2 * absb) & ((np.minimum(o, c) - l) <= 0.5 * absb + 1e-12) & (rng > 0.5 * atr)).astype(float)), "bb"
    E["doji"] = ((absb <= 0.1 * safe).astype(float), "n"); E["inside"] = (((h < pr(h)) & (l > pr(l))).astype(float), "n"); E["outside"] = (((h > pr(h)) & (l < pr(l))).astype(float), "n")
    b2, mid2 = pr(body, 2), (pr(o, 2) + pr(c, 2)) / 2
    E["star"] = (((b2 < 0) & (abs(b2) > 0.6 * pr(rng, 2)) & (abs(pr(body)) < 0.3 * pr(rng)) & (body > 0) & (c > mid2)).astype(float),
                 ((b2 > 0) & (abs(b2) > 0.6 * pr(rng, 2)) & (abs(pr(body)) < 0.3 * pr(rng)) & (body < 0) & (c < mid2)).astype(float)), "bb"
    sg = np.sign(body); ch = (sg != pr(sg)).cumsum(); E["streak"] = (pd.Series(np.ones(n)).groupby(ch).cumsum().to_numpy() * sg, "s")
    # --- класичний ТА ---
    d = pd.Series(c).diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy(); E["rsi"] = (rsi, "p100")
    hi24, lo24 = rmax(h, 24), rmin(l, 24); rM, rm = rmax(rsi, 24), rmin(rsi, 24)
    E["rsidiv"] = (((l <= lo24) & (rsi > rm + 5)).astype(float), ((h >= hi24) & (rsi < rM - 5)).astype(float)), "bb"
    macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9); hist = macd - sig; E["macd_h"] = (hist / atr, "s"); E["macd_dh"] = (np.r_[np.nan, np.diff(hist)] / atr, "s")
    ma = pd.Series(c).rolling(20).mean().to_numpy(); sd = pd.Series(c).rolling(20).std().to_numpy()
    E["bb_pct"] = ((c - (ma - 2 * sd)) / np.where(sd > 0, 4 * sd, np.nan), "p"); bw = 4 * sd / ma; E["bb_squeeze"] = (pd.Series(bw).rolling(168).rank(pct=True).to_numpy(), "n")
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    E["ema20d"] = ((c - e20) / atr, "s"); E["ema50d"] = ((c - e50) / atr, "s"); E["ema200d"] = ((c - e200) / atr, "s"); E["stack"] = (np.sign(e20 - e50) + np.sign(e50 - e200), "s")
    pdm = np.maximum(np.r_[0, np.diff(h)], 0); mdm = np.maximum(-np.r_[0, np.diff(l)], 0); m_ = pdm > mdm; pdm = np.where(m_, pdm, 0); mdm = np.where(~m_, mdm, 0)
    trw = pd.Series(np.maximum(h - l, np.maximum(abs(h - pr(c)), abs(l - pr(c))))).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    pdi = 100 * pd.Series(pdm).ewm(alpha=1 / 14, adjust=False).mean().to_numpy() / trw; mdi = 100 * pd.Series(mdm).ewm(alpha=1 / 14, adjust=False).mean().to_numpy() / trw
    E["adx"] = (pd.Series(100 * abs(pdi - mdi) / np.where(pdi + mdi > 0, pdi + mdi, np.nan)).ewm(alpha=1 / 14, adjust=False).mean().to_numpy(), "n"); E["di_diff"] = (pdi - mdi, "s")
    x = np.arange(48) - 23.5; sl = np.convolve(c, x[::-1], "valid") / (x ** 2).sum(); slope = np.full(n, np.nan); slope[47:] = sl
    vy = pd.Series(c).rolling(48).var().to_numpy(); E["slope48"] = (slope * 48 / atr, "s"); E["r2_48"] = (slope ** 2 * (x ** 2).sum() / 47 / np.where(vy > 0, vy, np.nan), "n")
    # --- об'єм / Вайков-подібні ---
    vm20 = pd.Series(v).rolling(20).mean().shift(1).to_numpy(); vm168 = pd.Series(v).rolling(168).mean().shift(1).to_numpy()
    obv = np.cumsum(np.sign(np.r_[0, np.diff(c)]) * v); E["obv24"] = ((obv - pr(obv, 24)) / (vm168 * 24), "s")
    eff = pd.Series(v).rolling(12).sum().to_numpy() / (vm168 * 12); res = abs(c - pr(c, 12)) / atr; E["effort"] = (eff, "n"); E["absorb"] = (eff / (res + 0.1), "n")
    adl = np.cumsum((2 * c - l - h) / safe * v); adl = np.nan_to_num(adl); E["ad24"] = ((adl - pr(adl, 24)) / (vm168 * 24), "s")
    lo_p48 = pd.Series(l).rolling(48).min().shift(4).to_numpy(); hi_p48 = pd.Series(h).rolling(48).max().shift(4).to_numpy()
    E["spring"] = (((rmin(l, 4) < lo_p48) & (c > lo_p48)).astype(float), ((rmax(h, 4) > hi_p48) & (c < hi_p48)).astype(float)), "bb"
    E["sweep_vol"] = (rmax(v, 4) / vm168, "n")
    su = ((rng > 1.5 * atr) & (c > l + 0.75 * rng) & (v > 1.5 * vm20)).astype(float); sd_ = ((rng > 1.5 * atr) & (c < l + 0.25 * rng) & (v > 1.5 * vm20)).astype(float)
    E["sos"] = (pd.Series(su).rolling(12).sum().to_numpy(), pd.Series(sd_).rolling(12).sum().to_numpy()), "bb"
    E["compress"] = ((rmax(h, 24) - rmin(l, 24)) / (rmax(h, 168) - rmin(l, 168)), "n")
    E.update(waves(h, l, c, atr))
    return E

def apply(E, ii, s, f):
    for k, (val, mode) in E.items():
        if mode == "bb": f[k] = val[0][ii] if s > 0 else val[1][ii]
        elif mode == "s": f[k] = val[ii] * s
        elif mode == "p": f[k] = val[ii] if s > 0 else 1 - val[ii]
        elif mode == "p100": f[k] = val[ii] if s > 0 else 100 - val[ii]
        else: f[k] = val[ii]
