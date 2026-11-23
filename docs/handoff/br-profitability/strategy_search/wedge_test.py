"""READ-ONLY. Клин (Falling/Rising Wedge) на історії: чи працює і як поєднується зі СВІНГом. ДЖЕРЕЛО правила: книга Булковскі (office_worker_library/books/bulkowski_encyclopedia_chart_patterns/KONSPEKT_UA.md §Wedges) + скриншоти власниці (TradingView «Клин»):
спадний клин — обидві лінії вниз і сходяться, пробій угору; висхідний — обидві вгору і сходяться, пробій униз; вхід лише після ЗАКРИТТЯ за межею; стоп за протилежну межу клина; ціль — висота фігури від пробою, не менше 3R (ядро Булковскі).
Детектор — існуючий office_bulkowski.triangles_rectangle (допуски від ATR, свінги по 2 свічки, МНК-лінії) — OUR_IMPLEMENTATION. ГІПОТЕЗА (технічні припущення, не з джерела): вхід на відкритті наступної свічки після закриття пробою; утримання до 10 діб (H4: 60 свічок) / 30 діб (D1); комісія 0,10% за круг; SL-першим; ризик $10; один відкритий клин на монету.
Використання: wedge_test.py CANDLES_DIR SYMS FEE SWING_TRADES_CSV OUT_PREFIX"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
import numpy as np, pandas as pd
import office_bulkowski as B
CD, SYMS, FEE, SWCSV, OUT = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]), sys.argv[4], sys.argv[5]
PER = {"H4": 14400, "D1": 86400}; HOLD = {"H4": 60, "D1": 30}; LOOK = 80

def bars(sym, per):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // per * per).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}
def atr14(h, l, c):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])))
    return pd.Series(tr).rolling(14).mean().to_numpy()
def walk(h, l, c, i0, side, e, sl, tp, H):
    risk = abs(e - sl)
    for j in range(i0, min(len(c), i0 + H)):
        if (l[j] <= sl) if side > 0 else (h[j] >= sl): return -1.0, "SL", j - i0
        if (h[j] >= tp) if side > 0 else (l[j] <= tp): return side * (tp - e) / risk, "TP", j - i0
    j = min(len(c) - 1, i0 + H - 1); return side * (c[j] - e) / risk, "TIME", j - i0

rows_out = []
for tf in ("H4", "D1"):
    for sym in SYMS:
        b = bars(sym, PER[tf]); o, h, l, c, t = b["open"], b["high"], b["low"], b["close"], b["open_time"]; A = atr14(h, l, c); n = len(c); busy = 0
        dicts = [{"open": o[k], "high": h[k], "low": l[k], "close": c[k], "ts": float(t[k])} for k in range(n)]
        for i in range(LOOK, n - 2):
            if i < busy or not A[i] > 0: continue
            win = dicts[i - LOOK + 1:i + 1]
            res = [r for r in B.triangles_rectangle(win, float(A[i])) if r["kind"] in ("rising_wedge", "falling_wedge") and r["confirmed"] and r.get("confirm_idx") == len(win) - 1]
            if not res: continue
            r = res[0]; side = 1 if r["side"] == "LONG" else -1; li = r.get("lines_idx") or []
            if len(li) < 2: continue
            up_line, lo_line = li[0][1][1], li[1][1][1]                      # межі на барі пробою
            e = o[i + 1]; sl = lo_line if side > 0 else up_line              # стоп за ПРОТИЛЕЖНУ межу
            risk = (e - sl) * side
            if risk <= 0 or risk / e < 0.0005 or risk / e > 0.25: continue
            tgt = r["target"]; tp = e + side * max(abs(tgt - e) if tgt is not None and (tgt - e) * side > 0 else 0, 3 * risk)    # висота фігури, не менше 3R
            R, why, held = walk(h, l, c, i + 1, side, e, sl, tp, HOLD[tf])
            R -= FEE / (risk / e); busy = i + 1 + held + 1
            rows_out.append((tf, sym, r["kind"], side, float(t[i + 1]), e, sl, tp, R, why, held, risk / e, int(pd.Timestamp(t[i + 1], unit="s").year)))
W = pd.DataFrame(rows_out, columns=["tf", "sym", "kind", "side", "ts", "entry", "sl", "tp", "r", "why", "held", "risk_pct", "y"]); W["usd"] = 10 * W.r
W.to_csv(OUT + "_trades.csv", index=False)
print(f"КЛИН: комісія {FEE*100:.2f}% за круг, ризик $10, монет {len(SYMS)}")
for tf in ("H4", "D1"):
    x = W[W.tf == tf]
    if x.empty: print(f"{tf}: угод немає"); continue
    print(f"\n== {tf}: угод {len(x)}, сума ${x.usd.sum():+.0f}, на угоду ${x.usd.mean():+.2f}, виграшних {100*(x.usd>0).mean():.0f}%, ціль {(x.why=='TP').sum()}, стоп {(x.why=='SL').sum()}, час {(x.why=='TIME').sum()}")
    print("по роках:", {int(k): round(v) for k, v in x.groupby('y').usd.sum().items()}, "| монет у плюсі:", int((x.groupby('sym').usd.sum() > 0).sum()), "з", x.sym.nunique())
    for k, g in x.groupby("kind"): print(f"  {k}: {len(g)} угод, ${g.usd.sum():+.0f}, на угоду ${g.usd.mean():+.2f}")
    for s, g in x.groupby("side"): print(f"  {'LONG' if s > 0 else 'SHORT'}: {len(g)}, ${g.usd.sum():+.0f}")
# поєднання зі СВІНГом (його угоди з файлу durations_sw_60.csv: tf,sig,exit,sym,y,r,ts,side,risk_pct,hold_bars,why)
S = pd.read_csv(SWCSV); S["usd"] = 10 * S.r
print(f"\n== ПОЄДНАННЯ зі СВІНГом (угод СВІНГу {len(S)}, сума ${S.usd.sum():+.0f})")
x = W[W.tf == "H4"]
if not x.empty:
    wk = {}
    for _, r in x.iterrows(): wk.setdefault((r.sym, int(r.side)), []).append(float(r.ts))
    def near(r, win=10 * 14400):
        return any(0 <= float(r.ts) - w <= win for w in wk.get((r.sym, int(r.side)), []))
    S["wedge_before"] = S.apply(near, axis=1)
    for flag, g in S.groupby("wedge_before"): print(f"СВІНГ-угоди {'ПІСЛЯ клина в той самий бік (≤10 діб)' if flag else 'без клина перед ними'}: {len(g)}, на угоду ${g.usd.mean():+.2f}, сума ${g.usd.sum():+.0f}, виграшних {100*(g.usd>0).mean():.0f}%")
    both = x.usd.sum() + S.usd.sum(); print(f"Просто додати клин H4 до СВІНГу: ${S.usd.sum():+.0f} + ${x.usd.sum():+.0f} = ${both:+.0f}")
