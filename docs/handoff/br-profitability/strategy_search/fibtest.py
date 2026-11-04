"""READ-ONLY. Перевірка ідеї з опису індикатора «Strong Candle Probability Levels Tester» (PDF власниці): сильна свічка -> лімітний вхід на відкаті Фібоначчі -> цілі на розширеннях.
З PDF ПІДТВЕРДЖЕНО лише структуру (вхід лімітом на відкатах 0-78.6%, тейки на розширеннях 127.2-462%, фільтр сили за ATR). Формула «сили» автором НЕ розкрита (інвайт-скрипт), обсяг/дельту ми не маємо.
ГІПОТЕЗА (наша): сильна = тіло >= K*ATR14, закриття в крайній чверті; відкат і розширення — від діапазону свічки (0% = екстремум у бік руху, 100% = протилежний); стоп = протилежний екстремум ∓0.1 ATR;
ліміт діє 12 барів; скасовується, якщо до входу ціна дійшла до 127.2%; вихід за часом 48 барів після входу; SL-first. Без моделі/навчання: усі роки 2022-2026 тестові.
Використання: fibtest.py CANDLES_DIR SYMS COST"""
import sys, random
from pathlib import Path
import numpy as np, pandas as pd
random.seed(7)
CD = Path(sys.argv[1]); SYMS = sys.argv[2].split(","); COST = float(sys.argv[3])
DAY = 86400; WAIT = 12; HZ = 48
RET = (0.236, 0.382, 0.5, 0.618, 0.786); EXT = (1.272, 1.618, 2.618, 3.618)

def load(s, tf):
    d = pd.read_csv(CD / s / "15m.csv").drop_duplicates("open_time").sort_values("open_time")
    if tf == "H1":
        d = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return {k: d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}

def atr(h, l, c):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return pd.Series(tr).rolling(14).mean().shift(1).to_numpy()

def trades(a, K):
    t, o, h, l, c = a["open_time"], a["open"], a["high"], a["low"], a["close"]; at = atr(h, l, c); n = len(c); out = []
    for i in range(20, n - WAIT - HZ - 2):
        rng = h[i] - l[i]
        if rng <= 0 or not at[i] == at[i] or abs(c[i] - o[i]) < K * at[i]: continue
        pos = (c[i] - l[i]) / rng
        if c[i] > o[i] and pos >= .75: s = 1
        elif c[i] < o[i] and pos <= .25: s = -1
        else: continue
        top, bot = (h[i], l[i]) if s > 0 else (l[i], h[i])          # top = екстремум у бік руху (0%), bot = протилежний (100%)
        sl = bot - s * 0.1 * at[i]; e1 = top + s * 0.272 * rng
        for r in RET:
            lvl = top - s * r * rng; sp = abs(lvl - sl) / lvl
            if not (0.0015 <= sp <= 0.05) or (lvl - sl) * s <= 0: continue
            fill = None
            for q in range(i + 1, i + 1 + WAIT):
                if (h[q] >= e1) if s > 0 else (l[q] <= e1): break
                if (l[q] <= lvl) if s > 0 else (h[q] >= lvl): fill = q; break
            if fill is None: continue
            if (l[fill] <= sl) if s > 0 else (h[fill] >= sl): res = {e: -1.0 for e in EXT}
            else:
                W = slice(fill + 1, fill + 1 + HZ); wh, wl = h[W], l[W]; risk = abs(lvl - sl)
                slh = wl <= sl if s > 0 else wh >= sl; si = slh.argmax() if slh.any() else 999
                end = c[min(fill + HZ, n - 1)]; res = {}
                for e in EXT:
                    tp = top + s * (e - 1) * rng
                    th = wh >= tp if s > 0 else wl <= tp; ti = th.argmax() if th.any() else 999
                    if si == 999 and ti == 999: res[e] = s * (end - lvl) / risk
                    else: res[e] = -1.0 if si <= ti else s * (tp - lvl) / risk
            for e in EXT: out.append((r, e, t[fill], res[e] - COST / sp, sp))
    return out

def boot(dd, nb=800):
    ks = list(dd)
    if not ks: return 0, 0
    ms = []
    for _ in range(nb):
        s = c = 0
        for _ in ks:
            x = dd[random.choice(ks)]; s += sum(x); c += len(x)
        ms.append(s / c)
    ms.sort(); return ms[int(.025 * nb)], ms[int(.975 * nb)]

def main():
    allres = []
    for tf in ("H1", "M15"):
        for K in (1.5, 2.0):
            rows = []
            for s in SYMS:
                if not (CD / s / "15m.csv").exists(): continue
                for r, e, tt, rr, sp in trades(load(s, tf), K): rows.append((s, r, e, tt, rr, sp))
            if not rows: continue
            df = pd.DataFrame(rows, columns=["sym", "ret", "ext", "t", "r", "sp"]); df["year"] = pd.to_datetime(df.t, unit="s").dt.year
            print(f"\n=== {tf}; сильна свічка: тіло >= {K} ATR; комісія {COST*100:.2f}%; 12 монет; $10 ризику; роки 2022-2026 ===", flush=True)
            print("| вхід (відкат) | ціль (розширення) | угод | 2022 | 2023 | 2024 | 2025 | 2026 | усього $ | R/угоду | CI95 R | сер. стоп | ✅ |\n|--|--|--|--|--|--|--|--|--|--|--|--|--|")
            for r in RET:
                for e in EXT:
                    z = df[(df.ret == r) & (df.ext == e)]
                    if len(z) < 50: continue
                    ys = {y: z[z.year == y] for y in range(2022, 2027)}
                    ok = all(len(q) >= 20 and q.r.mean() > 0 for q in ys.values())
                    dd = {}
                    for tt, rr in zip(z.t, z.r): dd.setdefault(int(tt // DAY), []).append(rr)
                    lo, hi = boot(dd); ok = ok and lo > 0
                    allres.append((tf, K, r, e, len(z), 10 * z.r.sum(), z.r.mean(), ok))
                    print(f"| {r*100:.1f}% | {e*100:.1f}% | {len(z)} | " + " | ".join(f"{10*ys[y].r.sum():+,.0f}" for y in range(2022, 2027)) + f" | {10*z.r.sum():+,.0f} | {z.r.mean():+.3f} | [{lo:+.3f};{hi:+.3f}] | {z.sp.mean()*100:.2f}% | {'✅' if ok else ''} |", flush=True)
    a = pd.DataFrame(allres, columns=["tf", "K", "ret", "ext", "n", "usd", "R", "ok"])
    print(f"\nКомбінацій {len(a)}; з плюсом у кожному з 5 років і CI>0: {int(a.ok.sum())}; із плюсовим підсумком: {int((a.usd>0).sum())}")
    print("Кращі 8 за підсумком:"); print(a.sort_values("usd", ascending=False).head(8).to_string(index=False))
    print("Середній R по кожному рівню входу:", a.groupby("ret").R.mean().round(3).to_dict()); print("Середній R по кожній цілі:", a.groupby("ext").R.mean().round(3).to_dict())
    print("Примітка: 80 комбінацій — кратне порівняння; ✅ = лише кандидат для shadow.\n##### ПІДСУМОК fibtest завершено")
if __name__ == "__main__": main()
