"""READ-ONLY. Готує ОБЕЗЛИЧЕНІ кейси сигналів TD-V1 для «сліпої» оцінки помічником (LLM) і файл результатів (окремо, помічник його не бачить).
Обезличення: без дати й назви інструмента, ціни у % від входу. Вибірка: 100 кейсів ПІСЛЯ 01.07.2026 (поза знанням моделі до червня 2026) + 50 раніше.
Використання: llmcases.py CANDLES_DIR TRAIN_SYMS NEW_SYMS OUT_DIR"""
import sys, json, random
import numpy as np, pandas as pd
CD, TRAIN, NEW, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.argv = ["x", CD, TRAIN, NEW, "0.001"]
import newcoins as nc
md, td = nc.md, nc.td
CUT = pd.Timestamp("2026-07-01", tz="UTC").timestamp()

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
    sel = pd.concat(parts); cases = []; cache = {}; H = {}; allrows = []
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
            allrows.append((float(a["open_time"][j]), x.sym, side, round(sp * 100, 3), round(at / ent * 100, 3), round(float(x.s), 3), round(-h1[-7][3], 2), round(-h1[-13][3], 2), round(-h1[0][3], 2), round(br24, 2), round(_r, 4)))
            cases.append(dict(t=float(a["open_time"][j]), sym=x.sym, side=side, ent=float(ent), sl=float(sl), tp=float(tp), score=round(float(x.s), 3), case=dict(direction="LONG" if side > 0 else "SHORT", stop_pct=round(sp * 100, 2), target_pct=round(abs(tp - ent) / ent * 100, 2), atr15_pct=round(at / ent * 100, 3), model_score=round(float(x.s), 3), market_btc_24h_pct=round(br24, 2), levels_pct_from_entry=lv, h1_last36_ohlc_pct=h1, m15_last32_ohlc_pct=m15), fwd=fwd)); break
    random.seed(11); post = [c for c in cases if c["t"] >= CUT]; pre = [c for c in cases if c["t"] < CUT]
    pick = random.sample(post, min(100, len(post))) + random.sample(pre, min(50, len(pre))); random.shuffle(pick)
    import os; os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/cases.jsonl", "w") as f1, open(f"{OUT}/outcomes.jsonl", "w") as f2:
        for n, c in enumerate(pick, 1):
            f1.write(json.dumps(dict(id=n, **c["case"]), ensure_ascii=False) + "\n")
            f2.write(json.dumps(dict(id=n, t=c["t"], sym=c["sym"], side=c["side"], ent=c["ent"], sl=c["sl"], tp=c["tp"], post_cutoff=c["t"] >= CUT, fwd=c["fwd"])) + "\n")
    pd.DataFrame(allrows, columns=["t", "sym", "side", "stop_pct", "atr15_pct", "score", "ret6h", "ret12h", "ret36h", "btc24h", "r48h_cost10"]).to_csv(f"{OUT}/all_signals.csv", index=False)
    print(f"усього кейсів {len(cases)} (після 01.07.2026: {len(post)}); у вибірці {len(pick)}")
if __name__ == "__main__": main()
