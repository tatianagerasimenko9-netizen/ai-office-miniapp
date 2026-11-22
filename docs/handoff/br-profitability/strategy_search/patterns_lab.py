"""READ-ONLY. «Лабораторія фігур»: усі основні фігури технічного аналізу з нашого детектора (office_bulkowski: голова і плечі пряма/перевернута, висхідний/низхідний/симетричний трикутник, прямокутник, висхідний/спадний клин, прапор, вимпел) на історії 42 монет, H4 і D1.
ДЖЕРЕЛА правил: книга Булковскі (KONSPEKT_UA.md, ядро Булковскі) + уроки TradingView/AcademyFakel зі скриншотів власниці (контекст тренду) + публічні огляди (IG, CMC, forex.com та ін.; ЗОВНІШНЄ). ГІПОТЕЗИ (наші технічні припущення): вхід на відкритті наступної свічки після закриття за межею (фігура «вмикається» лише закриттям, як у детекторі); стоп за ПРОТИЛЕЖНУ межу фігури (дві лінії → нижня/верхня на барі пробою; інакше — екстремум останніх 20 свічок); ціль = measure rule детектора, не менше 3R; утримання H4 60 свічок / D1 30; комісія за круг; SL-першим; один відкритий трейд на (монета, фігура).
Додатково для клинів: торкання ліній (свінг ≤0,5 ATR від лінії), хибний пробій (закриття назад усередину ≤3 свічок) і зворотна угода після хибного пробою. Використання: patterns_lab.py CANDLES_DIR SYMS FEE OUT_PREFIX"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
import numpy as np, pandas as pd
import office_bulkowski as B
CD, SYMS, FEE, OUT = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]), sys.argv[4]
PER = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}; HOLD = {"M15": 96, "H1": 48, "H4": 60, "D1": 30}; LOOK = 80
TFS = os.environ.get("TFS", "H4,D1").split(","); SINCE = float(pd.Timestamp(os.environ.get("SINCE", "2022-01-01")).timestamp())

def bars(sym, per):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // per * per).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close", "volume")}
def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))); return pd.Series(tr).rolling(14).mean().to_numpy()
def walk(h, l, c, i0, side, e, sl, tp, H):
    risk = abs(e - sl)
    for j in range(i0, min(len(c), i0 + H)):
        if (l[j] <= sl) if side > 0 else (h[j] >= sl): return -1.0, "SL", j - i0
        if (h[j] >= tp) if side > 0 else (l[j] <= tp): return side * (tp - e) / risk, "TP", j - i0
    j = min(len(c) - 1, i0 + H - 1); return side * (c[j] - e) / risk, "TIME", j - i0

rows = []; fails = []
for tf in TFS:
    for sym in SYMS:
        b = bars(sym, PER[tf]); o, h, l, c, t = b["open"], b["high"], b["low"], b["close"], b["open_time"]; A = atr14(h, l, c); M200 = pd.Series(c).rolling(200).mean().to_numpy(); n = len(c)
        dicts = [{"open": o[k], "high": h[k], "low": l[k], "close": c[k], "ts": float(t[k])} for k in range(n)]; busy = {}
        for i in range(LOOK, n - 2):
            if t[i] < SINCE or not (A[i] > 0 and M200[i] > 0): continue
            win = dicts[i - LOOK + 1:i + 1]; a = float(A[i]); now = len(win) - 1
            try: res = B.head_shoulders(win, a) + B.triangles_rectangle(win, a) + B.flags(win, a)
            except Exception: continue
            for r in res:
                if not r.get("confirmed") or r.get("confirm_idx") != now: continue
                kind = r["kind"]; side = 1 if r["side"] == "LONG" else -1
                if i < busy.get((kind, tf), 0): continue
                li = r.get("lines_idx") or []
                if len(li) >= 2: sl = li[1][1][1] if side > 0 else li[0][1][1]
                else: sl = float(np.min(l[i - 19:i + 1])) if side > 0 else float(np.max(h[i - 19:i + 1]))
                e = o[i + 1]; risk = (e - sl) * side
                if risk <= 0 or risk / e < 0.0005 or risk / e > 0.25: continue
                tg = r.get("target"); meas = abs(tg - e) if tg is not None and (tg - e) * side > 0 else 0.0
                tp = e + side * max(3 * risk, meas); R, why, held = walk(h, l, c, i + 1, side, e, sl, tp, HOLD[tf]); R -= FEE / (risk / e)
                busy[(kind, tf)] = i + 1 + held + 1
                ctx = "з трендом" if ((side > 0 and c[i] > M200[i]) or (side < 0 and c[i] < M200[i])) else "проти тренду"
                th = tl = -1; fail = -1; rev = np.nan
                if kind in ("rising_wedge", "falling_wedge") and len(li) >= 2:
                    hi, lo = B._sw(win, "high", False)[-5:], B._sw(win, "low", True)[-5:]
                    fh, fl = B._fit(hi), B._fit(lo)
                    if fh and fl:
                        th = sum(1 for (x, y) in hi if abs(y - B._at(fh, x)) <= 0.5 * a); tl = sum(1 for (x, y) in lo if abs(y - B._at(fl, x)) <= 0.5 * a)
                    brk = li[0] if side > 0 else li[1]; (x0, p0), (x1, p1) = brk; slope = (p1 - p0) / (x1 - x0) if x1 != x0 else 0.0
                    fail = 0
                    for k2 in range(1, 4):
                        j = i + k2
                        if j >= n - 2: break
                        lvl = p1 + slope * k2
                        if (side > 0 and c[j] < lvl) or (side < 0 and c[j] > lvl):          # закриття назад усередину клина
                            fail = 1; ex = float(np.max(h[i:j + 1])) if side > 0 else float(np.min(l[i:j + 1])); ee = o[j + 1]; rs = -side
                            rk = (ex - ee) * (-rs) if False else ((ex - ee) if side > 0 else (ee - ex))
                            if rk > 0 and rk / ee >= 0.0005 and rk / ee <= 0.25:
                                tp2 = ee + rs * 3 * rk; R2, w2, h2 = walk(h, l, c, j + 1, rs, ee, ex, tp2, HOLD[tf]); rev = R2 - FEE / (rk / ee)
                            break
                rows.append((tf, sym, kind, side, ctx, float(t[i + 1]), R, why, held, risk / e, int(pd.Timestamp(t[i + 1], unit="s").year), th, tl, fail, rev))
W = pd.DataFrame(rows, columns=["tf", "sym", "kind", "side", "ctx", "ts", "r", "why", "held", "risk_pct", "y", "th", "tl", "fail", "rev_r"]); W["usd"] = 10 * W.r
W.to_csv(OUT + "_trades.csv", index=False)
print(f"ЛАБОРАТОРІЯ ФІГУР: комісія {FEE*100:.2f}% за круг, ризик $10, монет {len(SYMS)}, 2022–2026")
for tf in TFS:
    print(f"\n######## {tf}")
    x = W[W.tf == tf]
    g = x.groupby(["kind", "side"]).agg(n=("usd", "size"), total=("usd", "sum"), mean=("usd", "mean"), win=("usd", lambda v: 100 * (v > 0).mean())).round(1)
    print(g.sort_values("total", ascending=False).to_string())
    for (kd, cx), gg in x.groupby(["kind", "ctx"]):
        print(f"  {kd:24s} {cx:13s}: {len(gg):5d} угод, ${gg.usd.sum():+8.0f}, на угоду ${gg.usd.mean():+.2f}")
print("\n######## КЛИН: нюанси (H4+D1)")
w = W[W.kind.isin(["rising_wedge", "falling_wedge"])].copy()
if len(w):
    w["touch"] = np.where((w.th + w.tl >= 5) & (w[["th", "tl"]].min(axis=1) >= 2) & (w[["th", "tl"]].max(axis=1) >= 3), "≥5 торкань", "<5 торкань")
    for tf in TFS:
        for kd in ("falling_wedge", "rising_wedge"):
            x = w[(w.tf == tf) & (w.kind == kd)]
            if x.empty: continue
            print(f"\n-- {tf} {'спадний (купівля)' if kd == 'falling_wedge' else 'висхідний (продаж)'}: усього {len(x)}, ${x.usd.sum():+.0f}")
            for tc, g in x.groupby("touch"): print(f"   {tc}: {len(g)}, ${g.usd.sum():+.0f}, на угоду ${g.usd.mean():+.2f}")
            for fl, g in x.groupby("fail"): print(f"   хибний пробій (повернулась у клин ≤3 свічок) = {'так' if fl == 1 else 'ні'}: {len(g)} ({100*len(g)/len(x):.0f}%), ${g.usd.sum():+.0f}, на угоду ${g.usd.mean():+.2f}")
            rv = x[x.fail == 1].rev_r.dropna() * 10
            if len(rv): print(f"   ЗВОРОТНА угода після хибного пробою: {len(rv)} угод, ${rv.sum():+.0f}, на угоду ${rv.mean():+.2f}, виграшних {100*(rv>0).mean():.0f}%")
