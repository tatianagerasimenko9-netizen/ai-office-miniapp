"""READ-ONLY. «ДРУГА НОГА»: пауза (прапор/прямокутник) після відскоку і пробій угору (27.11.2026, прохання власниці: «ходило від краю до краю і потім пробій — знайди закономірність»).
Приклад, з якого взято ідею: BTC 25–26.11.2026 — дно 57 258, відскок до ≈60 500, майже доба в боковику, потім пробій до 62 200.
ПРАВИЛА ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА; «прапор після імпульсу» — ЗОВНІШНЄ, числа наші):
 1) ЗЛИВ і ПОВЕРНЕННЯ — як у bounce_lab.py (мінімум за 72 год, падіння ≥ 3 ATR(H1-еквівалент); закриття вище максимуму бару зливу за ≤ 6 год).
 2) ПАУЗА: після повернення не менше N годин поспіль без нового максимуму (N = 6 або 12); за цей час ціна не опускалась нижче дна зливу і відкотила не більше Q руху «дно → максимум» (Q = 50% або 38%).
 3) ПРОБІЙ: бар закрився вище максимуму руху, не пізніше 72 год від повернення → LONG на закритті. Один вхід на один злив.
 Стоп: мінімум паузи − 0,1 ATR. Цілі 1R / 2R / 3R, утримання 48 год, стоп-першим, комісія 0,10%, ризик $10.
 Додаткові умови (окремо): U — вчорашнє денне закриття BTC вище середньої за 200 діб; N — вузька пауза (розмах ≤ 3 ATR(H1-екв.)).
 Таймфрейми: H1 і M15 (TF=900; ті самі вікна в годинах). Групи: пошук 42 монети / контроль 30 інших; періоди P1 2020–21, P2 2022–23, P3 2024–26. Зараховано лише плюс у всіх 6 клітинках.
Використання: [TF=900] bounce_leg2.py CANDLES_DIR S42 OUT"""
import os, sys
import numpy as np, pandas as pd
D, S42, OUT = sys.argv[1], set(sys.argv[2].split(",")), sys.argv[3]
TF = int(os.environ.get("TF", "3600")); M = 3600 // TF; KA = 3 * M ** 0.5; LB = 72 * M; WAIT = 6 * M; HOLD = 48 * M; LIFE = 72 * M
bd = pd.read_csv(f"{D}/BTCUSDT/15m.csv"); bd = bd.groupby(bd.open_time // 86400 * 86400).close.last(); BT = bd.index.to_numpy(float) + 86400; BU = (bd > bd.rolling(200).mean()).to_numpy(); BO = bd.rolling(200).mean().notna().to_numpy()
def big(te):
    i = np.searchsorted(BT, te, side="right") - 1; return int(i >= 0 and BO[i] and BU[i])
rows = []
for s in sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv")):
    if s in ("XAUUSDT", "XAGUSDT"): continue
    d = pd.read_csv(f"{D}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // TF * TF).agg(n=("open", "size"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g = g[g.n == TF // 900]
    if len(g) < 2000 * M: continue
    t, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "high", "low", "close")); n = len(c); pc = np.r_[c[0], c[:-1]]
    A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy()
    lo72 = pd.Series(l).rolling(LB).min().to_numpy(); hi24 = pd.Series(h).rolling(24 * M).max().to_numpy()
    fl = np.flatnonzero((l == lo72) & (hi24 - l >= KA * A)); fl = fl[(fl >= LB + 20) & (fl + LIFE + HOLD + 2 < n)]; busy = -1
    for f in fl:
        if f <= busy: continue
        ent = None
        for j in range(f + 1, f + 1 + WAIT):
            if l[j] < l[f]: break
            if c[j] > h[f]: ent = j; break
        if ent is None: continue
        busy = ent
        for NP in (6, 12):
            for Q in (0.5, 0.382):
                hm = h[f:ent + 1].max(); hi_bar = ent; plow = np.inf; got = None
                for j in range(ent + 1, ent + LIFE):
                    if l[j] < l[f]: break
                    if h[j] > hm:
                        if j - hi_bar > NP * M and c[j] > hm and plow >= hm - Q * (hm - l[f]): got = (j, plow, hm); break
                        if c[j] > hm or j - hi_bar <= NP * M or plow < hm - Q * (hm - l[f]): hm = max(hm, h[j]); hi_bar = j; plow = np.inf; continue
                        hm = h[j]; hi_bar = j; plow = np.inf; continue
                    plow = min(plow, l[j])
                if not got: continue
                j, plow, hm = got; e = c[j]; sl = plow - 0.1 * A[j]; risk = e - sl
                if not A[j] > 0 or not 0.0005 <= risk / e <= 0.25: continue
                H_ = h[j + 1:j + 1 + HOLD]; L_ = l[j + 1:j + 1 + HOLD]; hs = L_ <= sl; isx = int(np.argmax(hs)) if hs.any() else 10**6; res = []
                for tg in (1, 2, 3):
                    ht = H_ >= e + tg * risk; itx = int(np.argmax(ht)) if ht.any() else 10**6
                    res.append(-1.0 if (isx <= itx and isx < 10**6) else (float(tg) if itx < 10**6 else (c[j + HOLD] - e) / risk))
                rows.append((s, t[j] + TF, NP, Q, 100 * risk / e, res[0], res[1], res[2], big(t[j] + TF), int((hm - plow) <= 3 * M ** 0.5 * A[j])))
    print(s, flush=True)
E = pd.DataFrame(rows, columns=["sym", "te", "NP", "Q", "sp", "r1", "r2", "r3", "U", "N"]); y = pd.to_datetime(E.te, unit="s").dt.year
E["P"] = np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3")); E["grp"] = np.where(E.sym.isin(S42), "S", "C"); E.to_csv(OUT, index=False)
print(f"\n«ДРУГА НОГА» TF={TF//60} хв: записів {len(E):,}; медіанний стоп {E.sp.median():.2f}%.   $ на угоду (комісія 0,10%), у дужках n.   ПОШУК: P1 | P2 | P3   ||   КОНТРОЛЬ: P1 | P2 | P3")
tot = ok_n = 0
for NP in (6, 12):
    for Q in (0.5, 0.382):
        for lab, m in (("без умов", E.sp > 0), ("U великий тренд угору", E.U == 1), ("N вузька пауза", E.N == 1), ("U+N", (E.U == 1) & (E.N == 1))):
            for tg in (1, 2, 3):
                x = E[(E.NP == NP) & (E.Q == Q) & m]; cs = []
                for g_ in "SC":
                    for p in ("P1", "P2", "P3"):
                        z = x[(x.grp == g_) & (x.P == p)]; cs.append((len(z), 10 * (z[f"r{tg}"] - 0.10 / z.sp).mean() if len(z) else np.nan))
                ok = all(n_ >= 60 and v > 0 for n_, v in cs); tot += 1; ok_n += ok
                print(f" пауза ≥{NP} год, відкат ≤{int(Q*100)}%, {lab:22s} ціль {tg}R: " + " | ".join(f"{v:+5.2f} ({n_})" for n_, v in cs[:3]) + "  ||  " + " | ".join(f"{v:+5.2f} ({n_})" for n_, v in cs[3:]) + ("   <<< ПЛЮС У ВСІХ 6" if ok else ""))
print(f"\nПІДСУМОК: варіантів {tot}; плюс у всіх 6 клітинках: {ok_n}")
