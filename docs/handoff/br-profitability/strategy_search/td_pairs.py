"""READ-ONLY. ІНТРАДЕЙ: ПРОТИЛЕЖНІ СИГНАЛИ ПО ОДНІЙ МОНЕТІ (26.11.2026, питання власниці після ETH №139 SHORT і №140 LONG з різницею 14 хв: «який сигнал у таких випадках правий»).
Ті самі угоди, що в td_calm.py/newcoins.py (12 монет, модель навчена ≤2023, поріг 2024, вхід M15, 2024–2026), $10 ризику, комісія в результаті. Нічого не підбирається.
Пара = два сигнали по одній монеті в ПРОТИЛЕЖНІ боки, де другий увійшов не пізніше ніж через W годин після входу першого (W = 1, 4, 12, 48 — усі показано).
Показуємо: результат ПЕРШОГО в парі, ДРУГОГО в парі, обох разом, і для порівняння — сигнали без пари. Окремо: хто з двох виграв.
Використання: td_pairs.py CANDLES_DIR TRAIN COST OUT_CSV"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST, OUTCSV = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
from sklearn.ensemble import HistGradientBoostingRegressor
md, td = nc.md, nc.td
b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
tr = A[A.year <= 2023]; va = A[A.year == 2024]
m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
for y in (2024, 2025, 2026):
    z = A[A.year == y].copy()
    if len(z): z["s"] = m.predict(z[X]); parts.append(z[z.s >= thr])
sel = md.dedupe(pd.concat(parts)); res = []; cache = {}
for _, x in sel.iterrows():                                   # копія nc.m15_stage, але зберігаємо бік і час входу
    if x.sym not in cache:
        a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"]))
    a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
    o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
    for k in range(16):
        j = i0 + k
        if j < 9 or j >= len(c_) - 2: break
        if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
        at = at_[j]
        if not at == at: break
        ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
        if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
        res.append((x.sym, side, float(a["open_time"][j]) + 900, td.sim(a, j, side, ent, sl, tp) - float(COST) / sp)); break
T = pd.DataFrame(res, columns=["sym", "side", "t", "r"]).sort_values(["sym", "t"]).reset_index(drop=True); T["usd"] = 10 * T.r; T["y"] = pd.to_datetime(T.t, unit="s").dt.year; T.to_csv(OUTCSV, index=False)
print(f"ІНТРАДЕЙ, протилежні сигнали: {len(T)} угод, 2024–2026, $10 ризику; усі: на угоду ${T.usd.mean():+.2f} (LONG ${T[T.side>0].usd.mean():+.2f}, n={int((T.side>0).sum())}; SHORT ${T[T.side<0].usd.mean():+.2f}, n={int((T.side<0).sum())})")
for W in (1, 4, 12, 48):
    first = []; second = []
    for sym, g in T.groupby("sym"):
        tt = g.t.to_numpy(); sd = g.side.to_numpy(); ix = g.index.to_numpy(); used = set()
        for a_ in range(len(g)):
            if ix[a_] in used: continue
            for b_ in range(a_ + 1, len(g)):
                if tt[b_] - tt[a_] > W * 3600: break
                if sd[b_] == -sd[a_] and ix[b_] not in used: first.append(ix[a_]); second.append(ix[b_]); used.update((ix[a_], ix[b_])); break
    F = T.loc[first]; S = T.loc[second]; rest = T.drop(index=first + second)
    if len(F) < 15: print(f"\n== другий сигнал протягом {W} год: пар {len(F)} — замало"); continue
    fu = F.usd.to_numpy(); su = S.usd.to_numpy()
    print(f"\n== другий (протилежний) сигнал протягом {W} год після першого: пар {len(F)}")
    print(f"   ПЕРШИЙ сигнал пари : на угоду ${fu.mean():+.2f}, виграшних {100*(fu>0).mean():.0f}%")
    print(f"   ДРУГИЙ сигнал пари : на угоду ${su.mean():+.2f}, виграшних {100*(su>0).mean():.0f}%")
    print(f"   обидва разом       : на пару ${(fu+su).mean():+.2f}; обидва в мінусі {100*((fu<0)&(su<0)).mean():.0f}%, обидва в плюсі {100*((fu>0)&(su>0)).mean():.0f}%, виграв лише перший {100*((fu>0)&(su<=0)).mean():.0f}%, лише другий {100*((su>0)&(fu<=0)).mean():.0f}%")
    print(f"   сигнали БЕЗ пари   : на угоду ${rest.usd.mean():+.2f}, виграшних {100*(rest.usd>0).mean():.0f}%, n={len(rest)}")
    print(f"   другий = LONG: {int((S.side>0).sum())} пар, перший(SHORT) ${F[S.side.to_numpy()>0].usd.mean():+.2f} / другий(LONG) ${S[S.side>0].usd.mean():+.2f} | другий = SHORT: {int((S.side<0).sum())} пар, перший(LONG) ${F[S.side.to_numpy()<0].usd.mean():+.2f} / другий(SHORT) ${S[S.side<0].usd.mean():+.2f}")
    print("   по роках (перший / другий, сума $): " + ", ".join(f"{y}: {F[F.y==y].usd.sum():+.0f} / {S[(F.y==y).to_numpy()].usd.sum():+.0f} (пар {int((F.y==y).sum())})" for y in sorted(F.y.unique())))
