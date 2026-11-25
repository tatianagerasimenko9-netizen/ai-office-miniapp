"""READ-ONLY. ШЛЯХ 5: чи дає поєднання систем менше падіння рахунку при тому самому доході (25.11.2026). Потоки (денні $): СВІНГ спокійні ($10 ризику; swmfe_trades.csv, день виходу), ІНТРАДЕЙ ($10 ризику; td_trades.csv, день входу),
тижнева карта монет TSM (топ-20, L=30/H=7, витрати 0,15%; на $1 000 позиції; tsm_daily.csv). Спільний період — там, де є всі три (ІНТРАДЕЙ з 2024).
Метод без підгонки: кожен потік масштабуємо так, щоб його ВЛАСНЕ найбільше падіння = $400; порівнюємо суму трьох із кожним потоком окремо при падінні $1 200.
Використання: combine5.py SW_TRADES TD_TRADES TSM_DAILY"""
import sys, numpy as np, pandas as pd
sw = pd.read_csv(sys.argv[1]); td = pd.read_csv(sys.argv[2]); ts = pd.read_csv(sys.argv[3])
S = {}
g = sw[sw.atr_pct < 0.023]; S["СВІНГ спокійні"] = (10 * g.r).groupby((g.ts + g.hold * 14400) // 86400).sum()
g = sw; S["СВІНГ усі"] = (10 * g.r).groupby((g.ts + g.hold * 14400) // 86400).sum()
S["ІНТРАДЕЙ"] = td.usd.groupby(td.t // 86400).sum()
S["тижнева карта"] = pd.Series((1000 * ts.ret).to_numpy(), index=ts.day.to_numpy())
d0 = max(int(v.index.min()) for k, v in S.items() if k != "СВІНГ усі"); d1 = min(int(v.index.max()) for v in S.values()); idx = np.arange(d0, d1 + 1)
D = pd.DataFrame({k: v.reindex(idx, fill_value=0.0) for k, v in S.items()}); months = (d1 - d0) / 30.44
dd = lambda x: float((x.cumsum() - x.cumsum().cummax()).min())
print(f"ШЛЯХ 5: поєднання систем; спільний період {pd.Timestamp(d0*86400, unit='s'):%Y-%m-%d} — {pd.Timestamp(d1*86400, unit='s'):%Y-%m-%d} ({months:.0f} міс.)")
print("\n== Кожен потік окремо (як є)")
for k in D: print(f"  {k:16s}: ${D[k].sum():+8.0f}, на місяць ${D[k].sum()/months:+6.0f}, найбільше падіння ${dd(D[k]):.0f}, прибуток/падіння {D[k].sum()/abs(dd(D[k])):.1f}")
M = D.groupby((pd.to_datetime(idx * 86400, unit="s").to_period("M")).to_numpy()).sum()
print("\n== Наскільки потоки ходять разом (кореляція місячних результатів; 0 = незалежні, 1 = однакові)"); print(M.corr().round(2).to_string())
print("\n== Те саме падіння рахунку $1 200: один потік проти поєднань")
sc = {k: D[k] * (1200 / abs(dd(D[k]))) for k in D}
for k in D: print(f"  лише {k:16s}: на місяць ${sc[k].sum()/months:+6.0f}, найгірший місяць ${(M[k]*(1200/abs(dd(D[k])))).min():+.0f}")
for combo in (("СВІНГ спокійні", "ІНТРАДЕЙ"), ("СВІНГ спокійні", "тижнева карта"), ("ІНТРАДЕЙ", "тижнева карта"), ("СВІНГ спокійні", "ІНТРАДЕЙ", "тижнева карта")):
    part = sum(D[k] * (1200 / len(combo) / abs(dd(D[k]))) for k in combo); k2 = 1200 / abs(dd(part)); mm = sum(M[k] * (1200 / len(combo) / abs(dd(D[k]))) for k in combo) * k2
    print(f"  {' + '.join(combo):48s}: падіння разом було б ${dd(part):.0f} → після підгонки до $1 200: на місяць ${part.sum()*k2/months:+6.0f}, найгірший місяць ${mm.min():+.0f}, мінусових місяців {100*(mm<0).mean():.0f}%")
print("\nПояснення: якщо поєднання дає більше на місяць, ніж найкращий потік окремо, — системи справді доповнюють одна одну. Усе на історії; ІНТРАДЕЙ перевірений лише з 2024.")
