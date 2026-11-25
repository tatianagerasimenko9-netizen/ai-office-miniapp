"""READ-ONLY. Проп-рахунок: чистий результат за 24 місяці з урахуванням внесків і повторних спроб (25.11.2026). Ідея: на перевірці ризикуємо лише внеском, тому там можна брати більший ризик, а на оплачуваному рахунку — менший.
Рахунок $50 000, 2 етапи (10% і 5%, денний ліміт 5%, загальний 10% від початкового), внесок FEE за спробу (ЗОВНІШНЄ: ≈$400–450 за оглядами), виплата 80% раз на 30 днів, баланс після виплати повертається до початкового.
Провал перевірки або порушення на оплачуваному рахунку → новий внесок і нова спроба з наступного дня. СПРОЩЕННЯ (ГІПОТЕЗА): рахуємо закриті угоди по днях (реальні правила суворіші). Старт кожні 14 днів, горизонт 24 міс.
Використання: prop_ev.py SW_TRADES [TD_TRADES TSM_DAILY]"""
import sys, numpy as np, pandas as pd
A = 50000.0; FEE = 450.0; DL, ML = .05, .10; HOR = 730
sw = pd.read_csv(sys.argv[1]); g = sw[sw.atr_pct < 0.023]; idx = np.arange(int((sw.ts.min()) // 86400), int((sw.ts + sw.hold * 14400).max() // 86400) + 1)
R_sw = (g.r).groupby((g.ts + g.hold * 14400) // 86400).sum().reindex(idx, fill_value=0.0).to_numpy()          # у R на день
def sim(R, s, rc, rf, hor=HOR):
    """R — денний результат на $1 ризику; rc — ризик на перевірці, rf — на оплачуваному рахунку."""
    i = s; end = min(len(R), s + hor); pay = 0.0; fees = 0.0; first = None; passes = 0; attempts = 0
    while i < end:
        fees += FEE; attempts += 1; ok = True
        for tgt in (.10, .05):
            bal = A
            while True:
                if i >= end: ok = False; break
                p = R[i] * rc; i += 1; bal += p
                if p <= -DL * A or bal <= A * (1 - ML): ok = False; break
                if bal >= A * (1 + tgt): break
            if not ok: break
        if not ok: continue
        passes += 1; first = first if first is not None else i - s; bal = A; k = 0
        while i < end:
            p = R[i] * rf; i += 1; k += 1; bal += p
            if p <= -DL * A or bal <= A * (1 - ML): break
            if k % 30 == 0 and bal > A: pay += 0.8 * (bal - A); bal = A
    return pay, fees, first, attempts, passes
def table(R, name, hor=HOR, grid_c=(50, 65, 80, 100, 130, 160), grid_f=(35, 50, 65)):
    starts = range(0, len(R) - hor, 14); print(f"\n== {name}: спроб-стартів {len(starts)}, горизонт {hor//30} міс.")
    print("   ризик перевірка/рахунок | чистими за горизонт (виплати − внески): середнє, медіана, найгірше | на місяць | у плюсі | внесків у середньому | перша виплатна фаза через")
    best = []
    for rc in grid_c:
        for rf in grid_f:
            res = [sim(R, s, rc, rf, hor) for s in starts]; net = np.array([p - f for p, f, _, _, _ in res]); fst = [x[2] for x in res if x[2] is not None]
            print(f"   ${rc:3d} / ${rf:2d}: ${net.mean():+7.0f}, ${np.median(net):+7.0f}, ${net.min():+7.0f} | ${net.mean()/(hor/30.44):+5.0f}/міс | {100*(net>0).mean():3.0f}% | {np.mean([x[3] for x in res]):.1f} (${np.mean([x[1] for x in res]):.0f}) | {np.median(fst) if fst else float('nan'):.0f} дн. (дійшли {100*len(fst)/len(res):.0f}%)")
table(R_sw, "лише СВІНГ спокійні, 2022–2026 (ризик у $ на угоду)")
if len(sys.argv) > 3:
    td = pd.read_csv(sys.argv[2]); ts = pd.read_csv(sys.argv[3]); S = {"sw": (10 * g.r).groupby((g.ts + g.hold * 14400) // 86400).sum(), "td": td.usd.groupby(td.t // 86400).sum(), "ts": pd.Series((1000 * ts.ret).to_numpy(), index=ts.day.to_numpy())}
    d0 = max(int(v.index.min()) for v in S.values()); d1 = min(int(v.index.max()) for v in S.values()); ix = np.arange(d0, d1 + 1); D = pd.DataFrame({k: v.reindex(ix, fill_value=0.0) for k, v in S.items()})
    dd = lambda x: float((x.cumsum() - x.cumsum().cummax()).min())
    combo = sum(D[k] * (1 / 3 / abs(dd(D[k]))) for k in D); combo = combo / abs(dd(combo))          # одиниця = $1 історичного падіння поєднання
    swu = D["sw"] / abs(dd(D["sw"]))
    print("\n(нижче «ризик» = історичне найбільше падіння потоку в $ на рахунку $50 000; 2024–2026, горизонт 18 міс.)")
    table(swu.to_numpy(), "лише СВІНГ спокійні, 2024–2026", 548, (3000, 4000, 5000, 6500, 8000), (2500, 3500, 4500))
    table(combo.to_numpy(), "три системи разом, 2024–2026", 548, (3000, 4000, 5000, 6500, 8000), (2500, 3500, 4500))
