"""READ-ONLY. «ЧОМУ СПРАЦЮВАВ САМЕ ЦЕЙ ВІДСКОК» — пошук закономірності (27.11.2026, прохання власниці: «5 сигналів, а спрацював один — знайди, за якої умови»).
Події ті самі, що в bounce_lab.py (H1: ЗЛИВ = мінімум за 72 бари і падіння ≥ 3 ATR від максимуму 24 барів; ПОВЕРНЕННЯ = закриття вище максимуму бару зливу за ≤ 6 барів; LONG; стоп за дном − 0,1 ATR; ціль 3R; 48 барів; SL-першим; комісія 0,10%).
ОЗНАКИ І МЕЖІ ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА; ідеї власниці: «не з першого разу», «кілька разів від одного рівня»; решта — ЗОВНІШНЄ: капітуляція, хвіст, обсяг, подвійне дно):
 A номер спроби      : скільки ПОВЕРНЕНЬ цієї монети вже було за 7 діб: 0 | 1 | 2 | 3+
 P попередня спроба  : не було | закінчилась стопом | не стопом
 R те саме дно       : за 7 діб уже був злив (≥ 12 барів раніше) з дном у межах ±1 ATR від цього (повторний тест) | це дно нижче більш ніж на 1 ATR (нове дно) | попередніх зливів не було
 K скільки тестів    : скільки попередніх зливів за 7 діб мали дно в межах ±1 ATR: 0 | 1 | 2+
 G глибина зливу     : (макс. 24 барів − дно) / ATR: 3–4 | 4–6 | 6+
 W хвіст бару зливу  : (мін(відкриття, закриття) − дно) / (макс − дно): <0,25 | 0,25–0,5 | >0,5
 V обсяг бару зливу  : до середнього за 24 бари: <2 | 2–4 | 4+
 S швидкість         : барів від зливу до входу: 1 | 2–3 | 4–6
 X сила повернення   : (закриття входу − макс бару зливу) / ATR: <0,25 | 0,25–1 | >1
 I RSI(14) у дні     : <20 | 20–30 | >30
 F падіння від 7-денного максимуму: <10% | 10–20% | >20%
 H стоп              : <1,5% | 1,5–3% | >3%
 а також прапорці з bounce_lab: B весь ринок, L денний рівень, T BTC підтвердив, D дивергенція, U великий тренд BTC угору.
ПЕРЕВІРКА ВІД САМООБМАНУ: шукаємо на 42 монетах Офісу (група «пошук»), підтверджуємо на 30 ІНШИХ монетах (група «контроль»), і скрізь окремо в трьох періодах (P1 2020–21, P2 2022–23, P3 2024–26).
 Умова (одна ознака або пара) ЗНАЙДЕНА, лише якщо плюс у всіх трьох періодах пошуку І в усіх трьох періодах контролю (n ≥ 100 у кожній клітинці). Друкується, скільки умов перевірено — щоб бачити частку випадкових збігів.
Використання: bounce_feat.py CANDLES_DIR S42 OUT [OKX_CSV…]"""
import os, sys, itertools
import numpy as np, pandas as pd
D, S42, OUT = sys.argv[1], set(sys.argv[2].split(",")), sys.argv[3]
LB = 72; WAIT = 6; HOLD = 48; W7 = 168
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def cut(x, edges): return int(np.searchsorted(edges, x, side="right"))
def events(sym, t, o, h, l, c, v, need_future=True):
    n = len(c); pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); R = rsi(c)
    lo72 = pd.Series(l).rolling(LB).min().to_numpy(); hi24 = pd.Series(h).rolling(24).max().to_numpy(); hi7 = pd.Series(h).rolling(W7).max().to_numpy(); v24 = pd.Series(v).rolling(24).mean().shift(1).to_numpy()
    fl = np.flatnonzero((l == lo72) & (hi24 - l >= 3 * A)); fl = fl[fl >= W7 + 20]; out = []; last_entry = -1; hist = []          # hist: (бар входу, r1) попередніх повернень
    for f in fl:
        if f <= last_entry: continue
        ent = None
        for j in range(f + 1, min(n, f + 1 + WAIT)):
            if l[j] < l[f]: break
            if c[j] > h[f]: ent = j; break
        if ent is None or (need_future and ent + HOLD + 1 >= n): continue
        e = c[ent]; sl = l[f] - 0.1 * A[ent]; risk = e - sl
        if not A[ent] > 0 or not 0.0005 <= risk / e <= 0.25: continue
        H_ = h[ent + 1:ent + 1 + HOLD]; L_ = l[ent + 1:ent + 1 + HOLD]; hs = L_ <= sl; isx = int(np.argmax(hs)) if hs.any() else 10**6; res = []
        for tg in (1, 2, 3):
            ht = H_ >= e + tg * risk; itx = int(np.argmax(ht)) if ht.any() else 10**6
            res.append(-1.0 if (isx <= itx and isx < 10**6) else (float(tg) if itx < 10**6 else ((c[min(n - 1, ent + HOLD)] - e) / risk)))
        prev = [x for x in hist if ent - x[0] <= W7]; pf = fl[(fl >= f - W7) & (fl <= f - 12)]; near = int(sum(abs(l[q] - l[f]) <= A[f] for q in pf))
        rng = h[f] - l[f]
        out.append(dict(sym=sym, tf=t[f], te=t[ent] + 3600, entry=e, sl=sl, sp=100 * risk / e, r1=res[0], r2=res[1], r3=res[2], mfe=(H_.max() - e) / risk if len(H_) else 0.0,
                        A=min(len(prev), 3), P=0 if not prev else (1 if prev[-1][1] <= -1 else 2), R=(2 if not len(pf) else (0 if near else 1)), K=min(near, 2),
                        G=cut((hi24[f] - l[f]) / A[f], [4, 6]), W=cut((min(o[f], c[f]) - l[f]) / rng if rng > 0 else 0, [0.25, 0.5]), V=(cut(v[f] / v24[f], [2, 4]) if v24[f] > 0 else -1),
                        S=cut(ent - f, [2, 4]), X=cut((e - h[f]) / A[ent], [0.25, 1]), I=cut(R[f], [20, 30]), F=cut(100 * (hi7[f] - l[f]) / hi7[f], [10, 20]), H=cut(100 * risk / e, [1.5, 3])))
        hist.append((ent, res[0])); last_entry = ent
    return out
NAMES = {"A": ("номер спроби", ["перша", "друга", "третя", "4-та+"]), "P": ("попередня спроба", ["не було", "стоп", "не стоп"]), "R": ("дно", ["те саме дно (±1 ATR)", "нове дно", "перший злив"]), "K": ("тестів того ж дна", ["0", "1", "2+"]),
         "G": ("глибина", ["3–4 ATR", "4–6 ATR", "6+ ATR"]), "W": ("хвіст", ["<25%", "25–50%", ">50%"]), "V": ("обсяг", ["<2×", "2–4×", "4×+"]), "S": ("швидкість", ["1 бар", "2–3", "4–6"]), "X": ("сила повернення", ["<0,25 ATR", "0,25–1", ">1 ATR"]),
         "I": ("RSI у дні", ["<20", "20–30", ">30"]), "F": ("від 7-ден. макс.", ["<10%", "10–20%", ">20%"]), "H": ("стоп", ["<1,5%", "1,5–3%", ">3%"]), "B": ("весь ринок", ["ні", "так"]), "L": ("денний рівень", ["ні", "так"]), "T": ("BTC підтвердив", ["ні", "так"]), "D": ("дивергенція", ["ні", "так"]), "U": ("великий тренд угору", ["ні", "так"])}
def load(path):
    d = pd.read_csv(path).drop_duplicates("open_time").sort_values("open_time")
    if "volume" not in d: d["volume"] = 0.0
    g = d.groupby(d.open_time // 3600 * 3600).agg(n=("open", "size"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index()
    return g
if len(sys.argv) > 4:                                           # режим «розкласти свіжі випадки» (OKX H1-файли без обсягу)
    for pth in sys.argv[4:]:
        d = pd.read_csv(pth).sort_values("open_time"); z = np.zeros(len(d)); ev = events(os.path.basename(pth), *(d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")), z, need_future=False)
        print(f"\n== {pth}: останні повернення")
        for x in ev[-8:]:
            print(f"  злив {pd.to_datetime(x['tf'], unit='s')} → вхід {pd.to_datetime(x['te'], unit='s')} {x['entry']:.1f} стоп {x['sl']:.1f} ({x['sp']:.2f}%) | макс +{x['mfe']:.1f}R, r3={x['r3']:+.1f} | " + "; ".join(f"{NAMES[k][0]}: {NAMES[k][1][x[k]]}" for k in "APRKGWSXIFH"))
ALL = []
for s in sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv")):
    if s in ("XAUUSDT", "XAGUSDT"): continue
    g = load(f"{D}/{s}/15m.csv"); g = g[g.n == 4]
    if len(g) < 2000: continue
    ALL += events(s, *(g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close", "volume"))); print(s, len(g), flush=True)
E = pd.DataFrame(ALL)
old = pd.read_csv(os.path.join(os.path.dirname(OUT), "bounce_trades.csv.gz")); old = old[old.side > 0][["sym", "te", "B", "L", "T", "D", "U"]] if "U" in old else None
if old is not None: E = E.merge(old, on=["sym", "te"], how="left")
for k in "BLTDU":
    if k not in E: E[k] = -1
    E[k] = E[k].fillna(-1).astype(int)
y = pd.to_datetime(E.te, unit="s").dt.year; E["P_"] = np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3")); E["grp"] = np.where(E.sym.isin(S42), "S", "C"); E["usd"] = 10 * (E.r3 - 0.10 / E.sp); E["usd2"] = 10 * (E.r2 - 0.10 / E.sp); E.to_csv(OUT, index=False)
print(f"\nвходів LONG: {len(E):,}; пошук (42 монети): {(E.grp=='S').sum():,}; контроль (30 інших): {(E.grp=='C').sum():,}. База: ${E.usd.mean():+.2f} на угоду (ціль 3R), виграшних {100*(E.r3>0).mean():.0f}%")
CELLS = [(g, p) for g in "SC" for p in ("P1", "P2", "P3")]
def cells(m, col="usd"):
    out = []
    for g, p in CELLS:
        x = E[m & (E.grp == g) & (E.P_ == p)]; out.append((len(x), x[col].mean() if len(x) else np.nan, (x.r3 > 0).mean() if len(x) else np.nan))
    return out
def fmt(cs): return " | ".join(f"{v:+5.2f} ({n})" if n else "   —  " for n, v, _ in cs[:3]) + "  ||  " + " | ".join(f"{v:+5.2f} ({n})" if n else "   —  " for n, v, _ in cs[3:])
def passed(cs, nmin=100): return all(n >= nmin and v > 0 for n, v, _ in cs)
print("\n######## 1. КОЖНА ОЗНАКА ОКРЕМО — $ на угоду (ціль 3R, комісія 0,10%), у дужках кількість.   ПОШУК: P1 | P2 | P3   ||   КОНТРОЛЬ: P1 | P2 | P3")
tested = found = 0; SINGLE = []
for k, (nm, labs) in NAMES.items():
    print(f" {k} · {nm}")
    for i, lab in enumerate(labs):
        m = E[k] == i
        if not m.any(): continue
        cs = cells(m); ok = passed(cs); tested += 1; found += ok; SINGLE.append((k, i))
        print(f"    {lab:22s} {fmt(cs)}   виграшних {100*np.nanmean([w for _, _, w in cs]):.0f}%" + ("   <<< ЗНАЙДЕНО" if ok else ""))
print(f" окремих умов перевірено {tested}, пройшли всі 6 клітинок: {found}")
print("\n######## 2. ПАРИ ОЗНАК — показано лише ті, що плюсові в усіх 6 клітинках (n ≥ 100 у кожній)")
t2 = f2 = 0; PASS = []
for (k1, i1), (k2, i2) in itertools.combinations(SINGLE, 2):
    if k1 == k2: continue
    m = (E[k1] == i1) & (E[k2] == i2); cs = cells(m); t2 += 1
    if passed(cs): f2 += 1; PASS.append((min(v for _, v, _ in cs), k1, i1, k2, i2, cs))
for mn, k1, i1, k2, i2, cs in sorted(PASS, key=lambda x: -x[0])[:40]:
    print(f"  {NAMES[k1][0]}: {NAMES[k1][1][i1]}  +  {NAMES[k2][0]}: {NAMES[k2][1][i2]}\n      {fmt(cs)}   найслабша клітинка {mn:+.2f}; виграшних {100*np.nanmean([w for _, _, w in cs]):.0f}%")
print(f" пар перевірено {t2}, пройшли всі 6 клітинок: {f2} (якби переваги не було зовсім, випадково пройшло б ≈ {t2/64:.0f} із {t2})")
print("\n######## 3. ТРІЙКИ: до найкращих 12 пар додаємо третю ознаку (ті самі вимоги)")
t3 = f3 = 0; P3_ = []
for mn, k1, i1, k2, i2, _ in sorted(PASS, key=lambda x: -x[0])[:12]:
    for k3, i3 in SINGLE:
        if k3 in (k1, k2): continue
        cs = cells((E[k1] == i1) & (E[k2] == i2) & (E[k3] == i3)); t3 += 1
        if passed(cs, 60): f3 += 1; P3_.append((min(v for _, v, _ in cs), f"{NAMES[k1][0]}: {NAMES[k1][1][i1]} + {NAMES[k2][0]}: {NAMES[k2][1][i2]} + {NAMES[k3][0]}: {NAMES[k3][1][i3]}", cs))
for mn, lab, cs in sorted(P3_, key=lambda x: -x[0])[:20]: print(f"  {lab}\n      {fmt(cs)}   найслабша клітинка {mn:+.2f}")
print(f" трійок перевірено {t3}, пройшли: {f3} (поріг n ≥ 60)")
