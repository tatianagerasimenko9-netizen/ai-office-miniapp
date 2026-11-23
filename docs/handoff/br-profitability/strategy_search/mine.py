"""READ-ONLY. «Пошук без теорій» (22.11.2026, прохання власниці: шукати закономірності на історії поза відомими метриками).
Беремо СИРІ ознаки (повернення за різні вікна, волатильність, об'єм, форма свічки, відстань до екстремумів, відносна сила монети проти BTC і проти решти монет, ширина ринку, кореляція з BTC, година/день) на H1 для 42 монет, 2022–2026,
і двома способами дивимось, чи щось передбачає майбутній рух (горизонт h барів, комісія FEE за угоду, ВСЕ в процентах/б.п., без стопів — чиста передбачуваність):
 (A) walk-forward GBM: навчання на минулих роках, перевірка на наступному (2023, 2024, 2025, 2026); топ/низ 10% за прогнозом; ІС; важливість ознак.
 (B) майнінг правил «ознака1 × ознака2 у терцилях»: що «знайшли» на 2022–2023 → чи тримається на 2024 і на 2025–2026. Контроль випадковості: частка правил, що тримаються поза навчанням (випадково ≈ 50%/мало).
Використання: mine.py CANDLES_DIR SYMS FEE H OUT   (H — горизонт у барах H1, напр. 24)"""
import os, sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
CD, SYMS, FEE, H, OUT = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
rng = np.random.default_rng(7)
def load(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    if "volume" not in d: d["volume"] = 1.0
    g = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
    return g
P = {s: load(s) for s in SYMS}
idx = sorted(set().union(*[set(p.index) for p in P.values()])); idx = pd.Index(idx)
W = {k: pd.DataFrame({s: P[s][k] for s in SYMS}).reindex(idx) for k in ("open", "high", "low", "close", "volume")}
O, Hh, L, C, V = W["open"], W["high"], W["low"], W["close"], W["volume"]
lc = np.log(C); r1 = lc.diff()
BTC = "BTCUSDT" if "BTCUSDT" in SYMS else SYMS[0]
F = {}
for k in (1, 3, 6, 12, 24, 72, 168): F[f"r{k}"] = lc.diff(k)
F["vol24"] = r1.rolling(24).std(); F["vol168"] = r1.rolling(168).std(); F["volratio"] = F["vol24"] / F["vol168"]
rg = (Hh - L) / C; F["rngz"] = rg / rg.rolling(48).mean()
den = (Hh - L).replace(0, np.nan); F["cpos"] = (C - L) / den
F["upw"] = (Hh - np.maximum(O, C)) / den; F["dnw"] = (np.minimum(O, C) - L) / den
F["vz"] = (V - V.rolling(48).mean()) / V.rolling(48).std(); F["vtr"] = V.rolling(6).mean() / V.rolling(72).mean()
F["dh24"] = C / Hh.rolling(24).max() - 1; F["dl24"] = C / L.rolling(24).min() - 1
F["dh168"] = C / Hh.rolling(168).max() - 1; F["dl168"] = C / L.rolling(168).min() - 1
for k in (6, 24):
    b = F[f"r{k}"][BTC]; F[f"btc_r{k}"] = pd.DataFrame({s: b for s in SYMS}); F[f"rel{k}"] = F[f"r{k}"] - F[f"btc_r{k}"]
F["xs_r6"] = F["r6"].rank(axis=1, pct=True); F["xs_r24"] = F["r24"].rank(axis=1, pct=True); F["xs_vz"] = F["vz"].rank(axis=1, pct=True)
br = (F["r6"] > 0).mean(axis=1); F["breadth"] = pd.DataFrame({s: br for s in SYMS})
F["sgn6"] = np.sign(r1).rolling(6).sum()
bt = r1[BTC]; F["corr_btc"] = pd.DataFrame({s: r1[s].rolling(168).corr(bt) for s in SYMS})
hr = pd.Series(pd.to_datetime(idx, unit="s").hour, index=idx); dw = pd.Series(pd.to_datetime(idx, unit="s").day_of_week, index=idx)
F["hour"] = pd.DataFrame({s: hr for s in SYMS}); F["dow"] = pd.DataFrame({s: dw for s in SYMS})
FWD = C.shift(-H) / O.shift(-1) - 1                       # вхід на відкритті наступного бару, вихід через H барів
XS = FWD.sub(FWD.mean(axis=1), axis=0)                     # відносно решти монет (ринково-нейтральна ціль)
names = list(F)
tpos = pd.DataFrame({s: np.arange(len(idx)) for s in SYMS}, index=idx)
S = pd.concat({**{k: v.stack() for k, v in F.items()}, "fwd": FWD.stack(), "xs": XS.stack(), "t": tpos.stack()}, axis=1)
S = S.dropna(); S["year"] = pd.to_datetime(S.index.get_level_values(0), unit="s").year
for c in ("fwd", "xs"): lo, hi = S[c].quantile([0.005, 0.995]); S[c + "_w"] = S[c].clip(lo, hi)
print(f"ПОШУК БЕЗ ТЕОРІЙ: H1, горизонт {H} год, комісія {FEE*100:.2f}% за угоду, монет {len(SYMS)}, рядків {len(S)}, ознак {len(names)}")
NO = S[S.t % H == 0]                                       # непересічні вікна для оцінки

# ---------- A: walk-forward GBM
print("\n=== A. Walk-forward модель (навчання на минулих роках → перевірка на наступному) ===")
tot = []
for ty in (2023, 2024, 2025, 2026):
    tr = S[(S.year < ty) & (S.t % 3 == 0)]; te = NO[NO.year == ty]
    if len(tr) < 5000 or len(te) < 500: continue
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=200, min_samples_leaf=500, l2_regularization=1.0, random_state=1)
    m.fit(tr[names], tr["xs_w"]); p = m.predict(te[names]); te = te.assign(p=p)
    ic = pd.Series(p).corr(te["xs_w"].reset_index(drop=True), method="spearman")
    q = te.p.rank(pct=True); top, bot = te[q >= 0.9], te[q <= 0.1]
    lg = top.fwd - FEE; sh = -bot.fwd - FEE
    both = pd.concat([lg, sh])
    print(f" {ty}: ІС {ic:+.3f} | топ10% лонг: {len(top)} угод, {1e4*lg.mean():+.0f} б.п. на угоду, виграшних {100*(lg>0).mean():.0f}% | низ10% шорт: {len(bot)}, {1e4*sh.mean():+.0f} б.п., {100*(sh>0).mean():.0f}% | разом {1e4*both.mean():+.0f} б.п.")
    tot.append(both)
if tot:
    a = pd.concat(tot); print(f" УСЬОГО поза навчанням: {len(a)} угод, {1e4*a.mean():+.1f} б.п. на угоду (комісія вже врахована), виграшних {100*(a>0).mean():.0f}%, t≈{a.mean()/(a.std()/np.sqrt(len(a))):+.1f}")
    # важливість ознак на останній перевірці
    from sklearn.inspection import permutation_importance
    ss = te.sample(min(20000, len(te)), random_state=1)
    pi = permutation_importance(m, ss[names], ss["xs_w"], n_repeats=3, random_state=1, scoring="neg_mean_squared_error")
    print(" важливість ознак (остання перевірка; ~0 = нічого не додає):")
    for n_, v in sorted(zip(names, pi.importances_mean), key=lambda x: -x[1])[:10]: print(f"   {n_:10s} {v*1e8:+.2f}")

# ---------- B: майнінг правил
print("\n=== B. Майнінг правил «ознака1 × ознака2» (терцилі за 2022–2023; чи тримається поза навчанням) ===")
TR = NO[NO.year <= 2023]; V1 = NO[NO.year == 2024]; T1 = NO[NO.year >= 2025]
cut = {n: TR[n].quantile([1 / 3, 2 / 3]).to_numpy() for n in names if TR[n].nunique() > 3}
def code(df, n): return np.digitize(df[n].to_numpy(), cut[n])
cd = {k: {n: code(d, n) for n in cut} for k, d in (("tr", TR), ("v1", V1), ("t1", T1))}
fw = {"tr": TR.fwd.to_numpy(), "v1": V1.fwd.to_numpy(), "t1": T1.fwd.to_numpy()}
def stat(mask, k):
    x = fw[k][mask]
    return len(x), (x.mean() if len(x) else np.nan), (x.std() if len(x) > 1 else np.nan)
rules = []; cn = list(cut)
for i in range(len(cn)):
    for j in range(i + 1, len(cn)):
        for a in range(3):
            for b in range(3):
                mk = (cd["tr"][cn[i]] == a) & (cd["tr"][cn[j]] == b); n, mu, sd = stat(mk, "tr")
                if n < 400 or not sd: continue
                t = mu / (sd / np.sqrt(n))
                if abs(t) < 3.0: continue
                side = 1 if mu > 0 else -1
                m1 = (cd["v1"][cn[i]] == a) & (cd["v1"][cn[j]] == b); n1, mu1, _ = stat(m1, "v1")
                m2 = (cd["t1"][cn[i]] == a) & (cd["t1"][cn[j]] == b); n2, mu2, _ = stat(m2, "t1")
                if n1 < 100 or n2 < 100: continue
                rules.append((cn[i], a, cn[j], b, side, n, 1e4 * (side * mu - FEE), t, n1, 1e4 * (side * mu1 - FEE), n2, 1e4 * (side * mu2 - FEE)))
R = pd.DataFrame(rules, columns=["f1", "b1", "f2", "b2", "side", "n_tr", "net_tr_bp", "t", "n_v", "net_v_bp", "n_t", "net_t_bp"])
print(f" перевірено пар ознак: {len(cn)*(len(cn)-1)//2}, комірок ≈ {len(cn)*(len(cn)-1)//2*9}; «знайдено» на навчанні (|t|≥3, ≥400 угод): {len(R)}")
if len(R):
    ok_v = (R.net_v_bp > 0); ok_t = (R.net_t_bp > 0); both = ok_v & ok_t
    print(f" з них прибуткові (після комісії) на 2024: {ok_v.mean()*100:.0f}%, на 2025–2026: {ok_t.mean()*100:.0f}%, в обох: {both.mean()*100:.0f}%   (якби закономірностей немає — близько 25%)")
    print(f" середній результат знайдених правил: навчання {R.net_tr_bp.mean():+.0f} б.п., 2024 {R.net_v_bp.mean():+.0f}, 2025–26 {R.net_t_bp.mean():+.0f}")
    print(" правила, що тримаються в усіх трьох періодах (сторона: 1=лонг, -1=шорт; терцилі 0=низ,1=сер,2=верх):")
    G = R[both & (R.net_tr_bp > 0)].assign(w=lambda x: x[["net_tr_bp", "net_v_bp", "net_t_bp"]].min(axis=1)).sort_values("w", ascending=False).head(15)
    print(G.drop(columns=["w"]).round(1).to_string(index=False))
    R.to_csv(OUT + "_rules.csv", index=False)
