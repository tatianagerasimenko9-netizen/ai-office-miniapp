"""READ-ONLY. «ШОРТ ПІСЛЯ ВИЛЬОТУ ВГОРУ» — дзеркало «Відскоку», гіпотеза з розбору бота-еталона (журнал BR), перевірка на довгій історії (28.11.2026, згода власниці «так, перевір»).
Ідея «продавати перегрів» — ЗОВНІШНЄ; числа — наші (ГІПОТЕЗА), дзеркало bounce_lab.py. ПРАВИЛА І ВАРІАНТИ ЗАПИСАНО ДО ЗАПУСКУ:
 ВИЛІТ : годинний бар, чий максимум — найвищий за 72 бари, а ріст від мінімуму останніх 24 барів ≥ 3 ATR(14).
 ВХІД  : IM — одразу, на відкритті наступної години після бару вильоту | RT — після «повернення»: протягом 6 барів бар закрився нижче мінімуму бару вильоту (максимум не оновлено), вхід на закритті.
 СТОП  : S1 — за максимумом вильоту + 0,25 ATR | S2 — 2 ATR від входу. Пропуск, якщо стоп ближче 0,3% або далі 25%.
 ЦІЛЬ  : 1R | 2R | 3R; утримання 48 год; стоп першим; ризик $10; комісія 0,10%. Один вхід на один виліт; новий виліт по монеті — не раніше закриття попереднього входу.
 УМОВИ (окремо і разом): V — обсяг бару вильоту ≥ 2× середнього за 24 год;  NY — вхід у години Нью-Йорка (12:00–16:00 UTC);  LON — 07:00–12:00 UTC;
   M — монета за 24 год до входу виросла на 1,5–5% | M+ — більш ніж на 5%;  U — вчорашнє денне закриття BTC нижче середньої за 200 діб (великий тренд униз).
 Групи монет: 42 монети Офісу | 30 інших великих | решта (монети бота-еталона: дрібні, нові, акції). Періоди P1 2020–21, P2 2022–23, P3 2024–26; і по роках.
 Зараховано: плюс у КОЖНІЙ із трьох груп і в КОЖНОМУ з трьох періодів (для «решти» — у тих періодах, де ≥ 100 угод), і не лише за рахунок років, коли ринок падав.
Використання: pump_lab.py CANDLES_DIR S42 OTH OUT"""
import os, sys
import numpy as np, pandas as pd
D, S42, OTH, OUT = sys.argv[1], set(sys.argv[2].split(",")), set(sys.argv[3].split(",")), sys.argv[4]
LB = 72; WAIT = 6; HOLD = 48
bd = pd.read_csv(f"{D}/BTCUSDT/15m.csv"); bd = bd.groupby(bd.open_time // 86400 * 86400).close.last(); BT = bd.index.to_numpy(float) + 86400; BU = (bd > bd.rolling(200).mean()).to_numpy(); BO = bd.rolling(200).mean().notna().to_numpy()
def big(te):
    i = np.searchsorted(BT, te, side="right") - 1; return (1 if BU[i] else 0) if i >= 0 and BO[i] else -1
rows = []
for s in sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv")):
    d = pd.read_csv(f"{D}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    if "volume" not in d: d["volume"] = 0.0
    g = d.groupby(d.open_time // 3600 * 3600).agg(n=("open", "size"), open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum")).reset_index(); g = g[g.n == 4].reset_index(drop=True)
    if len(g) < 400: continue
    t, o, h, l, c, v = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close", "volume")); n = len(c); pc = np.r_[c[0], c[:-1]]
    A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); hi72 = pd.Series(h).rolling(LB).max().to_numpy(); lo24 = pd.Series(l).rolling(24).min().to_numpy(); v24 = pd.Series(v).rolling(24).mean().shift(1).to_numpy()
    fl = np.flatnonzero((h == hi72) & (h - lo24 >= 3 * A)); fl = fl[(fl >= LB + 20) & (fl + WAIT + HOLD + 2 < n)]; grp = "S" if s in S42 else ("C" if s in OTH else "W"); busy = {"IM": -1, "RT": -1}
    for f in fl:
        V = int(v24[f] > 0 and v[f] >= 2 * v24[f]); ents = {}
        if f > busy["IM"]: ents["IM"] = (f + 1, o[f + 1])
        if f > busy["RT"]:
            for j in range(f + 1, f + 1 + WAIT):
                if h[j] > h[f]: break
                if c[j] < l[f]: ents["RT"] = (j + 1, c[j]); break
        for EN, (ie, e) in ents.items():
            if ie + HOLD >= n or ie < 25: continue
            busy[EN] = ie; hr = int(t[ie] % 86400 // 3600); m24 = (e / c[ie - 25] - 1) * 100; H_, L_ = h[ie:ie + HOLD], l[ie:ie + HOLD]; last = c[ie + HOLD - 1]
            for SN, sl in (("S1", h[f] + 0.25 * A[f]), ("S2", e + 2 * A[ie - 1])):
                risk = sl - e
                if not A[ie - 1] > 0 or risk <= 0 or not 0.003 <= risk / e <= 0.25: continue
                hs = H_ >= sl; isx = int(np.argmax(hs)) if hs.any() else 10**9; fee = 0.001 * e / risk; rr = []
                for tg in (1, 2, 3):
                    ht = L_ <= e - tg * risk; itx = int(np.argmax(ht)) if ht.any() else 10**9
                    rr.append((-1.0 if (isx <= itx and isx < 10**9) else (float(tg) if itx < 10**9 else (e - last) / risk)) - fee)
                rows.append((s, grp, t[ie], EN, SN, V, hr, round(m24, 2), big(t[ie]), round(100 * risk / e, 2), rr[0], rr[1], rr[2]))
    print(s, len(c), flush=True)
E = pd.DataFrame(rows, columns=["sym", "grp", "te", "E", "S", "V", "hr", "m24", "U", "sp", "r1", "r2", "r3"]); y = pd.to_datetime(E.te, unit="s").dt.year; E["y"] = y; E["P"] = np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3"))
E["NY"] = ((E.hr >= 12) & (E.hr < 16)).astype(int); E["LON"] = ((E.hr >= 7) & (E.hr < 12)).astype(int); E["M"] = ((E.m24 >= 1.5) & (E.m24 <= 5)).astype(int); E["Mp"] = (E.m24 > 5).astype(int); E["DN"] = (E.U == 0).astype(int); E.to_csv(OUT, index=False)
print(f"\n«ШОРТ ПІСЛЯ ВИЛЬОТУ»: записів {len(E):,}; монет {E.sym.nunique()} (Офіс {E[E.grp=='S'].sym.nunique()}, великі {E[E.grp=='C'].sym.nunique()}, решта {E[E.grp=='W'].sym.nunique()}); медіанний стоп {E.sp.median():.1f}%")
print("формат: $ на угоду (n).   ОФІС 42: P1 | P2 | P3   ||   ВЕЛИКІ 30: P1 | P2 | P3   ||   РЕШТА: P1 | P2 | P3")
CONDS = [("без умов", lambda x: x.sp > 0), ("V обсяг 2×+", lambda x: x.V == 1), ("NY", lambda x: x.NY == 1), ("LON", lambda x: x.LON == 1), ("V + NY", lambda x: (x.V == 1) & (x.NY == 1)), ("M росла 1,5–5%", lambda x: x.M == 1), ("M+ росла >5%", lambda x: x.Mp == 1),
         ("M + NY", lambda x: (x.M == 1) & (x.NY == 1)), ("V + M", lambda x: (x.V == 1) & (x.M == 1)), ("U великий тренд униз", lambda x: x.DN == 1), ("великий тренд УГОРУ", lambda x: x.U == 1), ("V + NY + тренд угору", lambda x: (x.V == 1) & (x.NY == 1) & (x.U == 1)), ("V + NY + тренд униз", lambda x: (x.V == 1) & (x.NY == 1) & (x.DN == 1))]
tot = okn = 0; BEST = []
for EN, en in (("IM", "вхід ОДРАЗУ"), ("RT", "вхід ПІСЛЯ ПОВЕРНЕННЯ")):
    for SN in ("S1", "S2"):
        print(f"\n######## {en} · стоп {SN}")
        for lab, fn in CONDS:
            for tg in (1, 2, 3):
                x = E[(E.E == EN) & (E.S == SN)]; x = x[fn(x)]; col = f"r{tg}"; cs = [(len(z), 10 * z[col].mean() if len(z) else np.nan) for g_ in "SCW" for p in ("P1", "P2", "P3") for z in [x[(x.grp == g_) & (x.P == p)]]]
                ok = all(v > 0 for n_, v in cs if n_ >= 100) and sum(1 for n_, _ in cs if n_ >= 100) >= 6 and all(any(n_ >= 100 for n_, _ in cs[i:i + 3]) for i in (0, 3, 6)); tot += 1; okn += ok
                print(f" {lab:22s} ціль {tg}R: " + "  ||  ".join(" | ".join(f"{v:+5.2f} ({n_})" if n_ else "   —  " for n_, v in cs[i:i + 3]) for i in (0, 3, 6)) + ("   <<< ПЛЮС УСЮДИ" if ok else ""))
                if len(x) >= 300: BEST.append((10 * x[col].mean(), f"{en} · {SN} · {lab} · ціль {tg}R", len(x), x, col))
print(f"\nПІДСУМОК: варіантів {tot}; плюс у всіх клітинках із ≥100 угод: {okn}")
print("\n######## По роках для 8 найкращих за середнім (n ≥ 300): сума $ (кількість)")
for per, lab, n_, x, col in sorted(BEST, key=lambda z: -z[0])[:8]:
    dd = x.assign(day=(x.te // 86400).astype(int)).groupby("day")[col].sum() * 10
    print(f" {lab}: {per:+.2f}$ на угоду, n={n_}, виграшних {100*(x[col]>0).mean():.0f}%; без 5 найкращих днів {10*x[~(x.te//86400).astype(int).isin(dd.nlargest(5).index)][col].mean():+.2f}$\n     " + ", ".join(f"{int(k)}: {10*z[col].sum():+.0f} ({len(z)})" for k, z in x.groupby("y")))
