"""READ-ONLY. ДИВЕРГЕНЦІЇ RSI на історії (25.11.2026, прохання власниці: «перевіряємо на історії дивергенції»). Означення — ЗОВНІШНЄ (класичний теханаліз: звичайна і прихована, бичача і ведмежа); числа — наші, записані ДО запуску (ГІПОТЕЗА), не підбирались:
 RSI(14) на закриттях H4. Пивот = мінімум/максимум серед 5 барів з обох боків (видно лише через 5 барів — без заглядання вперед). Порівнюємо з ПОПЕРЕДНІМ пивотом того ж типу не далі 60 барів.
 Звичайна бичача  (RB): ціна нижчий мінімум, RSI вищий мінімум → LONG.   Звичайна ведмежа (RS): ціна вищий максимум, RSI нижчий максимум → SHORT.
 Прихована бичача (HB): ціна вищий мінімум, RSI нижчий мінімум → LONG.   Прихована ведмежа (HS): ціна нижчий максимум, RSI вищий максимум → SHORT.
 1) Як самостійний сигнал: вхід на закритті бару підтвердження, стоп 3×ATR14, ціль 6R, утримання 60 барів (як у СВІНГ), стоп-першим, комісія 0,10%, ризик $10. Розрізи: за трендом / проти (MA200), роки.
 2) Як підказка до СВІНГ (swmfe_trades.csv): чи була за останні 12 барів до входу дивергенція В БІК угоди (прихована або звичайна) або ПРОТИ неї — і чим закінчились такі угоди проти решти.
Використання: div_test.py CANDLES_DIR SYMS SW_TRADES OUT_PREFIX"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, SWF, OUT = sys.argv[1], sys.argv[2].split(","), sys.argv[3], sys.argv[4]
K = 5; LOOK = 60; HOLD = 60; FEE = 0.001; PER = 14400
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
rows = []; ev = []
for sym in SYMS:
    p = f"{CD}/{sym}/1h.csv"
    if not os.path.exists(p): continue
    d = pd.read_csv(p).drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // PER * PER).agg(n=("open", "size"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g = g[g.n == 4]
    t, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "high", "low", "close")); n = len(c)
    if n < 400: continue
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); M = pd.Series(c).rolling(200).mean().to_numpy(); R = rsi(c)
    lastL = lastH = None
    for i in range(210, n):
        q = i - K
        for typ in ("L", "H"):
            x = l if typ == "L" else h
            win = x[q - K:q + K + 1]
            if not ((x[q] == win.min()) if typ == "L" else (x[q] == win.max())) or (win == x[q]).sum() > 1: continue
            prev = lastL if typ == "L" else lastH
            if typ == "L": lastL = q
            else: lastH = q
            if prev is None or q - prev > LOOK or not R[q] > 0 or not R[prev] > 0: continue
            if typ == "L":
                kind = "RB" if (l[q] < l[prev] and R[q] > R[prev]) else ("HB" if (l[q] > l[prev] and R[q] < R[prev]) else None); side = 1
            else:
                kind = "RS" if (h[q] > h[prev] and R[q] < R[prev]) else ("HS" if (h[q] < h[prev] and R[q] > R[prev]) else None); side = -1
            if not kind or not A[i] > 0 or not M[i] > 0: continue
            ev.append((sym, t[i] + PER, kind, side))                       # видно з закриття бару i
            if i + HOLD >= n: continue
            e = c[i]; risk = 3 * A[i]; sl = e - side * risk; tp = e + side * 6 * risk; r = None
            for j in range(i + 1, i + 1 + HOLD):
                if (l[j] <= sl) if side > 0 else (h[j] >= sl): r = -1.0; break
                if (h[j] >= tp) if side > 0 else (l[j] <= tp): r = 6.0; break
            if r is None: r = side * (c[i + HOLD] - e) / risk
            rows.append((sym, t[i], kind, side, int(side * (c[i] - M[i]) > 0), r - FEE * e / risk))
    print(sym, len(rows), flush=True)
W = pd.DataFrame(rows, columns=["sym", "ts", "kind", "side", "trend", "r"]); W["usd"] = 10 * W.r; W["y"] = pd.to_datetime(W.ts, unit="s").dt.year; W.to_csv(OUT + "_trades.csv", index=False)
NAME = {"RB": "звичайна бичача (LONG)", "RS": "звичайна ведмежа (SHORT)", "HB": "прихована бичача (LONG)", "HS": "прихована ведмежа (SHORT)"}
print(f"\nДИВЕРГЕНЦІЇ RSI(14) на H4: монет {W.sym.nunique()}, {pd.Timestamp(W.ts.min(), unit='s'):%Y-%m-%d} — {pd.Timestamp(W.ts.max(), unit='s'):%Y-%m-%d}; ризик $10, комісія 0,10%")
print("\n== 1) ЯК САМОСТІЙНИЙ СИГНАЛ (стоп 3×ATR, ціль 6R, до 60 барів)")
def line(g, lab):
    if len(g) < 30: print(f"   {lab}: n<30"); return
    py = ", ".join(f"{y}:{v:+.0f}" for y, v in g.groupby("y").usd.sum().items())
    print(f"   {lab}: {len(g)} угод, ${g.usd.sum():+.0f}, на угоду ${g.usd.mean():+.2f}, виграшних {100*(g.usd>0).mean():.0f}%, роки [{py}]")
for k in ("RB", "RS", "HB", "HS"):
    g = W[W.kind == k]; print(f" {NAME[k]}"); line(g, "усі"); line(g[g.trend == 1], "за трендом (MA200)"); line(g[g.trend == 0], "проти тренду")
E = pd.DataFrame(ev, columns=["sym", "t", "kind", "side"]); sw = pd.read_csv(SWF); sw = sw[sw.sym.isin(E.sym.unique())].copy(); sw["usd"] = 10 * sw.r
WIN = 12 * PER
def flag(kinds, same):
    out = np.zeros(len(sw), bool)
    for sym, g in sw.groupby("sym"):
        e = E[(E.sym == sym) & E.kind.isin(kinds)]
        for sd in (1, -1):
            tt = np.sort(e[e.side == (sd if same else -sd)].t.to_numpy()); gi = g[g.side == sd]
            if not len(tt) or not len(gi): continue
            ts = gi.ts.to_numpy() + PER                                         # вхід СВІНГ — на закритті його бару
            k = np.searchsorted(tt, ts, side="right") - 1; ok = (k >= 0) & (ts - tt[np.clip(k, 0, len(tt) - 1)] <= WIN)
            out[sw.index.get_indexer(gi.index)] = ok
    return out
print(f"\n== 2) ЯК ПІДКАЗКА ДО СВІНГ: {len(sw)} угод СВІНГ, на угоду ${sw.usd.mean():+.2f}; дивергенція за останні 12 барів (2 доби) до входу")
def cmp(lab, f):
    a, b = sw[f], sw[~f]
    if len(a) < 30: print(f"   {lab}: n<30"); return
    py = ", ".join(f"{y}:{v:+.2f}" for y, v in a.groupby("y").usd.mean().items())
    print(f"   {lab}: з нею {len(a)} угод ${a.usd.mean():+.2f} на угоду (стопів {100*(a.why=='SL').mean():.0f}%) | без неї {len(b)} угод ${b.usd.mean():+.2f} (стопів {100*(b.why=='SL').mean():.0f}%) | з нею по роках [{py}]")
cmp("прихована В БІК угоди", flag(("HB", "HS"), True)); cmp("звичайна В БІК угоди", flag(("RB", "RS"), True)); cmp("будь-яка В БІК угоди", flag(("HB", "HS", "RB", "RS"), True))
cmp("звичайна ПРОТИ угоди (попередження)", flag(("RB", "RS"), False)); cmp("прихована ПРОТИ угоди", flag(("HB", "HS"), False)); cmp("будь-яка ПРОТИ угоди", flag(("HB", "HS", "RB", "RS"), False))
calm = sw.atr_pct < 0.023; print("   лише спокійні монети:"); sw0 = sw; sw = sw0[calm]
cmp("  прихована В БІК угоди", flag(("HB", "HS"), True)); cmp("  звичайна ПРОТИ угоди", flag(("RB", "RS"), False))
