"""READ-ONLY. B&R: ЧИМ СИГНАЛИ, ЩО ДІЙШЛИ ДО ЦІЛІ, ВІДРІЗНЯЮТЬСЯ ВІД СТОПІВ — ОБ'ЄМИ І ФОРМА СВІЧОК (28.11.2026, прохання власниці).
Усе нижче записано ДО запуску. ГІПОТЕЗА / наша автоматизація (не правила автора). Нічого не вмикає і не змінює в живих сигналах.

ДЕТЕКТОР: той самий, що в Офісі (office_br.detect: _follow/_targets/HYP), бари M15, 12 монет живого B&R, 2022-01 — 2026-11.
ВХІД: лімітна заявка на ціні входу сигналу, до 24 барів (як у br_hist.py). УТРИМАННЯ: 192 бари (48 год). Стоп-першим у спірному барі.
РЕЗУЛЬТАТ: стоп сигналу, ціль 3R (як рахується наживо) і довідково 2R. Комісія 0,10% за круг. Ризик $10.
ПЕРІОДИ: P1 2022–2023, P2 2024–2025, P3 2026.  ГРУПИ МОНЕТ: A (пошук) і B (контроль) — по 6 монет, поділ за абеткою через одну.
ОЗНАКА «працює» лише якщо її найкраща корзина в плюсі в усіх 6 клітинках (2 групи × 3 періоди). Інакше — НЕ ПІДТВЕРДЖЕНО.

ОЗНАКИ (усі відомі на момент підтвердження сигналу, бар q; b — бар пробою, j — бар ретесту):
 ОБ'ЄМ
  vb   об'єм бару пробою / середній об'єм 20 барів перед ним
  vp   середній об'єм барів відкату (b+1..q-1; якщо їх немає — бар q) / об'єм бару пробою   (малий = «тихий» відкат)
  vq   об'єм бару підтвердження / середній об'єм 20 барів перед пробоєм
  vd   середній об'єм 96 барів / середній об'єм 672 барів (доба проти тижня — чи «живий» ринок)
 ФОРМА СВІЧОК
  bb   тіло бару пробою / його розмах (сильне закриття)
  br   розмах бару пробою / ATR(14)
  bx   наскільки закриття пробою зайшло за рівень, в ATR
  qb   тіло бару підтвердження / його розмах
  qw   хвіст бару ретесту в бік рівня / його розмах (відбій хвостом)
  nq   скільки барів від пробою до підтвердження
 РІВЕНЬ І КОНТЕКСТ
  age  вік рівня: барів від пивота до пробою
  tch  скільки разів за 96 барів до пробою ціна підходила до рівня ближче ніж 0,2 ATR і не закривалась за ним
  ext  рух ціни за 96 барів до пробою в бік сигналу, в ATR (чи не «перегрітий» рух)
  tr4  сторона MA200 на H4 (за трендом = 1)
  tr1  нахил EMA50 на H1 у бік сигналу (1/0)
  atrp ATR(H4,14)/ціна (спокійна монета < 2,3%)
  btc  зміна BTC за 4 бари до q у бік сигналу, % (для самого BTC — його зміна)
  cl   скільки монет із 12 дали сигнал того ж напряму в тому ж барі q
  sp   розмір стопа, %
  hr   година UTC
КОРЗИНИ: для числових ознак — терцилі, межі рахуються ЛИШЕ на групі A періоду P1 і застосовуються до всіх.
ЗАЗДАЛЕГІДЬ ЗАПИСАНІ ПОЄДНАННЯ (перевіряються як є, без підгонки):
  K1  vb ≥ 2 і sp ≥ 0,5                 (пробій на об'ємі, стоп не мікро)
  K2  vb ≥ 2 і vp ≤ 0,5                 (пробій на об'ємі, тихий відкат)
  K3  bb ≥ 0,7 і vb ≥ 1,5               (сильна свічка пробою з об'ємом)
  K4  tr4 = 1 і vb ≥ 2                  (за трендом і на об'ємі)
  K5  cl ≥ 3 і vb ≥ 1,5                 (рух усього ринку з об'ємом)
  K6  qw ≥ 0,5 і vp ≤ 0,7               (відбій хвостом на тихому відкаті)
  K7  vb ≥ 2 і vp ≤ 0,5 і sp ≥ 0,5 і tr4 = 1   (усе разом)
Використання: br_feat.py CANDLES_DIR SYMS OUT_CSV"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
from office_br import detect
CD, SYMS, OUT = sys.argv[1], sys.argv[2].split(","), sys.argv[3]
cfg = dict(detect.HYP); K = cfg["pivot_k"]; LB = cfg["lookback"]; HOR = 192; WAIT = 24; FEE = 0.10
GA = set(sorted(SYMS)[0::2])


def load(sym):
    return pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


BT = load("BTCUSDT").set_index("open_time").close if os.path.exists(f"{CD}/BTCUSDT/15m.csv") else None


def run(sym):
    d = load(sym)
    t, o, h, l, c, v = (d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close", "volume")); n = len(c)
    g = d.groupby(d.open_time // 14400 * 14400).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    pc = g.close.shift(1); tr = np.maximum(g.high - g.low, np.maximum((g.high - pc).abs(), (g.low - pc).abs()))
    g["ma"] = g.close.rolling(200).mean(); g["atrp"] = tr.rolling(14).mean() / g.close; g = g.shift(1)
    key = (t // 14400 * 14400); ma = g.ma.reindex(key).to_numpy(); atrp = g.atrp.reindex(key).to_numpy()
    g1 = d.groupby(d.open_time // 3600 * 3600).close.last(); e1 = g1.ewm(span=50, adjust=False).mean(); sl1 = (e1 - e1.shift(4)).shift(1)
    slope = sl1.reindex(t // 3600 * 3600).to_numpy()
    pcl = np.roll(c, 1); pcl[0] = c[0]; trb = np.maximum(h - l, np.maximum(np.abs(h - pcl), np.abs(l - pcl)))
    atr = pd.Series(trb).rolling(14).mean().to_numpy()
    v20 = pd.Series(v).rolling(20).mean().shift(1).to_numpy(); v96 = pd.Series(v).rolling(96).mean().to_numpy(); v672 = pd.Series(v).rolling(672).mean().to_numpy()
    btc = BT.reindex(t).to_numpy() if BT is not None else c
    PH = np.zeros(n, bool); PL = np.zeros(n, bool)
    for p in range(K, n - K):
        if all(h[p] > h[p - j] and h[p] >= h[p + j] for j in range(1, K + 1)): PH[p] = True
        if all(l[p] < l[p - j] and l[p] <= l[p + j] for j in range(1, K + 1)): PL[p] = True
    used = set(); rows = []
    for i in range(max(K * 2 + cfg["atr_n"], LB + 1, 700), n - 1):
        lo = i - LB; hi = i - K
        cand = [("H", p, h[p]) for p in range(lo, hi + 1) if PH[p]] + [("L", p, l[p]) for p in range(lo, hi + 1) if PL[p]]
        hit = [(ty, p, L) for ty, p, L in cand if (ty, p) not in used and ((ty == "H" and c[i] > L >= c[i - 1]) or (ty == "L" and c[i] < L <= c[i - 1]))]
        if not hit: continue
        piv = sorted([{"i": p, "p": float(L), "type": ty} for ty, p, L in cand], key=lambda x: x["i"])
        for ty, p, L in hit:
            used.add((ty, p))
            if any((c[j] > L) if ty == "H" else (c[j] < L) for j in range(p + 1, i)): continue
            dr = "LONG" if ty == "H" else "SHORT"
            res = detect._follow(dr, L, i, t, o, h, l, c, cfg, piv)
            if not res: continue
            q = res["confirm_i"]; j = res["retest_i"]; e = res["entry"]; risk = res["risk"]; sg = 1 if dr == "LONG" else -1
            t1 = res["targets"][0]["p"] if res["targets"] else e + sg * risk
            f = None
            for x in range(q + 1, min(n, q + 1 + WAIT)):
                if l[x] <= e <= h[x]: f = x; break
                if (h[x] >= t1) if sg > 0 else (l[x] <= t1): break
            if f is None or f + HOR >= n: continue
            H_, L_ = h[f:f + HOR], l[f:f + HOR]; last = c[f + HOR - 1]; slp = e - sg * risk
            hs = (L_ <= slp) if sg > 0 else (H_ >= slp); isl = int(np.argmax(hs)) if hs.any() else HOR + 1
            out = {}
            for k in (2, 3):
                tp = e + sg * k * risk; ht = (H_ >= tp) if sg > 0 else (L_ <= tp); itp = int(np.argmax(ht)) if ht.any() else HOR + 1
                out[k] = -1.0 if isl <= itp and isl <= HOR else (float(k) if itp <= HOR else sg * (last - e) / risk)
            a = atr[i] if atr[i] > 0 else np.nan; rb = max(h[i] - l[i], 1e-12); rq = max(h[q] - l[q], 1e-12); rj = max(h[j] - l[j], 1e-12)
            pull = v[i + 1:q].mean() if q > i + 1 else v[q]
            near = np.abs((h[i - 96:i] if ty == "H" else l[i - 96:i]) - L) <= 0.2 * a
            notbr = (c[i - 96:i] <= L) if ty == "H" else (c[i - 96:i] >= L)
            rows.append({"sym": sym, "ts": t[q], "side": sg, "r3": out[3], "r2": out[2], "sp": 100 * risk / e, "hr": int(t[q] // 3600 % 24),
                         "vb": v[i] / v20[i] if v20[i] > 0 else np.nan, "vp": pull / v[i] if v[i] > 0 else np.nan, "vq": v[q] / v20[i] if v20[i] > 0 else np.nan,
                         "vd": v96[i] / v672[i] if v672[i] > 0 else np.nan,
                         "bb": abs(c[i] - o[i]) / rb, "br": rb / a, "bx": sg * (c[i] - L) / a, "qb": abs(c[q] - o[q]) / rq,
                         "qw": ((min(o[j], c[j]) - l[j]) if sg > 0 else (h[j] - max(o[j], c[j]))) / rj, "nq": q - i,
                         "age": i - p, "tch": int((near & notbr).sum()), "ext": sg * (c[i] - c[i - 96]) / a,
                         "tr4": int(sg * (c[q] - ma[q]) > 0) if ma[q] > 0 else -1, "tr1": int(sg * slope[q] > 0) if slope[q] == slope[q] else -1,
                         "atrp": atrp[q], "btc": 100 * sg * (btc[q] / btc[q - 4] - 1) if btc[q - 4] > 0 else np.nan})
    return rows


allr = []
for s in SYMS:
    if os.path.exists(f"{CD}/{s}/15m.csv"): r = run(s); allr += r; print(s, len(r), flush=True)
W = pd.DataFrame(allr); W["y"] = pd.to_datetime(W.ts, unit="s").dt.year
W["cl"] = W.groupby(["ts", "side"]).sym.transform("count")
W["P"] = np.where(W.y <= 2023, "P1", np.where(W.y <= 2025, "P2", "P3")); W["G"] = np.where(W.sym.isin(GA), "A", "B")
W["u3"] = 10 * (W.r3 - FEE / W.sp); W["u2"] = 10 * (W.r2 - FEE / W.sp); W["win"] = (W.r3 >= 3).astype(int)
W.to_csv(OUT, index=False)
CELLS = [(g, p) for g in "AB" for p in ("P1", "P2", "P3")]
print(f"\nB&R · ОЗНАКИ: входів {len(W)}, монет {W.sym.nunique()}, група A: {sorted(GA)}")
print(f"УСІ: до цілі 3R дійшло {100*W.win.mean():.1f}%, $ на угоду {W.u3.mean():+.2f} (ціль 2R: {W.u2.mean():+.2f}); усього ${W.u3.sum():+.0f}")
print("формат рядка: корзина: A·P1 | A·P2 | A·P3 || B·P1 | B·P2 | B·P3  — $ на угоду при цілі 3R (n, % до цілі)")


def line(mask, name):
    cells = []; allpos = True
    for g, p in CELLS:
        x = W[mask & (W.G == g) & (W.P == p)]
        if len(x) < 20: cells.append(f"  —  ({len(x)})"); allpos = False; continue
        m = x.u3.mean(); allpos &= m > 0; cells.append(f"{m:+.2f} ({len(x)}, {100*x.win.mean():.0f}%)")
    x = W[mask]
    print(f" {name:<30}: " + " | ".join(cells[:3]) + "  ||  " + " | ".join(cells[3:]) + f"   разом {x.u3.mean():+.2f} / 2R {x.u2.mean():+.2f}, n={len(x)}" + ("   <<< ПЛЮС У ВСІХ 6" if allpos else ""))
    return allpos


ok = []
base = W[(W.G == "A") & (W.P == "P1")]
for f in ("vb", "vp", "vq", "vd", "bb", "br", "bx", "qb", "qw", "nq", "age", "tch", "ext", "atrp", "btc", "sp"):
    q1, q2 = base[f].quantile([1 / 3, 2 / 3]); print(f"\n== {f} (межі {q1:.3g} / {q2:.3g})")
    for nm, m in ((f"{f} низ", W[f] <= q1), (f"{f} середина", (W[f] > q1) & (W[f] <= q2)), (f"{f} верх", W[f] > q2)):
        if line(m, nm): ok.append(nm)
for f, vals in (("tr4", (1, 0)), ("tr1", (1, 0)), ("side", (1, -1))):
    print(f"\n== {f}")
    for x in vals:
        if line(W[f] == x, f"{f}={x}"): ok.append(f"{f}={x}")
print("\n== cl (скільки монет разом)")
for nm, m in (("cl=1", W.cl == 1), ("cl=2", W.cl == 2), ("cl>=3", W.cl >= 3)):
    if line(m, nm): ok.append(nm)
print("\n== години UTC")
for nm, a, b in (("00-07", 0, 7), ("07-13", 7, 13), ("13-17", 13, 17), ("17-21", 17, 21), ("21-24", 21, 24)):
    if line((W.hr >= a) & (W.hr < b), nm): ok.append(nm)
print("\n== ЗАЗДАЛЕГІДЬ ЗАПИСАНІ ПОЄДНАННЯ")
KK = {"K1 об'єм>=2, стоп>=0,5": (W.vb >= 2) & (W.sp >= 0.5), "K2 об'єм>=2, тихий відкат": (W.vb >= 2) & (W.vp <= 0.5), "K3 сильна свічка+об'єм": (W.bb >= 0.7) & (W.vb >= 1.5),
      "K4 тренд+об'єм>=2": (W.tr4 == 1) & (W.vb >= 2), "K5 ринок разом+об'єм": (W.cl >= 3) & (W.vb >= 1.5), "K6 хвіст+тихий відкат": (W.qw >= 0.5) & (W.vp <= 0.7),
      "K7 усе разом": (W.vb >= 2) & (W.vp <= 0.5) & (W.sp >= 0.5) & (W.tr4 == 1)}
for nm, m in KK.items():
    if line(m, nm): ok.append(nm)
    x = W[m]; print("      по роках, $: " + ", ".join(f"{y}: {a.u3.sum():+.0f} ({len(a)})" for y, a in x.groupby("y")))
print("\nПІДСУМОК: у плюсі в усіх 6 клітинках — " + (", ".join(ok) if ok else "НІЧОГО"))
