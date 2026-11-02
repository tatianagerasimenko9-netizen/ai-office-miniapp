"""READ-ONLY бектест (без ордерів). «Імпульс -> відкат (Фібоначчі як ЗОНА) -> продовження».
Джерело рівнів: docs/sources (Дарія: retracement 23.6/38.2/50/61.8/78.6, extension 100/127.2/161.8 як ЗОНИ; «спочатку структура, потім Фібоначчі»).
Усе інше (розмір ноги в ATR, підтвердження, вікна, стоп-буфер) — ГІПОТЕЗА. Дані: {SYM}/15m.csv.
Нога: пара послідовних swing-піків (pivot k=4) розміром >= MINLEG * ATR14.  Після нижнього піка B (шорт-продовження) чекаємо відкат до зони,
вхід -> стоп за структурою -> цілі: T1 = кінець ноги (100%), T2 = 127.2%, T3 = 161.8%.
Використання: swing_fib.py CANDLES_DIR SYMS COST"""
import sys, random
from pathlib import Path
import numpy as np, pandas as pd

random.seed(7)
CD = Path(sys.argv[1]); SYMS = sys.argv[2].split(","); COST = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0005
K = 4; WAIT = 48; HZ = 96; DAY = 86400
SPLIT = pd.Timestamp("2025-11-01").timestamp()
MIN_SP, MAX_SP = 0.003, 0.03
ENTRIES = ("E1 ліміт 50%", "E2 ліміт 61.8%", "E3 підтвердження (свічка продовження)")
EXITS = ("T1 все (100% ноги)", "T2 все (127.2%)", "T3 все (161.8%)", "50% T1 + беззбиток, 50% T2")


def load(s):
    p = CD / s / "15m.csv"
    if not p.exists(): return None
    return pd.read_csv(p).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    cs = np.cumsum(np.r_[0, tr]); out = np.full(len(c), np.nan); n = len(c)
    out[14:] = (cs[15:] - cs[1:n - 13]) / 14
    return out


def pivots(h, l):
    """список (idx, 'H'/'L', price, confirm_idx), чергування H/L (лишаємо екстремальніший)"""
    n = len(h); raw = []
    for j in range(K, n - K):
        if h[j] == h[j - K:j + K + 1].max(): raw.append((j, "H", h[j], j + K))
        if l[j] == l[j - K:j + K + 1].min(): raw.append((j, "L", l[j], j + K))
    raw.sort(key=lambda x: (x[0], x[1]))
    out = []
    for p in raw:
        if out and out[-1][1] == p[1]:
            if (p[1] == "H" and p[2] > out[-1][2]) or (p[1] == "L" and p[2] < out[-1][2]): out[-1] = p
        else: out.append(p)
    return out


def exit_sim(h, l, c, q, side, ent, sl, t1, t2, t3, mode):
    """повертає R (до комісії). SL-first; беззбиток з наступного бару після T1."""
    risk = abs(ent - sl)
    if risk <= 0: return None
    pos = 1.0; r = 0.0; be = False
    tg = {0: [(1.0, t1)], 1: [(1.0, t2)], 2: [(1.0, t3)], 3: [(0.5, t1), (0.5, t2)]}[mode]; done = [False] * len(tg)
    stop = sl
    for k in range(1, HZ + 1):
        j = q + k
        if j >= len(c): break
        if (l[j] <= stop) if side > 0 else (h[j] >= stop):
            return r + pos * side * (stop - ent) / risk
        for n, (fr, px) in enumerate(tg):
            if done[n]: continue
            if (h[j] >= px) if side > 0 else (l[j] <= px):
                r += fr * side * (px - ent) / risk; pos -= fr; done[n] = True
                if mode == 3 and n == 0: stop = ent
        if pos <= 1e-9: return r
    return r + pos * side * (c[min(q + HZ, len(c) - 1)] - ent) / risk


def trades(d, minleg):
    t = d.open_time.to_numpy(float); o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = atr14(h, l, c); n = len(c); out = []
    pv = pivots(h, l)
    for m in range(1, len(pv)):
        A, B = pv[m - 1], pv[m]
        cb = B[3]
        if cb + WAIT + HZ + 2 >= n or not a[B[0]] == a[B[0]]: continue
        D = abs(A[2] - B[2])
        if D < minleg * a[B[0]]: continue
        side = -1 if B[1] == "L" else 1                     # нога вниз -> шорт-продовження; вгору -> лонг
        sgn = -side                                         # напрям відкату
        lv = lambda r: B[2] + sgn * r * D                   # рівень відкату r від B у бік A
        t1p, t2p, t3p = B[2] + side * 0.0 * D, B[2] + side * 0.272 * D, B[2] + side * 0.618 * D
        # T1 = кінець ноги (B), T2 = 127.2% ноги (B + 0.272*D за B), T3 = 161.8%
        atr = a[B[0]]
        for ei, ename in enumerate(ENTRIES):
            ent = sl = None; q0 = None
            if ei < 2:
                lvl = lv(0.5 if ei == 0 else 0.618); stop = lv(0.786) + sgn * 0.1 * atr
                for q in range(cb + 1, cb + 1 + WAIT):
                    if (h[q] >= A[2]) if side < 0 else (l[q] <= A[2]): break      # досягли початку ноги — сценарій скасовано
                    hit = (h[q] >= lvl) if side < 0 else (l[q] <= lvl)
                    if hit:
                        stop_hit = (h[q] >= stop) if side < 0 else (l[q] <= stop)
                        ent, sl, q0 = lvl, stop, q
                        if stop_hit:
                            sp0 = abs(lvl - stop) / lvl
                            if MIN_SP <= sp0 <= MAX_SP and not ((side < 0 and lvl <= t1p) or (side > 0 and lvl >= t1p)):
                                for xi in range(4): out.append((ename, EXITS[xi], t[q], -1.0 - COST / sp0, sp0, abs(t1p - lvl) / abs(lvl - stop), 1))   # стоп у барі виконання = збиток
                            ent = None
                        break
            else:
                touched = False; ext_ = None
                for q in range(cb + 1, cb + 1 + WAIT):
                    if (h[q] >= A[2]) if side < 0 else (l[q] <= A[2]): break
                    ext_ = h[cb + 1:q + 1].max() if side < 0 else l[cb + 1:q + 1].min()
                    if (h[q] >= lv(0.382)) if side < 0 else (l[q] <= lv(0.382)): touched = True
                    if touched and ((c[q] < o[q] and c[q] < l[q - 1]) if side < 0 else (c[q] > o[q] and c[q] > h[q - 1])):
                        ent, sl, q0 = c[q], ext_ + sgn * 0.1 * atr, q; break
            if ent is None: continue
            sp = abs(ent - sl) / ent
            if not (MIN_SP <= sp <= MAX_SP): continue
            if (side < 0 and sl <= ent) or (side > 0 and sl >= ent): continue
            if (side < 0 and ent <= t1p) or (side > 0 and ent >= t1p): continue    # вхід уже нижче/вище цілі
            for xi in range(4):
                r = exit_sim(h, l, c, q0, side, ent, sl, t1p, t2p, t3p, xi)
                if r is None: continue
                out.append((ename, EXITS[xi], t[q0], r - COST / sp, sp, abs(t1p - ent) / abs(ent - sl), 1))
    return [x for x in out if x[6] == 1]


def boot(dd, n=1500):
    ks = list(dd)
    if not ks: return 0, 0
    ms = []
    for _ in range(n):
        s = cnt = 0
        for _ in ks:
            v = dd[random.choice(ks)]; s += sum(v); cnt += len(v)
        ms.append(s / cnt)
    ms.sort(); return ms[int(.025 * n)], ms[int(.975 * n)]


def main():
    for minleg in (3, 5):
        rows = []
        for s in SYMS:
            d = load(s)
            if d is None: continue
            for x in trades(d, minleg): rows.append((s,) + x)
        if not rows: print("немає угод"); continue
        df = pd.DataFrame(rows, columns=["sym", "entry", "exit", "t", "r", "sp", "planR", "k"])
        df["year"] = pd.to_datetime(df.t, unit="s").dt.year
        yrs = sorted(df.year.unique()); days = (df.t.max() - df.t.min()) / DAY
        print(f"\n=== Нога >= {minleg} ATR; комісія {COST*100:.2f}%; угод (усі вхід×вихід) {len(df)}; період {days:.0f} діб ===")
        print("R/угоду і $ ($10 ризику) по роках; ✅ = плюс у КОЖНОМУ році з n>=20")
        print("| вхід | вихід | " + " | ".join(f"{y} n/R/$" for y in yrs) + " | усього $ | CI95 | ✅ |\n|--|--|" + "--|" * (len(yrs) + 3))
        good = []
        for e in ENTRIES:
            for x in EXITS:
                z = df[(df.entry == e) & (df["exit"] == x)]
                cells = []; ok = True; seen = 0
                for y in yrs:
                    q = z[z.year == y]
                    if len(q) < 20: cells.append(f"{len(q)}/–/–"); continue
                    seen += 1; cells.append(f"{len(q)}/{q.r.mean():+.2f}/{10*q.r.sum():+,.0f}")
                    if q.r.mean() <= 0: ok = False
                if seen < 3: ok = False
                dd = {}
                for tt, rr in zip(z.t, z.r): dd.setdefault(int(tt // DAY), []).append(rr)
                lo, hi = boot(dd) if len(z) else (0, 0)
                if ok: good.append((e, x))
                print(f"| {e} | {x} | " + " | ".join(cells) + f" | {10*z.r.sum():+,.0f} | [{lo:+.3f}; {hi:+.3f}] | {'✅' if ok else ''} |")
        for e, x in good:
            z = df[(df.entry == e) & (df["exit"] == x)]
            print(f"\n✅ {e} / {x}: угод на добу {len(z)/days:.1f} (12 монет); по сесіях UTC:", end=" ")
            for nm, lo_, hi_ in (("Азія 0-7", 0, 7), ("Лондон 7-13", 7, 13), ("НЙ 13-24", 13, 24)):
                hh = (z.t % DAY) // 3600; q = z[(hh >= lo_) & (hh < hi_)]
                print(f"{nm}: n={len(q)} R={q.r.mean() if len(q) else 0:+.3f} $={10*q.r.sum():+,.0f};", end=" ")
            print()
        if not good: print("\nЖодна комбінація не дала плюс у кожному році.")
    print("\nПримітка: ~24 комбінації × 2 довжини ноги — кратне порівняння; ✅ = лише кандидат для shadow.")


main()
