"""READ-ONLY. Перевірка ручної ідеї з скриншотів: шорт від максимуму доби (і лонг від мінімуму доби) на BTC, M15, 2022-2026. $10 ризику, SL-first, таймаут 48 год.
Правила зафіксовані ДО запуску (не підбирались): рівень = максимум/мінімум попередніх 96 барів M15 (24 год); дотик = high/low в межах 0,3% від рівня; тригер = M15 свічка проти напрямку (червона для шорта);
вхід = close; стоп = екстремум 8 барів M15 ∓0,1 ATR14 (те саме, що в TD-V1); ціль 2R і 3R; тренд-фільтр = close H4 нижче SMA99(H4) (для шорта) / вище (для лонга); пауза 24 бари між угодами.
Контроль: той самий тригер без дотику рівня. ГІПОТЕЗА — не підтверджено. Використання: btclevel.py CANDLES_DIR COST"""
import sys, numpy as np, pandas as pd
CD, C = sys.argv[1], float(sys.argv[2])
d = pd.read_csv(f"{CD}/BTCUSDT/15m.csv"); d.columns = [c.lower() for c in d.columns]
tcol = "open_time" if "open_time" in d else d.columns[0]
t = d[tcol].to_numpy(float); o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
n = len(c); pc = np.r_[c[0], c[:-1]]
tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); atr = pd.Series(tr).rolling(14).mean().to_numpy()
# H4: закриті 4-годинні свічки, SMA99, значення відомі лише після закриття
df = pd.DataFrame({"t": t, "c": c}); df["b"] = (df.t // 14400).astype(int)
g = df.groupby("b").agg(t0=("t", "first"), c=("c", "last")); g["sma"] = g.c.rolling(99).mean()
g["ok_t"] = g.index * 14400 + 14400
h4 = g.set_index("ok_t")
idx = np.searchsorted(h4.index.to_numpy(float), t, side="right") - 1
h4c = np.where(idx >= 0, h4.c.to_numpy()[np.clip(idx, 0, None)], np.nan); h4s = np.where(idx >= 0, h4.sma.to_numpy()[np.clip(idx, 0, None)], np.nan)
down = h4c < h4s; up = h4c > h4s
hh = pd.Series(h).shift(1).rolling(96).max().to_numpy(); ll = pd.Series(l).shift(1).rolling(96).min().to_numpy()
def sim(j, side, ent, sl, tp):
    for k in range(j + 1, min(j + 193, n)):
        if side < 0:
            if h[k] >= sl: return -1.0
            if l[k] <= tp: return abs(ent - tp) / abs(sl - ent)
        else:
            if l[k] <= sl: return -1.0
            if h[k] >= tp: return abs(tp - ent) / abs(ent - sl)
    k = min(j + 192, n - 1); return side * (c[k] - ent) / abs(ent - sl)
def run(name, side, level_touch, trend):
    out = []; last = -999
    for j in range(120, n - 2):
        if j - last < 24 or not atr[j] == atr[j]: continue
        if trend is not None and not trend[j]: continue
        if side < 0:
            if not c[j] < o[j]: continue
            if level_touch and not h[j] >= hh[j] * 0.997: continue
            sl = h[j - 7:j + 1].max() + 0.1 * atr[j]
        else:
            if not c[j] > o[j]: continue
            if level_touch and not l[j] <= ll[j] * 1.003: continue
            sl = l[j - 7:j + 1].min() - 0.1 * atr[j]
        ent = c[j]; sp = abs(sl - ent) / ent
        if not (0.0015 <= sp <= 0.03): continue
        last = j; out.append((t[j], sp, [sim(j, side, ent, sl, ent + side * m * abs(ent - sl)) - C / sp for m in (2, 3)]))
    return out
def rep(name, out):
    if not out: print(f"{name}: угод немає"); return
    y = pd.to_datetime([x[0] for x in out], unit="s").year.to_numpy()
    for mi, m in enumerate((2, 3)):
        r = np.array([x[2][mi] for x in out]) * 10
        line = " | ".join(f"{yy}: {int((y == yy).sum())} угод {r[y == yy].sum():+.0f}$" for yy in sorted(set(y)))
        print(f"{name} ціль {m}R: {len(r)} угод, разом {r.sum():+.0f}$, середня {r.mean():+.2f}$/угоду, виграшних {np.mean(r > 0) * 100:.0f}% | {line}")
print(f"BTC M15, комісія+проковзування {C * 100:.2f}% за круг, ризик $10")
rep("A шорт від макс. доби, тренд вниз", run("A", -1, True, down))
rep("A2 шорт від макс. доби, будь-який тренд", run("A2", -1, True, None))
rep("C контроль: шорт без рівня, тренд вниз", run("C", -1, False, down))
rep("B лонг від мін. доби, тренд вгору", run("B", 1, True, up))
rep("B2 лонг від мін. доби, тренд вниз (контртренд)", run("B2", 1, True, down))
rep("D контроль: лонг без рівня, тренд вгору", run("D", 1, False, up))
