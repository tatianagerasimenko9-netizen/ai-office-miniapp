"""READ-ONLY. ЧЕК-ЛИСТ ТВХ (О. Герчик, сторіз alexgerchik_official, скриншот власниці 28.11.2026) — перевірка на історії крипти.
ДЖЕРЕЛО (дослівно зі скриншота): 1) Рівень: якої сили (D1, H4, H15), наскільки відпрацьований («чим більше торкань, тим сильніший»), чи був основний рух від рівня на історії;
«зашльопані» рівні та рівні з мікрорухом у роботу не брати. 2) Яка відстань пройдена: ES ≈ 60 пт, NQ ≈ 270 пт в обидва боки; «чим більше інструмент пройшов, тим менше підходить
для продовження руху і вища ймовірність розвороту». 3) Швидкість підходу до рівня: швидкий/імпульсний підхід — частіше хибний пробій (ЛП); повільний, поступальний, під невеликим
кутом — вищий шанс на пробій (за збігу інших факторів).
ЩО В ДЖЕРЕЛІ Є / ЧОГО НЕМАЄ: напрям тверджень — Є. Чисел для крипти (скільки це «швидко», «багато пройшов», «зашльопаний») — НЕМАЄ → усі пороги нижче = ГІПОТЕЗА, записані ДО запуску.
Бари H1, 42 монети (група A) + 30 інших (група B), 2020–2026; P1 ≤2022, P2 2023–24, P3 2025–26; ризик $10, комісія 0,10%.
РІВЕНЬ: максимум за 240 годин (опір); підтримка — дзеркально. ПОДІЯ: бар закрився за рівнем (рівню ≥ 12 год; не частіше 1 разу на 24 год на монету).
ОЗНАКИ на барі пробою:
  швидкість   рух за останні 6 год у бік рівня, в ATR(H1): «швидко» ≥ 4, «середньо» 2–4, «повільно» < 2
  кут         за 24 год до пробою ціна йшла рівно: частка годин, що закрились у бік рівня ≥ 60% і жодна година не дала > 1,5 ATR («поступально») / інакше
  пройдено    шлях від 24-годинного мінімуму до ціни пробою у денних ATR (ATR 14 діб): «мало» < 0,7, «норма» 0,7–1,3, «багато» > 1,3
  торкання    скільки разів за 240 год ціна підходила до рівня ближче 0,3 ATR і відходила на ≥ 2 ATR: 1 / 2 / 3+ («зашльопаний» = 4+)
ДВА РЕЗУЛЬТАТИ для кожної події:
  ПРОБІЙ   вхід у бік пробою на закритті, стоп за мінімумом останніх 3 барів − 0,1 ATR (0,3%…5%), ціль 2R, до 72 год.
  ЛП       хибний пробій: якщо за 3 наступні бари ціна ЗАКРИЛАСЬ назад за рівнем — вхід проти пробою, стоп за екстремумом пробою + 0,1 ATR, ціль 2R, до 72 год.
  Окремо: частка пробоїв, що стали хибними (повернулись за 3 бари).
ТВЕРДЖЕННЯ ПІДТВЕРДЖЕНЕ, якщо різниця між корзинами має той самий знак у всіх 6 клітинках (2 групи × 3 періоди).
Використання: tvh_lab.py CANDLES_DIR SEARCH CONTROL"""
import os, sys
import numpy as np, pandas as pd
CD, GA, GB = sys.argv[1], sys.argv[2].split(","), sys.argv[3].split(",")
LB = 240; FEE = 0.001; HOR = 72; R = []
def trade(H, L, C, i, e, sl, k=2):
    risk = e - sl
    for j in range(i + 1, min(len(C), i + HOR + 1)):
        if L[j] <= sl: return -1.0
        if H[j] >= e + k * risk: return float(k)
    return (C[min(len(C) - 1, i + HOR)] - e) / risk
def run(sym, grp):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(n=("open", "size"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g = g[g.n == 4]
    t, o, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
    if n < LB + 500: return
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); A = pd.Series(tr).rolling(14).mean().to_numpy()
    dr = pd.Series(h).rolling(24).max() - pd.Series(l).rolling(24).min(); AD = dr.rolling(336).mean().to_numpy()           # середній добовий розмах за 14 діб
    for side in (1, -1):
        O, H, L, C = (o, h, l, c) if side > 0 else (-o, -l, -h, -c)
        lvl = pd.Series(H).rolling(LB).max().shift(1).to_numpy(); set_i = 0; last = -10 ** 9
        for i in range(LB + 340, n - HOR - 5):
            if lvl[i] != lvl[i - 1]: set_i = i - 1
            if not (A[i] > 0 and AD[i] > 0 and C[i] > lvl[i]): continue
            if i - last < 24 or i - set_i < 12: last = i if C[i] > lvl[i] else last; continue
            last = i; a = A[i]; lv = lvl[i]
            sp = (C[i] - C[i - 6]) / a; ups = (C[i - 24:i] > O[i - 24:i]).mean(); mx = (np.abs(C[i - 24:i] - O[i - 24:i]) / a).max()
            dist = (C[i] - L[i - 24:i + 1].min()) / AD[i]
            w = H[i - LB:i]; wl = L[i - LB:i]; near = w >= lv - 0.3 * a; touches = 0; k = 0
            while k < LB:
                if near[k]:
                    touches += 1; k += 1
                    while k < LB and wl[k] > lv - 2 * a: k += 1                # чекаємо відходу на 2 ATR, тоді наступний підхід — нове торкання
                else: k += 1
            y = pd.Timestamp(t[i], unit="s").year; P = "P1" if y <= 2022 else ("P2" if y <= 2024 else "P3")
            e = C[i]; sl = L[i - 2:i + 1].min() - 0.1 * a; rp = (e - sl) / abs(e); ub = 10 * (trade(H, L, C, i, e, sl) - FEE / rp) if 0.003 <= rp <= 0.05 else np.nan
            fake = 0; ul = np.nan
            for j in range(i + 1, i + 4):
                if C[j] < lv:
                    fake = 1; top = H[i:j + 1].max() + 0.1 * a; e2 = C[j]; rp2 = (top - e2) / abs(e2)
                    if 0.003 <= rp2 <= 0.05: ul = 10 * (trade(-L, -H, -C, j, -e2, -top) - FEE / rp2)
                    break
            R.append((grp, P, side, "швидко" if sp >= 4 else ("середньо" if sp >= 2 else "повільно"), "поступально" if (ups >= 0.6 and mx <= 1.5) else "ривками",
                      "мало" if dist < 0.7 else ("норма" if dist <= 1.3 else "багато"), "1" if touches <= 1 else ("2" if touches == 2 else ("3" if touches == 3 else "4+ (зашльопаний)")), ub, fake, ul))
for grp, syms in (("A", GA), ("B", GB)):
    for s in syms:
        if os.path.exists(f"{CD}/{s}/15m.csv"): run(s, grp)
W = pd.DataFrame(R, columns=["g", "P", "side", "швидкість", "кут", "пройдено", "торкання", "ub", "fake", "ul"]); CELLS = [(g, p) for g in "AB" for p in ("P1", "P2", "P3")]
print(f"ЧЕК-ЛИСТ ТВХ на крипті: пробоїв рівня {len(W)} (LONG {int((W.side>0).sum())}, SHORT {int((W.side<0).sum())}); хибних (повернулись за 3 год) {100*W.fake.mean():.0f}%")
print(f"УСІ: вхід у пробій {W.ub.mean():+.2f}$ на угоду (n={W.ub.notna().sum()}); вхід у хибний пробій (ЛП) {W.ul.mean():+.2f}$ (n={W.ul.notna().sum()})")
print("формат клітинок: A·P1 | A·P2 | A·P3 || B·P1 | B·P2 | B·P3")
for f, order in (("швидкість", ["повільно", "середньо", "швидко"]), ("кут", ["поступально", "ривками"]), ("пройдено", ["мало", "норма", "багато"]), ("торкання", ["1", "2", "3", "4+ (зашльопаний)"])):
    print(f"\n== {f}")
    for v in order:
        x = W[W[f] == v]
        if not len(x): continue
        def cell(col, fn=np.nanmean):
            out = []
            for g, p in CELLS:
                z = x[(x.g == g) & (x.P == p)][col].dropna(); out.append(f"{fn(z):+.2f}" if len(z) >= 30 else " — ")
            return " | ".join(out[:3]) + " || " + " | ".join(out[3:])
        fk = " | ".join(f"{100*x[(x.g==g)&(x.P==p)].fake.mean():.0f}%" for g, p in CELLS)
        print(f"  {v:18s} n={len(x):6d}  хибних {100*x.fake.mean():.0f}% [{fk}]")
        print(f"  {'':18s} ПРОБІЙ $ {x.ub.mean():+.2f}: {cell('ub')}")
        print(f"  {'':18s} ЛП     $ {x.ul.mean():+.2f}: {cell('ul')}")
print("\n== поєднання за чек-листом: повільно + поступально + пройдено мало/норма + торкань 2–3  проти  швидко + пройдено багато")
for nm, m in (("ЗА ЧЕК-ЛИСТОМ (чекаємо пробій)", (W["швидкість"] == "повільно") & (W["кут"] == "поступально") & (W["пройдено"] != "багато") & W["торкання"].isin(["2", "3"])),
              ("ПРОТИ ЧЕК-ЛИСТА (чекаємо ЛП)", (W["швидкість"] == "швидко") & (W["пройдено"] == "багато"))):
    x = W[m]; print(f"  {nm}: n={len(x)}, хибних {100*x.fake.mean():.0f}%, ПРОБІЙ {x.ub.mean():+.2f}$, ЛП {x.ul.mean():+.2f}$ | по клітинках ПРОБІЙ: " + " | ".join(f"{x[(x.g==g)&(x.P==p)].ub.mean():+.2f}({int(((x.g==g)&(x.P==p)).sum())})" for g, p in CELLS) + " | ЛП: " + " | ".join(f"{x[(x.g==g)&(x.P==p)].ul.mean():+.2f}" for g, p in CELLS))
