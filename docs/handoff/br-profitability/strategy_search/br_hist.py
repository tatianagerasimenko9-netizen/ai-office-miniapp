"""READ-ONLY. B&R НА ДОВГІЙ ІСТОРІЇ, «як є» і «НАВПАКИ» (25.11.2026, прохання власниці: «він дає купу сигналів, але вони йдуть в іншу сторону — зробити навпаки»).
Правила записані ДО запуску (ГІПОТЕЗА / OUR_IMPLEMENTATION): той самий детектор, що в Офісі (office_br.detect: _follow/_targets/HYP), лише пошук пивотів прискорено (той самий результат: пивот видно з бару p+k, рівень не старіший за lookback).
Вхід: лімітна заявка на ціні входу сигналу; виконано, коли наступні бари M15 торкнулися ціни (до 24 барів; якщо раніше торкнуло ціль 1 — скасовано, як в Офісі).
Після входу, 48 год (192 бари), стоп-першим у спірному барі (для ОБОХ напрямів):
  «як є»   : стоп = m × відстань до стопа сигналу, ціль = k × цей ризик;
  «навпаки»: протилежний напрям із тієї ж ціни, стоп = m × та сама відстань по інший бік, ціль = k × ризик.
  m ∈ {1,2,3}, k ∈ {1,2,3}. Тайм-аут → за ціною закриття. Комісія за круг: 0,10% (ринкові) і 0,04% (лімітні) — обидві показано. Ризик $10 на угоду.
Розрізи (усі показано, нічого не відбирається): роки; розмір стопа; за трендом/проти (сторона MA200 на H4); спокійна монета (ATR(H4,14)/ціна < 2,3%); година UTC.
Використання: br_hist.py CANDLES_DIR SYMS OUT_CSV"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
from office_br import detect
CD, SYMS, OUT = sys.argv[1], sys.argv[2].split(","), sys.argv[3]
cfg = dict(detect.HYP); K = cfg["pivot_k"]; LB = cfg["lookback"]; MS = (1, 2, 3); KS = (1, 2, 3); HOR = 192; WAIT = 24
def run(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    t, o, h, l, c = (d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
    g = d.groupby(d.open_time // 14400 * 14400).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = g.close.shift(1); tr = np.maximum(g.high - g.low, np.maximum((g.high - pc).abs(), (g.low - pc).abs()))
    g["ma"] = g.close.rolling(200).mean(); g["atrp"] = tr.rolling(14).mean() / g.close
    g = g.shift(1)                                              # лише ЗАКРИТІ бари H4
    key = (t // 14400 * 14400); ma = g.ma.reindex(key).to_numpy(); atrp = g.atrp.reindex(key).to_numpy()
    PH = np.zeros(n, bool); PL = np.zeros(n, bool)
    for p in range(K, n - K):
        if all(h[p] > h[p - j] and h[p] >= h[p + j] for j in range(1, K + 1)): PH[p] = True
        if all(l[p] < l[p - j] and l[p] <= l[p + j] for j in range(1, K + 1)): PL[p] = True
    used = set(); rows = []
    for i in range(max(K * 2 + cfg["atr_n"], LB + 1), n - 1):
        lo = i - LB; hi = i - K
        cand = [("H", p, h[p]) for p in range(lo, hi + 1) if PH[p]] + [("L", p, l[p]) for p in range(lo, hi + 1) if PL[p]]
        hit = [(ty, p, L) for ty, p, L in cand if (ty, p) not in used and ((ty == "H" and c[i] > L >= c[i - 1]) or (ty == "L" and c[i] < L <= c[i - 1]))]
        if not hit: continue
        piv = sorted([{"i": p, "p": float(L), "type": ty} for ty, p, L in cand], key=lambda x: x["i"])
        for ty, p, L in hit:
            used.add((ty, p))
            if any((c[j] > L) if ty == "H" else (c[j] < L) for j in range(p + 1, i)): continue
            dr = "LONG" if ty == "H" else "SHORT"
            res = detect._follow(dr, L, i, t, o, h, l, c, cfg, piv)
            if not res: continue
            q = res["confirm_i"]; e = res["entry"]; risk = res["risk"]; sg = 1 if dr == "LONG" else -1; t1 = res["targets"][0]["p"] if res["targets"] else e + sg * risk
            f = None
            for j in range(q + 1, min(n, q + 1 + WAIT)):
                if l[j] <= e <= h[j]: f = j; break
                if (h[j] >= t1) if sg > 0 else (l[j] <= t1): break
            if f is None or f + HOR >= n: continue
            H_, L_ = h[f:f + HOR], l[f:f + HOR]; last = c[f + HOR - 1]
            row = {"sym": sym, "ts": t[q], "side": sg, "stop_pct": 100 * risk / e, "trend": int(sg * (c[q] - ma[q]) > 0) if ma[q] > 0 else -1, "calm": int(atrp[q] < 0.023) if atrp[q] > 0 else -1}
            for m in MS:
                for way, s2 in (("o", sg), ("r", -sg)):
                    R = m * risk; slp = e - s2 * R
                    hs = (L_ <= slp) if s2 > 0 else (H_ >= slp); isl = int(np.argmax(hs)) if hs.any() else HOR + 1
                    for k in KS:
                        tp = e + s2 * k * R; ht = (H_ >= tp) if s2 > 0 else (L_ <= tp); itp = int(np.argmax(ht)) if ht.any() else HOR + 1
                        row[f"{way}{m}_{k}"] = -1.0 if isl <= itp and isl <= HOR else (float(k) if itp <= HOR else s2 * (last - e) / R)
            rows.append(row)
    return rows
allr = []
for s in SYMS:
    if os.path.exists(f"{CD}/{s}/15m.csv"): r = run(s); allr += r; print(s, len(r), flush=True)
W = pd.DataFrame(allr); W["y"] = pd.to_datetime(W.ts, unit="s").dt.year; W["hour"] = pd.to_datetime(W.ts, unit="s").dt.hour; W.to_csv(OUT, index=False)
days = (W.ts.max() - W.ts.min()) / 86400
print(f"\nB&R НА ІСТОРІЇ: {len(W)} входів, монет {W.sym.nunique()}, {pd.Timestamp(W.ts.min(), unit='s'):%Y-%m-%d} — {pd.Timestamp(W.ts.max(), unit='s'):%Y-%m-%d}; медіанний стоп {W.stop_pct.median():.2f}%; ризик $10; у дужках — на одну угоду")
def cell(g, col, fee, m): x = 10 * (g[col] - fee / (m * g.stop_pct)); return f"${x.sum():+9.0f} ({x.mean():+.2f})"
def table(g, title):
    print(f"\n== {title}: n={len(g)}")
    for m in MS:
        for k in KS:
            py = lambda way, fee: ", ".join(f"{y}:{10*(a[f'{way}{m}_{k}']-fee/(m*a.stop_pct)).sum():+.0f}" for y, a in g.groupby("y"))
            print(f"  стоп×{m} ціль {k}R | ЯК Є: без комісії {cell(g, f'o{m}_{k}', 0, m)}, 0,04% {cell(g, f'o{m}_{k}', 0.04, m)}, 0,10% {cell(g, f'o{m}_{k}', 0.10, m)} | НАВПАКИ: без комісії {cell(g, f'r{m}_{k}', 0, m)}, 0,04% {cell(g, f'r{m}_{k}', 0.04, m)}, 0,10% {cell(g, f'r{m}_{k}', 0.10, m)}")
            print(f"      по роках 0,04%: як є [{py('o', 0.04)}] | навпаки [{py('r', 0.04)}]")
table(W, "УСІ СИГНАЛИ")
for lab, g in (("за трендом (сторона MA200 H4)", W[W.trend == 1]), ("проти тренду", W[W.trend == 0]), ("спокійна монета", W[W.calm == 1]), ("неспокійна монета", W[W.calm == 0]), ("LONG", W[W.side > 0]), ("SHORT", W[W.side < 0])): table(g, lab)
W["bk"] = pd.cut(W.stop_pct, [0, 0.3, 0.5, 0.8, 1.2, 2, 99])
for b, g in W.groupby("bk", observed=True): table(g, f"стоп {b}%")
print("\n== години UTC (стоп×1 ціль 2R, комісія 0,04%): як є / навпаки, $ на угоду; n")
for hh, g in W.groupby("hour"):
    a = 10 * (g.o1_2 - 0.04 / g.stop_pct); b = 10 * (g.r1_2 - 0.04 / g.stop_pct); print(f"   {hh:02d}: {a.mean():+.2f} / {b.mean():+.2f}; n={len(g)}")
