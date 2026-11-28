"""READ-ONLY. «РАНКОВИЙ ХИБНИЙ ПРОБІЙ» (Judas Swing) — ідея бота-еталона, перевірена чисто на довгій історії (28.11.2026, згода власниці «так, запускай»).
Ідея — ЗОВНІШНЄ (ICT, як у bot.py: Азія 00:00–06:00 UTC, Лондон 07:00–10:00 UTC). Числа й варіанти — наші (ГІПОТЕЗА), ЗАПИСАНІ ДО ЗАПУСКУ, нічого не підбирається:
 АЗІЯ   : максимум і мінімум 00:00–06:00 UTC.
 ПРОБІЙ : у вікні 07:00–10:00 UTC максимум вище максимуму Азії на 0,1%+ → очікуємо ВНИЗ (SHORT); мінімум нижче мінімуму Азії на 0,1%+ → очікуємо ВГОРУ (LONG). Пробито обидва боки → дня немає.
 ВХІД   : за ринком на відкритті 15-хв свічки у час T: 10:00 | 12:00 | 13:30 UTC (кінець Лондонського вікна / середина дня / відкриття Нью-Йорка). Чесна ціна тієї хвилини, без «рівня з картки».
 УМОВА R: «ціна повернулась» — у час T ціна вже знову всередині діапазону Азії (так / будь-де).
 СТОП   : S1 за крайньою точкою Лондонського пробою (+0,1 ATR H1) | S2 1,5 ATR(14) H1 від входу. Пропуск, якщо стоп ближче 0,3% або далі 8%.
 ЦІЛЬ   : 1R | 2R | протилежний край Азії (якщо він далі за 0,5R). Вихід за часом о 24:00 UTC того ж дня. У спірній свічці — стоп першим. Ризик $10, комісія 0,10%.
 КОНТРОЛЬ: та сама угода В БІК пробою («продовження») — щоб бачити, чи «розворот» узагалі кращий за протилежне.
 Групи: пошук 42 монети / контроль 30 інших; періоди P1 2020–21, P2 2022–23, P3 2024–26. Зараховано лише плюс у всіх 6 клітинках (n ≥ 100). Додатково: при BTC вище / нижче 200-денної середньої.
Використання: judas_lab.py CANDLES_DIR S42 OUT"""
import os, sys
import numpy as np, pandas as pd
D, S42, OUT = sys.argv[1], set(sys.argv[2].split(",")), sys.argv[3]
bd = pd.read_csv(f"{D}/BTCUSDT/15m.csv"); bd = bd.groupby(bd.open_time // 86400 * 86400).close.last(); BT = bd.index.to_numpy(float) + 86400; BU = (bd > bd.rolling(200).mean()).to_numpy(); BO = bd.rolling(200).mean().notna().to_numpy()
def big(te):
    i = np.searchsorted(BT, te, side="right") - 1; return (1 if BU[i] else 0) if i >= 0 and BO[i] else -1
rows = []
for s in sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv")):
    if s in ("XAUUSDT", "XAGUSDT"): continue
    d = pd.read_csv(f"{D}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time"); t, o, h, l, c = (d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close"))
    if len(t) < 5000: continue
    g = d.groupby(d.open_time // 3600 * 3600).agg(high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); pc = g.close.shift(1)
    a1 = pd.concat([g.high - g.low, (g.high - pc).abs(), (g.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean().shift(1); A1t = g.open_time.to_numpy(float); A1 = a1.to_numpy()
    day = (t // 86400).astype(np.int64); starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]]); ends = np.r_[starts[1:], len(t)]
    for a, b in zip(starts, ends):
        if b - a < 90: continue                                                             # неповний день
        d0 = day[a] * 86400.0; sod = t[a:b] - d0
        asia = sod < 6 * 3600; lon = (sod >= 7 * 3600) & (sod < 10 * 3600)
        if asia.sum() < 20 or lon.sum() < 10: continue
        ah, al = h[a:b][asia].max(), l[a:b][asia].min(); lh, ll = h[a:b][lon].max(), l[a:b][lon].min()
        up, dn = lh > ah * 1.001, ll < al * 0.999
        if up == dn: continue
        bias = -1 if up else 1; ext = lh if up else ll
        for T in (36000, 43200, 48600):
            k = np.flatnonzero(sod == T)
            if not len(k): continue
            i = a + int(k[0]); e = o[i]; ia = np.searchsorted(A1t, t[i], side="right") - 1; atr = A1[ia] if ia >= 0 else np.nan
            if not atr > 0: continue
            inside = int(al <= e <= ah); H_, L_ = h[i:b], l[i:b]; last = c[b - 1]; U = big(t[i])
            for mode, side in (("REV", bias), ("CONT", -bias)):
                for SN, sl in (("S1", (ext - side * 0.1 * atr) if mode == "REV" else ((ll if side > 0 else lh) - side * 0.1 * atr)), ("S2", e - side * 1.5 * atr)):
                    risk = side * (e - sl)
                    if risk <= 0 or not 0.003 <= risk / e <= 0.08: continue
                    hs = (L_ <= sl) if side > 0 else (H_ >= sl); isx = int(np.argmax(hs)) if hs.any() else 10**9; fee = 0.001 * e / risk
                    far = (ah if side > 0 else al) if mode == "REV" else None
                    for TN, tp in (("1R", e + side * risk), ("2R", e + side * 2 * risk), ("AS", far)):
                        if tp is None or side * (tp - e) < 0.5 * risk: continue
                        ht = (H_ >= tp) if side > 0 else (L_ <= tp); itx = int(np.argmax(ht)) if ht.any() else 10**9
                        r = -1.0 if (isx <= itx and isx < 10**9) else (side * (tp - e) / risk if itx < 10**9 else side * (last - e) / risk)
                        rows.append((s, t[i], mode, side, T // 3600 + (0.5 if T % 3600 else 0), SN, TN, inside, U, round(100 * risk / e, 3), round(r - fee, 4)))
    print(s, flush=True)
E = pd.DataFrame(rows, columns=["sym", "te", "mode", "side", "T", "S", "TG", "inside", "U", "sp", "r"]); y = pd.to_datetime(E.te, unit="s").dt.year
E["P"] = np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3")); E["grp"] = np.where(E.sym.isin(S42), "S", "C"); E["usd"] = 10 * E.r; E["y"] = y
E[(E["mode"] == "REV")].to_csv(OUT, index=False)
print(f"\n«РАНКОВИЙ ХИБНИЙ ПРОБІЙ»: записів {len(E):,}; монет {E.sym.nunique()}.   $ на угоду (у дужках n).   ПОШУК 42: P1 | P2 | P3   ||   КОНТРОЛЬ 30: P1 | P2 | P3")
def cells(x): return [(len(z), z.usd.mean() if len(z) else np.nan) for g_ in "SC" for p in ("P1", "P2", "P3") for z in [x[(x.grp == g_) & (x.P == p)]]]
def line(lab, x):
    cs = cells(x); ok = all(n >= 100 and v > 0 for n, v in cs)
    print(f" {lab:58s} " + " | ".join(f"{v:+5.2f} ({n})" for n, v in cs[:3]) + "  ||  " + " | ".join(f"{v:+5.2f} ({n})" for n, v in cs[3:]) + ("   <<< ПЛЮС У ВСІХ 6" if ok else "")); return ok
tot = okn = 0
for mode, mn in (("REV", "РОЗВОРОТ (ідея бота)"), ("CONT", "КОНТРОЛЬ: продовження в бік пробою")):
    for side, sn in ((-1, "SHORT"), (1, "LONG")):
        print(f"\n######## {mn} · {sn}")
        for T in (10.0, 12.0, 13.5):
            for ins, inn in ((None, "будь-де"), (1, "ціна повернулась в Азію")):
                for SN in ("S1", "S2"):
                    for TG in (("1R", "2R", "AS") if mode == "REV" else ("1R", "2R")):
                        x = E[(E["mode"] == mode) & (E.side == side) & (E["T"] == T) & (E.S == SN) & (E.TG == TG)]
                        if ins is not None: x = x[x.inside == 1]
                        tot += 1; okn += line(f"вхід {T:g}:00 UTC · {inn} · стоп {SN} · ціль {TG}", x)
print(f"\nПІДСУМОК: варіантів {tot}; плюс у всіх 6 клітинках: {okn}")
print("\n######## За великим трендом BTC (розворот, стоп S1, ціль 2R, вхід 12:00, будь-де): $ на угоду (n)")
for side, sn in ((-1, "SHORT"), (1, "LONG")):
    x = E[(E["mode"] == "REV") & (E.side == side) & (E["T"] == 12.0) & (E.S == "S1") & (E.TG == "2R")]
    print(f" {sn}: BTC вище 200-денної {x[x.U==1].usd.mean():+.2f} ({(x.U==1).sum()}); нижче {x[x.U==0].usd.mean():+.2f} ({(x.U==0).sum()}); по роках: " + ", ".join(f"{int(k)}: {v.usd.sum():+.0f} ({len(v)})" for k, v in x.groupby("y")))
