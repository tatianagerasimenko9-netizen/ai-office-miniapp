"""READ-ONLY. Подія «зняття ліквідності азійського діапазону» (як у сигналах бота: Asian range -> sweep -> повернення в діапазон).
День UTC: Азія 00:00-07:00 (hi/lo). Після 07:00 до 21:00: бар виходить за межу діапазону (sweep), потім M15 закривається назад всередині -> сигнал у протилежний бік.
Короткий сценарій: sweep вище Asian high, закриття назад нижче -> SHORT, стоп = екстремум sweep + 0.1 ATR, цілі: протилежна межа діапазону / 2R / 3R. Дзеркально для LONG.
Входи: E1 = ринок на закритті повернення; E2 = ліміт на межі діапазону (ретест, чекаємо 16 барів).
Усі пороги (07:00, 21:00, буфер 0.1 ATR, min/max стоп) — ГІПОТЕЗА. По роках 2022..2026; ✅ = плюс у кожному році (n>=20) та нижня межа CI95 по днях >0.
Використання: asian_sweep.py CANDLES_DIR SYMS COST [CASE_SYM CASE_DATE]"""
import sys, random
from pathlib import Path
import numpy as np, pandas as pd
random.seed(7)
CD = Path(sys.argv[1]); SYMS = sys.argv[2].split(","); COST = float(sys.argv[3])
CASE = (sys.argv[4], sys.argv[5]) if len(sys.argv) > 5 else None
DAY = 86400; MIN_SP, MAX_SP = 0.003, 0.04; HZ = 96
X = ("X1 ціль = протилежна межа Азії", "X2 ціль 2R", "X3 ціль 3R")

def load(s):
    p = CD / s / "15m.csv"
    if not p.exists(): return None
    return pd.read_csv(p).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)

def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    cs = np.cumsum(np.r_[0, tr]); n = len(c); out = np.full(n, np.nan); out[14:] = (cs[15:] - cs[1:n - 13]) / 14
    return out

def outcome(h, l, c, q, side, ent, sl, tp):
    risk = abs(ent - sl)
    for k in range(1, HZ + 1):
        j = q + k
        if j >= len(c): break
        if (l[j] <= sl) if side > 0 else (h[j] >= sl): return -1.0
        if (h[j] >= tp) if side > 0 else (l[j] <= tp): return side * (tp - ent) / risk
    return side * (c[min(q + HZ, len(c) - 1)] - ent) / risk

def events(sym, d, verbose=False):
    t = d.open_time.to_numpy(float); o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close")); a = atr14(h, l, c)
    day = (t // DAY).astype(int); hr = ((t % DAY) // 3600).astype(int); out = []
    idx = pd.Series(np.arange(len(t))).groupby(day).agg(["min", "max"])
    for dd, (i0, i1) in idx.iterrows():
        sl_ = slice(i0, i1 + 1); hh = hr[sl_]
        am = np.nonzero(hh < 7)[0]
        if len(am) < 24 or i1 - i0 < 90: continue
        ah, al = h[i0 + am].max(), l[i0 + am].min()
        if ah <= al: continue
        for side in (-1, 1):                                  # -1: sweep вгору -> SHORT; +1: sweep вниз -> LONG
            ext = None
            for q in range(i0 + am[-1] + 1, i1 + 1):
                if hr[q] >= 21: break
                swept = (h[q] > ah) if side < 0 else (l[q] < al)
                if swept:
                    v = h[q] if side < 0 else l[q]
                    ext = v if ext is None else (max(ext, v) if side < 0 else min(ext, v))
                if ext is None: continue
                back = (c[q] < ah) if side < 0 else (c[q] > al)
                if not back: continue
                atr = a[q]
                if not atr == atr: break
                sl = ext + 0.1 * atr if side < 0 else ext - 0.1 * atr
                edge = ah if side < 0 else al; opp = al if side < 0 else ah
                for en, ent, q0 in (("E1 ринок на поверненні", c[q], q), ("E2 ліміт на межі діапазону", edge, None)):
                    if en.startswith("E2"):
                        q0 = None
                        for qq in range(q + 1, min(q + 17, i1 + 1)):
                            if (h[qq] >= edge) if side < 0 else (l[qq] <= edge): q0 = qq; break
                            if (l[qq] <= sl) if side > 0 else (h[qq] >= sl): break
                        if q0 is None: continue
                        if (h[q0] >= sl) if side < 0 else (l[q0] <= sl):
                            sp = abs(ent - sl) / ent
                            if MIN_SP <= sp <= MAX_SP:
                                for xi in range(3): out.append((sym, en, X[xi], t[q0], -1.0 - COST / sp, sp, 0.0, int(hr[q] < 12)))
                            continue
                    sp = abs(ent - sl) / ent
                    if not (MIN_SP <= sp <= MAX_SP) or (side < 0 and sl <= ent) or (side > 0 and sl >= ent): continue
                    risk = abs(ent - sl); planR = abs(ent - opp) / risk
                    if (side < 0 and opp >= ent) or (side > 0 and opp <= ent): continue
                    d_ = -1 if side < 0 else 1                      # напрям УГОДИ: sweep вгору -> шорт (-1)
                    tps = (opp, ent + d_ * 2 * risk, ent + d_ * 3 * risk)
                    for xi in range(3):
                        r = outcome(h, l, c, q0, d_, ent, sl, tps[xi])
                        out.append((sym, en, X[xi], t[q0], r - COST / sp, sp, planR, int(hr[q] < 12)))
                    if verbose: print(f"   {sym} {pd.to_datetime(t[q], unit='s')} {'SHORT' if side<0 else 'LONG'} {en}: Asia {al:.4f}-{ah:.4f}, sweep-екстремум {ext:.4f}, вхід {ent:.4f}, стоп {sl:.4f} ({sp*100:.2f}%), план до протилежної межі {planR:.1f}R")
                break
    return out

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
    if CASE:
        d = load(CASE[0])
        if d is not None:
            dt = pd.Timestamp(CASE[1]).timestamp(); dd = d[(d.open_time >= dt - 86400) & (d.open_time < dt + 2 * 86400)].reset_index(drop=True)
            print(f"=== КЕЙС {CASE[0]} {CASE[1]} (дні -1..+1) ==="); events(CASE[0], dd, verbose=True)
        else: print("кейс: немає даних", CASE[0])
    rows = []
    for s in SYMS:
        d = load(s)
        if d is None: continue
        rows += events(s, d); print(s, len(rows), flush=True)
    df = pd.DataFrame(rows, columns=["sym", "entry", "exit", "t", "r", "sp", "planR", "london"]); df["year"] = pd.to_datetime(df.t, unit="s").dt.year
    yrs = sorted(df.year.unique()); days = (df.t.max() - df.t.min()) / DAY
    print(f"\nКомісія {COST*100:.2f}%; період {days:.0f} діб; подій-сигналів (E1) на добу на {len(SYMS)} монет: {len(df[(df.entry.str.startswith('E1')) & (df['exit']==X[0])])/days:.1f}")
    print("| вхід | вихід | сер. планR | " + " | ".join(f"{y} n/R/$" for y in yrs) + " | усього $ | CI95 | ✅ |\n|--|--|--|" + "--|" * (len(yrs) + 3))
    good = []
    for e in sorted(df.entry.unique()):
        for x in X:
            z = df[(df.entry == e) & (df["exit"] == x)]; cells = []; ok = True; seen = 0
            for y in yrs:
                q = z[z.year == y]
                if len(q) < 20: cells.append(f"{len(q)}/–/–"); continue
                seen += 1; cells.append(f"{len(q)}/{q.r.mean():+.2f}/{10*q.r.sum():+,.0f}")
                if q.r.mean() <= 0: ok = False
            dd = {}
            for tt, rr in zip(z.t, z.r): dd.setdefault(int(tt // DAY), []).append(rr)
            lo, hi = boot(dd) if len(z) else (0, 0); ok = ok and seen >= 3 and lo > 0
            if ok: good.append((e, x))
            print(f"| {e} | {x} | {z.planR.mean():.1f} | " + " | ".join(cells) + f" | {10*z.r.sum():+,.0f} | [{lo:+.3f}; {hi:+.3f}] | {'✅' if ok else ''} |")
    for e, x in good:
        z = df[(df.entry == e) & (df["exit"] == x)]
        print(f"✅ {e}/{x}: Лондон(<12 UTC) n={int(z.london.sum())} R={z[z.london==1].r.mean():+.3f}; Нью-Йорк n={int((1-z.london).sum())} R={z[z.london==0].r.mean():+.3f}")
    print(f"\n##### ПІДСУМОК комісія {COST*100:.2f}%: ✅ = {len(good)}")
main()
