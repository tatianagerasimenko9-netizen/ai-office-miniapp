"""READ-ONLY. Гіпотеза власниці (приклад ATOM 03.11.2026): стоп вибило, а ціна розвернулась у бік угоди. Скільки таких випадків і чи допомагає (a) ширший стоп, (b) пізніший вхід на ретесті, (c) повторний вхід після стопа.
Ті самі угоди TD-V1 (12 монет, фіксований поріг, вхід M15), $10 ризику, SL-first. Використання: stophunt.py CANDLES_DIR TRAIN COST"""
import sys
import numpy as np, pandas as pd
CD, TRAIN, COST = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = ["x", CD, TRAIN, TRAIN, COST]
import newcoins as nc
md, td, HG = nc.md, nc.td, nc.HistGradientBoostingRegressor
C = float(COST)

def run(a, j, side, ent, sl, tp, hz=192):
    """-> (R до комісії, індекс виходу, 'sl'|'tp'|'time')"""
    h, l, c = a["high"], a["low"], a["close"]; risk = abs(ent - sl)
    for k in range(1, hz + 1):
        q = j + k
        if q >= len(c): break
        if (l[q] <= sl) if side > 0 else (h[q] >= sl): return -1.0, q, "sl"
        if (h[q] >= tp) if side > 0 else (l[q] <= tp): return side * (tp - ent) / risk, q, "tp"
    q = min(j + hz, len(c) - 1); return side * (c[q] - ent) / risk, q, "time"

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(TRAIN.split(","), btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = HG(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy(); z["s"] = m.predict(z[X]); parts.append(md.dedupe(z[z.s >= thr]))
    sel = pd.concat(parts); cache = {}; R = {}; yrs = []; hunt = []; n_sl = 0
    def add(k, v): R.setdefault(k, []).append(v)
    ms = (0.0, 0.25, 0.5, 1.0); fs = (0.25, 0.5, 0.75)
    for _, x in sel.iterrows():
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
            yrs.append(int(x.year))
            # a) ширший стоп (додатково m*ATR M15); R у новому ризику => $10 ризику лишається
            for mm in ms:
                sl2 = sl - side * mm * at; sp2 = abs(ent - sl2) / ent
                if mm and sp2 > 0.05: add(("wide", mm), 0.0); continue
                r, q, kind = run(a, j, side, ent, sl2, tp); add(("wide", mm), r - C / sp2)
                if mm == 0.0 and kind == "sl":
                    n_sl += 1; ok_re = ok_tp = False
                    for z in range(q + 1, min(q + 49, len(c_))):
                        if (h_[z] >= tp) if side > 0 else (l_[z] <= tp): ok_tp = True; break
                    for z in range(q + 1, min(q + 13, len(c_))):
                        if (h_[z] >= ent) if side > 0 else (l_[z] <= ent): ok_re = True; break
                    hunt.append((ok_re, ok_tp))
            # b) вхід на ретесті: ліміт глибше на f*ризик, стоп той самий, діє 16 барів
            risk = abs(ent - sl)
            for f in fs:
                lv = ent - side * f * risk; sp3 = abs(lv - sl) / lv; got = None
                for q in range(j + 1, j + 17):
                    if q >= len(c_) - 2: break
                    if (l_[q] <= lv) if side > 0 else (h_[q] >= lv): got = q; break
                r0, _, _ = run(a, j, side, ent, sl, tp)
                if got is None: add(("retest", f), None); add(("retest_missed", f), r0 - C / sp); continue
                if (l_[got] <= sl) if side > 0 else (h_[got] >= sl): r = -1.0
                else: r, _, _ = run(a, got, side, lv, sl, tp)
                add(("retest", f), r - C / sp3); add(("retest_missed", f), None)
            # c) повторний вхід: після стопа чекаємо закриття назад за початковим входом (до 12 барів), той самий SL/TP
            r, q, kind = run(a, j, side, ent, sl, tp); tot = r - C / sp
            if kind == "sl":
                for z in range(q + 1, min(q + 13, len(c_) - 2)):
                    if (c_[z] > ent) if side > 0 else (c_[z] < ent):
                        r2, _, _ = run(a, z, side, c_[z], sl, tp)
                        sp4 = abs(c_[z] - sl) / c_[z]
                        if (c_[z] - sl) * side > 0 and sp4 <= 0.05: tot += r2 - C / sp4
                        break
            add(("reentry", 0), tot)
            break
    yrs = np.array(yrs); print(f"Угод {len(yrs)}; комісія {C*100:.2f}%; $10 ризику")
    h = np.array(hunt); print(f"\nПісля стопа ({n_sl} угод): ціна повернулась до початкового входу за 3 год: {100*h[:,0].mean():.0f}%; дійшла до цілі за 48 год: {100*h[:,1].mean():.0f}%")
    print("(для порівняння: усі угоди разом доходять до цілі у ~18%)\n")
    print("| варіант | угод | усього $ | 2024 | 2025 | 2026 | плюсових |\n|--|--|--|--|--|--|--|")
    def row(nm, key):
        v = [(y, r) for y, r in zip(yrs, R[key]) if r is not None]
        if not v: return
        r = np.array([z[1] for z in v]); yy = np.array([z[0] for z in v])
        print(f"| {nm} | {len(r)} | {10*r.sum():+,.0f} | " + " | ".join(f"{10*r[yy==y].sum():+,.0f}" for y in (2024, 2025, 2026)) + f" | {100*(r>0).mean():.0f}% |")
    row("0. Як зараз", ("wide", 0.0))
    for mm in ms[1:]: row(f"a. Стоп ширший на {mm} ATR(M15), ризик $10 лишається", ("wide", mm))
    for f in fs:
        row(f"b. Вхід лімітом глибше на {int(f*100)}% відстані до стопа (виконані)", ("retest", f))
        row(f"   пропущені угоди (не виконались), як би вони закрились зараз", ("retest_missed", f))
    row("c. Як зараз + повторний вхід після стопа (якщо ціна закрилась назад за входом)", ("reentry", 0))
    print("\n##### ПІДСУМОК stophunt завершено")
if __name__ == "__main__": main()
