"""READ-ONLY. «МІСЯЦІ ТАК, ЯК ЇХ РЕАЛЬНО МОЖНА ПРОТОРГУВАТИ» (26.11.2026; порада з огляду ChatGPT, згода власниці). СВІНГ, угоди з swmfe_trades.csv (комісія 0,10% уже в r), ризик $10 на угоду.
Додаємо по черзі (усе показано, нічого не підбирається):
 Б) плата за утримання ф'ючерса (funding): фактичні ставки Binance з data/funding/*.csv за час угоди; LONG платить при додатній ставці, SHORT отримує (і навпаки).
 В) гірша ціна виконання (ГІПОТЕЗА): ще 0,05% від ціни на кожну угоду (вхід+вихід разом) і додатково 0,05% на угодах, що закрились стопом.
 Г) обмеження «не більше N відкритих угод одночасно» (N = 10, 20): нові сигнали понад ліміт пропускаються в порядку надходження (рішення вручну, без знання результату).
 Капітал $4 000: потрібна сума позицій = ризик / відстань до стопа; показуємо найбільшу сумарну позицію як частку капіталу (чи вистачає без великого плеча).
Використання: realistic.py SW_TRADES FUNDING_DIR"""
import sys, os, numpy as np, pandas as pd
sw = pd.read_csv(sys.argv[1]).sort_values("ts").reset_index(drop=True); FD = sys.argv[2]; PER = 14400
sw["t_in"] = sw.ts + PER; sw["t_out"] = sw.t_in + sw.hold * PER
F = {}
for s in sw.sym.unique():
    p = f"{FD}/{s}.csv"
    if os.path.exists(p): d = pd.read_csv(p); F[s] = (d.calc_time.to_numpy() / 1000.0, np.cumsum(d.last_funding_rate.to_numpy()))
def fund(r):
    if r.sym not in F: return 0.0
    t, cs = F[r.sym]; a = np.searchsorted(t, r.t_in, side="right"); b = np.searchsorted(t, r.t_out, side="right")
    tot = (cs[b - 1] if b > 0 else 0.0) - (cs[a - 1] if a > 0 else 0.0)
    return -r.side * tot / r.risk_pct                                  # у ризиках R
sw["r_f"] = [fund(r) for r in sw.itertuples()]
sw["r_s"] = -(0.0005 + np.where(sw.why == "SL", 0.0005, 0.0)) / sw.risk_pct
sw["month"] = pd.to_datetime(sw.t_out, unit="s").dt.to_period("M"); sw["day"] = (sw.t_out // 86400).astype(int)
def cap(g, N):
    keep = np.zeros(len(g), bool); open_out = []
    for i, (tin, tout) in enumerate(zip(g.t_in.to_numpy(), g.t_out.to_numpy())):
        open_out = [x for x in open_out if x > tin]
        if len(open_out) < N: keep[i] = True; open_out.append(tout)
    return g[keep]
def stats(g, col):
    x = 10 * g[col]; m = x.groupby(g.month).sum(); allm = pd.period_range(sw.month.min(), sw.month.max(), freq="M"); m = m.reindex(allm, fill_value=0.0)
    d = x.groupby(g.day).sum().sort_index(); eq = d.cumsum(); dd = (eq - eq.cummax()).min()
    return m, dd, x
def maxexp(g):
    ev = sorted([(a, n) for a, n in zip(g.t_in, 10 / g.risk_pct)] + [(b, -n) for b, n in zip(g.t_out, 10 / g.risk_pct)]); cur = mx = 0.0
    for _, n in ev: cur += n; mx = max(mx, cur)
    return mx
sw["A"] = sw.r; sw["B"] = sw.r + sw.r_f; sw["C"] = sw.r + sw.r_f + sw.r_s
print(f"РЕАЛІСТИЧНИЙ ПЕРЕРАХУНОК СВІНГ: {len(sw)} угод, {sw.month.min()} — {sw.month.max()}; ризик $10 на угоду")
print(f"плата за утримання в середньому: {10*sw.r_f.mean():+.2f}$ на угоду (LONG {10*sw[sw.side>0].r_f.mean():+.2f}, SHORT {10*sw[sw.side<0].r_f.mean():+.2f}); гірше виконання: {10*sw.r_s.mean():+.2f}$ на угоду")
for lab, base in (("УСІ СИГНАЛИ", sw), ("ЛИШЕ СПОКІЙНІ МОНЕТИ", sw[sw.atr_pct < 0.023])):
    print(f"\n######## {lab}")
    for name, g, col in (("А) як у перевірці (лише комісія)", base, "A"), ("Б) + плата за утримання", base, "B"), ("В) + гірша ціна виконання", base, "C"),
                         ("Г) як В, не більше 20 угод одночасно", cap(base, 20), "C"), ("Г) як В, не більше 10 угод одночасно", cap(base, 10), "C"), ("Г) як В, не більше 5 угод одночасно", cap(base, 5), "C")):
        m, dd, x = stats(g, col)
        print(f"  {name:42s}: угод {len(g):5d} ({len(g)/len(m):.0f}/міс), на угоду ${x.mean():+.2f}, на місяць ${m.mean():+.0f}, найгірший місяць ${m.min():+.0f}, мінусових місяців {100*(m<0).mean():.0f}%, найбільше падіння ${dd:+.0f}, найбільша сума позицій ${maxexp(g):,.0f}")
    m, dd, x = stats(base, "C"); g2 = cap(base, 10); m2, _, _ = stats(g2, "C"); cnt = base.groupby("month").size(); cnt2 = g2.groupby("month").size()
    print("  по місяцях (варіант В: усі доступні угоди / результат $ | варіант Г-10: взято / результат $):")
    for y in sorted(set(p.year for p in m.index)):
        print(f"   {y}: " + "  ".join(f"{p.month:02d}: {int(cnt.get(p,0))}/{m[p]:+.0f} | {int(cnt2.get(p,0))}/{m2[p]:+.0f}" for p in m.index if p.year == y))
