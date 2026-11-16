"""READ-ONLY. B&R (break&retest M15): що можна поліпшити САМЕ для нього? (1) ознаки сигналу на момент картки; (2) сітка стопів/цілей за шляхом ціни: стоп = m × поточна відстань до стопа, ціль = k × новий ризик, 48 год, SL-першим (валовий R, комісію додаємо в аналізі).
Використання: br_study.py CANDLES_DIR BR_SIGNALS_CSV BR_EXTRA_CSV OUT_CSV"""
import sys, numpy as np, pandas as pd
sys.path.insert(0, __file__.rsplit("/", 1)[0]); import d1lv
CD, SIG, EXT, OUT = sys.argv[1:5]
S = pd.read_csv(SIG); S = S[S.ENTRY.notna()].merge(pd.read_csv(EXT), on="seq", how="left")
M = {}; LV = {}
def load(sym):
    if sym in M: return
    d = pd.read_csv(f"{CD}/{sym}USDT/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    a = {k: d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}; M[sym] = a
    pc = np.r_[a["close"][0], a["close"][:-1]]; tr = np.maximum(a["high"] - a["low"], np.maximum(abs(a["high"] - pc), abs(a["low"] - pc))); a["atr"] = pd.Series(tr).rolling(14).mean().to_numpy()
    h = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); a["h1"] = h
    LV[sym] = {per: (d1lv.build(a, per), None) for per in (86400, 14400, 3600)}
    for per in LV[sym]: D = LV[sym][per][0]; LV[sym][per] = (D, d1lv.levels(D, life=d1lv.LIFE[per]))
for s in list(S.sym.unique()) + ["BTC"]: load(s)
rows = []
for r in S.itertuples():
    try:
        a = M[r.sym]; side = int(r.side); ent = float(r.entry); sl = float(r.sl); risk = abs(ent - sl); ts = float(r.ts)
        j = int(np.searchsorted(a["open_time"], ts // 900 * 900)); atr = a["atr"][j - 1] if j > 15 else np.nan
        h1 = a["h1"]; cut = ts // 3600 * 3600; k = int(np.searchsorted(h1.open_time.to_numpy(float), cut)); c = h1.close.to_numpy(float)
        bt = M["BTC"]["h1"]; kb = int(np.searchsorted(bt.open_time.to_numpy(float), cut)); bc = bt.close.to_numpy(float)
        f = dict(seq=r.seq, sym=r.sym, side=side, ts=ts, stop_pct=risk / ent * 100, atr15_pct=atr / ent * 100 if atr == atr else np.nan, stop_atr=risk / atr if atr == atr else np.nan,
                 ret6=(ent / c[k - 6] - 1) * 100 if k > 40 else np.nan, ret12=(ent / c[k - 12] - 1) * 100 if k > 40 else np.nan, ret36=(ent / c[k - 35] - 1) * 100 if k > 40 else np.nan,
                 btc24=(bc[kb - 1] / bc[kb - 25] - 1) * 100 if kb > 30 else np.nan, hour=int(ts // 3600 % 24), dow=int(ts // 86400 % 7),
                 lvl_stops=abs(ent - float(r.level)) / risk if pd.notna(r.level) else np.nan, rt_gap=(float(r.retest_ts) - float(r.break_ts)) / 900 if pd.notna(r.retest_ts) else np.nan, R1=r.R1 if hasattr(r, "R1") else np.nan)
        for per, nm in ((86400, "d1"), (14400, "h4"), (3600, "h1")):
            D, Ls = LV[r.sym][per]; di = int(np.searchsorted(D["u"], int(ts // per))); atrd = D["atr"][di] if di < len(D["atr"]) else np.nan
            al = [(L["p"], d1lv.state(L, di, d1lv.LIFE[per])) for L in Ls]; al = [(p, kk) for p, kk in al if kk is not None]
            ah = [(abs(p - ent), kk) for p, kk in al if (p - ent) * side > 0.0005 * ent]; bk = [(abs(p - ent), kk) for p, kk in al if (p - ent) * side < -0.0005 * ent]
            a1 = min(ah) if ah else None; b1 = min(bk) if bk else None; nr = min(al, key=lambda z: abs(z[0] - ent)) if al else None
            f[f"ahead_R_{nm}"] = a1[0] / risk if a1 else np.nan; f[f"ahead_t_{nm}"] = a1[1] if a1 else np.nan; f[f"back_R_{nm}"] = b1[0] / risk if b1 else np.nan; f[f"back_t_{nm}"] = b1[1] if b1 else np.nan
            f[f"near_atr_{nm}"] = abs(nr[0] - ent) / atrd if nr and atrd == atrd else np.nan; f[f"near_behind_{nm}"] = (1 if (nr[0] - ent) * side < 0 else -1) if nr else np.nan
        # сітка стопів/цілей: після бару входу
        e0 = int(np.searchsorted(a["open_time"], float(r.ENTRY), side="right"))
        for m in (1.0, 1.5, 2.0, 3.0):
            rk = m * risk; slm = ent - side * rk
            res = {kk: None for kk in (1, 2, 3, 4)}
            for kk in (1, 2, 3, 4):
                tp = ent + side * kk * rk; out = None
                for q in range(e0, min(e0 + 192, len(a["close"]))):
                    hs = (a["low"][q] <= slm) if side > 0 else (a["high"][q] >= slm); ht = (a["high"][q] >= tp) if side > 0 else (a["low"][q] <= tp)
                    if hs: out = -1.0; break
                    if ht: out = float(kk); break
                if out is None and e0 + 191 < len(a["close"]): out = side * (a["close"][e0 + 191] - ent) / rk
                f[f"g{m}_{kk}"] = out
            f[f"sp{m}"] = rk / ent * 100
        rows.append(f)
    except Exception as e:
        print("помилка", r.seq, type(e).__name__, e)
pd.DataFrame(rows).to_csv(OUT, index=False); print("готово", len(rows))
