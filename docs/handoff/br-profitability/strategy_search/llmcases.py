"""READ-ONLY. Готує ОБЕЗЛИЧЕНІ кейси сигналів TD-V1 для «сліпої» оцінки помічником (LLM) і файл результатів (окремо, помічник його не бачить).
Обезличення: без дати й назви інструмента, ціни у % від входу. Вибірка: 100 кейсів ПІСЛЯ 01.07.2026 (поза знанням моделі до червня 2026) + 50 раніше.
Використання: llmcases.py CANDLES_DIR TRAIN_SYMS NEW_SYMS OUT_DIR"""
import sys, json, random
import numpy as np, pandas as pd
CD, TRAIN, NEW, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.argv = ["x", CD, TRAIN, NEW, "0.001"]
import newcoins as nc
sys.path.insert(0, __file__.rsplit('/', 1)[0]); import d1lv
md, td = nc.md, nc.td
CUT = pd.Timestamp("2026-07-01", tz="UTC").timestamp()

def path(a, j, side, ent, sl, tp, hz=192):
    """Шлях угоди (SL-першим): результат, бар виходу, макс. сприятливий рух до виходу (R), і кожен рівень +0.5/+1/+1.5/+2R: бар першого досягнення та бар першого повернення до входу після нього."""
    h, l = a["high"], a["low"]; c = a["close"]; risk = abs(ent - sl); out = "TIME"; nb = hz; fav = []; ret = []; rn = {}
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(h): nb = k - 1; break
        hit_sl = (l[q] <= sl) if side > 0 else (h[q] >= sl); hit_tp = (h[q] >= tp) if side > 0 else (l[q] <= tp)
        if hit_sl: out, nb = "SL", k; break
        if hit_tp: out, nb = "TP", k; break
        fav.append(((h[q] - ent) if side > 0 else (ent - l[q])) / risk); ret.append((l[q] <= ent) if side > 0 else (h[q] >= ent))
        if k in (8, 16, 32, 48, 96): rn[k] = round(((c[q] - ent) if side > 0 else (ent - c[q])) / risk, 3)
    res = dict(out=out, nb=nb, mfe=round(max(fav), 3) if fav else 0.0)
    for k in (8, 16, 32, 48, 96): res[f"r{k}"] = rn.get(k)
    for lv in (0.5, 1.0, 1.5, 2.0):
        t = next((i + 1 for i, f in enumerate(fav) if f >= lv), None); res[f"t{lv}"] = t
        res[f"b{lv}"] = next((i + 1 for i in range(t, len(ret)) if ret[i]), None) if t else None
    return res

def limit_sim(a, j, side, ent, sl, tp, at, off, W=4, hz=192):
    """Лімітний вхід: рівень = вхід сигналу, зсунутий у бік ПОЛІПШЕННЯ ціни на off*ATR. Виконується, якщо за W барів (1 год) ціна торкнулась рівня; далі той самий стоп і ціль (абсолютні ціни). SL-першим; на барі виконання ціль не рахується (консервативно)."""
    h, l, o, c = a["high"], a["low"], a["open"], a["close"]; lvl = ent - side * off * at
    for k in range(1, W + 1):
        q = j + k
        if q >= len(c): return None
        if (l[q] <= lvl) if side > 0 else (h[q] >= lvl):
            fp = min(lvl, o[q]) if side > 0 else max(lvl, o[q]); risk = abs(fp - sl)
            if risk <= 0 or (tp - fp) * side <= 0 or (fp - sl) * side <= 0: return None
            sp = risk / fp
            if (l[q] <= sl) if side > 0 else (h[q] >= sl): return dict(k=k, out="SL", R=-1.0, sp=sp)
            for m in range(1, hz + 1):
                z = q + m
                if z >= len(c): return None
                if (l[z] <= sl) if side > 0 else (h[z] >= sl): return dict(k=k, out="SL", R=-1.0, sp=sp)
                if (h[z] >= tp) if side > 0 else (l[z] <= tp): return dict(k=k, out="TP", R=side * (tp - fp) / risk, sp=sp)
            return dict(k=k, out="TIME", R=side * (c[q + hz] - fp) / risk, sp=sp)
    return dict(k=0, out="NOFILL", R=0.0, sp=0.0)

def d1_levels(a, N=3):
    """Рівні з денного графіка: фрактальні максимуми/мінімуми (екстремум серед N днів з обох боків). ГІПОТЕЗА щодо N. Повертає (день_підтвердження, ціна, тип)."""
    day = (a["open_time"] // 86400).astype(int); u, st = np.unique(day, return_index=True); en = np.r_[st[1:], len(day)]
    hi = np.array([a["high"][x:y].max() for x, y in zip(st, en)]); lo = np.array([a["low"][x:y].min() for x, y in zip(st, en)]); out = []
    for i in range(N, len(u) - N):
        if hi[i] > hi[i - N:i].max() and hi[i] > hi[i + 1:i + N + 1].max(): out.append((int(u[i + N]), float(hi[i]), "H"))
        if lo[i] < lo[i - N:i].min() and lo[i] < lo[i + 1:i + N + 1].min(): out.append((int(u[i + N]), float(lo[i]), "L"))
    return out

def rel(p, e): return round((float(p) / e - 1) * 100, 2)

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(TRAIN.split(","), btc); N = nc.rows(NEW.split(","), btc)
    for d_ in (A, N): d_["year"] = pd.to_datetime(d_.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = nc.HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for D in (A, N):
        for y in (2024, 2025, 2026):
            z = D[D.year == y].copy()
            if len(z): z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
    sel = pd.concat(parts); cases = []; cache = {}; H = {}; allrows = []; limrows = []; lvrows = []; D1L = {}
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"])); H[x.sym] = md.load_h1(x.sym)
        a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
        for k in range(16):
            j = i0 + k
            if j < 200 or j >= len(c_) - 700: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            hh = H[x.sym]; tt = hh.open_time.to_numpy(float); i = int(np.searchsorted(tt, a["open_time"][j] + 900)) - 1
            if i < 200: break
            h1 = [[rel(hh.open.iloc[q], ent), rel(hh.high.iloc[q], ent), rel(hh.low.iloc[q], ent), rel(hh.close.iloc[q], ent)] for q in range(i - 35, i + 1)]
            m15 = [[rel(o_[q], ent), rel(h_[q], ent), rel(l_[q], ent), rel(c_[q], ent)] for q in range(j - 31, j + 1)]
            dd = (a["open_time"][j] // 86400) * 86400; hi_d = hh[(tt >= dd - 86400) & (tt < dd)]; wk = hh[(tt >= dd - 7 * 86400) & (tt < dd)]
            lv = {"prev_day_high": rel(hi_d.high.max(), ent) if len(hi_d) else None, "prev_day_low": rel(hi_d.low.min(), ent) if len(hi_d) else None, "week_high": rel(wk.high.max(), ent) if len(wk) else None, "week_low": rel(wk.low.min(), ent) if len(wk) else None}
            bi = int(np.searchsorted(btc.index.to_numpy(float), x.t)); br24 = float(btc.r24.iloc[min(bi, len(btc) - 1)]) * 100
            fwd = [[round(float(h_[q]), 8), round(float(l_[q]), 8), round(float(c_[q]), 8)] for q in range(j + 1, min(j + 673, len(c_)))]
            _r = td.sim(a, j, side, ent, sl, tp, 192) - 0.001 / sp
            if x.sym not in D1L: _D = d1lv.build(a); D1L[x.sym] = (_D, d1lv.levels(_D))
            _D, _Ls = D1L[x.sym]; _di = int(np.searchsorted(_D["u"], int(a["open_time"][j] // 86400))); _risk = abs(ent - sl); _atrd = _D["atr"][_di] if _di < len(_D["atr"]) else float("nan")
            _al = [(L_["p"], L_["t"], d1lv.state(L_, _di)) for L_ in _Ls]; _al = [(p_, t_, k_) for p_, t_, k_ in _al if k_ is not None]
            _ah = [(abs(p_ - ent), k_) for p_, t_, k_ in _al if (p_ - ent) * side > 0.0005 * ent]; _bk = [(abs(p_ - ent), k_) for p_, t_, k_ in _al if (p_ - ent) * side < -0.0005 * ent]
            _a1 = min(_ah) if _ah else None; _b1 = min(_bk) if _bk else None; _nr = min(_al, key=lambda z: abs(z[0] - ent)) if _al else None
            lvrows.append([float(a["open_time"][j]), x.sym, side, round(_a1[0] / _risk, 3) if _a1 else None, _a1[1] if _a1 else None, round(_b1[0] / _risk, 3) if _b1 else None, _b1[1] if _b1 else None,
                           round(abs(_nr[0] - ent) / _atrd, 3) if _nr and _atrd == _atrd else None, (1 if (_nr[0] - ent) * side < 0 else -1) if _nr else None, _nr[2] if _nr else None, len(_al)])
            _p = path(a, j, side, ent, sl, tp)
            _lm = {off: limit_sim(a, j, side, ent, sl, tp, at, off) for off in (0.0, 0.1, 0.25)}
            if all(v is not None for v in _lm.values()):
                limrows.append([float(a["open_time"][j]), x.sym, side, round(sp * 100, 3)] + sum(([v["k"], v["out"], round(v["R"], 4), round(v["sp"] * 100, 4)] for v in _lm.values()), []))
            allrows.append((float(a["open_time"][j]), x.sym, side, round(sp * 100, 3), round(at / ent * 100, 3), round(float(x.s), 3), round(-h1[-7][3], 2), round(-h1[-13][3], 2), round(-h1[0][3], 2), round(br24, 2), round(_r, 4), round(abs(tp - ent) / abs(ent - sl), 2), _p["out"], _p["nb"], _p["mfe"], _p["t0.5"], _p["b0.5"], _p["t1.0"], _p["b1.0"], _p["t1.5"], _p["b1.5"], _p["t2.0"], _p["b2.0"], _p["r8"], _p["r16"], _p["r32"], _p["r48"], _p["r96"]))
            cases.append(dict(t=float(a["open_time"][j]), sym=x.sym, side=side, ent=float(ent), sl=float(sl), tp=float(tp), score=round(float(x.s), 3), case=dict(direction="LONG" if side > 0 else "SHORT", stop_pct=round(sp * 100, 2), target_pct=round(abs(tp - ent) / ent * 100, 2), atr15_pct=round(at / ent * 100, 3), model_score=round(float(x.s), 3), market_btc_24h_pct=round(br24, 2), levels_pct_from_entry=lv, h1_last36_ohlc_pct=h1, m15_last32_ohlc_pct=m15), fwd=fwd)); break
    random.seed(11); post = [c for c in cases if c["t"] >= CUT]; pre = [c for c in cases if c["t"] < CUT]
    pick = random.sample(post, min(100, len(post))) + random.sample(pre, min(50, len(pre))); random.shuffle(pick)
    import os; os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/cases.jsonl", "w") as f1, open(f"{OUT}/outcomes.jsonl", "w") as f2:
        for n, c in enumerate(pick, 1):
            f1.write(json.dumps(dict(id=n, **c["case"]), ensure_ascii=False) + "\n")
            f2.write(json.dumps(dict(id=n, t=c["t"], sym=c["sym"], side=c["side"], ent=c["ent"], sl=c["sl"], tp=c["tp"], post_cutoff=c["t"] >= CUT, fwd=c["fwd"])) + "\n")
    pd.DataFrame(allrows, columns=["t", "sym", "side", "stop_pct", "atr15_pct", "score", "ret6h", "ret12h", "ret36h", "btc24h", "r48h_cost10", "tp_R", "out", "nbars", "mfe", "t05", "b05", "t1", "b1", "t15", "b15", "t2", "b2", "r2h", "r4h", "r8h", "r12h", "r24h"]).to_csv(f"{OUT}/all_signals.csv", index=False)
    pd.DataFrame(lvrows, columns=["t", "sym", "side", "ahead_R", "ahead_touches", "back_R", "back_touches", "near_atr", "near_behind", "near_touches", "n_alive"]).to_csv(f"{OUT}/all_levels.csv", index=False)
    cols = ["t", "sym", "side", "stop_pct"] + [f"{n}{o}" for o in ("0", "01", "025") for n in ("k", "out", "R", "sp")]
    pd.DataFrame(limrows, columns=cols).to_csv(f"{OUT}/all_limit.csv", index=False)
    print(f"усього кейсів {len(cases)} (після 01.07.2026: {len(post)}); у вибірці {len(pick)}")
if __name__ == "__main__": main()
