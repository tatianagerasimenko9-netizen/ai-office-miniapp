"""READ-ONLY. «ВІДСКОК ПІСЛЯ ЗЛИВУ»: скальп/інтрадей у бік розвороту (27.11.2026, прохання власниці після 25–27.11: BTC 57 258 → 62 199, «ризик був мінімальний, це можна було побачити; знаходь можливості»).
ПРАВИЛА ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА; ідеї «капітуляція», «хибний пробій рівня», «ринок розвертається разом» — від власниці/ЗОВНІШНЄ; числа наші, не підбирались). Годинні свічки (з M15), 72 монети, 2020–2026.
 ЗЛИВ      : бар, чий мінімум — найнижчий за 72 бари (3 доби), а падіння від максимуму останніх 24 барів до цього мінімуму ≥ 3 ATR(14).
 ПОВЕРНЕННЯ: протягом наступних 6 барів якийсь бар ЗАКРИВСЯ вище максимуму бару зливу → LONG на цьому закритті (мінімум зливу за цей час не оновлено).
 СТОП      : за мінімум зливу − 0,1 ATR («мінімальний стоп за дном»). Цілі 1R / 2R / 3R, утримання 48 барів (2 доби). Стоп-першим. Ризик $10. Комісія 0,10% і 0,04%.
 Умови, що додаються ПО ОДНІЙ і разом (усі комбінації показано):
   B «весь ринок»   : за останні 6 год свій 72-годинний мінімум зробили ≥ 50% монет, що торгувались (розвертаються всі разом).
   L «сильний рівень»: мінімум зливу проколов попередній ДЕННИЙ свінг-мінімум (3 доби з обох боків, за останні 90 діб), а вхід — уже вище цього рівня (хибний пробій денного рівня).
   T «біткоїн підтвердив»: BTC за останні 6 год теж дав ПОВЕРНЕННЯ після свого ЗЛИВУ (для самого BTC умова завжди виконана, якщо є сигнал).
   D «дивергенція»  : RSI(14) у мінімумі зливу вищий, ніж у попередньому 72-годинному мінімумі (не далі 60 барів).
 Дзеркально SHORT після «вильоту вгору» (максимум за 72 бари, ріст ≥ 3 ATR, закриття нижче мінімуму того бару).
 Групи часу (ринок розвертається разом, тому ділимо за роками, а не за монетами): P1 = 2020–2021, P2 = 2022–2023, P3 = 2024–2026. Правило підтверджене, лише якщо плюс у всіх трьох.
Використання: bounce_lab.py CANDLES_DIR OUT"""
import os, sys, itertools
import numpy as np, pandas as pd
D, OUT = sys.argv[1], sys.argv[2]
LB = 72; WAIT = 6; HOLD = 48
def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
DATA = {}
for s in sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv")):
    if s in ("XAUUSDT", "XAGUSDT"): continue
    d = pd.read_csv(f"{D}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(n=("open", "size"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g = g[g.n == 4].reset_index(drop=True)
    if len(g) < 2000: continue
    t, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "high", "low", "close")); pc = np.r_[c[0], c[:-1]]
    A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); R = rsi(c)
    dd = d.groupby(d.open_time // 86400 * 86400).agg(high=("high", "max"), low=("low", "min")).reset_index(); dt = dd.open_time.to_numpy(float); dl = dd.low.to_numpy(float); dh = dd.high.to_numpy(float)
    pl = [(dt[i] + 4 * 86400, dl[i]) for i in range(3, len(dl) - 3) if dl[i] == dl[i - 3:i + 4].min()]          # денний свінг-мінімум стає видимим через 3 доби після нього (+1 доба на закриття)
    ph = [(dt[i] + 4 * 86400, dh[i]) for i in range(3, len(dh) - 3) if dh[i] == dh[i - 3:i + 4].max()]
    DATA[s] = dict(t=t, h=h, l=l, c=c, A=A, R=R, pl=pl, ph=ph); print(s, len(c), flush=True)
# 1) події «злив» і «повернення» по кожній монеті
EV = []
for s, a in DATA.items():
    t, h, l, c, A, R = a["t"], a["h"], a["l"], a["c"], a["A"], a["R"]; n = len(c)
    lo72 = pd.Series(l).rolling(LB).min().to_numpy(); hi72 = pd.Series(h).rolling(LB).max().to_numpy(); hi24 = pd.Series(h).rolling(24).max().to_numpy(); lo24 = pd.Series(l).rolling(24).min().to_numpy()
    for side in (1, -1):
        x = l if side > 0 else h
        fl = np.flatnonzero(((l == lo72) & (hi24 - l >= 3 * A)) if side > 0 else ((h == hi72) & (h - lo24 >= 3 * A))); fl = fl[(fl >= LB + 20) & (fl + WAIT + HOLD + 1 < n)]
        a["flush_t" if side > 0 else "blow_t"] = t[fl]; last_entry = -1; prev_f = None
        for f in fl:
            if f <= last_entry: prev_f = f; continue
            ent = None
            for j in range(f + 1, f + 1 + WAIT):
                if (l[j] < l[f]) if side > 0 else (h[j] > h[f]): break                    # дно оновлено — це вже інший злив
                if (c[j] > h[f]) if side > 0 else (c[j] < l[f]): ent = j; break
            if ent is None: prev_f = f; continue
            e = c[ent]; sl = x[f] - side * 0.1 * A[ent]; risk = side * (e - sl)
            if not A[ent] > 0 or not 0.0005 <= risk / e <= 0.25: prev_f = f; continue
            H_ = h[ent + 1:ent + 1 + HOLD]; L_ = l[ent + 1:ent + 1 + HOLD]; last = c[ent + HOLD]
            hs = (L_ <= sl) if side > 0 else (H_ >= sl); isx = int(np.argmax(hs)) if hs.any() else HOLD + 1; out = []
            for tg in (1, 2, 3):
                tp = e + side * tg * risk; ht = (H_ >= tp) if side > 0 else (L_ <= tp); itx = int(np.argmax(ht)) if ht.any() else HOLD + 1
                out.append(-1.0 if (isx <= itx and isx <= HOLD) else (float(tg) if itx <= HOLD else side * (last - e) / risk))
            te = t[ent] + 3600; lv = [p for (tv, p) in (a["pl"] if side > 0 else a["ph"]) if te - 90 * 86400 <= tv <= t[f]]
            Lc = int(any((x[f] < p < e) if side > 0 else (e < p < x[f]) for p in lv))
            Dv = int(prev_f is not None and f - prev_f <= 60 and R[f] > 0 and R[prev_f] > 0 and side * (R[f] - R[prev_f]) > 0 and side * (x[prev_f] - x[f]) > 0)
            EV.append([s, side, t[f], te, 100 * risk / e, out[0], out[1], out[2], Lc, Dv]); last_entry = ent; prev_f = f
E = pd.DataFrame(EV, columns=["sym", "side", "tf", "te", "sp", "r1", "r2", "r3", "L", "D"])
# 2) ширина ринку і підтвердження BTC на момент входу
alive = {s: (a["t"][0], a["t"][-1]) for s, a in DATA.items()}
def breadth(side, te):
    k = "flush_t" if side > 0 else "blow_t"; tot = hit = 0
    for s, a in DATA.items():
        if not alive[s][0] <= te - 72 * 3600 or alive[s][1] < te: continue
        tot += 1; ft = a[k]; i = np.searchsorted(ft, te - 3600, side="right") - 1
        hit += int(i >= 0 and ft[i] >= te - 6 * 3600 - 3600)
    return hit / tot if tot >= 10 else 0.0
bcache = {}
E["B"] = [int(bcache.setdefault((sd, te), breadth(sd, te)) >= 0.5) for sd, te in zip(E.side, E.te)]
btc = E[E.sym == "BTCUSDT"]; bt = {1: np.sort(btc[btc.side > 0].te.to_numpy()), -1: np.sort(btc[btc.side < 0].te.to_numpy())}
def btc_ok(sd, te):
    x = bt[sd]; i = np.searchsorted(x, te, side="right") - 1; return int(i >= 0 and te - x[i] <= 6 * 3600)
E["T"] = [btc_ok(sd, te) for sd, te in zip(E.side, E.te)]
y = pd.to_datetime(E.te, unit="s").dt.year; E["P"] = np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3")); E["y"] = y; E.to_csv(OUT, index=False)
print(f"\n«ВІДСКОК ПІСЛЯ ЗЛИВУ»: {len(E):,} входів ({int((E.side>0).sum())} LONG, {int((E.side<0).sum())} SHORT), монет {E.sym.nunique()}; медіанний стоп {E.sp.median():.2f}%; ризик $10")
print("формат: $ на угоду при комісії 0,10% (у дужках 0,04%), n, частка виграшних; періоди P1 2020–21 | P2 2022–23 | P3 2024–26")
def val(x, tg, fee): return 10 * (x[f"r{tg}"] - fee / x.sp).mean()
def row(lab, m, tg, mark=True):
    parts = []; ok = ok4 = True
    for p in ("P1", "P2", "P3"):
        x = E[m & (E.P == p)]
        if len(x) < 60: parts.append(f"{p}: n={len(x)}"); ok = ok4 = False; continue
        a_, b_ = val(x, tg, 0.10), val(x, tg, 0.04); ok &= a_ > 0; ok4 &= b_ > 0; parts.append(f"{p}: {a_:+.2f} ({b_:+.2f}), n={len(x)}, виграшних {100*(x[f'r{tg}']>0).mean():.0f}%, стоп {x.sp.median():.1f}%")
    print(f"   {lab:22s} ціль {tg}R: " + " | ".join(parts) + (("   <<< ПЛЮС У ТРЬОХ ПЕРІОДАХ" if ok else ("   << плюс у трьох лише з лімітною комісією" if ok4 else "")) if mark else ""))
    return ok, ok4
tot = pos = pos4 = 0
for side, sn in ((1, "LONG після зливу"), (-1, "SHORT після вильоту вгору")):
    print(f"\n######## {sn}")
    base = E.side == side
    for r in range(0, 5):
        for combo in itertools.combinations(("B", "L", "T", "D"), r):
            m = base.copy()
            for cnd in combo: m &= E[cnd] == 1
            for tg in (1, 2, 3):
                a_, b_ = row("+".join(combo) if combo else "без умов", m, tg); tot += 1; pos += a_; pos4 += b_
print(f"\nПІДСУМОК: комбінацій {tot}; плюсові в усіх трьох періодах при 0,10%: {pos}; при 0,04%: {pos4}.")
print("\nпо роках для «весь ринок» (B), LONG, ціль 2R, комісія 0,10%: " + ", ".join(f"{yy}: {10*(g.r2-0.10/g.sp).sum():+.0f} (n={len(g)})" for yy, g in E[(E.side > 0) & (E.B == 1)].groupby("y")))
print("останні входи LONG з умовою B (для звірки з 25.11.2026):"); print(E[(E.side > 0) & (E.B == 1)].tail(8).assign(час=lambda z: pd.to_datetime(z.te, unit="s"))[["sym", "час", "sp", "r1", "r2", "r3", "L", "T", "D"]].round(2).to_string(index=False))
