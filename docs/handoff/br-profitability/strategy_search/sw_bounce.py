"""READ-ONLY. ШОРТ СВІНГУ + СИГНАЛ ВІДСКОКУ: що робити з відкритим шортом, коли по цій монеті приходить сигнал розвороту вгору (27.11.2026, логіка власниці:
«зафіксуйся, бо можливий розворот; потім можна відкрити знову; або взяти лонг на інтрадей, а шорт не закривати, бо стоп вище — перевір усі варіанти»).
Шорти СВІНГ — як у sw_exitlab.py BASE (H4, стоп 3 ATR, ціль 6R, 60 барів, комісія FEE). Сигнали відскоку — з data/bounce_feat.csv.gz (H1; правила bounce_lab/bounce_feat).
ВАРІАНТИ ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА):
 Сигнал (перший за життя угоди):  S1 будь-яке ПОВЕРНЕННЯ по цій монеті | S2 повернення + «весь ринок» (B) | S3 трійка (дно тестували ≥2 рази + падіння >20% від 7-ден. максимуму + BTC підтвердив).
 Фільтр: усі угоди | шорт на момент сигналу в плюсі ≥ +1R | ≥ +2R.
 Дії в момент сигналу (ціна = ціна входу відскоку):
   HOLD     нічого не робити (як зараз).
   CLOSE    закрити шорт повністю.
   HALF     закрити половину, решта — як було.
   RE-A     закрити; відкрити шорт знову, якщо годинна свічка закрилась нижче стопа відскоку (розворот не вдався); далі старий стоп, стара ціль, старий строк.
   RE-B     закрити; відкрити шорт знову в момент, коли лонг-відскок завершився (ціль 3R, стоп або 48 год), якщо ціна нижче старого стопа шорта; далі старий стоп/ціль/строк.
   HEDGE    шорт тримати і додатково взяти лонг-відскок на $10 ризику (стоп за дном, ціль 3R, 48 год).  HEDGE½ — лонг на $5.
   HALF+H   закрити половину шорта і взяти лонг на $5.
 Додатково «що було із шортом після сигналу»: як часто він закінчився краще / гірше, ніж був у момент сигналу; як часто дійшов до стопа.
Показники: сума $ по зачеплених угодах для кожної дії, по періодах P1/P2/P3, різниця до HOLD. Повторний вхід = ще одна комісія.
Використання: sw_bounce.py CANDLES_DIR SYMS FEE FEAT_CSV_GZ"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, FEE, FEAT = sys.argv[1], [s for s in sys.argv[2].split(",") if os.path.exists(f"{sys.argv[1]}/{s}/15m.csv")], float(sys.argv[3]), sys.argv[4]
PER = 14400; H = 60; K = 6.0; S = 3.0
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; return pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
F = pd.read_csv(FEAT); F["S1"] = 1; F["S2"] = (F.B == 1).astype(int); F["S3"] = ((F.K == 2) & (F.F == 2) & (F["T"] == 1)).astype(int)
ACTS = ["HOLD", "CLOSE", "HALF", "RE-A", "RE-B", "HEDGE", "HEDGE½", "HALF+H"]; rows = []
for sym in SYMS:
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    t, o, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c); A = atr(h, l, c); m200 = sma(c, 200)
    g1 = d.groupby(d.open_time // 3600 * 3600).agg(high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); t1, h1, l1, c1 = (g1[k].to_numpy(float) for k in ("open_time", "high", "low", "close"))
    fs = F[F.sym == sym].sort_values("te"); fte = fs.te.to_numpy(float)
    dn = c < m200; lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy(); r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub = mb + 2 * sb
    up = c > m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lb = mb - 2 * sb
    L = (ev(c > hi20) & up) | ev((r2 < 10) & up) | ev((c < lb) & up); Sx = (ev(c < lo20) & dn) | ev((r2 > 90) & dn) | ev((c > ub) & dn)
    def follow(k0, e2, sl_px, tp_px, t_end):
        """Шорт від H1-бару k0 (вхід e2 на його закритті) зі старими стопом/ціллю до t_end. Повертає ціну виходу."""
        k = k0 + 1
        while k < len(c1) and t1[k] < t_end:
            if h1[k] >= sl_px: return sl_px
            if l1[k] <= tp_px: return tp_px
            k += 1
        return c1[min(k, len(c1)) - 1]
    i = 201
    while i < n - 2:
        if L[i] == Sx[i] or not A[i] > 0: i += 1; continue
        side = 1 if L[i] else -1; e = o[i + 1]; risk = S * A[i]
        if risk <= 0 or risk / e < 0.0005: i += 1; continue
        res = None; j = i + 1
        while j < n and j <= i + H:
            adv = side * ((l[j] if side > 0 else h[j]) - e) / risk; fav = side * ((h[j] if side > 0 else l[j]) - e) / risk
            if adv <= -1: res = -1.0; break
            if fav >= K: res = K; break
            j += 1
        if res is None: jj = min(j, n - 1); res = side * (c[jj] - e) / risk
        t_in = t[i + 1]; t_out = t[min(j, n - 1)] + PER; t_end = t[min(i + H, n - 1)] + PER; fee = FEE / (risk / e)
        if side < 0:
            a0 = np.searchsorted(fte, t_in + 3600, side="left"); a1 = np.searchsorted(fte, t_out - 1, side="right")
            for sg in ("S1", "S2", "S3"):
                x = fs.iloc[a0:a1]; x = x[x[sg] == 1]
                if not len(x): continue
                q = x.iloc[0]; p = float(q.entry); r_sig = (e - p) / risk; sl_px = e + risk; tp_px = e - K * risk; k0 = int(np.searchsorted(t1, q.te - 3600))       # бар входу відскоку (його закриття = te)
                if k0 >= len(c1) - 2: continue
                lr = float(q.r3) - 0.10 / float(q.sp)                                             # результат лонга, R (ризик $10), з комісією
                # RE-A: перше годинне закриття нижче стопа відскоку
                ra = r_sig - fee; kk = k0 + 1
                while kk < len(c1) and t1[kk] < t_end:
                    if h1[kk] >= sl_px: break                                                     # без нас ціна дійшла б до стопа — повторного входу вже немає сенсу
                    if c1[kk] < q.sl: ra = r_sig - fee + (c1[kk] - follow(kk, c1[kk], sl_px, tp_px, t_end)) / risk - fee; break
                    kk += 1
                # RE-B: момент завершення лонга
                btp = p + 3 * (p - q.sl); kk = k0 + 1; px = None
                while kk < len(c1) and kk <= k0 + 48 and t1[kk] < t_end:
                    if l1[kk] <= q.sl: px = float(q.sl); break
                    if h1[kk] >= btp: px = btp; break
                    kk += 1
                else:
                    if kk < len(c1) and t1[kk] < t_end: px = c1[kk]
                rb = r_sig - fee
                if px is not None and px < sl_px and kk < len(c1): rb = r_sig - fee + (px - follow(kk, px, sl_px, tp_px, t_end)) / risk - fee
                base = res - fee
                rows.append((sym, sg, t_out, r_sig, res, base, r_sig - fee, 0.5 * (r_sig - fee) + 0.5 * base, ra, rb, base + lr, base + 0.5 * lr, 0.5 * (r_sig - fee) + 0.5 * base + 0.5 * lr, lr))
        i = max(j, i + 1)
    print(sym, flush=True)
T = pd.DataFrame(rows, columns=["sym", "sig", "tx", "r_sig", "res"] + ACTS + ["long"]); y = pd.to_datetime(T.tx, unit="s").dt.year; T["P"] = np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3")); T["y"] = y
NM = {"S1": "будь-яке повернення по монеті", "S2": "повернення + весь ринок", "S3": "трійка (дно ≥2 тестів + падіння >20% + BTC)"}
for sg in ("S1", "S2", "S3"):
    for fl, fn in ((-99, "усі шорти"), (1, "шорт у плюсі ≥ +$10"), (2, "шорт у плюсі ≥ +$20")):
        x = T[(T.sig == sg) & (T.r_sig >= fl)]
        if len(x) < 30: print(f"\n######## {NM[sg]} · {fn}: лише {len(x)} угод — замало"); continue
        print(f"\n######## {NM[sg]} · {fn}: {len(x)} шортів.  У момент сигналу шорт у середньому {10*x.r_sig.mean():+.1f}$; у кінці (HOLD) {10*x.res.mean():+.1f}$")
        print(f"   після сигналу: закінчився КРАЩЕ, ніж був у момент сигналу — {100*(x.res > x.r_sig).mean():.0f}%; гірше — {100*(x.res < x.r_sig).mean():.0f}%; дійшов до стопа — {100*(x.res <= -1).mean():.0f}%; дійшов до цілі — {100*(x.res >= 6).mean():.0f}%; сам лонг-відскок: {10*x.long.mean():+.2f}$ на угоду, виграшних {100*(x.long>0).mean():.0f}%")
        b = x.HOLD.sum() * 10
        for a in ACTS:
            pp = (10 * x.groupby("P")[a].sum()).reindex(["P1", "P2", "P3"], fill_value=0.0); pb = (10 * x.groupby("P").HOLD.sum()).reindex(["P1", "P2", "P3"], fill_value=0.0); yb = int(((10 * x.groupby("y")[a].sum()) > (10 * x.groupby("y").HOLD.sum())).sum())
            ok = a != "HOLD" and all(pp[k] > pb[k] for k in pp.index)
            print(f"   {a:7s} сума {10*x[a].sum():+9.0f}$  проти HOLD {10*x[a].sum()-b:+8.0f}$  на угоду {10*x[a].mean():+6.2f} | P1 {pp['P1']:+7.0f} P2 {pp['P2']:+7.0f} P3 {pp['P3']:+7.0f} | років краще {yb}/{x.y.nunique()}" + ("   <<< краще за HOLD в усіх трьох періодах" if ok else ""))
