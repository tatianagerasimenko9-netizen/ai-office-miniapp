"""READ-ONLY. «Від зворотного»: для кожного моменту історії (M15, кожні 2 бари) і напрямку рахуємо результат входу
(стоп за екстремумом 8 барів ∓0.1 ATR, ціль 2R, SL-first, горизонт 48 барів, комісія), записуємо ознаки, ВІДОМІ на момент входу,
вчимо неглибоке дерево лише на TRAIN (перші 55% часу), перевіряємо листки на TEST (останні 45%, ембарго 2 доби) з CI95 по днях.
Використання: reverse_search.py CANDLES_DIR SYM1,SYM2,...  (потрібен {SYM}/15m.csv). Пороги — ГІПОТЕЗА."""
import sys, random
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.tree import DecisionTreeRegressor, export_text

random.seed(7)
CD = Path(sys.argv[1]); SYMS = sys.argv[2].split(",")
DAY = 86400; COST = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0010
FEATS = ["hour", "sess_asia", "sess_london", "sess_ny", "dow", "dist_open_atr", "pos_range24", "atr_ratio", "pullback_atr",
         "ema_align", "h1_align", "vol_ratio", "day_used", "btc_h1_align", "stop_pct"]


def load(s):
    p = CD / s / "15m.csv"
    if not p.exists(): return None
    d = pd.read_csv(p).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    return d


def ema(x, n):
    a = 2 / (n + 1); o = np.empty_like(x); o[0] = x[0]
    for i in range(1, len(x)): o[i] = a * x[i] + (1 - a) * o[i - 1]
    return o


def build(d, btc_ret):
    t = d.open_time.to_numpy(float); o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = d.volume.to_numpy(float) if "volume" in d else np.ones(len(d))
    n = len(c); pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    cs = np.cumsum(np.r_[0, tr])
    atr14 = np.full(n, np.nan); atr14[14:] = (cs[15:] - cs[1:n - 13]) / 14
    atr96 = np.full(n, np.nan); atr96[96:] = (cs[97:] - cs[1:n - 95]) / 96
    e20, e50 = ema(c, 20), ema(c, 50)
    hour = ((t % DAY) // 3600).astype(int); dow = ((t // DAY + 4) % 7).astype(int)
    day = (t // DAY).astype(int)
    day_open = pd.Series(o).groupby(day).transform("first").to_numpy()
    day_hi = pd.Series(h).groupby(day).cummax().to_numpy(); day_lo = pd.Series(l).groupby(day).cummin().to_numpy()
    dr = pd.Series(h - l).groupby(day).sum()  # грубий добовий діапазон як відносна база
    day_atr = pd.Series(day).map(pd.Series((pd.Series(h).groupby(day).max() - pd.Series(l).groupby(day).min()).rolling(14).mean().shift(1))).to_numpy()
    sess_open = np.empty(n)
    for i in range(n):
        s0 = 0 if hour[i] < 7 else (7 if hour[i] < 13 else 13)
        sess_open[i] = o[i] if i == 0 or day[i] != day[i - 1] or (hour[i] == s0 and hour[i - 1] != hour[i]) else sess_open[i - 1]
    rows = []
    for i in range(110, n - 50, 2):
        if not (atr14[i] == atr14[i] and atr96[i] == atr96[i] and day_atr[i] == day_atr[i]): continue
        rng24 = h[i - 95:i + 1].max() - l[i - 95:i + 1].min()
        for side in (1, -1):
            ext = l[i - 7:i + 1].min() if side > 0 else h[i - 7:i + 1].max()
            sl = ext - side * 0.1 * atr14[i]; ent = c[i]; risk = (ent - sl) * side
            sp = risk / ent
            if risk <= 0 or not (0.003 <= sp <= 0.02): continue
            tp = ent + side * 2 * risk
            hi_, lo_ = h[i + 1:i + 49], l[i + 1:i + 49]
            if side > 0:
                si = np.argmax(lo_ <= sl) if (lo_ <= sl).any() else 99; ti = np.argmax(hi_ >= tp) if (hi_ >= tp).any() else 99
            else:
                si = np.argmax(hi_ >= sl) if (hi_ >= sl).any() else 99; ti = np.argmax(lo_ <= tp) if (lo_ <= tp).any() else 99
            if si == 99 and ti == 99: r = side * (c[i + 48] - ent) / risk
            else: r = -1.0 if si <= ti else 2.0
            r -= COST / sp
            imp = (h[i - 11:i + 1].max() - l[i - 11:i + 1].min())
            last_ext = h[i - 11:i + 1].max() if side > 0 else l[i - 11:i + 1].min()
            pull = abs(last_ext - c[i]) / atr14[i]
            hr = hour[i]
            br = btc_ret.get(int(t[i] // 900), 0.0)
            rows.append(dict(t=t[i], r=r, hour=hr, sess_asia=int(hr < 7), sess_london=int(7 <= hr < 13), sess_ny=int(hr >= 13), dow=dow[i],
                             dist_open_atr=side * (c[i] - sess_open[i]) / atr14[i],
                             pos_range24=((c[i] - l[i - 95:i + 1].min()) / rng24 if rng24 > 0 else .5) if side > 0 else 1 - ((c[i] - l[i - 95:i + 1].min()) / rng24 if rng24 > 0 else .5),
                             atr_ratio=atr14[i] / atr96[i], pullback_atr=pull,
                             ema_align=side * np.sign(e20[i] - e50[i]), h1_align=side * np.sign(c[i] - c[i - 4]),
                             vol_ratio=v[i] / (v[i - 20:i].mean() or 1), day_used=(day_hi[i] - day_lo[i]) / day_atr[i],
                             btc_h1_align=side * br, stop_pct=sp, side=side))
    return rows


def boot(dd, n=2000):
    ks = list(dd)
    if not ks: return 0, 0
    m = []
    for _ in range(n):
        s = c = 0
        for _ in ks:
            x = dd[random.choice(ks)]; s += sum(x); c += len(x)
        m.append(s / c)
    m.sort(); return m[int(.025 * n)], m[int(.975 * n)]


def main():
    btc = load("BTCUSDT"); btc_ret = {}
    if btc is not None:
        bt = btc.open_time.to_numpy(float); bc = btc.close.to_numpy(float)
        for i in range(4, len(bc)): btc_ret[int(bt[i] // 900)] = np.sign(bc[i] - bc[i - 4])
    allrows = []
    for s in SYMS:
        d = load(s)
        if d is None: print("пропуск", s); continue
        r = build(d, btc_ret)
        for x in r: x["sym"] = s
        allrows += r; print(s, len(r), flush=True)
    df = pd.DataFrame(allrows).sort_values("t").reset_index(drop=True)
    t0, t1 = df.t.min(), df.t.max(); cut = t0 + .55 * (t1 - t0); emb = cut + 2 * DAY
    tr, te = df[df.t < cut], df[df.t >= emb]
    print(f"\nМоментів: TRAIN {len(tr)}, TEST {len(te)}; середній R (всі входи без фільтра): TRAIN {tr.r.mean():+.3f}, TEST {te.r.mean():+.3f}; комісія {COST*100:.2f}%")
    for depth, leaf in ((3, 500), (4, 400)):
        m = DecisionTreeRegressor(max_depth=depth, min_samples_leaf=leaf).fit(tr[FEATS], tr.r)
        print(f"\n=== Дерево depth={depth}, мін. листок {leaf} ===")
        print(export_text(m, feature_names=FEATS))
        tr_leaf = m.apply(tr[FEATS]); te_leaf = m.apply(te[FEATS]); nok = 0
        print("| листок | n train | R train | n test | R test | CI95 test | $ test ($10/угоду) | ✅ |\n|--|--|--|--|--|--|--|--|")
        for lf in sorted(set(tr_leaf)):
            a, b = tr[tr_leaf == lf], te[te_leaf == lf]
            if len(b) < 30: continue
            dd = {}
            for tt, x in zip(b.t, b.r): dd.setdefault(int(tt // DAY), []).append(x)
            lo, hi = boot(dd); ok = a.r.mean() > 0 and b.r.mean() > 0 and lo > 0; nok += ok
            print(f"| {lf} | {len(a)} | {a.r.mean():+.3f} | {len(b)} | {b.r.mean():+.3f} | [{lo:+.3f}; {hi:+.3f}] | {10*b.r.sum():+,.0f} | {'✅' if ok else ''} |")
        print(f"Листків ✅: {nok}. Кратне порівняння ≈ кількість листків; ✅ — кандидат, потрібен shadow.")
    # прості умови, зрозумілі без дерева
    print("\nПрості зрізи TEST (R/угоду, n):")
    for name, col in (("сесія", None),):
        for nm, mask in (("Азія 00-07", te.sess_asia == 1), ("Лондон 07-13", te.sess_london == 1), ("Нью-Йорк 13-24", te.sess_ny == 1)):
            x = te[mask]; print(f"  {nm}: n={len(x)}, R={x.r.mean():+.3f}, $={10*x.r.sum():+,.0f}")


main()
