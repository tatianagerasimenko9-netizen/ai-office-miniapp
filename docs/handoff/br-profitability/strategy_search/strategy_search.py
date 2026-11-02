"""Пошук 1–3 СТАБІЛЬНИХ стратегій на довгій історії (12 міс., M15, ~20 монет). Протокол зафіксовано ДО запуску (без підбору параметрів):
 Стратегії (по одній формалізації, без перебору): S1 хибний пробій рівня (винос → повернення), S3 сильна свічка → відкат 50%, S4 відкат до EMA20 у тренді H1, S5 пробій діапазону відкриття сесії (London 07:00, NY 13:30 UTC).
 Вхід: S1/S4/S5 — ринковий на open наступного бару; S3 — лімітний на 50% свічки. Стоп за структурою (+0.1 ATR), ціль 1.5R та 2R. Мін. стоп 0.25%, макс 2%. SL першим при одному барі. Горизонт 48 барів.
 Комісія 0.10% круг (консервативно) і 0.05% (лімітні/maker). Одна угода на монету не частіше ніж раз на 16 барів.
 Поділ: TRAIN = перші 55% часу, TEST = останні 45% (embargo 2 доби). Стратегія «знайдена» лише якщо TRAIN>0 і TEST>0 і CI95 по днях на TEST не містить 0.
 Сесії UTC: Азія 00–07, Лондон 07–13, перекриття 13–17, пізня 17–24. Результат у $ при ризику $10/угоду."""
import csv, sys, random, math, statistics as st, collections, datetime as dt
from pathlib import Path
random.seed(7); CD = Path(sys.argv[1]); SYMS = sys.argv[2].split(",")
def load(s):
    try:
        rows = [(int(r["open_time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r.get("volume") or 0)) for r in csv.DictReader(open(CD / s / "15m.csv"))]
    except FileNotFoundError: return None
    return rows if len(rows) > 3000 else None
def ema(vals, n):
    k = 2 / (n + 1); out = []; e = vals[0]
    for v in vals: e = v * k + e * (1 - k); out.append(e)
    return out
def atr_series(b, n=14):
    tr = [b[0][2] - b[0][3]] + [max(b[i][2] - b[i][3], abs(b[i][2] - b[i - 1][4]), abs(b[i][3] - b[i - 1][4])) for i in range(1, len(b))]
    out = []; s = 0
    for i, x in enumerate(tr):
        s += x
        if i >= n: s -= tr[i - n]
        out.append(s / min(i + 1, n))
    return out
def sim(b, i0, d, ent, stop, tp, hz=48):
    for j in range(i0, min(len(b), i0 + hz)):
        lo, hi = b[j][3], b[j][2]
        if (lo <= stop) if d == 1 else (hi >= stop): return -1.0
        if (hi >= tp) if d == 1 else (lo <= tp): return abs(tp - ent) / abs(ent - stop)
    return None
def session(ts):
    h = (ts // 3600) % 24
    return "Азія" if h < 7 else "Лондон" if h < 13 else "перекриття" if h < 17 else "пізня"
def signals(sym, b):
    atr = atr_series(b); n = len(b); closes = [x[4] for x in b]; e20 = ema(closes, 20); h1c = [closes[i] for i in range(3, n, 4)]
    e20h = ema(h1c, 20); e50h = ema(h1c, 50); vol = [x[5] for x in b]; out = []; last = -99
    def add(i, strat, d, ent, stop, fill_i):
        nonlocal last
        sp = abs(ent - stop) / ent * 100
        if not (0.25 <= sp <= 2.0) or fill_i - last < 16: return
        last = fill_i; out.append((strat, d, ent, stop, fill_i, sp))
    for i in range(60, n - 60):
        a = atr[i]
        if a <= 0: continue
        # S1 хибний пробій: рівень = макс/мін 48 барів до i-1, бар i виносить і закривається назад
        hi48 = max(x[2] for x in b[i - 48:i]); lo48 = min(x[3] for x in b[i - 48:i])
        if b[i][2] > hi48 and b[i][4] < hi48 and (b[i][2] - b[i][4]) > 0.3 * a: add(i, "S1 хибний пробій", -1, b[i + 1][1], b[i][2] + 0.1 * a, i + 1)
        elif b[i][3] < lo48 and b[i][4] > lo48 and (b[i][4] - b[i][3]) > 0.3 * a: add(i, "S1 хибний пробій", 1, b[i + 1][1], b[i][3] - 0.1 * a, i + 1)
        # S3 сильна свічка → лімітний вхід на 50% (виконання в наступні 8 барів)
        vs = sum(vol[i - 20:i]) / 20 if i >= 20 else 0
        if (b[i][2] - b[i][3]) >= 1.2 * a and vs > 0 and vol[i] >= 2 * vs:
            d = 1 if b[i][4] > b[i][1] else -1; mid = (b[i][2] + b[i][3]) / 2
            stop = b[i][3] - 0.1 * a if d == 1 else b[i][2] + 0.1 * a
            for j in range(i + 1, i + 9):
                if (b[j][3] <= mid) if d == 1 else (b[j][2] >= mid):
                    add(i, "S3 сильна свічка→відкат 50%", d, mid, stop, j); break
        # S4 відкат до EMA20 у тренді H1 (H1 ема з кожного 4-го закриття)
        hi_idx = i // 4
        if 50 < hi_idx < len(e20h):
            tr = 1 if e20h[hi_idx - 1] > e50h[hi_idx - 1] else -1
            if tr == 1 and b[i][3] <= e20[i] and b[i][4] > e20[i] and b[i][4] > b[i][1]: add(i, "S4 відкат EMA20 у тренді", 1, b[i + 1][1], min(b[i][3], b[i - 1][3]) - 0.1 * a, i + 1)
            if tr == -1 and b[i][2] >= e20[i] and b[i][4] < e20[i] and b[i][4] < b[i][1]: add(i, "S4 відкат EMA20 у тренді", -1, b[i + 1][1], max(b[i][2], b[i - 1][2]) + 0.1 * a, i + 1)
        # S5 пробій діапазону відкриття сесії: OR = перші 2 бари (30 хв) London 07:00 / NY 13:30 (бар 13:30)
        t = b[i][0]; hm = (t // 60) % 1440
        for start in (7 * 60, 13 * 60 + 30):
            if hm == start + 30 + 15 and i >= 3:  # після закритого OR (2 бари) — перший бар після
                orh = max(b[i - 2][2], b[i - 1][2]); orl = min(b[i - 2][3], b[i - 1][3])
                if b[i][4] > orh: add(i, "S5 пробій діапазону сесії", 1, b[i + 1][1], orl, i + 1)
                elif b[i][4] < orl: add(i, "S5 пробій діапазону сесії", -1, b[i + 1][1], orh, i + 1)
    return out
data = {s: load(s) for s in SYMS}; data = {k: v for k, v in data.items() if v}
all_ts = sorted(x[0] for v in data.values() for x in v); T0, T1 = all_ts[0], all_ts[-1]; cut = T0 + int((T1 - T0) * 0.55); emb = 2 * 86400
trades = collections.defaultdict(list)
for s, b in data.items():
    for strat, d, ent, stop, fi, sp in signals(s, b):
        for m in (1.5, 2.0):
            tp = ent + d * m * abs(ent - stop); r = sim(b, fi, d, ent, stop, tp)
            if r is None: continue
            ts = b[fi][0]; trades[(strat, m)].append(dict(ts=ts, day=ts // 86400, r=(m if r > 0 else -1.0), sp=sp, ses=session(ts), sym=s))
def ci(xs):
    cl = collections.defaultdict(list)
    for x in xs: cl[x["day"]].append(x["net"])
    ks = list(cl)
    if len(ks) < 8: return (float("nan"),) * 2
    ms = []
    for _ in range(400):
        a = c = 0
        for _ in ks: v = cl[random.choice(ks)]; a += sum(v); c += len(v)
        ms.append(a / c)
    ms.sort(); return ms[10], ms[389]
print(f"монет {len(data)}, період {dt.datetime.utcfromtimestamp(T0):%Y-%m-%d} … {dt.datetime.utcfromtimestamp(T1):%Y-%m-%d}; межа TRAIN/TEST {dt.datetime.utcfromtimestamp(cut):%Y-%m-%d}\n")
print("| стратегія | ціль | комісія | TRAIN n | TRAIN R/угоду | TEST n | TEST R/угоду | TEST CI95 | TEST $ ($10/угоду) | $/добу TEST | ✅ |\n|--|--|--|--|--|--|--|--|--|--|--|")
found = []; days_test = (T1 - cut - emb) / 86400
for (strat, m), L in sorted(trades.items()):
    for cost in (0.10, 0.05):
        for x in L: x["net"] = x["r"] - cost / x["sp"]
        tr = [x for x in L if x["ts"] < cut]; te = [x for x in L if x["ts"] >= cut + emb]
        if len(tr) < 30 or len(te) < 30: continue
        mt = sum(x["net"] for x in tr) / len(tr); me = sum(x["net"] for x in te) / len(te); lo, hi = ci(te)
        ok = mt > 0 and me > 0 and lo > 0
        if ok: found.append((strat, m, cost))
        print(f"| {strat} | {m}R | {cost:.2f}% | {len(tr)} | {mt:+.3f} | {len(te)} | {me:+.3f} | [{lo:+.3f}; {hi:+.3f}] | {sum(x['net'] for x in te)*10:+,.0f} | {sum(x['net'] for x in te)*10/days_test:+,.0f} | {'✅' if ok else ''} |")
print("\n## Сесії (TEST), лише за стратегіями, що пройшли ✅:" if found else "\nЖодна стратегія не пройшла критерій (TRAIN>0, TEST>0, CI95>0).")
for strat, m, cost in found:
    L = trades[(strat, m)]
    for x in L: x["net"] = x["r"] - cost / x["sp"]
    te = [x for x in L if x["ts"] >= cut + emb]
    print(f"\n{strat}, {m}R, комісія {cost:.2f}%:")
    for ses in ("Азія", "Лондон", "перекриття", "пізня"):
        S = [x for x in te if x["ses"] == ses]
        if S: print(f"  {ses}: n={len(S)}, R/угоду {sum(x['net'] for x in S)/len(S):+.3f}, $ {sum(x['net'] for x in S)*10:+,.0f}")
print("\nКратне порівняння: 4 стратегії × 2 цілі × 2 комісії = 16 перевірок. ✅ — кандидат; обов'язкове підтвердження живими сигналами (shadow) перед використанням.")
