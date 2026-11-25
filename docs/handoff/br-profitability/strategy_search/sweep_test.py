"""READ-ONLY. «ЗБІР СТОПІВ І ПОВЕРНЕННЯ» (25.11.2026, згода власниці «так, прожени»). Ідея з теорії ігор: за очевидним рівнем стоять чужі стопи; ціна заходить за рівень, збирає їх і повертається.
ПРАВИЛО ЗАПИСАНЕ ДО ЗАПУСКУ (ГІПОТЕЗА / OUR_IMPLEMENTATION; назва «sweep / SFP» — ЗОВНІШНЄ, числа наші й не підбирались):
 Рівень  : підтверджений свінг-мінімум/максимум (екстремум серед 3 барів з обох боків, як у детекторі B&R), не старший за 96 барів, після нього ЖОДЕН бар не закривався за рівнем.
 Сигнал  : бар проколов рівень тінню (low < рівень-мінімум) і ЗАКРИВСЯ назад (close > рівень) → LONG на закритті. Дзеркально для максимуму → SHORT. Якщо за бар зібрано кілька рівнів — один сигнал.
 Стоп    : за екстремум цього бару ∓ 0,10 ATR14. Цілі 1R / 2R / 3R (усі показано). Утримання H4 60 барів, H1 96 барів. Шлях ціни після входу перевіряється на 15-хвилинних свічках (стоп-першим лише в спірній 15-хвилинці) — щоб великий бар не давав хибних стопів. Комісія 0,10% і 0,04% за круг. Ризик $10.
 КОНТРОЛЬ («натовп»): на тому самому рівні бар ЗАКРИВСЯ за рівнем (пробій) → угода в бік пробою, стоп за протилежний край бару ∓ 0,10 ATR. Якщо «збір стопів» кращий за «пробій» — ідея має сенс.
 Розрізи : за трендом / проти (сторона MA200 того ж ТФ), спокійна монета (ATR(H4,14)/ціна < 2,3%), LONG / SHORT, роки. Нічого не відбирається.
Використання: sweep_test.py CANDLES_DIR SYMS OUT_PREFIX"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, OUT = sys.argv[1], sys.argv[2].split(","), sys.argv[3]
K = 3; LB = 96; TFS = {"H4": (14400, 60), "H1": (3600, 96)}; KS = (1, 2, 3)
rows = []
for sym in SYMS:
    p = f"{CD}/{sym}/15m.csv"
    if not os.path.exists(p): continue
    d0 = pd.read_csv(p).drop_duplicates("open_time").sort_values("open_time")
    t15, h15, l15, c15 = (d0[k].to_numpy(float) for k in ("open_time", "high", "low", "close"))
    g4 = d0.groupby(d0.open_time // 14400 * 14400).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = g4.close.shift(1); atrp4 = (np.maximum(g4.high - g4.low, np.maximum((g4.high - pc).abs(), (g4.low - pc).abs())).rolling(14).mean() / g4.close).shift(1)
    for tf, (per, HOR) in TFS.items():
        d = d0.groupby(d0.open_time // per * per).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
        t, o, h, l, c = (d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
        pcl = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pcl), abs(l - pcl)))).rolling(14).mean().to_numpy(); M = pd.Series(c).rolling(200).mean().to_numpy()
        calm = atrp4.reindex(t // 14400 * 14400).to_numpy()
        PH = np.zeros(n, bool); PL = np.zeros(n, bool)
        for q in range(K, n - K):
            if all(h[q] > h[q - j] and h[q] >= h[q + j] for j in range(1, K + 1)): PH[q] = True
            if all(l[q] < l[q - j] and l[q] <= l[q + j] for j in range(1, K + 1)): PL[q] = True
        liveL, liveH = [], []                                  # ще не пробиті закриттям рівні: (індекс, ціна)
        N15 = HOR * per // 900
        for i in range(220, n - HOR - 1):
            q = i - K
            if PL[q]: liveL.append((q, l[q]))
            if PH[q]: liveH.append((q, h[q]))
            liveL = [x for x in liveL if x[0] >= i - LB]; liveH = [x for x in liveH if x[0] >= i - LB]
            if not A[i] > 0 or not M[i] > 0: continue
            ev = []
            swL = [x for x in liveL if l[i] < x[1] < c[i]]; brL = [x for x in liveL if c[i] < x[1]]
            swH = [x for x in liveH if h[i] > x[1] > c[i]]; brH = [x for x in liveH if c[i] > x[1]]
            if swL: ev.append(("sweep", 1, l[i] - 0.1 * A[i]))
            if swH: ev.append(("sweep", -1, h[i] + 0.1 * A[i]))
            if brL: ev.append(("break", -1, h[i] + 0.1 * A[i]))
            if brH: ev.append(("break", 1, l[i] - 0.1 * A[i]))
            liveL = [x for x in liveL if not c[i] < x[1]]; liveH = [x for x in liveH if not c[i] > x[1]]      # закриття за рівнем гасить рівень
            for kind, s, sl in ev:
                e = c[i]; R = (e - sl) * s
                if R <= 0 or not 0.0005 <= R / e <= 0.25: continue
                j0 = int(np.searchsorted(t15, t[i] + per)); H_, L_ = h15[j0:j0 + N15], l15[j0:j0 + N15]
                if len(H_) < N15: continue
                last = c15[j0 + N15 - 1]; HORX = N15
                hs = (L_ <= sl) if s > 0 else (H_ >= sl); isl = int(np.argmax(hs)) if hs.any() else HORX + 1
                row = {"tf": tf, "kind": kind, "sym": sym, "ts": t[i], "side": s, "stop_pct": 100 * R / e, "trend": int(s * (c[i] - M[i]) > 0), "calm": int(calm[i] < 0.023) if calm[i] > 0 else -1}
                for k in KS:
                    tp = e + s * k * R; ht = (H_ >= tp) if s > 0 else (L_ <= tp); itp = int(np.argmax(ht)) if ht.any() else HORX + 1
                    row[f"r{k}"] = -1.0 if isl <= itp and isl <= HORX else (float(k) if itp <= HORX else s * (last - e) / R)
                rows.append(row)
    print(sym, len(rows), flush=True)
W = pd.DataFrame(rows); W["y"] = pd.to_datetime(W.ts, unit="s").dt.year; W.to_csv(OUT + "_trades.csv", index=False)
print(f"\nЗБІР СТОПІВ І ПОВЕРНЕННЯ проти ПРОБОЮ: монет {W.sym.nunique()}, {pd.Timestamp(W.ts.min(), unit='s'):%Y-%m-%d} — {pd.Timestamp(W.ts.max(), unit='s'):%Y-%m-%d}; ризик $10; формат: $ на угоду (сума) при комісії 0,10% | 0,04%; роки — сума при 0,10%")
def table(g, title):
    if len(g) < 50: return
    print(f"  {title}: n={len(g)}, медіанний стоп {g.stop_pct.median():.2f}%")
    for k in KS:
        a = 10 * (g[f"r{k}"] - 0.10 / g.stop_pct); b = 10 * (g[f"r{k}"] - 0.04 / g.stop_pct)
        py = ", ".join(f"{y}:{v:+.0f}" for y, v in a.groupby(g.y).sum().items())
        print(f"     ціль {k}R: {a.mean():+.2f} (${a.sum():+.0f}) | {b.mean():+.2f} (${b.sum():+.0f}); виграшних {100*(g[f'r{k}']>0).mean():.0f}%; роки [{py}]")
for tf in TFS:
    for kind, lab in (("sweep", "ЗБІР СТОПІВ І ПОВЕРНЕННЯ"), ("break", "КОНТРОЛЬ: ПРОБІЙ («натовп»)")):
        g = W[(W.tf == tf) & (W.kind == kind)]; print(f"\n######## {tf} · {lab}")
        table(g, "усі"); table(g[g.trend == 1], "за трендом"); table(g[g.trend == 0], "проти тренду"); table(g[g.calm == 1], "спокійна монета"); table(g[(g.calm == 1) & (g.trend == 1)], "спокійна + за трендом"); table(g[g.side > 0], "LONG"); table(g[g.side < 0], "SHORT")
