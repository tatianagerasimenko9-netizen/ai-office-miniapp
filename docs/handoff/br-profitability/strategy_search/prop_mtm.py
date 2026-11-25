"""READ-ONLY. Проп-рахунок, ЧЕСНІШИЙ рахунок: денний капітал = закриті угоди + незакритий результат відкритих угод на кінець дня (25.11.2026). Угоди СВІНГу, лише спокійні (ATR H4 < 2,3%), знімки d1…d10 (R на кінець кожної доби угоди).
Правила й логіка як у prop_ev.py: рахунок $50 000, 2 етапи (10% і 5%), денний ліміт 5% (за зміною капіталу за день), загальний 10% від початкового, внесок $450, виплата 80% раз на 30 днів, повторні спроби, горизонт 24 міс., старт кожні 14 днів.
Залишкове спрощення: мінус УСЕРЕДИНІ дня між знімками не видно (стоп = −1R враховано в день виходу). Використання: prop_mtm.py SW_TRADES"""
import sys, numpy as np, pandas as pd
A = 50000.0; FEE = 450.0; DL, ML = .05, .10; HOR = 730
W = pd.read_csv(sys.argv[1]); G = W[W.atr_pct < 0.023]
d0 = int(W.ts.min() // 86400); n = int((W.ts + W.hold * 14400).max() // 86400) - d0 + 3
def series(g, mtm):
    diff = np.zeros(n)
    for r in g.itertuples():
        ex = r.ts + r.hold * 14400; last = 0.0
        if mtm:
            for k in range(1, 11):
                v = getattr(r, f"d{k}"); tk = r.ts + k * 86400
                if v != v or tk >= ex: break
                diff[int(tk // 86400) - d0] += v - last; last = v
        diff[int(ex // 86400) - d0] += r.r - last
    return diff                                                    # денна зміна капіталу в R
def sim(R, s, rc, rf, hor=HOR):
    i = s; end = min(len(R), s + hor); pay = 0.0; fees = 0.0; first = None; att = 0
    while i < end:
        fees += FEE; att += 1; ok = True
        for tgt in (.10, .05):
            bal = A
            while True:
                if i >= end: ok = False; break
                p = R[i] * rc; i += 1; bal += p
                if p <= -DL * A or bal <= A * (1 - ML): ok = False; break
                if bal >= A * (1 + tgt): break
            if not ok: break
        if not ok: continue
        first = first if first is not None else i - s; bal = A; k = 0
        while i < end:
            p = R[i] * rf; i += 1; k += 1; bal += p
            if p <= -DL * A or bal <= A * (1 - ML): break
            if k % 30 == 0 and bal > A: pay += 0.8 * (bal - A); bal = A
    return pay - fees, fees, first, att
dd = lambda x: float((np.cumsum(x) - np.maximum.accumulate(np.cumsum(x))).min())
for lab, g in (("лише спокійні", G),):
    a = series(g, False); b = series(g, True)
    print(f"{lab}: найбільше падіння (у ризиках R): за закритими угодами {dd(a):.0f}R, з незакритим результатом {dd(b):.0f}R; найгірший день: {a.min():.1f}R / {b.min():.1f}R")
    for nm, R in (("за ЗАКРИТИМИ угодами (як раніше)", a), ("з НЕЗАКРИТИМ результатом (чесніше)", b)):
        print(f"\n== {nm}: ризик перевірка/рахунок → чистими на місяць (середнє), найгірший старт за 24 міс., старти в плюсі, внесків, перша оплачувана фаза")
        for rc in (50, 65, 80, 100, 130, 160):
            for rf in (25, 35, 50, 65):
                res = [sim(R, s, rc, rf) for s in range(0, len(R) - HOR, 14)]; net = np.array([x[0] for x in res]); fst = [x[2] for x in res if x[2] is not None]
                print(f"   ${rc:3d} / ${rf:2d}: ${net.mean()/24:+5.0f}/міс, найгірший ${net.min():+7.0f}, у плюсі {100*(net>0).mean():3.0f}%, внесків {np.mean([x[3] for x in res]):.1f} (${np.mean([x[1] for x in res]):.0f}), перша фаза {np.median(fst) if fst else float('nan'):.0f} дн. (дійшли {100*len(fst)/len(res):.0f}%)")
    # останні роки окремо: старти з 2024
    R = b; s0 = int(pd.Timestamp("2024-01-01").timestamp() // 86400) - d0; hor = len(R) - s0 - 60
    print(f"\n== з НЕЗАКРИТИМ результатом, лише старти у 2024 (горизонт {hor//30} міс.)")
    for rc, rf in ((50, 35), (80, 35), (80, 50), (100, 50), (130, 50), (160, 65)):
        res = [sim(R, s, rc, rf, hor) for s in range(s0, s0 + 60, 7)]; net = np.array([x[0] for x in res])
        print(f"   ${rc:3d} / ${rf:2d}: ${net.mean()/(hor/30.44):+5.0f}/міс, найгірший ${net.min():+7.0f}, у плюсі {100*(net>0).mean():3.0f}%, внесків {np.mean([x[3] for x in res]):.1f}")
