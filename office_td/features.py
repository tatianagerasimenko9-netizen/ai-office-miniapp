"""Ознаки H1, ІДЕНТИЧНІ тим, на яких навчалась модель (docs/handoff/br-profitability/strategy_search/ml_discover2.py).
Лише причинні (на барі i відомі тільки бари <= i). Еквівалентність перевіряє scripts/test_td_features.py."""
from __future__ import annotations
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv

DAY = 86400
MIN_SP, MAX_SP = 0.003, 0.05          # допустимий розмір H1-стопа (частка ціни), як у навчанні


def _rmax(x, n): return pd.Series(x).rolling(n).max().to_numpy()
def _rmin(x, n): return pd.Series(x).rolling(n).min().to_numpy()


def compute(t, o, h, l, c, v, btc4, btc24):
    """t,o,h,l,c,v — масиви H1 (t = час відкриття, сек); btc4/btc24 — відносна зміна BTC за 4/24 бари, вирівняна по цих барах."""
    t, o, h, l, c, v = (np.asarray(x, float) for x in (t, o, h, l, c, v)); n = len(c)
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).rolling(14).mean().shift(1).to_numpy()
    atr96 = pd.Series(tr).rolling(96).mean().shift(1).to_numpy(); atr336 = pd.Series(tr).rolling(336).mean().shift(1).to_numpy()
    F = {}
    for L in (1, 2, 4, 8, 24, 72, 168): F[f"ret{L}"] = (c - np.r_[np.full(L, np.nan), c[:-L]]) / atr
    for L in (12, 24, 72, 168):
        mx, mn = _rmax(h, L), _rmin(l, L); w = mx - mn
        F[f"pos{L}"] = (c - mn) / np.where(w > 0, w, np.nan); F[f"width{L}"] = w / atr
        if L <= 24: F[f"since_hi{L}"] = pd.Series(h).rolling(L).apply(lambda a: L - 1 - np.argmax(a), raw=True).to_numpy() / L
    for k in (0, 1, 2):
        sh = lambda a: np.r_[np.full(k, np.nan), a[:n - k]] if k else a
        F[f"body{k}"] = (sh(c) - sh(o)) / atr; F[f"range{k}"] = (sh(h) - sh(l)) / atr
        F[f"clv{k}"] = (sh(c) - sh(l)) / np.where((sh(h) - sh(l)) > 0, sh(h) - sh(l), np.nan)
    vm20 = pd.Series(v).rolling(20).mean().shift(1).to_numpy(); vm168 = pd.Series(v).rolling(168).mean().shift(1).to_numpy()
    F["vol20"] = v / vm20; F["vol168"] = v / vm168; F["atr_r96"] = atr / atr96; F["atr_r336"] = atr / atr336
    hrs = (t % DAY) / 3600; F["hsin"] = np.sin(2 * np.pi * hrs / 24); F["hcos"] = np.cos(2 * np.pi * hrs / 24); F["dow"] = ((t // DAY + 4) % 7).astype(float)
    F["btc4"] = np.asarray(btc4, float); F["btc24"] = np.asarray(btc24, float)
    dts = pd.to_datetime(t, unit="s"); pid = {"D": (t // DAY).astype(int), "W": ((t // DAY + 3) // 7).astype(int), "M": (dts.year * 12 + dts.month).to_numpy()}
    LV = {}
    for P, key in pid.items():
        ph = pd.Series(pd.Series(h).groupby(key).max()).shift(1); pl = pd.Series(pd.Series(l).groupby(key).min()).shift(1)
        LV[P] = (pd.Series(key).map(ph).to_numpy(), pd.Series(key).map(pl).to_numpy())
    LV["H4"] = (pd.Series(h).rolling(80).max().shift(4).to_numpy(), pd.Series(l).rolling(80).min().shift(4).to_numpy())
    h4 = _rmax(h, 4); l4 = _rmin(l, 4)
    hi72, lo72 = _rmax(h, 72), _rmin(l, 72)
    ihi = pd.Series(h).rolling(72).apply(lambda a: 71 - np.argmax(a), raw=True).to_numpy(); ilo = pd.Series(l).rolling(72).apply(lambda a: 71 - np.argmin(a), raw=True).to_numpy()
    leg_up = ilo > ihi; w72 = np.where(hi72 - lo72 > 0, hi72 - lo72, np.nan)
    F["leg_size"] = w72 / atr
    fib_up = (hi72 - c) / w72; fib_dn = (c - lo72) / w72
    th = np.full(n, np.nan); tl = np.full(n, np.nan)
    if n >= 168:
        Wh = swv(h, 168); Wl = swv(l, 168); cc = c[167:]; tol = 0.25 * atr[167:]
        th[167:] = (abs(Wh - cc[:, None]) <= tol[:, None]).sum(1); tl[167:] = (abs(Wl - cc[:, None]) <= tol[:, None]).sum(1)
    F["touch_hi"] = th; F["touch_lo"] = tl; F["flip"] = (np.minimum(th, tl) > 0).astype(float); F["touch_tot"] = th + tl
    return dict(t=t, o=o, h=h, l=l, c=c, atr=atr, F=F, LV=LV, h4=h4, l4=l4, fib_up=fib_up, fib_dn=fib_dn, leg_up=leg_up,
                lo8=_rmin(l, 8), hi8=_rmax(h, 8))


def side_features(B, ii, s):
    """Вирівняні за напрямом s (+1 лонг / −1 шорт) ознаки для індексів ii. Повертає (dict ознак, ent, sl, stop_pct)."""
    ii = np.asarray(ii); c, atr = B["c"], B["atr"]
    f = {k: v[ii] for k, v in B["F"].items()}
    for k in list(f):
        if k.startswith(("ret", "body", "btc")): f[k] = f[k] * s
        elif k.startswith(("pos", "clv")): f[k] = f[k] if s > 0 else 1 - f[k]
    for P, (PH, PL) in B["LV"].items():
        up = (PH[ii] - c[ii]) / atr[ii]; dn = (c[ii] - PL[ii]) / atr[ii]
        sw_hi = ((B["h4"][ii] > PH[ii]) & (c[ii] < PH[ii])).astype(float); sw_lo = ((B["l4"][ii] < PL[ii]) & (c[ii] > PL[ii])).astype(float)
        f[f"{P}_ahead"] = up if s > 0 else dn; f[f"{P}_behind"] = dn if s > 0 else up; f[f"{P}_swept"] = sw_lo if s > 0 else sw_hi
    f["fib_ret"] = B["fib_up"][ii] if s > 0 else B["fib_dn"][ii]
    f["leg_with"] = np.where(B["leg_up"][ii] == (s > 0), 1.0, 0.0)
    for k in (0, 1, 2):
        j = ii - k
        oo, hh_, ll_, cc_ = B["o"][j], B["h"][j], B["l"][j], B["c"][j]
        f[f"tail{k}"] = ((np.minimum(oo, cc_) - ll_) if s > 0 else (hh_ - np.maximum(oo, cc_))) / atr[ii]
    ent = c[ii]; sl = (B["lo8"][ii] - 0.1 * atr[ii]) if s > 0 else (B["hi8"][ii] + 0.1 * atr[ii])
    sp = (ent - sl) * s / ent
    f["stop_pct"] = sp
    return f, ent, sl, sp
