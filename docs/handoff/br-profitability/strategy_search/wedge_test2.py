"""READ-ONLY. ВЕРСІЯ 2 (суворіша): ≥5 торкань (3 на одній лінії і 2 на другій) і окремо — з обсягами. ЗОВНІШНІ умови (НЕ з матеріалів власниці; з публічних переказів Булковскі та уроку TradingView на скриншоті): ГІПОТЕЗА, у бою не використовувати без окремого дозволу. Клин (Falling/Rising Wedge) на історії: чи працює і як поєднується зі СВІНГом. ДЖЕРЕЛО правила: книга Булковскі (office_worker_library/books/bulkowski_encyclopedia_chart_patterns/KONSPEKT_UA.md §Wedges) + скриншоти власниці (TradingView «Клин»):
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
    g = d.groupby(d.open_time // per * per).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close", "volume")}
def atr14(h, l, c):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])))
    return pd.Series(tr).rolling(14).mean().to_numpy()
def walk(h, l, c, i0, side, e, sl, tp, H):
    risk = abs(e - sl)
    for j in range(i0, min(len(c), i0 + H)):
        if (l[j] <= sl) if side > 0 else (h[j] >= sl): return -1.0, "SL", j - i0
        if (h[j] >= tp) if side > 0 else (l[j] <= tp): return side * (tp - e) / risk, "TP", j - i0
    j = min(len(c) - 1, i0 + H - 1); return side * (c[j] - e) / risk, "TIME", j - i0

def find_wedge(win, a, vols):
    """Клин за правилами джерела (лінії сходяться, обидві в один бік) + ≥5 торкань; пробій закриттям за межею саме на останній свічці. Повертає (kind, side, lines_idx, ok_touch, vol_decl, brk_vol) або None."""
    hi, lo = B._sw(win, "high", False)[-5:], B._sw(win, "low", True)[-5:]
    if len(hi) < 2 or len(lo) < 2: return None
    if max(hi[-1][0], lo[-1][0]) - min(hi[0][0], lo[0][0]) < 8: return None
    fh, fl = B._fit(hi), B._fit(lo)
    if not fh or not fl: return None
    slope_tol = 0.05 * a; x0 = min(hi[0][0], lo[0][0]); sw_ = B._at(fh, x0) - B._at(fl, x0); xe = max(hi[-1][0], lo[-1][0])
    if not (sw_ > (B._at(fh, xe) - B._at(fl, xe)) > 0): return None
    now = len(win) - 1
    if fh[0] > slope_tol and fl[0] > slope_tol and fl[0] > fh[0]: kind, side, line = "rising_wedge", -1, fl; up = False
    elif fh[0] < -slope_tol and fl[0] < -slope_tol and fh[0] < fl[0]: kind, side, line = "falling_wedge", 1, fh; up = True
    else: return None
    cl = float(win[now]["close"]); lv = B._at(line, now)
    if not ((up and cl > lv) or ((not up) and cl < lv)): return None
    prev = float(win[now - 1]["close"]); pl = B._at(line, now - 1)
    if ((up and prev > pl) or ((not up) and prev < pl)): return None          # пробій має відбутися САМЕ на цій свічці
    th = sum(1 for (x, y) in hi if abs(y - B._at(fh, x)) <= 0.5 * a); tl = sum(1 for (x, y) in lo if abs(y - B._at(fl, x)) <= 0.5 * a)      # торкання = свінг у межах 0,5 ATR від лінії (ГІПОТЕЗА допуску)
    ok_touch = th + tl >= 5 and min(th, tl) >= 2 and max(th, tl) >= 3
    f0 = min(hi[0][0], lo[0][0]); seg = vols[f0:xe + 1]; half = max(1, len(seg) // 2)
    vol_decl = len(seg) >= 4 and float(np.mean(seg[half:])) < float(np.mean(seg[:half]))
    brk_vol = len(vols) > 20 and float(vols[now]) > float(np.mean(vols[now - 20:now]))
    return kind, side, [B._ln(fh, x0, now), B._ln(fl, x0, now)], ok_touch, vol_decl, brk_vol

rows_out = []
for tf in ("H4", "D1"):
    for sym in SYMS:
        b = bars(sym, PER[tf]); o, h, l, c, t, vol = b["open"], b["high"], b["low"], b["close"], b["open_time"], b["volume"]; A = atr14(h, l, c); n = len(c)
        dicts = [{"open": o[k], "high": h[k], "low": l[k], "close": c[k], "ts": float(t[k])} for k in range(n)]
        busy = {"base": 0, "touch": 0, "touch_vol": 0}
        for i in range(LOOK, n - 2):
            if not A[i] > 0: continue
            win = dicts[i - LOOK + 1:i + 1]; w = find_wedge(win, float(A[i]), vol[i - LOOK + 1:i + 1])
            if not w: continue
            kind, side, li, ok_touch, vol_decl, brk_vol = w
            up_line, lo_line = li[0][1][1], li[1][1][1]
            e = o[i + 1]; sl = lo_line if side > 0 else up_line; risk = (e - sl) * side
            if risk <= 0 or risk / e < 0.0005 or risk / e > 0.25: continue
            height = abs(B._at(B._fit(B._sw(win, "high", False)[-5:]), 0) - B._at(B._fit(B._sw(win, "low", True)[-5:]), 0)) if False else None
            tp = e + side * 3 * risk                                               # ціль: не менше 3R (висота клина від пробою тут спрощена до 3R: ГІПОТЕЗА)
            R, why, held = walk(h, l, c, i + 1, side, e, sl, tp, HOLD[tf]); R -= FEE / (risk / e)
            for var, cond in (("base", True), ("touch", ok_touch), ("touch_vol", ok_touch and vol_decl and brk_vol)):
                if cond and i >= busy[var]:
                    busy[var] = i + 1 + held + 1
                    rows_out.append((tf, sym, kind + "|" + var, side, float(t[i + 1]), e, sl, tp, R, why, held, risk / e, int(pd.Timestamp(t[i + 1], unit="s").year)))
W = pd.DataFrame(rows_out, columns=["tf", "sym", "kind", "side", "ts", "entry", "sl", "tp", "r", "why", "held", "risk_pct", "y"]); W["usd"] = 10 * W.r
W.to_csv(OUT + "_trades.csv", index=False)
print(f"КЛИН v2 (суворіше): комісія {FEE*100:.2f}% за круг, ризик $10, монет {len(SYMS)}")
W["var"] = W.kind.str.split("|").str[1]; W["kind"] = W.kind.str.split("|").str[0]
for var, nm in (("base", "як було (2+2 торкання, без об'ємів)"), ("touch", "≥5 торкань"), ("touch_vol", "≥5 торкань + об'єми (падають у клині, ростуть на пробої)")):
    for tf in ("H4", "D1"):
        x = W[(W.tf == tf) & (W["var"] == var)]
        if x.empty: print(f"\n== {nm} · {tf}: угод немає"); continue
        print(f"\n== {nm} · {tf}: угод {len(x)}, сума ${x.usd.sum():+.0f}, на угоду ${x.usd.mean():+.2f}, виграшних {100*(x.usd>0).mean():.0f}%, ціль {(x.why=='TP').sum()}, стоп {(x.why=='SL').sum()}, час {(x.why=='TIME').sum()}")
        print("   по роках:", {int(a): round(b) for a, b in x.groupby('y').usd.sum().items()}, "| монет у плюсі:", int((x.groupby('sym').usd.sum() > 0).sum()), "з", x.sym.nunique())
        for kd, g in x.groupby("kind"): print(f"     {'купівля (спадний клин)' if kd == 'falling_wedge' else 'продаж (висхідний клин)'}: {len(g)} угод, ${g.usd.sum():+.0f}, на угоду ${g.usd.mean():+.2f}")
S = pd.read_csv(SWCSV); S["usd"] = 10 * S.r
print(f"\n== ПОЄДНАННЯ зі СВІНГом (його угод {len(S)}, сума ${S.usd.sum():+.0f})")
for var in ("touch", "touch_vol"):
    x = W[(W.tf == "H4") & (W["var"] == var)]
    if x.empty: continue
    wk = {}
    for _, r in x.iterrows(): wk.setdefault((r.sym, int(r.side)), []).append(float(r.ts))
    near = S.apply(lambda r: any(0 <= float(r.ts) - w_ <= 10 * 14400 for w_ in wk.get((r.sym, int(r.side)), [])), axis=1)
    for flag, g in S.groupby(near): print(f"[{var}] СВІНГ {'ПІСЛЯ клина (≤10 діб, той самий бік)' if flag else 'без клина'}: {len(g)}, на угоду ${g.usd.mean():+.2f}, сума ${g.usd.sum():+.0f}")
    print(f"[{var}] СВІНГ + клин H4: ${S.usd.sum():+.0f} + ${x.usd.sum():+.0f} = ${S.usd.sum() + x.usd.sum():+.0f}")
