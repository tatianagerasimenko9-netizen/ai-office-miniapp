"""READ-ONLY бектест (без ордерів). Старший ТФ (D1 рівні Герчика / H4 канал) + вхід на M5 / M1.
Використання: htf_ltf_search.py CANDLES_DIR SYM1,SYM2,...   (потрібні {SYM}/1d.csv 4h.csv 5m.csv 1m.csv)
Усі пороги, яких нема в SOURCE_RULES, позначені ГІПОТЕЗА. Джерело: Герчик — рівень D1 (≥3 удари, відбій/пробій, закриття як сигнал).
Результат у $ при $10 ризику на угоду; TRAIN перші 55% часу / TEST останні 45%; CI95 — bootstrap по днях."""
import sys, random
from pathlib import Path
import numpy as np, pandas as pd

random.seed(7)
CD = Path(sys.argv[1]); SYMS = sys.argv[2].split(",")
DAY = 86400
H_BARS = {"5m": 864, "1m": 4320}      # горизонт 72 год
COSTS = (0.0010, 0.0005)              # ГІПОТЕЗА: комісії+проковзування round-trip
TGTS = (2.0, 3.0)
MIN_STOP, MAX_STOP = 0.002, 0.03      # ГІПОТЕЗА: фільтр розміру стопа


def load(s, tf):
    p = CD / s / f"{tf}.csv"
    if not p.exists():
        return None
    d = pd.read_csv(p).drop_duplicates("open_time").sort_values("open_time")
    return {k: d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}


def atr(ser, n=14):
    h, l, c = ser["high"], ser["low"], ser["close"]
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.full(len(tr), np.nan)
    cs = np.cumsum(np.r_[0, tr])
    out[n:] = (cs[n + 1:] - cs[1:len(tr) - n + 1]) / n   # ATR за n попередніх барів (без поточного)
    return out


def resolve(ser, e, side, entry, sl, tgt_r, hb):
    risk = abs(entry - sl)
    hi, lo = ser["high"][e + 1:e + 1 + hb], ser["low"][e + 1:e + 1 + hb]
    if len(hi) == 0:
        return None
    tp = entry + side * tgt_r * risk
    if side > 0:
        sli = np.argmax(lo <= sl) if (lo <= sl).any() else 10**9
        tpi = np.argmax(hi >= tp) if (hi >= tp).any() else 10**9
    else:
        sli = np.argmax(hi >= sl) if (hi >= sl).any() else 10**9
        tpi = np.argmax(lo <= tp) if (lo <= tp).any() else 10**9
    if sli == 10**9 and tpi == 10**9:
        return side * (ser["close"][min(e + hb, len(ser["close"]) - 1)] - entry) / risk
    return -1.0 if sli <= tpi else tgt_r


def first_touch(m5, t_from, t_to, level, side_touch, tol):
    """перший M5 бар у вікні, що торкнувся рівня; side_touch=+1 — ціна підходить знизу (опір), -1 — зверху (підтримка)"""
    i0 = int(np.searchsorted(m5["open_time"], t_from)); i1 = int(np.searchsorted(m5["open_time"], t_to))
    if i1 <= i0:
        return None
    if side_touch > 0:
        idx = np.nonzero(m5["high"][i0:i1] >= level - tol)[0]
    else:
        idx = np.nonzero(m5["low"][i0:i1] <= level + tol)[0]
    return i0 + int(idx[0]) if len(idx) else None


def setups_for(sym, d1, h4, m5):
    out = []
    a1 = atr(d1)
    n = len(d1["close"]); k = 3
    hi, lo, cl, ot = d1["high"], d1["low"], d1["close"], d1["open_time"]
    for j in range(k + 14, n - k):
        for typ in ("H", "L"):
            if typ == "H" and not hi[j] == hi[j - k:j + k + 1].max(): continue
            if typ == "L" and not lo[j] == lo[j - k:j + k + 1].min(): continue
            L = hi[j] if typ == "H" else lo[j]
            i0 = j + k; ad = a1[i0] if i0 < n else np.nan
            if not ad == ad: continue
            lo_i = max(0, i0 - 90)
            touches = int((abs((hi if typ == "H" else lo)[lo_i:i0 + 1] - L) <= 0.25 * ad).sum())
            strong = touches >= 3                                   # Герчик: лімітний рівень ≥3 удари
            m = next((x for x in range(i0 + 1, min(n, i0 + 91)) if (cl[x] > L if typ == "H" else cl[x] < L)), None)
            t_end = (ot[m] + DAY) if m is not None else ot[min(n - 1, i0 + 90)]
            tol = 0.1 * ad
            # ВІДБІЙ: опір -> шорт, підтримка -> лонг
            ti = first_touch(m5, ot[i0] + DAY, ot[m] + DAY if m is not None else t_end, L, +1 if typ == "H" else -1, tol)
            if ti is not None:
                side = -1 if typ == "H" else 1
                out.append(dict(sym=sym, strat="G_відбій", strong=strong, side=side, level=L, ti=ti, e0_sl=L - side * 0.5 * ad, atrd=ad))
            # РЕТЕСТ ПРОБОЮ: після D1-закриття за рівнем, повернення до рівня, 3 доби
            if m is not None and m + 1 < n:
                t0 = ot[m] + DAY
                ti2 = first_touch(m5, t0, t0 + 3 * DAY, L, -1 if typ == "H" else +1, tol)
                if ti2 is not None:
                    side = 1 if typ == "H" else -1
                    out.append(dict(sym=sym, strat="G_ретест", strong=strong, side=side, level=L, ti=ti2, e0_sl=L - side * 0.5 * ad, atrd=ad))
    # H4 пробій каналу 20 (ГІПОТЕЗА: N=20, стоп=структура 10 барів H4)
    N = 20; ah = a1
    last = {1: -1e18, -1: -1e18}
    hh, ll, cc, oh = h4["high"], h4["low"], h4["close"], h4["open_time"]
    for i in range(N, len(cc)):
        t0 = oh[i] + 4 * 3600
        for side in (1, -1):
            lvl = hh[i - N:i].max() if side > 0 else ll[i - N:i].min()
            if (cc[i] > lvl if side > 0 else cc[i] < lvl) and t0 - last[side] > DAY:
                di = int(np.searchsorted(ot, t0)) - 1
                ad = a1[di] if 0 <= di < n else np.nan
                if not ad == ad: continue
                ti = first_touch(m5, t0, t0 + DAY, lvl, -1 if side > 0 else +1, 0.1 * ad)
                last[side] = t0
                if ti is None: continue
                sl = ll[i - 9:i + 1].min() if side > 0 else hh[i - 9:i + 1].max()
                out.append(dict(sym=sym, strat="T_H4канал", strong=True, side=side, level=lvl, ti=ti, e0_sl=sl, atrd=ad))
    return out


def trades_for(sym, st, m5, m1, a5, a1m):
    res = []
    side, L, ti = st["side"], st["level"], st["ti"]
    t0 = m5["open_time"][ti]
    # E0: ліміт на рівні в момент дотику, стоп HTF
    sl = st["e0_sl"]; sp = abs(L - sl) / L
    if MIN_STOP <= sp <= MAX_STOP:
        for tg in TGTS:
            r = resolve(m5, ti, side, L, sl, tg, H_BARS["5m"])
            if r is not None: res.append(("E0 ліміт на рівні", tg, r, sp, t0))
    # E1: M5 підтвердження — закриття за рівнем у бік угоди, стоп за екстремумом реакції
    for q in range(ti, min(ti + 36, len(m5["close"]) - 1)):
        if (m5["close"][q] > L) if side > 0 else (m5["close"][q] < L):
            ext = m5["low"][ti:q + 1].min() if side > 0 else m5["high"][ti:q + 1].max()
            b = a5[q] if a5[q] == a5[q] else 0
            sl = ext - side * 0.1 * b; ent = m5["close"][q]; sp = abs(ent - sl) / ent
            if sl != ent and MIN_STOP <= sp <= MAX_STOP and (ent - sl) * side > 0:
                for tg in TGTS:
                    r = resolve(m5, q, side, ent, sl, tg, H_BARS["5m"])
                    if r is not None: res.append(("E1 M5 підтвердження", tg, r, sp, m5["open_time"][q]))
            break
    # E2: M1 мікро-пробій екстремуму 10 барів, після торкання рівня
    if m1 is not None:
        j0 = int(np.searchsorted(m1["open_time"], t0))
        for q in range(max(j0 + 10, 10), min(j0 + 180, len(m1["close"]) - 1)):
            c = m1["close"][q]
            ok = (c > L and c > m1["high"][q - 10:q].max()) if side > 0 else (c < L and c < m1["low"][q - 10:q].min())
            if ok:
                ext = m1["low"][j0:q + 1].min() if side > 0 else m1["high"][j0:q + 1].max()
                b = a1m[q] if a1m[q] == a1m[q] else 0
                sl = ext - side * 0.1 * b; sp = abs(c - sl) / c
                if MIN_STOP <= sp <= MAX_STOP and (c - sl) * side > 0:
                    for tg in TGTS:
                        r = resolve(m1, q, side, c, sl, tg, H_BARS["1m"])
                        if r is not None: res.append(("E2 M1 мікро-пробій", tg, r, sp, m1["open_time"][q]))
                break
    return res


def boot_ci(day_to_r, n=2000):
    days = list(day_to_r); tot = sum(len(v) for v in day_to_r.values())
    if not days or tot == 0: return (0, 0)
    ms = []
    for _ in range(n):
        s = c = 0
        for _ in days:
            v = day_to_r[random.choice(days)]; s += sum(v); c += len(v)
        ms.append(s / c if c else 0)
    ms.sort(); return ms[int(.025 * n)], ms[int(.975 * n)]


def main():
    rows = []   # (strat, strong, entry, tgt, ts, R_gross, stop_pct)
    for s in SYMS:
        d1, h4, m5, m1 = load(s, "1d"), load(s, "4h"), load(s, "5m"), load(s, "1m")
        if d1 is None or h4 is None or m5 is None:
            print("пропуск", s); continue
        a5 = atr(m5); a1m = atr(m1) if m1 is not None else None
        for st in setups_for(s, d1, h4, m5):
            for en, tg, r, sp, ts in trades_for(s, st, m5, m1, a5, a1m):
                rows.append((st["strat"], st["strong"], en, tg, ts, r, sp))
        print(s, "setups зібрано, угод усього", len(rows), flush=True)
    if not rows:
        print("немає угод"); return
    ts_all = sorted(r[4] for r in rows); span_days = max(1, (ts_all[-1] - ts_all[0]) / DAY)
    cut = ts_all[0] + 0.55 * (ts_all[-1] - ts_all[0]); emb = cut + 2 * DAY
    print(f"\nУгод усього {len(rows)}, період {span_days:.0f} діб. TRAIN до {cut:.0f}, TEST після {emb:.0f}\n")
    print("| стратегія | рівень | вхід | ціль | комісія | n train | R train | n test | R test | CI95 test | $ test (на $10/угоду) | $/міс (test) | ✅ |")
    print("|--|--|--|--|--|--|--|--|--|--|--|--|--|")
    passed = []
    for strat in sorted({r[0] for r in rows}):
        for lvlname, pred in (("будь-який", lambda r: True), ("сильний ≥3", lambda r: r[1])):
            if strat.startswith("T_") and lvlname != "будь-який": continue
            for en in sorted({r[2] for r in rows}):
                for tg in TGTS:
                    for cost in COSTS:
                        sel = [r for r in rows if r[0] == strat and pred(r) and r[2] == en and r[3] == tg]
                        net = [(r[4], r[5] - cost / r[6]) for r in sel]
                        tr = [x for t, x in net if t < cut]; te = [(t, x) for t, x in net if t >= emb]
                        if len(tr) < 20 or len(te) < 20: continue
                        dd = {}
                        for t, x in te: dd.setdefault(int(t // DAY), []).append(x)
                        lo, hi = boot_ci(dd)
                        mtr = sum(tr) / len(tr); mte = sum(x for _, x in te) / len(te)
                        tdays = max(1, (ts_all[-1] - emb) / DAY)
                        dol = 10 * sum(x for _, x in te)
                        ok = mtr > 0 and mte > 0 and lo > 0
                        if ok: passed.append((strat, lvlname, en, tg, cost, te))
                        print(f"| {strat} | {lvlname} | {en} | {tg:.0f}R | {cost*100:.2f}% | {len(tr)} | {mtr:+.3f} | {len(te)} | {mte:+.3f} | [{lo:+.3f}; {hi:+.3f}] | {dol:+,.0f} | {dol/tdays*30:+,.0f} | {'✅' if ok else ''} |")
    print()
    if not passed:
        print("Жодна комбінація не пройшла критерій (TRAIN>0, TEST>0, CI95>0).")
    else:
        for strat, lvl, en, tg, cost, te in passed:
            print(f"✅ {strat} / {lvl} / {en} / {tg:.0f}R / {cost*100:.2f}% — розбивка TEST за сесіями UTC:")
            blocks = {}
            for t, x in te: blocks.setdefault(int((t % DAY) // 3600 // 4) * 4, []).append(x)
            for b in sorted(blocks): print(f"   {b:02d}-{b+4:02d} UTC: n={len(blocks[b])}, R/угоду {sum(blocks[b])/len(blocks[b]):+.3f}")
    nm = len(set((r[0], r[2], r[3]) for r in rows)) * 2 * len(COSTS)
    print(f"\nКратне порівняння: ~{nm}+ перевірок. ✅ — лише кандидат, потрібне підтвердження живим shadow.")


main()
