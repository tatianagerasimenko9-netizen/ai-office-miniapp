"""READ-ONLY. Безіменне відкриття умов: багато загальних числових ознак «що було з ціною до моменту» -> модель сама шукає, що відрізняє входи з рухом >=3R від решти.
Жодних назв стратегій у ознаках. Бари H1 (з M15). Для кожного бара і напрямку (ознаки вирівняні за напрямом): вхід за закриттям, стоп = екстремум 8 барів ∓0.1 ATR, ціль 3R, горизонт 48 барів, SL-first, комісія COST/stop.
TRAIN: 2022-2023. VAL: 2024 (вибір частки відбору). TEST: 2025-2026 (не торкаємось). Контроль: та ж модель на перемішаному результаті.
Використання: ml_discover.py CANDLES_DIR SYMS COST"""
import sys, random
from pathlib import Path
import numpy as np, pandas as pd
import toolkit
from numpy.lib.stride_tricks import sliding_window_view as swv
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

random.seed(7); np.random.seed(7)
CD = Path(sys.argv[1]); SYMS = sys.argv[2].split(","); COST = float(sys.argv[3])
DAY = 86400; HZ = 48; MIN_SP, MAX_SP = 0.003, 0.05


def load_h1(s):
    p = CD / s / "15m.csv"
    if not p.exists(): return None
    d = pd.read_csv(p).drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return g


def rollmax(x, n): return pd.Series(x).rolling(n).max().to_numpy()
def rollmin(x, n): return pd.Series(x).rolling(n).min().to_numpy()


def feats(d, btc):
    t = d.open_time.to_numpy(float); o, h, l, c, v = (d[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")); n = len(c)
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).rolling(14).mean().shift(1).to_numpy()   # ATR до поточного бара
    atr96 = pd.Series(tr).rolling(96).mean().shift(1).to_numpy(); atr336 = pd.Series(tr).rolling(336).mean().shift(1).to_numpy()
    F = {}
    for L in (1, 2, 4, 8, 24, 72, 168): F[f"ret{L}"] = (c - np.r_[np.full(L, np.nan), c[:-L]]) / atr
    for L in (12, 24, 72, 168):
        mx, mn = rollmax(h, L), rollmin(l, L); w = mx - mn
        F[f"pos{L}"] = (c - mn) / np.where(w > 0, w, np.nan); F[f"width{L}"] = w / atr
        if L <= 24: F[f"since_hi{L}"] = pd.Series(h).rolling(L).apply(lambda a: L - 1 - np.argmax(a), raw=True).to_numpy() / L
    for k in (0, 1, 2):
        sh = lambda a: np.r_[np.full(k, np.nan), a[:n - k]] if k else a
        body = (sh(c) - sh(o)) / atr; rng = (sh(h) - sh(l)) / atr
        F[f"body{k}"] = body; F[f"range{k}"] = rng
        F[f"clv{k}"] = (sh(c) - sh(l)) / np.where((sh(h) - sh(l)) > 0, sh(h) - sh(l), np.nan)
    vm20 = pd.Series(v).rolling(20).mean().shift(1).to_numpy(); vm168 = pd.Series(v).rolling(168).mean().shift(1).to_numpy()
    F["vol20"] = v / vm20; F["vol168"] = v / vm168; F["atr_r96"] = atr / atr96; F["atr_r336"] = atr / atr336
    hrs = (t % DAY) / 3600; F["hsin"] = np.sin(2 * np.pi * hrs / 24); F["hcos"] = np.cos(2 * np.pi * hrs / 24); F["dow"] = ((t // DAY + 4) % 7).astype(float)
    F["btc4"] = btc["r4"].reindex(t).to_numpy(); F["btc24"] = btc["r24"].reindex(t).to_numpy()
    # --- рівні різних періодів: попередні день/тиждень/місяць (high/low), H4-свінг (80 барів без останніх 4) ---
    dts = pd.to_datetime(t, unit="s"); pid = {"D": (t // DAY).astype(int), "W": ((t // DAY + 3) // 7).astype(int), "M": (dts.year * 12 + dts.month).to_numpy()}
    LV = {}
    for P, key in pid.items():
        ph = pd.Series(pd.Series(h).groupby(key).max()).shift(1); pl = pd.Series(pd.Series(l).groupby(key).min()).shift(1)
        PH = pd.Series(key).map(ph).to_numpy(); PL = pd.Series(key).map(pl).to_numpy()
        LV[P] = (PH, PL)
    LV["H4"] = (pd.Series(h).rolling(80).max().shift(4).to_numpy(), pd.Series(l).rolling(80).min().shift(4).to_numpy())
    h4 = rollmax(h, 4); l4 = rollmin(l, 4)
    # --- Фібоначчі від останньої ноги за 72 бари ---
    hi72, lo72 = rollmax(h, 72), rollmin(l, 72)
    ihi = pd.Series(h).rolling(72).apply(lambda a: 71 - np.argmax(a), raw=True).to_numpy(); ilo = pd.Series(l).rolling(72).apply(lambda a: 71 - np.argmin(a), raw=True).to_numpy()
    leg_up = ilo > ihi; w72 = np.where(hi72 - lo72 > 0, hi72 - lo72, np.nan)
    F["leg_size"] = w72 / atr
    fib_up = (hi72 - c) / w72      # відкат вниз у висхідній нозі (для лонга)
    fib_dn = (c - lo72) / w72      # відкат вгору у низхідній нозі (для шорта)
    # --- щільність дотиків (сила/дзеркальність рівня) за 168 барів ---
    Wh = swv(h, 168); Wl = swv(l, 168); cc = c[167:]; tol = 0.25 * atr[167:]
    th = np.full(n, np.nan); tl = np.full(n, np.nan)
    th[167:] = (abs(Wh - cc[:, None]) <= tol[:, None]).sum(1); tl[167:] = (abs(Wl - cc[:, None]) <= tol[:, None]).sum(1)
    F["touch_hi"] = th; F["touch_lo"] = tl; F["flip"] = (np.minimum(th, tl) > 0).astype(float); F["touch_tot"] = th + tl
    EX = dict(E=toolkit.extra(t, o, h, l, c, v, atr), LV=LV, h4=h4, l4=l4, fib_up=fib_up, fib_dn=fib_dn, leg_up=leg_up, o=o, h=h, l=l, c=c, atr=atr)
    return t, o, h, l, c, atr, F, EX


def rows_for(sym, d, btc):
    t, o, h, l, c, atr, F, EX = feats(d, btc); n = len(c); out = []
    lo8, hi8 = rollmin(l, 8), rollmax(h, 8)
    idx = np.arange(n); ok0 = (idx > 336) & (idx < n - HZ - 1) & np.isfinite(atr)
    for s in (1, -1):
        ent = c; sl = (lo8 - 0.1 * atr) if s > 0 else (hi8 + 0.1 * atr); risk = (ent - sl) * s; sp = risk / ent
        ok = ok0 & np.isfinite(sl) & (risk > 0) & (sp >= MIN_SP) & (sp <= MAX_SP)
        ii = idx[ok]
        if len(ii) == 0: continue
        Wh = swv(h, HZ + 1)[:, 1:]; Wl = swv(l, HZ + 1)[:, 1:]                  # вікно наступних HZ барів для індексу i
        wh_, wl_ = Wh[ii], Wl[ii]; e, sL, rk = ent[ii], sl[ii], risk[ii]
        tp = e + s * 3 * rk
        if s > 0: slh = wl_ <= sL[:, None]; tph = wh_ >= tp[:, None]
        else: slh = wh_ >= sL[:, None]; tph = wl_ <= tp[:, None]
        si = np.where(slh.any(1), slh.argmax(1), 999); ti = np.where(tph.any(1), tph.argmax(1), 999)
        r = np.where((si == 999) & (ti == 999), s * (c[np.minimum(ii + HZ, n - 1)] - e) / rk, np.where(si <= ti, -1.0, 3.0))
        net = r - COST / sp[ii]
        f = {k: (v[ii] if isinstance(v, np.ndarray) else np.full(len(ii), v)) for k, v in F.items()}
        for k in list(f):                                                         # вирівнювання за напрямом
            if k.startswith(("ret", "body", "btc")): f[k] = f[k] * s
            elif k.startswith(("pos", "clv")): f[k] = f[k] if s > 0 else 1 - f[k]
        for P, (PH, PL) in EX["LV"].items():
            up = (PH[ii] - c[ii]) / atr[ii]; dn = (c[ii] - PL[ii]) / atr[ii]
            sw_hi = ((EX["h4"][ii] > PH[ii]) & (c[ii] < PH[ii])).astype(float); sw_lo = ((EX["l4"][ii] < PL[ii]) & (c[ii] > PL[ii])).astype(float)
            f[f"{P}_ahead"] = up if s > 0 else dn; f[f"{P}_behind"] = dn if s > 0 else up; f[f"{P}_swept"] = sw_lo if s > 0 else sw_hi
        toolkit.apply(EX["E"], ii, s, f)
        f["fib_ret"] = EX["fib_up"][ii] if s > 0 else EX["fib_dn"][ii]
        f["leg_with"] = np.where(EX["leg_up"][ii] == (s > 0), 1.0, 0.0)
        for k in (0, 1, 2):
            ok_ = np.arange(n)[ii] - k
            oo, hh_, ll_, cc_ = EX["o"][ok_], EX["h"][ok_], EX["l"][ok_], EX["c"][ok_]
            f[f"tail{k}"] = ((np.minimum(oo, cc_) - ll_) if s > 0 else (hh_ - np.maximum(oo, cc_))) / atr[ii]
        df = pd.DataFrame(f); df["stop_pct"] = sp[ii]; df["ent"] = e; df["sl"] = sL; df["t"] = t[ii]; df["r"] = net; df["side"] = s; df["sym"] = sym
        out.append(df)
    return pd.concat(out) if out else None


def boot(dd, n=1000):
    ks = list(dd)
    if not ks: return 0, 0
    ms = []
    for _ in range(n):
        s = c = 0
        for _ in ks:
            x = dd[random.choice(ks)]; s += sum(x); c += len(x)
        ms.append(s / c)
    ms.sort(); return ms[int(.025 * n)], ms[int(.975 * n)]


def dedupe(df):
    df = df.sort_values(["sym", "side", "t"]); keep = (df.sym != df.sym.shift()) | (df.side != df.side.shift()) | (df.t - df.t.shift() > 12 * 3600)
    return df.groupby(keep.cumsum()).head(1)


def evaluate(df, score, q, name, years):
    out = []
    for y in years:
        z = df[(df.year == y)].copy(); z["s"] = score[df.year.to_numpy() == y]
        thr = np.quantile(z.s, 1 - q); sel = dedupe(z[z.s >= thr]); dd = {}
        for tt, rr in zip(sel.t, sel.r): dd.setdefault(int(tt // DAY), []).append(rr)
        lo, hi = boot(dd) if len(sel) else (0, 0)
        out.append((y, len(sel), sel.r.mean() if len(sel) else 0, 10 * sel.r.sum(), lo, hi))
    print(f"  {name}: " + " | ".join(f"{y}: n={n} R={r:+.3f} ${d:+,.0f} CI[{lo:+.2f};{hi:+.2f}]" for y, n, r, d, lo, hi in out))
    return out


def main():
    b = load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    parts = []
    for s in SYMS:
        d = load_h1(s)
        if d is None: continue
        r = rows_for(s, d, btc)
        if r is not None: parts.append(r); print(s, len(r), flush=True)
    df = pd.concat(parts).reset_index(drop=True); df["year"] = pd.to_datetime(df.t, unit="s").dt.year
    X = [c for c in df.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    print(f"\nВходів {len(df)}; ознак {len(X)}; комісія {COST*100:.2f}%; сер. R усіх входів по роках:", {int(y): round(g.r.mean(), 3) for y, g in df.groupby("year")})
    tr = df[df.year <= 2023]; va = df[df.year == 2024]; te = df[df.year >= 2025]
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    mc = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], np.random.permutation(tr.r.to_numpy()))
    allv = pd.concat([va, te]); allv["year"] = allv.year.astype(int)
    for q in (0.01, 0.03, 0.10):
        print(f"\n--- відбір топ {int(q*100)}% за прогнозом моделі (дедуплікація 12 год) ---")
        evaluate(allv, m.predict(allv[X]), q, "МОДЕЛЬ", (2024, 2025, 2026))
        evaluate(allv, mc.predict(allv[X]), q, "КОНТРОЛЬ (перемішаний результат)", (2024, 2025, 2026))
    print("\n--- Які ознаки модель вважає важливими (на VAL 2024, зміна якості при перемішуванні) ---")
    sub = va.sample(min(40000, len(va)), random_state=7)
    pi = permutation_importance(m, sub[X], sub.r, n_repeats=3, random_state=7, scoring="neg_mean_squared_error")
    for i in np.argsort(-pi.importances_mean)[:15]: print(f"   {X[i]} [{toolkit.family_of(X[i])}]: {pi.importances_mean[i]:.5f}")
    fam = {}
    for i, nme in enumerate(X): fam[toolkit.family_of(nme)] = fam.get(toolkit.family_of(nme), 0) + max(pi.importances_mean[i], 0)
    tot = sum(fam.values()) or 1
    print("\n--- Внесок ГРУП інструментів у прогноз (частка від загальної важливості) ---")
    for k, vv in sorted(fam.items(), key=lambda x: -x[1]): print(f"   {k}: {100*vv/tot:.1f}%")
    print("\n--- Калібрування: децилі прогнозу моделі на TEST 2025-2026 (без дедуплікації; чи росте результат разом з прогнозом?) ---")
    z = te.copy(); z["s"] = m.predict(z[X]); z["dec"] = pd.qcut(z.s, 10, labels=False, duplicates="drop")
    for dcl, g in z.groupby("dec"): print(f"   дециль {int(dcl)}: n={len(g)} R/угоду={g.r.mean():+.3f} частка плюсових={100*(g.r>0).mean():.1f}%")
    print("\n##### ПІДСУМОК ml_discover3 завершено")
if __name__ == "__main__":
    main()
