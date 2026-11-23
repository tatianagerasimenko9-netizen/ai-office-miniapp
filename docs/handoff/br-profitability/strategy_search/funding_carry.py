"""READ-ONLY. «Рівняння ф'ючерсу»: фандинг-перенос (cash-and-carry), 22.11.2026. Це НЕ прогноз напрямку ціни, а арифметика.
Ідея (публічно відома, ЗОВНІШНЄ): на безстроковому ф'ючерсі кожні 8 год одна сторона платить іншій «фандинг». Коли він додатний, покупці платять продавцям.
Хедж: купити монету на споті + продати такий самий обсяг ф'ючерсом (шорт) → ціна взаємно гаситься, ми отримуємо фандинг. Прибуток = Σ фандингу − комісії − ризик базису/ліквідації (НЕ моделюється: ГІПОТЕЗА, що хедж ідеальний).
Капітал: половина на спот, половина маржа під шорт (плече 1×) → дохід на капітал = фандинг/2.
Варіанти (все показуємо): S1 тримати завжди (1 вхід, комісія раз); S2 тримати монету лише коли середній фандинг за останні 3 виплати > MIN (рішення тільки з минулого); кошик = рівні ваги серед монет, що «увімкнені».
Комісії: спот 0.10% + ф'ючерс 0.04% на кожну ногу (вхід і вихід) = 0.28% за круг; дешевший варіант 0.15%.
Використання: funding_carry.py fetch DIR SYMS   |   funding_carry.py run DIR SYMS OUT"""
import io, os, sys, zipfile, urllib.request, urllib.error
import numpy as np, pandas as pd
mode, D, SYMS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
MONTHS = [f"{y}-{m:02d}" for y in range(2022, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)]
if mode == "fetch":
    os.makedirs(D, exist_ok=True)
    for s in SYMS:
        parts = []
        for mo in MONTHS:
            u = f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{mo}.zip"
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "office-research"}), timeout=60) as r: z = zipfile.ZipFile(io.BytesIO(r.read()))
            except Exception: continue
            df = pd.read_csv(z.open(z.namelist()[0]))
            if "last_funding_rate" not in df: df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"][:len(df.columns)]
            parts.append(df[["calc_time", "last_funding_rate"]])
        if parts: pd.concat(parts).drop_duplicates("calc_time").sort_values("calc_time").to_csv(f"{D}/{s}.csv", index=False); print(s, sum(len(p) for p in parts), end="; ")
    print(); sys.exit(0)
OUT = sys.argv[4]
R = {}
for s in SYMS:
    p = f"{D}/{s}.csv"
    if os.path.exists(p):
        d = pd.read_csv(p); d["t"] = (d.calc_time // 1000 // 28800) * 28800 if d.calc_time.iloc[0] > 1e11 else (d.calc_time // 28800) * 28800
        R[s] = d.drop_duplicates("t").set_index("t").last_funding_rate
F = pd.DataFrame(R).sort_index(); yr = pd.to_datetime(F.index, unit="s").year
print(f"ФАНДИНГ-ПЕРЕНОС: монет {F.shape[1]}, виплат {len(F)}, {pd.to_datetime(F.index[0], unit='s'):%Y-%m-%d} — {pd.to_datetime(F.index[-1], unit='s'):%Y-%m-%d}")
print(f"середній фандинг за виплату: {1e4*F.stack().mean():+.2f} б.п. (≈ {F.stack().mean()*3*365*100:+.1f}% річних на обсяг ноги); частка виплат з мінусом: {100*(F.stack()<0).mean():.0f}%")
print("\nСередній фандинг по роках, % річних на обсяг: " + ", ".join(f"{y}: {F[yr==y].stack().mean()*3*365*100:+.1f}%" for y in sorted(set(yr))))
CAP = 5000.0
def run(name, W, fee_rt):
    W = W.fillna(0.0)                                   # ваги в обсязі ноги, сума ≤1 (капітал = 2×обсяг)
    gross = (W.shift(1).fillna(0) * F.fillna(0)).sum(axis=1)  # дохід за виплату на 1 одиницю обсягу (вага сформована ДО виплати)
    turn = W.diff().abs().sum(axis=1); turn.iloc[0] = W.iloc[0].abs().sum()
    net = gross - turn * fee_rt / 2
    ann = net.groupby(yr).sum()
    cap = 2.0                                            # капітал = 2 × обсяг
    line = ", ".join(f"{y}: {100*v/cap:+.1f}% (${CAP*v/cap:+.0f})" for y, v in ann.items())
    tot = net.sum() / cap; yrs = (F.index[-1] - F.index[0]) / (365 * 86400)
    print(f" {name}: на капітал ${CAP:.0f}: по роках {line} | усього {100*tot:+.1f}% за {yrs:.1f} р. (${CAP*tot:+.0f}); обіг {turn.sum():.1f} обсягів; в середньому задіяно {100*W.sum(axis=1).mean():.0f}%")
n = F.shape[1]
for fee in (0.0028, 0.0015):
    print(f"\n#### комісія {fee*100:.2f}% за круг")
    W1 = pd.DataFrame(1.0 / n, index=F.index, columns=F.columns); run("S1 завжди, усі монети, рівні ваги", W1, fee)
    for mn in (0.0001, 0.00015, 0.0003):
        tr = F.rolling(3).mean().shift(1)                # лише минуле
        on = (tr > mn).astype(float); w = on.div(on.sum(axis=1).replace(0, np.nan), axis=0)
        run(f"S2 лише коли серед.фандинг 3 виплат > {mn*1e4:.0f} б.п.", w, fee)
print("\nКоментар: значення — це ДОХІД ВІД ФАНДИНГУ МІНУС КОМІСІЇ. Не враховано: розбіжність спот/ф'ючерс (базис) під час входу/виходу, ліквідацію шорта при різкому рості (плече 1× — запас 100%), комісію за переказ і відсотки за маржу. Це ГІПОТЕЗА ідеального хеджу, не гарантія.")
