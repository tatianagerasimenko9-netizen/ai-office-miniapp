"""READ-ONLY. Схема «зверху вниз» з ЩОРІЧНИМ ПЕРЕНАВЧАННЯМ (чесний walk-forward) + проковзування + довірчі інтервали.
Для року Y: модель навчається на роках <= Y-2; поріг сигналу = 97-й перцентиль оцінок моделі на році Y-1 (поза навчанням); угоди року Y відбираються ФІКСОВАНИМ порогом.
Етап 2 як у topdown (M15-підтвердження, стоп M15, ціль = 3R плану H1). Проковзування SLIP (частка ціни, на круг) віднімається як додаткова комісія.
Використання: MODEL=ml_discover2 walkforward.py CANDLES_DIR SYMS COST SLIP"""
import os, sys, importlib
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
SLIP = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
sys.argv = sys.argv[:4]
md = importlib.import_module(os.environ.get("MODEL", "ml_discover2"))
import topdown as td
CD, SYMS, COST = md.CD, md.SYMS, md.COST; DAY = 86400

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    parts = [r for s in SYMS for r in [md.rows_for(s, md.load_h1(s), btc)] if r is not None]
    df = pd.concat(parts).reset_index(drop=True); df["year"] = pd.to_datetime(df.t, unit="s").dt.year
    X = [c for c in df.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    M15 = {s: td.load15(s) for s in SYMS}; AT = {s: td.atr_arr(a["high"], a["low"], a["close"]) for s, a in M15.items()}
    print(f"\nWalk-forward (модель Y обучена на <= Y-2; поріг із Y-1); комісія {COST*100:.2f}% + проковзування {SLIP*100:.2f}% = {100*(COST+SLIP):.2f}% на круг; $ при $10 ризику на угоду")
    print("| рік | навчання | поріг | сигналів H1 | БАЗА H1 R / $ | вхід M15: угод | R / $ | CI95 R (по днях) | сер. стоп M15 |\n|--|--|--|--|--|--|--|--|--|")
    allr = []
    for Y in (2024, 2025, 2026):
        tr = df[df.year <= Y - 2]; va = df[df.year == Y - 1]; te = df[df.year == Y].copy()
        m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
        thr = float(np.quantile(m.predict(va[X]), 0.97)); te["s"] = m.predict(te[X]); sel = md.dedupe(te[te.s >= thr])
        rows = []
        for _, x in sel.iterrows():
            a = M15.get(x.sym); side = int(x.side); T0 = x.t + 3600; i0 = int(np.searchsorted(a["open_time"], T0)); risk_h1 = abs(x.ent - x.sl); tp = x.ent + side * 3 * risk_h1
            for k in range(0, 16):
                j = i0 + k
                if j < 9 or j >= len(a["close"]) - 2: break
                o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
                if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
                at = AT[x.sym][j]
                if not at == at: break
                ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
                if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
                rows.append((td.sim(a, j, side, ent, sl, tp) - (COST + SLIP) / sp, sp, x.t)); break
        base = (sel.r - SLIP / sel.stop_pct)
        if rows:
            rr = np.array([r[0] for r in rows]); dd = {}
            for r_, _, tt in rows: dd.setdefault(int(tt // DAY), []).append(r_)
            lo, hi = md.boot(dd); allr += list(rr)
            print(f"| {Y} | <= {Y-2} | {thr:.3f} | {len(sel)} | {base.mean():+.3f} / {10*base.sum():+,.0f} | {len(rows)} | {rr.mean():+.3f} / {10*rr.sum():+,.0f} | [{lo:+.3f}; {hi:+.3f}] | {100*np.mean([r[1] for r in rows]):.2f}% |")
        else: print(f"| {Y} | <= {Y-2} | {thr:.3f} | {len(sel)} | – | 0 | – | – | – |")
    if allr: print(f"\nВсі три роки разом: угод {len(allr)}, R/угоду {np.mean(allr):+.3f}, $ {10*sum(allr):+,.0f}")
    print("\n##### ПІДСУМОК walkforward завершено")
if __name__ == "__main__": main()
