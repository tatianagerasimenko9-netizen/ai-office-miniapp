"""READ-ONLY. СВІНГ: УГОДА ДІЙШЛА ДО +$10 / +$20 — ЗАКРИТИ ЗАРАЗ ЧИ ТРИМАТИ? Які умови в цей момент кажуть «далі піде до стопа» (28.11.2026, питання власниці).
Записано ДО запуску. ГІПОТЕЗА (наша автоматизація). Нічого не вмикає.
Угоди: СВІНГ як у sw_exitlab.py BASE (H4, 3 рукави + MA200, стоп 3×ATR, ціль 6R, до 60 барів, одна позиція на монету), 42 монети, 2020–2026, ризик $10, комісія 0,10%.
МОМЕНТ: перший бар H4, який ЗАКРИВСЯ з результатом ≥ +kR (k = 1 і k = 2). У цей момент порівнюємо два рішення:
  ЗАКРИТИ ЗАРАЗ — результат = закриття цього бару;   ТРИМАТИ — результат угоди за базовими правилами.
«Умова корисна», якщо для угод з цією умовою ЗАКРИТИ ЗАРАЗ краще за ТРИМАТИ в КОЖНОМУ з трьох періодів (P1 2020–21, P2 2022–23, P3 2024–26) і таких угод ≥ 100 у періоді.
УМОВИ (усі відомі в цей момент):
  швидкість  : скільки барів від входу до моменту (≤3 / 4–12 / >12)
  рукав      : пробій / повернення (RSI2 або Боллінджер)
  бік        : LONG / SHORT
  монета     : спокійна (ATR/ціна < 2,3%) / рухлива
  BTC        : з моменту входу BTC пішов у бік угоди / проти
  день       : момент у ср–пт / в інші дні (київський час)
  свічка     : бар моменту закрився у «поганій» половині свого розмаху (для LONG — у нижній) / у «добрій»
  RSI        : RSI(14) на H4 у крайній зоні в бік угоди (LONG > 75, SHORT < 25) / ні
  рівень     : ціна ближче ніж 1% до 30-денного екстремуму в бік угоди (LONG — максимум 30 днів без останніх 2 діб) або щойно його проколола / далеко
  розгін     : за останні 3 бари угода додала ≥ 1R (різкий стрибок) / ні
Використання: sw_peak_lab.py CANDLES_DIR SYMS"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS = sys.argv[1], sys.argv[2].split(",")
PER = 14400; H = 60; K = 6.0; S = 3.0; FEE = 0.001
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
def h4(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    return d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
bt = h4("BTCUSDT").set_index("open_time").close
rows = []
for sym in SYMS:
    if not os.path.exists(f"{CD}/{sym}/15m.csv"): continue
    g = h4(sym); t, o, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
    if n < 400: continue
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); m200 = sma(c, 200)
    up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    r2 = rsi(c, 2); r14 = rsi(c, 14); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
    Lb, Sb = ev(c > hi20) & up, ev(c < lo20) & dn
    L = Lb | ev((r2 < 10) & up) | ev((c < lb) & up); Sx = Sb | ev((r2 > 90) & dn) | ev((c > ub) & dn)
    hi30 = pd.Series(h).rolling(180).max().shift(12).to_numpy(); lo30 = pd.Series(l).rolling(180).min().shift(12).to_numpy(); btc = bt.reindex(t).to_numpy()
    i = 201
    while i < n - 2:
        if L[i] == Sx[i] or not A[i] > 0: i += 1; continue
        side = 1 if L[i] else -1; e = o[i + 1]; risk = S * A[i]
        if risk <= 0 or risk / e < 0.0005: i += 1; continue
        res = None; j = i + 1; mom = {}
        while j < n and j <= i + H:
            adv = side * ((l[j] if side > 0 else h[j]) - e) / risk; fav = side * ((h[j] if side > 0 else l[j]) - e) / risk; cR = side * (c[j] - e) / risk
            if adv <= -1: res = -1.0; break
            if fav >= K: res = K; break
            for k in (1, 2):
                if k not in mom and cR >= k: mom[k] = j
            j += 1
        if res is None: res = side * (c[min(j, n - 1)] - e) / risk
        fee = FEE / (risk / e); arm = "пробій" if (Lb[i] if side > 0 else Sb[i]) else "повернення"
        for k, q in mom.items():
            rng = max(h[q] - l[q], 1e-12); pos = (c[q] - l[q]) / rng; lv = hi30[q] if side > 0 else lo30[q]
            dow = pd.Timestamp(t[q] + PER, unit="s", tz="UTC").tz_convert("Europe/Kyiv").weekday()
            rows.append({"k": k, "sym": sym, "ts": t[q], "now": side * (c[q] - e) / risk - fee, "hold": res - fee,
                         "швидкість": "≤3 бари" if q - i <= 3 else ("4–12 барів" if q - i <= 12 else ">12 барів"), "рукав": arm, "бік": "LONG" if side > 0 else "SHORT",
                         "монета": "спокійна" if A[i] / c[i] < 0.023 else "рухлива",
                         "BTC": "за угодою" if side * (btc[q] - btc[i]) > 0 else "проти угоди",
                         "день": "ср–пт" if dow in (2, 3, 4) else "інші дні",
                         "свічка": "погана половина" if (pos < 0.5 if side > 0 else pos > 0.5) else "добра половина",
                         "RSI": "крайня зона" if (r14[q] > 75 if side > 0 else r14[q] < 25) else "звичайна",
                         "рівень": "біля 30-денного екстремуму" if (lv == lv and (abs(c[q] - lv) / lv <= 0.01 or side * (c[q] - lv) > 0)) else "далеко",
                         "розгін": "стрибок ≥1R за 3 бари" if side * (c[q] - c[max(q - 3, i)]) / risk >= 1 else "плавно"})
        i = max(j, i + 1)
W = pd.DataFrame(rows); W["y"] = pd.to_datetime(W.ts, unit="s").dt.year; W["P"] = np.where(W.y <= 2021, "P1", np.where(W.y <= 2023, "P2", "P3")); PS = ("P1", "P2", "P3")
FE = ["швидкість", "рукав", "бік", "монета", "BTC", "день", "свічка", "RSI", "рівень", "розгін"]; good = []
for k in (1, 2):
    X = W[W.k == k]; print(f"\n######## Угода вперше закрила бар на +{k}R (+${10*k}): {len(X)} випадків")
    print(f"  УСІ: закрити зараз {10*X.now.mean():+.2f}$ | тримати {10*X.hold.mean():+.2f}$ | після цього до стопа (−$10) дійшли {100*(X.hold <= -0.95).mean():.0f}%, закінчили нижче, ніж було зараз, {100*(X.hold < X.now).mean():.0f}%, до цілі {100*(X.hold >= 5.5).mean():.0f}%")
    print("  по періодах (тримати − закрити, $): " + ", ".join(f"{p}: {10*(X[X.P == p].hold - X[X.P == p].now).mean():+.2f}" for p in PS))
    print(f"  {'умова':44s} {'n':>5s} {'закрити':>8s} {'тримати':>8s} {'до стопа':>8s} | тримати − закрити по періодах (n)")
    for f in FE:
        for v, g in X.groupby(f):
            d = {p: (10 * (g[g.P == p].hold - g[g.P == p].now).mean(), int((g.P == p).sum())) for p in PS}
            ok = all(d[p][1] >= 100 and d[p][0] < 0 for p in PS)
            if ok: good.append(f"+{k}R · {f}: {v}")
            print(f"  {f + ': ' + v:44s} {len(g):5d} {10*g.now.mean():+8.2f} {10*g.hold.mean():+8.2f} {100*(g.hold <= -0.95).mean():7.0f}% | " + " | ".join(f"{d[p][0]:+.2f} ({d[p][1]})" for p in PS) + ("   <<< КРАЩЕ ЗАКРИТИ" if ok else ""))
print("\nУМОВИ, ЗА ЯКИХ КРАЩЕ ЗАКРИТИ (в усіх трьох періодах): " + ("; ".join(good) if good else "НЕМАЄ"))
