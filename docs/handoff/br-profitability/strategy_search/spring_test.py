"""READ-ONLY. «ПРУЖИНА» + дивергенція: скальп на відскок після проколу (26.11.2026, прохання власниці після випадку BTC 25.11: «чому ми це не використовуємо»).
ПРАВИЛА ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА; «spring/upthrust» і дивергенція — ЗОВНІШНЄ, числа наші, не підбирались). Таймфрейми M15 і H1. RSI(14), пивот k=5 (видно через 5 барів), попередній пивот ≤60 барів.
 База D   : звичайна дивергенція (LONG: ціна нижчий мінімум, RSI вищий; SHORT дзеркально).
 Умови, які додаємо ПО ОДНІЙ і разом (усі комбінації показано):
   S «пружина»   : новий мінімум проколов попередній, а бар підтвердження ЗАКРИВСЯ вище попереднього мінімуму (ціна повернулась).
   F «злив»      : падіння від максимуму останніх 24 барів до мінімуму-пивота ≥ 3 ATR (різкий рух, як 25.11).
   O «перепроданість» : RSI у пивоті < 30 (для SHORT > 70).
   H «старший ТФ»: RSI на старшому таймфреймі (H1 для M15, H4 для H1) на момент входу < 40 (для SHORT > 60).
 Контроль N: той самий новий мінімум/максимум БЕЗ дивергенції з тими самими умовами.
 Вхід: закриття бару підтвердження. Стоп: за мінімум пивота − 0,1 ATR. Цілі 1R / 2R / 3R. Утримання 32 бари (M15 = 8 год; H1 = 32 год). Стоп-першим. Ризик $10. Комісія 0,10% і 0,04%.
 Групи (незалежні): A = 42 монети 2022–26, B = ті самі 2020–21, C = інші монети. Правило підтверджене, лише якщо плюс у всіх трьох.
Використання: spring_test.py CANDLES_DIR SYMS42 OUT"""
import os, sys, itertools
import numpy as np, pandas as pd
D, SY42, OUT = sys.argv[1], set(sys.argv[2].split(",")), sys.argv[3]
K = 5; LOOK = 60; HOLD = 32
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
CH = []
def study(grp, tf, t, h, l, c, tH, rH, perH):
    n = len(c); rows = []
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); R = rsi(c); yr = pd.to_datetime(t, unit="s").year.to_numpy()
    hi24 = pd.Series(h).rolling(24).max().to_numpy(); lo24 = pd.Series(l).rolling(24).min().to_numpy()
    for side, x in ((1, l), (-1, h)):
        ext = (pd.Series(x).rolling(2 * K + 1, center=True).min() if side > 0 else pd.Series(x).rolling(2 * K + 1, center=True).max()).to_numpy()
        piv = np.flatnonzero(ext == x); piv = piv[(piv >= 60) & (piv + K + HOLD < n)]
        for p, q in zip(piv[:-1], piv[1:]):
            if q - p > LOOK or q - p <= K: continue
            if not side * (x[p] - x[q]) > 0: continue                         # лише НОВИЙ мінімум (для LONG) / новий максимум (для SHORT)
            i = q + K
            if not A[i] > 0 or not R[q] > 0 or not R[p] > 0: continue
            div = int(side * (R[q] - R[p]) > 0); S = int(side * (c[i] - x[p]) > 0)
            F = int(((hi24[q] - l[q]) if side > 0 else (h[q] - lo24[q])) >= 3 * A[q]); O = int(R[q] < 30 if side > 0 else R[q] > 70)
            j = np.searchsorted(tH, t[i] + (t[1] - t[0]) - perH, side="right") - 1       # останній ЗАКРИТИЙ бар старшого ТФ
            Hh = int(j >= 20 and (rH[j] < 40 if side > 0 else rH[j] > 60))
            e = c[i]; sl = x[q] - side * 0.1 * A[i]; risk = side * (e - sl)
            if not 0.0005 <= risk / e <= 0.25: continue
            H_ = h[i + 1:i + 1 + HOLD]; L_ = l[i + 1:i + 1 + HOLD]; last = c[i + HOLD]
            hs = (L_ <= sl) if side > 0 else (H_ >= sl); isx = int(np.argmax(hs)) if hs.any() else HOLD + 1; out = []
            for tg in (1, 2, 3):
                tp = e + side * tg * risk; ht = (H_ >= tp) if side > 0 else (L_ <= tp); itx = int(np.argmax(ht)) if ht.any() else HOLD + 1
                out.append(-1.0 if (isx <= itx and isx <= HOLD) else (float(tg) if itx <= HOLD else side * (last - e) / risk))
            g = grp if grp != "X" else ("A" if yr[i] >= 2022 else "B")
            rows.append((g, tf, side, div, S, F, O, Hh, 100 * risk / e, int(yr[i]), out[0], out[1], out[2]))
    if rows: CH.append(pd.DataFrame(rows, columns=["g", "tf", "side", "div", "S", "F", "O", "H", "sp", "y", "r1", "r2", "r3"]))
for s in sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv")):
    if s in ("XAUUSDT", "XAGUSDT"): continue
    d = pd.read_csv(f"{D}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time"); grp = "X" if s in SY42 else "C"
    def agg(per, need):
        g = d.groupby(d.open_time // per * per).agg(n=("open", "size"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); return g[g.n >= need]
    h1 = agg(3600, 4); h4 = agg(14400, 15)
    study(grp, "M15", d.open_time.to_numpy(float), d.high.to_numpy(float), d.low.to_numpy(float), d.close.to_numpy(float), h1.open_time.to_numpy(float), rsi(h1.close.to_numpy(float)), 3600)
    study(grp, "H1", h1.open_time.to_numpy(float), h1.high.to_numpy(float), h1.low.to_numpy(float), h1.close.to_numpy(float), h4.open_time.to_numpy(float), rsi(h4.close.to_numpy(float)), 14400)
    print(s, grp, sum(len(x) for x in CH), flush=True)
W = pd.concat(CH, ignore_index=True)
print(f"\n«ПРУЖИНА» + ДИВЕРГЕНЦІЯ: {len(W):,} випадків нового мінімуму/максимуму; ризик $10; формат $ на угоду при комісії 0,10% (у дужках 0,04%), n; групи A | B | C")
def val(x, tg, fee): return 10 * (x[f"r{tg}"] - fee / x.sp).mean()
def row(lab, m, tg):
    parts = []; ok = True; ok4 = True
    for g in "ABC":
        x = W[m & (W.g == g)]
        if len(x) < 150: parts.append(f"{g}: n={len(x)}"); ok = ok4 = False; continue
        a, b = val(x, tg, 0.10), val(x, tg, 0.04); ok &= a > 0; ok4 &= b > 0; parts.append(f"{g}: {a:+.2f} ({b:+.2f}), n={len(x)}, виграшних {100*(x[f'r{tg}']>0).mean():.0f}%")
    print(f"   {lab:34s} ціль {tg}R: " + " | ".join(parts) + ("   <<< ПЛЮС У ТРЬОХ ГРУПАХ" if ok else ("   << плюс у трьох лише з лімітною комісією" if ok4 else "")))
    return ok, ok4
CONDS = ("S", "F", "O", "H"); tot = pos = pos4 = 0
for tf in ("M15", "H1"):
    for side, sn in ((1, "LONG (відскок після проколу вниз)"), (-1, "SHORT (після проколу вгору)")):
        print(f"\n######## {tf} · {sn}")
        base = (W.tf == tf) & (W.side == side)
        for r in range(0, 5):
            for combo in itertools.combinations(CONDS, r):
                m = base.copy()
                for cnd in combo: m &= W[cnd] == 1
                name = "+".join(combo) if combo else "без умов"
                for tg in (1, 2, 3):
                    a, b = row(f"дивергенція · {name}", m & (W["div"] == 1), tg); tot += 1; pos += a; pos4 += b
                row(f"  контроль без дивергенції · {name}", m & (W["div"] == 0), 2)
print(f"\nПІДСУМОК: комбінацій із дивергенцією {tot}; плюсові в усіх трьох групах при комісії 0,10%: {pos}; при 0,04%: {pos4}. Випадково очікували б ≈{tot*0.125:.0f}, якби переваги не було і комісії теж.")
W.groupby(["g", "tf", "side", "div", "S", "F", "O", "H"]).agg(n=("r1", "size"), r1=("r1", "mean"), r2=("r2", "mean"), r3=("r3", "mean"), sp=("sp", "median")).round(4).to_csv(OUT)
