"""READ-ONLY. ЧИСТИЙ ТЕСТ «відскок після різкого падіння за годину» (22.11.2026). Правило записано ДО запуску (pre-registered), параметри не підганяються.
ГІПОТЕЗА (з майнінгу mine.py, h=24, НЕ підтверджена): монета різко впала за останню годину → за наступну добу частково відскакує.
Правило: на закритті H1-бару z = (повернення за 1 год) / (std 1-год повернень за попередні 168 год). Сигнал LONG, якщо z ≤ -Z. Вхід на відкритті наступного бару, вихід через HOLD годин (або стоп -STOP від входу за low бару, оптимістично за рівнем стопа).
Один трейд на монету одночасно. Комісія FEE за угоду (круг). Позиція $1000 (результат у $ = 1000·(ret−FEE)).
Сітка (все показуємо, жодного відбору «кращого»): Z∈{2,3} × HOLD∈{12,24,48} × STOP∈{немає, 8%}. Дзеркало (SHORT після різкого росту z≥+Z) — окремо.
Перевірка стійкості: по роках 2022–2026, частка монет у плюсі, t-статистика за ДЕННИМИ сумами (монети корелюють у обвалах), найгірша угода і найгірший день.
ПЕРЕД-РЕЄСТРАЦІЯ ТЕСТУ ІМПУЛЬСУ (MOM=1, записано 22.11.2026 ДО запуску; спостереження виникло на 2022–2026, тому ПІДТВЕРДЖЕННЯ = ТІЛЬКИ ВНЕ ВИБІРКИ 2020–2021):
 «ПІДТВЕРДЖЕНО», якщо на 2020–2021 для LONG після росту без стопа (Z=2 і 3, утримання 24 і 48 год: 4 варіанти) РАЗОМ: (1) сума в плюсі у кожному з двох років, (2) t(дні) ≥ 2, (3) ≥ 60% монет у плюсі, у щонайменше 3 з 4 варіантів. Інакше — НЕ ПІДТВЕРДЖЕНО.
Використання: dip_test.py CANDLES_DIR SYMS FEE OUT"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, FEE, OUT = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]), sys.argv[4]
MOM = os.environ.get("MOM") == "1"      # MOM=1: ІМПУЛЬС (дзеркало): LONG після різкого РОСТУ, SHORT після різкого ПАДІННЯ
def load(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    return g.reset_index()
rows = []
for sym in SYMS:
    g = load(sym)
    if len(g) < 1000: continue
    t = g.open_time.to_numpy(); o = g.open.to_numpy(float); h = g.high.to_numpy(float); l = g.low.to_numpy(float); c = g.close.to_numpy(float); n = len(c)
    # без пропусків у часі: індекс = номер бару; пропуски розривають вікно — простий захист
    r1 = np.r_[np.nan, np.diff(np.log(c))]; sd = pd.Series(r1).rolling(168).std().shift(1).to_numpy(); z = r1 / sd
    for Z in (2, 3):
        for HOLD in (12, 24, 48):
            for STOP in (0, 0.08):
                for side in (1, -1):
                    busy = 0
                    for i in range(170, n - HOLD - 2):
                        if i < busy or not np.isfinite(z[i]): continue
                        zz = z[i] if MOM else -z[i]         # у режимі відскоку LONG після падіння (z<0), у режимі імпульсу LONG після росту (z>0)
                        if side == 1 and not zz >= Z: continue
                        if side == -1 and not zz <= -Z: continue
                        if t[i + HOLD + 1] - t[i + 1] != HOLD * 3600: continue
                        e = o[i + 1]; ex = c[i + HOLD]; j_end = i + HOLD; why = "TIME"
                        if STOP:
                            lvl = e * (1 - STOP) if side == 1 else e * (1 + STOP)
                            for j in range(i + 1, i + HOLD + 1):
                                if (side == 1 and l[j] <= lvl) or (side == -1 and h[j] >= lvl): ex = lvl; j_end = j; why = "STOP"; break
                        ret = side * (ex / e - 1) - FEE; busy = j_end + 1
                        rows.append((sym, Z, HOLD, STOP, side, int(t[i + 1]), int(pd.Timestamp(t[i + 1], unit="s").year), ret, why))
W = pd.DataFrame(rows, columns=["sym", "Z", "HOLD", "STOP", "side", "ts", "y", "ret", "why"]); W["usd"] = 1000 * W.ret
W.to_csv(OUT + "_trades.csv", index=False)
print(f"ТЕСТ ВІДСКОКУ ПІСЛЯ РІЗКОГО РУХУ ЗА ГОДИНУ: монет {len(SYMS)}, позиція $1000, комісія {FEE*100:.2f}% за угоду; правило записано до запуску")
for side in (1, -1):
    print(f"\n######## {('LONG після різкого РОСТУ' if side == 1 else 'SHORT після різкого ПАДІННЯ') if MOM else ('LONG після різкого ПАДІННЯ' if side == 1 else 'SHORT після різкого РОСТУ')}")
    for (Z, HOLD, STOP), g in W[W.side == side].groupby(["Z", "HOLD", "STOP"]):
        d = g.assign(day=g.ts // 86400).groupby("day").usd.sum(); tt = d.mean() / (d.std() / np.sqrt(len(d))) if len(d) > 2 and d.std() > 0 else float("nan")
        py = g.groupby("y").usd.sum().round(0).astype(int).to_dict(); pc = (g.groupby("sym").usd.sum() > 0).mean() * 100
        print(f" Z={Z} утримання {HOLD:2d} год стоп {'8%' if STOP else 'нема'}: {len(g):5d} угод, ${g.usd.sum():+8.0f}, на угоду ${g.usd.mean():+.2f}, виграшних {100*(g.usd>0).mean():.0f}%, t(дні)={tt:+.1f}, монет у плюсі {pc:.0f}%, найгірша угода ${g.usd.min():.0f}, найгірший день ${d.min():.0f}, по роках {py}")
