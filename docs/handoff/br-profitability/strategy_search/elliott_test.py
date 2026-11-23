"""READ-ONLY. Хвилі Еліота — ОБ'ЄКТИВНА (причинна) реалізація і тест на історії (23.11.2026, прохання власниці: знайти перевірені публічні правила і прогнати на історії).
ПРАВИЛА: див. docs/strategies/ELLIOTT_PUBLIC_RULES_UA.md (ЗОВНІШНЄ: Frost & Prechter / eSignal / O'Reilly «Mastering Elliott Wave» / StockCharts). Наші припущення — ГІПОТЕЗА / OUR_IMPLEMENTATION: пошук хвиль через ATR-зигзаг (поріг K·ATR14, K∈{2,3,4}), пивоти ПІДТВЕРДЖУЮТЬСЯ тільки після розвороту на K·ATR (без заглядання вперед),
 вхід на відкритті наступного бару, стопи/цілі нижче, SL-першим, ліміт утримання H4 60 / D1 30 барів, комісія FEE за круг, ризик $10.
 СЕТАП A «вхід у хвилю 3» (після завершення хвилі 2): LONG, коли підтверджено послідовність мінімум P0 → максимум P1 → мінімум P2 і P2>P0 (хвиля 2 не заходить за початок хвилі 1 — ЖОРСТКЕ правило). Дзеркально SHORT.
   варіанти: A0 лише це правило; A1 + відкат 38,2–78,6% хвилі 1; A2 + відкат 50–61,8% (гайдлайн). Стоп за P0; ціль P2 + 1,618·(P1−P0) (гайдлайн для хвилі 3).
 СЕТАП B «кінець хвилі 5» (розворот): після 5 хвиль угору P0↓ P1↑ P2↓ P3↑ P4↓ P5↑: SHORT, коли виконані ЖОРСТКІ правила: P2>P0; хвиля 3 не найкоротша серед 1,3,5; P4>P1 (немає перекриття хвилі 4 і 1). Стоп за P5, ціль P4 (корекція до зони хвилі 4). Дзеркально LONG.
   Контроль: ті самі п'ять хвиль, але з ПОРУШЕННЯМ жорстких правил (valid=0) — чи правила мають значення.
 Контекст: «з трендом» — сторона MA200 збігається з напрямом угоди (як у patterns_lab).
Використання: elliott_test.py CANDLES_DIR SYMS FEE OUT_PREFIX"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, FEE, OUT = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]), sys.argv[4]
PER = {"H4": 14400, "D1": 86400}; HOLD = {"H4": 60, "D1": 30}; KS = (2, 3, 4)
def bars(sym, per):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // per * per).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}
def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))); return pd.Series(tr).rolling(14).mean().to_numpy()
def zigzag(h, l, A, K):
    """Причинний зигзаг: список (i_confirm, i_pivot, price, typ) typ=+1 максимум / −1 мінімум. Пивот видно лише з бару підтвердження."""
    n = len(h); out = []; trend = 0; eh, ehi, el, eli = h[0], 0, l[0], 0
    for i in range(1, n):
        if not A[i] > 0: continue
        thr = K * A[i]
        if trend == 0:
            if h[i] > eh: eh, ehi = h[i], i
            if l[i] < el: el, eli = l[i], i
            if eh - l[i] >= thr and ehi < i: out.append((i, ehi, eh, 1)); trend = -1; el, eli = l[i], i
            elif h[i] - el >= thr and eli < i: out.append((i, eli, el, -1)); trend = 1; eh, ehi = h[i], i
        elif trend == 1:
            if h[i] > eh: eh, ehi = h[i], i
            if eh - l[i] >= thr: out.append((i, ehi, eh, 1)); trend = -1; el, eli = l[i], i
        else:
            if l[i] < el: el, eli = l[i], i
            if h[i] - el >= thr: out.append((i, eli, el, -1)); trend = 1; eh, ehi = h[i], i
    return out
def walk(h, l, c, i0, side, e, sl, tp, H):
    risk = abs(e - sl)
    for j in range(i0, min(len(c), i0 + H)):
        if (l[j] <= sl) if side > 0 else (h[j] >= sl): return -1.0, "SL", j - i0
        if (h[j] >= tp) if side > 0 else (l[j] <= tp): return side * (tp - e) / risk, "TP", j - i0
    j = min(len(c) - 1, i0 + H - 1); return side * (c[j] - e) / risk, "TIME", j - i0
rows = []
for tf in PER:
    for sym in SYMS:
        b = bars(sym, PER[tf]); o, h, l, c, t = b["open"], b["high"], b["low"], b["close"], b["open_time"]; A = atr14(h, l, c); n = len(c); M = pd.Series(c).rolling(200).mean().to_numpy()
        for K in KS:
            Z = zigzag(h, l, A, K); busy = {}
            for z in range(len(Z)):
                ic, ip, pr, ty = Z[z]
                if ic >= n - 2 or not M[ic] > 0: continue
                def emit(setup, side, sl, tp, valid):
                    e = o[ic + 1]; risk = (e - sl) * side
                    if risk <= 0 or risk / e < 0.0005 or risk / e > 0.25: return
                    if (tp - e) * side <= 0: return
                    if ic < busy.get((setup, valid), 0): return
                    R, why, held = walk(h, l, c, ic + 1, side, e, sl, tp, HOLD[tf]); R -= FEE / (risk / e); busy[(setup, valid)] = ic + 1 + held + 1
                    ctx = "з трендом" if ((side > 0 and c[ic] > M[ic]) or (side < 0 and c[ic] < M[ic])) else "проти тренду"
                    rows.append((tf, K, sym, setup, side, valid, ctx, float(t[ic + 1]), int(pd.Timestamp(t[ic + 1], unit="s").year), R, why, held, risk / e))
                if z >= 2:                                   # СЕТАП A: P0, P1, P2 (P2 щойно підтверджено)
                    P0, P1, P2 = Z[z - 2][2], Z[z - 1][2], pr; side = 1 if ty == -1 else -1                       # ty=-1: P2 мінімум → LONG
                    w1 = abs(P1 - P0)
                    if w1 > 0 and ((side > 0 and P2 > P0) or (side < 0 and P2 < P0)):
                        ret = abs(P1 - P2) / w1; tp = P2 + side * 1.618 * w1
                        emit("A0", side, P0, tp, 1)
                        if 0.382 <= ret <= 0.786: emit("A1", side, P0, tp, 1)
                        if 0.5 <= ret <= 0.618: emit("A2", side, P0, tp, 1)
                if z >= 5:                                   # СЕТАП B: P0..P5 (P5 щойно підтверджено); P5 максимум → SHORT (після п'яти хвиль угору)
                    p = [Z[z - 5 + k][2] for k in range(6)]; up = ty == 1; side = -1 if up else 1
                    s = 1 if up else -1                      # напрямок імпульсу
                    W1, W3, W5 = s * (p[1] - p[0]), s * (p[3] - p[2]), s * (p[5] - p[4])
                    if min(W1, W3, W5) <= 0: continue        # не імпульс
                    r1 = s * (p[2] - p[0]) > 0; r4 = s * (p[4] - p[1]) > 0                    # правило 1 (хвиля 2 не за початок хвилі 1), правило 3 (хвиля 4 не перекриває хвилю 1)
                    valid = int(r1 and (not (W3 < W1 and W3 < W5)) and r4)
                    emit("B", side, p[5], p[4], valid)
W = pd.DataFrame(rows, columns=["tf", "K", "sym", "setup", "side", "valid", "ctx", "ts", "y", "r", "why", "held", "risk_pct"]); W["usd"] = 10 * W.r
W.to_csv(OUT + "_trades.csv", index=False)
print(f"ХВИЛІ ЕЛІОТА: об'єктивна реалізація, комісія {FEE*100:.2f}% за круг, ризик $10, монет {len(SYMS)}, 2022–2026. Усі сітки (K=2,3,4 ATR; H4, D1) показано, нічого не підбиралось.")
for tf in PER:
    print(f"\n######## {tf}")
    for (K, st, vl), g in W[W.tf == tf].groupby(["K", "setup", "valid"]):
        py = g.groupby("y").usd.sum().round(0).astype(int).to_dict(); wt = g[g.ctx == "з трендом"].usd.sum(); ag = g[g.ctx != "з трендом"].usd.sum()
        print(f" K={K} {st}{'' if st != 'B' else (' правила виконано' if vl else ' ПРАВИЛА ПОРУШЕНО')}: {len(g):5d} угод, ${g.usd.sum():+8.0f}, на угоду ${g.usd.mean():+.2f}, виграшних {100*(g.usd>0).mean():.0f}%, ціль {100*(g.why=='TP').mean():.0f}%, з трендом ${wt:+.0f} / проти ${ag:+.0f}, по роках {py}")
