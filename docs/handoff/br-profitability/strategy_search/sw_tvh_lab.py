"""READ-ONLY. ЧЕК-ЛИСТ ТВХ НА НАШИХ СИГНАЛАХ СВІНГ: чи дає результат врахування рівня, пройденої відстані і швидкості підходу (28.11.2026, прохання власниці).
Джерело тверджень: docs/strategies/GERCHIK_LEVELS_UA.md («Чек-лист ТВХ»). Чисел для крипти в джерелі немає → усі пороги = ГІПОТЕЗА, записані ДО запуску. Нічого не вмикає.
Сигнали: СВІНГ як у sw_exitlab.py BASE (H4, 3 рукави + MA200, стоп 3×ATR, ціль 6R, до 60 барів, одна позиція на монету), $10, комісія 0,10%, 2020–2026.
Групи: A — наші 42 монети, B — 30 інших (контроль). Періоди P1 2020–21, P2 2022–23, P3 2024–26. Окремо показано рукав «пробій» і рукави «повернення».
ОЗНАКИ на барі сигналу (усі відомі в цей момент):
  ПРОЙДЕНО за добу   рух ціни за 6 барів (24 год) у бік угоди, у середніх добових розмахах (за 14 діб): «мало» < 0,5 · «норма» 0,5–1,2 · «багато» > 1,2
  ПРОЙДЕНО за 5 діб  те саме за 30 барів: «мало» < 1 · «норма» 1–3 · «багато» > 3
  ШВИДКІСТЬ          рух за останні 2 бари (8 год) у бік угоди в ATR(H4): «повільно» < 1 · «середньо» 1–2,5 · «швидко» > 2,5
  КУТ                з 12 останніх барів ≥ 60% закрились у бік угоди і жоден не більший за 1,5 ATR — «поступально»; інакше «ривками»
  ТОРКАННЯ           (лише пробій) скільки разів за 120 барів ціна підходила до пробитого рівня ближче 0,3 ATR і відходила на ≥ 2 ATR: 1 · 2 · 3 · 4+ («зашльопаний»)
  РІВЕНЬ ПОПЕРЕДУ    до 30-денного екстремуму в бік угоди: «впритул» < 2 ATR · «поруч» 2–6 · «далеко» > 6 · «уже за ним» (ціна оновила 30-денний екстремум)
ТВЕРДЖЕННЯ ПІДТВЕРДЖЕНЕ, якщо «гірша» за чек-листом корзина гірша за «кращу» в усіх 6 клітинках (n ≥ 50 у кожній).
Використання: sw_tvh_lab.py CANDLES_DIR SEARCH CONTROL"""
import os, sys
import numpy as np, pandas as pd
CD, GA, GB = sys.argv[1], sys.argv[2].split(","), sys.argv[3].split(",")
PER = 14400; H = 60; K = 6.0; FEE = 0.001
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
def h4(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    return d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
rows = []
for grp, syms in (("A", GA), ("B", GB)):
    for sym in syms:
        if not os.path.exists(f"{CD}/{sym}/15m.csv"): continue
        g = h4(sym); t, o, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
        if n < 500: continue
        pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); m200 = sma(c, 200)
        AD = (pd.Series(h).rolling(6).max() - pd.Series(l).rolling(6).min()).rolling(84).mean().to_numpy()
        up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
        r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
        Lb, Sb = ev(c > hi20) & up, ev(c < lo20) & dn
        L = Lb | ev((r2 < 10) & up) | ev((c < lb) & up); Sx = Sb | ev((r2 > 90) & dn) | ev((c > ub) & dn)
        hi180 = pd.Series(h).rolling(180).max().shift(1).to_numpy(); lo180 = pd.Series(l).rolling(180).min().shift(1).to_numpy()
        i = 201
        while i < n - 2:
            if L[i] == Sx[i] or not (A[i] > 0 and AD[i] > 0): i += 1; continue
            side = 1 if L[i] else -1; e = o[i + 1]; risk = 3.0 * A[i]
            if risk <= 0 or risk / e < 0.0005: i += 1; continue
            res = None; j = i + 1
            while j < n and j <= i + H:
                adv = side * ((l[j] if side > 0 else h[j]) - e) / risk; fav = side * ((h[j] if side > 0 else l[j]) - e) / risk
                if adv <= -1: res = -1.0; break
                if fav >= K: res = K; break
                j += 1
            if res is None: res = side * (c[min(j, n - 1)] - e) / risk
            arm = bool(Lb[i] if side > 0 else Sb[i]); a = A[i]
            d24 = side * (c[i] - c[i - 6]) / AD[i]; d5 = side * (c[i] - c[i - 30]) / AD[i]; sp = side * (c[i] - c[i - 2]) / a
            share = (side * (c[i - 11:i + 1] - o[i - 11:i + 1]) > 0).mean(); mx = (np.abs(c[i - 11:i + 1] - o[i - 11:i + 1]) / a).max()
            tch = ""
            if arm:
                lv = hi20[i] if side > 0 else lo20[i]; w = (h if side > 0 else -l)[i - 120:i]; wo = (l if side > 0 else -h)[i - 120:i]; LV = lv if side > 0 else -lv; cnt = 0; q = 0
                while q < 120:
                    if w[q] >= LV - 0.3 * a:
                        cnt += 1; q += 1
                        while q < 120 and wo[q] > LV - 2 * a: q += 1
                    else: q += 1
                tch = "1" if cnt <= 1 else ("2" if cnt == 2 else ("3" if cnt == 3 else "4+ (зашльопаний)"))
            ex = hi180[i] if side > 0 else lo180[i]; da = side * (ex - c[i]) / a if ex == ex else np.nan
            ahead = "уже за ним" if da <= 0 else ("впритул" if da < 2 else ("поруч" if da <= 6 else "далеко"))
            y = pd.Timestamp(t[i + 1], unit="s").year
            rows.append({"g": grp, "P": "P1" if y <= 2021 else ("P2" if y <= 2023 else "P3"), "arm": "пробій" if arm else "повернення", "usd": 10 * (res - FEE / (risk / e)),
                         "ПРОЙДЕНО за добу": "мало" if d24 < 0.5 else ("норма" if d24 <= 1.2 else "багато"), "ПРОЙДЕНО за 5 діб": "мало" if d5 < 1 else ("норма" if d5 <= 3 else "багато"),
                         "ШВИДКІСТЬ": "повільно" if sp < 1 else ("середньо" if sp <= 2.5 else "швидко"), "КУТ": "поступально" if (share >= 0.6 and mx <= 1.5) else "ривками", "ТОРКАННЯ": tch, "РІВЕНЬ ПОПЕРЕДУ": ahead})
            i = max(j, i + 1)
W = pd.DataFrame(rows); CELLS = [(g, p) for g in "AB" for p in ("P1", "P2", "P3")]
ORD = {"ПРОЙДЕНО за добу": ["мало", "норма", "багато"], "ПРОЙДЕНО за 5 діб": ["мало", "норма", "багато"], "ШВИДКІСТЬ": ["повільно", "середньо", "швидко"], "КУТ": ["поступально", "ривками"],
       "ТОРКАННЯ": ["1", "2", "3", "4+ (зашльопаний)"], "РІВЕНЬ ПОПЕРЕДУ": ["уже за ним", "впритул", "поруч", "далеко"]}
for arm in ("пробій", "повернення", "усі"):
    X = W if arm == "усі" else W[W.arm == arm]
    print(f"\n################ СВІНГ · рукав: {arm} — сигналів {len(X)}, на сигнал {X.usd.mean():+.2f}$ (A {X[X.g=='A'].usd.mean():+.2f}, B {X[X.g=='B'].usd.mean():+.2f})")
    print("формат: корзина n | $ на сигнал | клітинки A·P1 | A·P2 | A·P3 || B·P1 | B·P2 | B·P3 | стопів %")
    for f, order in ORD.items():
        if f == "ТОРКАННЯ" and arm != "пробій": continue
        print(f"== {f}")
        for v in order:
            x = X[X[f] == v]
            if len(x) < 30: continue
            cs = [(x[(x.g == g) & (x.P == p)].usd) for g, p in CELLS]
            print(f"   {v:18s} {len(x):6d} | {x.usd.mean():+.2f} | " + " | ".join((f"{z.mean():+.2f}" if len(z) >= 50 else f" —({len(z)})") for z in cs[:3]) + " || " + " | ".join((f"{z.mean():+.2f}" if len(z) >= 50 else f" —({len(z)})") for z in cs[3:]) + f" | {100*(x.usd<=-9.5).mean():.0f}%")
print("\n################ ПОЄДНАННЯ ЗА ЧЕК-ЛИСТОМ (рукав пробій)")
B = W[W.arm == "пробій"]
for nm, m in (("за чек-листом: повільно/середньо + поступально + пройдено за добу не «багато» + торкань 2–3", (B["ШВИДКІСТЬ"] != "швидко") & (B["КУТ"] == "поступально") & (B["ПРОЙДЕНО за добу"] != "багато") & B["ТОРКАННЯ"].isin(["2", "3"])),
              ("проти чек-листа: швидко + пройдено за добу «багато»", (B["ШВИДКІСТЬ"] == "швидко") & (B["ПРОЙДЕНО за добу"] == "багато")),
              ("зашльопаний рівень (4+ торкань)", B["ТОРКАННЯ"] == "4+ (зашльопаний)")):
    x = B[m]; print(f"  {nm}: n={len(x)}, {x.usd.mean():+.2f}$ | " + " | ".join(f"{x[(x.g==g)&(x.P==p)].usd.mean():+.2f}({int(((x.g==g)&(x.P==p)).sum())})" for g, p in CELLS))
