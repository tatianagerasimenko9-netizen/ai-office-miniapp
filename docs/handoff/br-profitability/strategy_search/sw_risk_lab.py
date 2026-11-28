"""READ-ONLY. СВІНГ: ЯК ЗМЕНШИТИ ВТРАТИ — відсів сигналів і раннє обрізання збитку (28.11.2026, прохання власниці: «максимально зменшити втрати, шукай, що ми не перевірили»).
Усе записано ДО запуску. ГІПОТЕЗА (наша автоматизація). Нічого не вмикає.
Угоди: СВІНГ як у sw_exitlab.py BASE (H4, 3 рукави + MA200, стоп 3×ATR, ціль 6R, до 60 барів, одна позиція на монету), 42 монети, 2020–2026, $10, комісія 0,10%.
Рахуємо двічі: УСІ ДНІ і лише СИЛЬНІ ДНІ (сигнал у ср–пт за Києвом — правило з розділів BW/BY).
А. ВІДСІВ (сигнал не беремо, якщо умова виконана; раніше НЕ перевірялось):
  F1 пробій у слабкий день      рукав «пробій» і сигнал у пн, вт, сб, нд
  F2 проти BTC (H4)             бік угоди проти сторони BTC відносно його MA200 на H4
  F3 проти BTC (50 днів)        бік угоди проти сторони BTC відносно його середньої за 300 барів H4
  F4 велика свічка              розмах сигнального бару > 2×ATR
  F5 перегрів                   ціна далі ніж 8 ATR від MA200 у бік угоди
  F6 чорна смуга                з 10 останніх ЗАКРИТИХ угод СВІНГу (всі монети) 8 і більше — стопи
  F7 натовп                     у тому ж барі той самий бік дали 10 і більше монет
  F8 березень/грудень           сигнал у березні або грудні
  F9 рухлива монета             ATR/ціна ≥ 2,3% (відоме; тут для порівняння і поєднань)
  F10 повтор після стопа        та сама монета мала стоп за останні 24 год
  F11 протилежний недавно       по цій монеті за останні 5 діб був сигнал у протилежний бік
  F12 тренд монети слабкий      MA200 за останні 30 барів змінилась менше ніж на 0,5 ATR (боковик)
Б. РАННЄ ОБРІЗАННЯ ЗБИТКУ (стосується всіх угод; вихід на закритті бару):
  C1 кінець 1-ї доби (6 барів): результат ≤ −0,5R → закрити      C2 те саме з порогом −0,3R
  C3 кінець 2-ї доби (12 барів): ≤ −0,5R → закрити                 C4 кінець 3-ї доби (18 барів): ≤ 0 → закрити
  C5 стоп 2×ATR замість 3 (ціль та сама ціна, ризик $10)           C6 стоп 4×ATR замість 3
«КОРИСНЕ» = у КОЖНОМУ з трьох періодів (P1 2020–21, P2 2022–23, P3 2024–26) сума $ не менша за базу І просадка менша; для відсіву додатково: відсіяні сигнали
в мінусі або близько нуля (≤ +$0,3 на сигнал) у кожному періоді. Усе інше — НЕ ПІДТВЕРДЖЕНО.
Використання: sw_risk_lab.py CANDLES_DIR SYMS"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS = sys.argv[1], sys.argv[2].split(",")
PER = 14400; H = 60; K = 6.0; FEE = 0.001
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
def h4(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    return d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
b = h4("BTCUSDT").set_index("open_time"); bside200 = np.sign(b.close - b.close.rolling(200).mean()); bside300 = np.sign(b.close - b.close.rolling(300).mean())
CUTS = {"C1": (6, -0.5), "C2": (6, -0.3), "C3": (12, -0.5), "C4": (18, 0.0)}
def sim(o, h, l, c, i, side, e, risk0, n, smult=3.0, cut=None):
    """Повертає (R відносно ФАКТИЧНОГО ризику, індекс виходу). Ціль — та сама ЦІНА, що в базі (e ± 6×risk0)."""
    risk = risk0 * smult / 3.0; tp = e + side * K * risk0; sl = e - side * risk
    for j in range(i + 1, min(n, i + H + 1)):
        if (l[j] <= sl) if side > 0 else (h[j] >= sl): return -1.0, j
        if (h[j] >= tp) if side > 0 else (l[j] <= tp): return side * (tp - e) / risk, j
        if cut and j - i == cut[0] and side * (c[j] - e) / risk <= cut[1]: return side * (c[j] - e) / risk, j
    j = min(n - 1, i + H); return side * (c[j] - e) / risk, j
rows = []
for sym in SYMS:
    if not os.path.exists(f"{CD}/{sym}/15m.csv"): continue
    g = h4(sym); t, o, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
    if n < 400: continue
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); m200 = sma(c, 200)
    up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
    Lb, Sb = ev(c > hi20) & up, ev(c < lo20) & dn
    L = Lb | ev((r2 < 10) & up) | ev((c < lb) & up); Sx = Sb | ev((r2 > 90) & dn) | ev((c > ub) & dn)
    b2 = bside200.reindex(t).to_numpy(); b3 = bside300.reindex(t).to_numpy()
    i = 201
    while i < n - 2:
        if L[i] == Sx[i] or not A[i] > 0: i += 1; continue
        side = 1 if L[i] else -1; e = o[i + 1]; risk0 = 3.0 * A[i]
        if risk0 <= 0 or risk0 / e < 0.0005: i += 1; continue
        r, j = sim(o, h, l, c, i, side, e, risk0, n); fee = FEE / (risk0 / e)
        row = {"sym": sym, "side": side, "ts": t[i + 1], "tx": t[j] + PER, "r": r - fee, "arm": int(Lb[i] if side > 0 else Sb[i]),
               "F2": side * b2[i] < 0, "F3": side * b3[i] < 0, "F4": (h[i] - l[i]) > 2 * A[i], "F5": side * (c[i] - m200[i]) / A[i] > 8,
               "F9": A[i] / c[i] >= 0.023, "F12": abs(m200[i] - m200[i - 30]) < 0.5 * A[i]}
        for nm, cut in CUTS.items(): row[nm] = sim(o, h, l, c, i, side, e, risk0, n, cut=cut)[0] - fee
        for nm, sm in (("C5", 2.0), ("C6", 4.0)): row[nm] = sim(o, h, l, c, i, side, e, risk0, n, smult=sm)[0] - FEE / (risk0 * sm / 3.0 / e)
        rows.append(row); i = max(j, i + 1)
W = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True); k = pd.to_datetime(W.ts, unit="s", utc=True).dt.tz_convert("Europe/Kyiv")
W["y"] = k.dt.year; W["dow"] = k.dt.day_of_week; W["mon"] = k.dt.month; W["good"] = W.dow.isin([2, 3, 4]); W["P"] = np.where(W.y <= 2021, "P1", np.where(W.y <= 2023, "P2", "P3")); W["usd"] = 10 * W.r
W["F1"] = (W.arm == 1) & ~W.good; W["F7"] = W.groupby(["ts", "side"]).sym.transform("count") >= 10; W["F8"] = W.mon.isin([3, 12])
ts, tx, rr, sy, sd = W.ts.to_numpy(), W.tx.to_numpy(), W.r.to_numpy(), W.sym.to_numpy(), W.side.to_numpy(); order = np.argsort(tx); txs = tx[order]; stop_s = (rr[order] <= -0.95).astype(int)
F6 = np.zeros(len(W), bool); F10 = np.zeros(len(W), bool); F11 = np.zeros(len(W), bool); last_stop = {}; last_sig = {}
cs = np.r_[0, np.cumsum(stop_s)]
for q in range(len(W)):
    m = int(np.searchsorted(txs, ts[q], side="right"))
    if m >= 10: F6[q] = cs[m] - cs[m - 10] >= 8
for q in np.argsort(ts, kind="stable"):
    p = last_sig.get(sy[q])
    if p is not None and sd[p] != sd[q] and ts[q] - ts[p] <= 5 * 86400: F11[q] = True
    last_sig[sy[q]] = q
ev_list = sorted([(ts[q], 1, q) for q in range(len(W))] + [(tx[q], 0, q) for q in range(len(W)) if rr[q] <= -0.95])
for tt, kind, q in ev_list:
    if kind == 0: last_stop[sy[q]] = tt
    elif sy[q] in last_stop and tt - last_stop[sy[q]] <= 86400: F10[q] = True
W["F6"], W["F10"], W["F11"] = F6, F10, F11
PS = ("P1", "P2", "P3")
def st(x, col="usd"):
    z = x.sort_values("ts"); eq = z[col].cumsum(); return len(z), z[col].sum(), (eq - eq.cummax()).min() if len(z) else 0.0
NAMES = {"F1": "пробій у слабкий день", "F2": "проти BTC (H4)", "F3": "проти BTC (50 днів)", "F4": "велика свічка", "F5": "перегрів", "F6": "чорна смуга", "F7": "натовп", "F8": "березень/грудень",
         "F9": "рухлива монета", "F10": "повтор після стопа", "F11": "протилежний недавно", "F12": "боковик"}
for scope, X in (("УСІ ДНІ", W), ("ЛИШЕ СИЛЬНІ ДНІ (ср–пт)", W[W.good])):
    n0, s0, d0 = st(X); bp = {p: st(X[X.P == p]) for p in PS}; good = []
    print(f"\n################ {scope}: база {n0} сигналів, сума ${s0:+.0f}, на сигнал {s0/n0:+.2f}, просадка ${d0:.0f}, стопів {100*(X.r<=-0.95).mean():.0f}% | " + " | ".join(f"{p}: ${bp[p][1]:+.0f}, просадка {bp[p][2]:.0f}" for p in PS))
    print("А. ВІДСІВ:  відсіяно% | відсіяні: $ на сигнал (P1/P2/P3) | що лишилось: сума, на сигнал, просадка | сума по періодах проти бази")
    for f in [f"F{i}" for i in range(1, 13)]:
        if scope.startswith("ЛИШЕ") and f == "F1": continue
        D = X[X[f]]; Kp = X[~X[f]]
        if len(D) < 30: print(f"  {f:4s} {NAMES[f]:24s}: відсіяно {len(D)} — замало"); continue
        nk, sk, dk = st(Kp); dp = {p: D[D.P == p].usd.mean() if (D.P == p).sum() >= 20 else np.nan for p in PS}; kp = {p: st(Kp[Kp.P == p]) for p in PS}
        ok = all(dp[p] == dp[p] and dp[p] <= 0.3 for p in PS) and all(kp[p][1] >= bp[p][1] - 1e-9 or kp[p][2] > bp[p][2] for p in PS) and all(kp[p][2] >= bp[p][2] for p in PS)
        if ok: good.append(f"{f} {NAMES[f]}")
        print(f"  {f:4s} {NAMES[f]:24s}: {100*len(D)/n0:4.0f}% | {D.usd.mean():+.2f} (" + "/".join(f"{dp[p]:+.2f}" for p in PS) + f") | ${sk:+.0f}, {sk/nk:+.2f}, просадка {dk:.0f} | " + " ".join(f"{p}: {kp[p][1]-bp[p][1]:+.0f} (просадка {kp[p][2]:.0f})" for p in PS) + ("   <<< КОРИСНЕ" if ok else ""))
    print("Б. ОБРІЗАННЯ ЗБИТКУ:  сума, на сигнал, просадка, стопів% | сума по періодах проти бази")
    for cn, lab in (("C1", "1-ша доба ≤ −0,5R"), ("C2", "1-ша доба ≤ −0,3R"), ("C3", "2-га доба ≤ −0,5R"), ("C4", "3-тя доба ≤ 0"), ("C5", "стоп 2×ATR"), ("C6", "стоп 4×ATR")):
        Y = X.assign(u=10 * X[cn]); n1, s1, d1 = st(Y, "u"); yp = {p: st(Y[Y.P == p], "u") for p in PS}
        ok = all(yp[p][1] >= bp[p][1] and yp[p][2] > bp[p][2] for p in PS)
        if ok: good.append(f"{cn} {lab}")
        print(f"  {cn} {lab:20s}: ${s1:+.0f}, {s1/n1:+.2f}, просадка {d1:.0f}, повних стопів {100*(Y[cn]<=-0.95).mean():.0f}% | " + " ".join(f"{p}: {yp[p][1]-bp[p][1]:+.0f} (просадка {yp[p][2]:.0f})" for p in PS) + ("   <<< КОРИСНЕ" if ok else ""))
    print(f"ПІДСУМОК ({scope}): " + ("; ".join(good) if good else "НІЧОГО не пройшло критерій"))
