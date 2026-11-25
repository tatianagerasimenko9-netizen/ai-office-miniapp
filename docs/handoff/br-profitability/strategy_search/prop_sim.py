"""READ-ONLY. Чи проходить СВІНГ правила проп-компаній (25.11.2026, запит власниці). Угоди — swmfe_trades.csv (42 монети, 2022–2026, одна позиція на монету). Рахунок $50 000.
Правила (ЗОВНІШНЄ, публічні огляди HyroTrader/Breakout; у різних джерелах цифри різняться — перевіряти на сайті фірми): 2 етапи: ціль 10% і 5%, денний ліміт 5%, загальний 10%; 1 етап: ціль 10%, денний 3%, загальний 6%.
Загальний ліміт: static (від початкового балансу) або trailing (від найвищого балансу). Після проходження: раз на 30 днів виплата 80% прибутку, баланс повертається до початкового.
СПРОЩЕННЯ (ГІПОТЕЗА): рахуємо за ЗАКРИТИМИ угодами по днях; реальні правила враховують і незакритий мінус, тому справжній результат гірший. Старт спроби — кожні 14 днів.
Використання: prop_sim.py TRADES_CSV"""
import sys, numpy as np, pandas as pd
W = pd.read_csv(sys.argv[1]); W["d"] = (W.ts + W.hold * 14400) // 86400; A = 50000.0
idx = np.arange(int(W.d.min()), int(W.d.max()) + 1)
def daily(g): return g.groupby("d").r.sum().reindex(idx, fill_value=0.0).to_numpy()
SETS = {"усі сигнали": daily(W), "лише спокійні": daily(W[W.atr_pct < 0.023])}
PLANS = {"2 етапи 10%+5%, денний 5%, загальний 10%": dict(t=[.10, .05], dl=.05, ml=.10), "1 етап 10%, денний 3%, загальний 6%": dict(t=[.10], dl=.03, ml=.06)}
def breach(bal, peak, pnl, plan, trail): return pnl <= -plan["dl"] * A or bal <= (peak if trail else A) - plan["ml"] * A
def challenge(R, i, risk, plan, trail, maxdays=365):
    days = 0
    for tgt in plan["t"]:
        bal = peak = A
        while True:
            if i >= len(R) or days > maxdays: return False, days, "час", i
            pnl = R[i] * risk; i += 1; days += 1; bal += pnl; peak = max(peak, bal)
            if breach(bal, peak, pnl, plan, trail): return False, days, "ліміт", i
            if bal >= A * (1 + tgt): break
    return True, days, "", i
def funded(R, i, risk, plan, trail, months=12):
    pay = 0.0; bal = peak = A; m = 0
    while m < months and i + 30 <= len(R):
        for _ in range(30):
            pnl = R[i] * risk; i += 1; bal += pnl; peak = max(peak, bal)
            if breach(bal, peak, pnl, plan, trail): return m, pay, False
        if bal > A: pay += 0.8 * (bal - A); bal = peak = A
        m += 1
    return m, pay, True
for sname, R in SETS.items():
    for pname, plan in PLANS.items():
        for trail in (False, True):
            print(f"\n== {sname} · {pname} · загальний ліміт {'від найвищого балансу (trailing)' if trail else 'від початкового (static)'}")
            for risk in (25, 35, 50, 65, 80, 100):
                res = [challenge(R, s, risk, plan, trail) for s in range(0, len(R) - 420, 14)]; ok = [r for r in res if r[0]]
                f = [funded(R, r[3], risk, plan, trail) for r in ok]
                if not ok: print(f"   ризик ${risk}: не проходить"); continue
                p = len(ok) / len(res); pay12 = np.mean([x[1] for x in f]); live = np.mean([x[2] for x in f]); mm = np.median([x[0] for x in f])
                print(f"   ризик ${risk:3d} на угоду ({100*risk/A:.2f}% рахунку): проходить {100*p:3.0f}% спроб (медіана {np.median([r[1] for r in ok]):.0f} дн., час вийшов у {100*np.mean([r[2]=='час' for r in res]):.0f}%) | далі: рік без порушень {100*live:3.0f}%, медіана {mm:.0f} міс., виплат за перший рік у середньому ${pay12:.0f} (${pay12/12:.0f}/міс)")
