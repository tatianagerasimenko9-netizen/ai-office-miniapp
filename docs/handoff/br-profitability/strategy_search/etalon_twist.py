"""READ-ONLY. БОТ-ЕТАЛОН: «покрутити ідею» — чи є в його сигналах щось корисне, якщо інакше входити й виходити (28.11.2026, прохання власниці: «не відкидай одразу, подивись моменти; він шле багато третіх тейків»).
Сигнали бота беремо як є (монета, напрям, хвилина, рівні з картки). Свічки 5 хв. УСІ ВАРІАНТИ ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА). Ризик $10 = відстань від фактичного входу до стопа варіанта. Комісія 0,10%. Стоп першим. Життя угоди до 7 діб.
 1) ЧИ ВГАДУЄ НАПРЯМ: рух ціни в бік сигналу через 1 / 4 / 24 / 72 год від ціни хвилини сигналу (у % і в частках стопа з картки), окремо SHORT і LONG, по місяцях.
 2) ВХОДИ: M за ринком | P лімітом за ціною з картки (6 год) | A лімітом за ціною «добору» з картки (6 год; ближче до стопа) | C підтвердження: за ринком, коли ціна пройшла 0,5R у бік сигналу (6 год; R = відстань до стопа з картки від ціни сигналу).
 3) СТОПИ: K стоп із картки | W ширший (×1,5 відстані) | N вужчий (×0,5).
 4) ВИХОДИ: T1 / T2 / T3 — усе на відповідній цілі з картки | R1 / R2 / R3 / R5 — ціль у 1, 2, 3, 5 стопів | TR — без цілі: після +1R стоп іде за ціною на відстані 1R | H4 / H24 / H72 — вихід за часом (зі стопом) |
    B3 — як бот, але без беззбитку: 50% TP1, 25% TP2, 25% TP3 зі стопом із картки до кінця.
 5) НАВПАКИ (F): угода ПРОТИ сигналу бота за ринком: стоп на TP1 з картки, ціль на стопі з картки; і проста: стоп = ціль = відстань до стопа з картки.
 Критерій: варіант «живий», якщо плюс у сумі, у ≥ 6 із 7 місяців і в обох половинах (травень–серпень, вересень–листопад). Період короткий (7 місяців, ринок падав) — це пошук гіпотез, не доказ.
Використання: etalon_twist.py SIGNALS_CSV DIR OUT_TXT"""
import os, sys
import numpy as np, pandas as pd
SIG, DIR = sys.argv[1], sys.argv[2]
S = pd.read_csv(SIG); FEE = 0.001; LIFE = 7 * 288; rows = []; fw = []
def first(arr, px, up):
    m = (arr >= px) if up else (arr <= px); return int(np.argmax(m)) if m.any() else 10**9
def sim(h, l, c, i, e, side, sl, tp=None, hold=None, trail=False, parts=None):
    """Повертає R (без комісії). parts = [(частка, ціль), ...] зі спільним стопом."""
    risk = side * (e - sl)
    if risk <= 0: return None
    n = min(len(c), i + (hold or LIFE)); H, L = h[i:n], l[i:n]; fav, adv = (H, L) if side > 0 else (L, H)
    if len(H) == 0: return None
    isl = first(adv, sl, side < 0); R = lambda px: side * (px - e) / risk; last = c[n - 1]
    if trail:
        st = sl; peak = e
        for j in range(len(H)):
            if (L[j] <= st) if side > 0 else (H[j] >= st): return R(st)
            peak = max(peak, H[j]) if side > 0 else min(peak, L[j])
            if side * (peak - e) >= risk: st = max(st, peak - risk) if side > 0 else min(st, peak + risk)
        return R(last)
    if parts:
        tot = 0.0
        for w, px in parts:
            it = first(fav, px, side > 0); tot += w * (-1.0 if (isl <= it and isl < 10**9) else (R(px) if it < 10**9 else R(last)))
        return tot
    if tp is None: return -1.0 if isl < 10**9 else R(last)
    it = first(fav, tp, side > 0); return -1.0 if (isl <= it and isl < 10**9) else (R(tp) if it < 10**9 else R(last))
for sym, g in S.groupby("sym"):
    if not os.path.exists(f"{DIR}/{sym}.csv"): continue
    d = pd.read_csv(f"{DIR}/{sym}.csv"); t, o, h, l, c = (d[k].to_numpy(float) for k in "tohlc")
    for r in g.itertuples():
        side = 1 if r.dir == "LONG" else -1; i0 = int(np.searchsorted(t, r.ts, side="left"))
        if i0 >= len(t) - 2 or t[i0] - r.ts > 900: continue
        p0 = o[i0]; d0 = side * (p0 - r.sl)
        if d0 <= 0: continue
        base = dict(ts=r.ts, sym=sym, dir=r.dir, tf=r.tf, tier=r.tier, ses=r.ses, regime=r.regime)
        fw.append(dict(base, **{f"h{k}": (side * (c[min(len(c) - 1, i0 + k * 12 - 1)] - p0) / p0 * 100) for k in (1, 4, 24, 72)}, sp=100 * d0 / p0))
        ents = {"M": (i0, p0)}
        hit = np.flatnonzero((l[i0:i0 + 72] <= r.entry) & (h[i0:i0 + 72] >= r.entry));  ents["P"] = (i0 + int(hit[0]), r.entry) if len(hit) else None
        if r.addp == r.addp and r.addp:
            hit = np.flatnonzero((l[i0:i0 + 72] <= r.addp) & (h[i0:i0 + 72] >= r.addp)); ents["A"] = (i0 + int(hit[0]), float(r.addp)) if len(hit) and side * (float(r.addp) - r.sl) > 0 else None
        cpx = p0 + side * 0.5 * d0; k = first(h[i0:i0 + 72] if side > 0 else l[i0:i0 + 72], cpx, side > 0); ks = first(l[i0:i0 + 72] if side > 0 else h[i0:i0 + 72], r.sl, side < 0)
        ents["C"] = (i0 + k + 1, cpx) if k < 10**9 and k < ks and i0 + k + 1 < len(c) else None
        for EN, v in ents.items():
            if v is None: continue
            ie, e = v
            for SN, mult in (("K", 1.0), ("W", 1.5), ("N", 0.5)):
                dist = side * (e - r.sl) * mult
                if dist <= 0 or dist / e < 0.002: continue
                sl = e - side * dist; fee = FEE * e / dist
                for XN, kw in (("T1", dict(tp=r.tp1)), ("T2", dict(tp=r.tp2)), ("T3", dict(tp=r.tp3)), ("R1", dict(tp=e + side * dist)), ("R2", dict(tp=e + side * 2 * dist)), ("R3", dict(tp=e + side * 3 * dist)), ("R5", dict(tp=e + side * 5 * dist)),
                               ("TR", dict(trail=True)), ("H4", dict(hold=48)), ("H24", dict(hold=288)), ("H72", dict(hold=864)), ("B3", dict(parts=[(0.5, r.tp1), (0.25, r.tp2), (0.25, r.tp3)]))):
                    if "tp" in kw and side * (kw["tp"] - e) <= 0: continue
                    if "parts" in kw and side * (r.tp1 - e) <= 0: continue
                    v_ = sim(h, l, c, ie, e, side, sl, **kw)
                    if v_ is not None: rows.append(dict(base, var=f"{EN}-{SN}-{XN}", r=v_ - fee))
        # навпаки
        if side * (r.tp1 - p0) > 0:
            dist = side * (r.tp1 - p0); v_ = sim(h, l, c, i0, p0, -side, r.tp1, tp=r.sl); rows.append(dict(base, var="F-навпаки: стоп TP1, ціль SL", r=v_ - FEE * p0 / dist))
        v_ = sim(h, l, c, i0, p0, -side, p0 + side * d0, tp=r.sl); rows.append(dict(base, var="F-навпаки: стоп = ціль", r=v_ - FEE * p0 / d0))
T = pd.DataFrame(rows); T["usd"] = 10 * T.r; T["mo"] = pd.to_datetime(T.ts, unit="s").dt.strftime("%m"); T["half"] = np.where(T.mo <= "08", "A", "B"); F = pd.DataFrame(fw); F["mo"] = pd.to_datetime(F.ts, unit="s").dt.strftime("%m")
print(f"сигналів зі свічками: {len(F)}")
print("\n######## 1. ЧИ ВГАДУЄ НАПРЯМ: середній рух у бік сигналу, % (медіана) [частка «у плюсі»]")
for dn, x in (("УСІ", F), ("SHORT", F[F.dir == "SHORT"]), ("LONG", F[F.dir == "LONG"])):
    print(f" {dn:6s} n={len(x):3d}: " + " | ".join(f"{k} год: {x[f'h{k}'].mean():+.2f}% ({x[f'h{k}'].median():+.2f}%) [{100*(x[f'h{k}']>0).mean():.0f}%]" for k in (1, 4, 24, 72)))
for dn in ("SHORT", "LONG"):
    x = F[F.dir == dn]; print(f" {dn} рух за 24 год по місяцях: " + ", ".join(f"{k}: {v:+.2f}%" for k, v in x.groupby("mo").h24.mean().items()))
def summ(x):
    pm = x.groupby("mo").usd.sum(); hv = x.groupby("half").usd.sum(); return len(x), x.usd.sum(), x.usd.mean(), 100 * (x.usd > 0).mean(), int((pm > 0).sum()), len(pm), hv.get("A", 0.0), hv.get("B", 0.0)
print("\n######## 2. УСІ ВАРІАНТИ (відсортовано за сумою). Позначка <<< — плюс, ≥6 місяців із 7 у плюсі, обидві половини в плюсі")
for dn, sub in (("УСІ СИГНАЛИ", T), ("ЛИШЕ SHORT", T[T.dir == "SHORT"]), ("ЛИШЕ LONG", T[T.dir == "LONG"])):
    out = []
    for v, x in sub.groupby("var"):
        n, tot, per, win, pmn, pmt, ha, hb = summ(x); out.append((tot, v, n, per, win, pmn, pmt, ha, hb))
    out.sort(reverse=True); live = [o_ for o_ in out if o_[0] > 0 and o_[5] >= 6 and o_[7] > 0 and o_[8] > 0]
    print(f"\n==== {dn}: варіантів {len(out)}; у плюсі {sum(1 for o_ in out if o_[0] > 0)}; «живих» {len(live)}")
    for tot, v, n, per, win, pmn, pmt, ha, hb in out[:14] + out[-3:]:
        print(f"   {v:32s} n={n:4d} сума ${tot:+7.0f} на угоду ${per:+6.2f} виграшних {win:3.0f}% місяців у плюсі {pmn}/{pmt} | трав–серп {ha:+6.0f} | вер–лист {hb:+6.0f}" + ("   <<<" if (tot > 0 and pmn >= 6 and ha > 0 and hb > 0) else ""))
print("\n######## 3. По блоках (усі сигнали): середнє по варіантах, $ на угоду")
T["E"] = T["var"].str.split("-").str[0]; T["Sx"] = T["var"].str.split("-").str[1]; T["X"] = T["var"].str.split("-").str[2]; Z = T[T.E != "F"]
print(" вхід :", Z.groupby("E").usd.mean().round(2).to_dict(), "| n:", Z[Z["var"].str.endswith("K-T1")].groupby("E").size().to_dict())
print(" стоп :", Z.groupby("Sx").usd.mean().round(2).to_dict()); print(" вихід:", Z.groupby("X").usd.mean().round(2).to_dict())
print(" SHORT вихід:", Z[Z.dir == "SHORT"].groupby("X").usd.mean().round(2).to_dict()); print(" LONG вихід:", Z[Z.dir == "LONG"].groupby("X").usd.mean().round(2).to_dict())
