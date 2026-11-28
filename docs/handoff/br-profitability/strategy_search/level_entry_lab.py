"""READ-ONLY. «ВХІД ВІД РІВНЯ З КОРОТКИМ СТОПОМ» — перевірка на історії (28.11.2026, прохання власниці: «йому вдається заходити з мінімальними стопами; мені треба так само; дуже чіткі входи»).
ДЖЕРЕЛА: спосіб читати рівень — матеріали власниці (docs/strategies/GERCHIK_LEVELS_UA.md). Точні правила автора для входу, стопа й цілі власниця НЕ надавала → `НЕ ПІДТВЕРДЖЕНО`.
Нижче — НАША формалізація (ГІПОТЕЗА; «стоп за рівень», «ціль 3 до 1» — ЗОВНІШНЄ, загальновідома практика торгівлі від рівнів), ЗАПИСАНА ДО ЗАПУСКУ, нічого не підбирається:
 РІВНІ : денні, ті самі, що в апці (office_levels.find_levels), перераховані на кожен день лише за минулим (800 діб); беремо СИЛЬНІ зони: спирались ≥10 днів або річний екстремум.
 ВХОДИ на годинних свічках протягом дня (для підтримки → LONG; для опору — дзеркально SHORT):
   F «хибний пробій» : за останні 3 години мінімум був НИЖЧЕ низу зони, і година закрилась ВИЩЕ низу зони → вхід на закритті; стоп за мінімум проколу − 0,05 ATR(1 год).
   B «відбій»        : година торкнулась зони (мінімум ≤ верх зони), низ зони не пробито, закриття ≥ верху зони → вхід на закритті; стоп за низ зони − 0,1 ATR.
   K «пробій»        : година закрилась НИЖЧЕ низу зони (попередня — ні) → SHORT на закритті; стоп за верх зони + 0,1 ATR. (Для опору: закриття вище верху → LONG.)
 ЦІЛЬ  : 2R | 3R | наступний рівень у бік угоди (якщо він далі 1R). Утримання до 72 год. Стоп першим. Ризик $10. Комісія 0,10% від суми позиції (при короткому стопі вона велика — показуємо чесно).
 Один вхід на зону на день для кожного типу. Пропуск, якщо стоп ближче 0,15% або далі 5%.
 Розрізи: розмір стопа (<0,5% | 0,5–1% | 1–2% | >2%); за трендом / проти (ціна до середньої за 200 діб); групи монет 42 / 30; періоди P1 2020–21, P2 2022–23, P3 2024–26.
 Зараховано: плюс у всіх 6 клітинках (n ≥ 100).
Використання: level_entry_lab.py CANDLES_DIR S42 OUT"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
import numpy as np, pandas as pd
import office_levels as ol
D, S42, OUT = sys.argv[1], set(sys.argv[2].split(",")), sys.argv[3]
HOLD = 72; rows = []
for s in sorted(x for x in os.listdir(D) if os.path.exists(f"{D}/{x}/15m.csv")):
    if s in ("XAUUSDT", "XAGUSDT"): continue
    d = pd.read_csv(f"{D}/{s}/15m.csv", usecols=["open_time", "open", "high", "low", "close"]).drop_duplicates("open_time").sort_values("open_time")
    gd = d.groupby(d.open_time // 86400 * 86400).agg(n=("close", "size"), h=("high", "max"), l=("low", "min"), c=("close", "last")).reset_index(); gd = gd[gd.n >= 90]
    days = [{"t": float(a), "h": float(b), "l": float(c_), "c": float(e)} for a, b, c_, e in zip(gd.open_time, gd.h, gd.l, gd.c)]
    if len(days) < 460: continue
    g = d.groupby(d.open_time // 3600 * 3600).agg(n=("close", "size"), h=("high", "max"), l=("low", "min"), c=("close", "last")).reset_index(); g = g[g.n == 4]
    t, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "h", "l", "c")); n = len(c); pc = np.r_[c[0], c[:-1]]
    A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().shift(1).to_numpy()
    dc = np.array([x["c"] for x in days]); ma200 = pd.Series(dc).rolling(200).mean().to_numpy(); grp = "S" if s in S42 else "C"
    for di in range(400, len(days)):
        day0 = days[di]["t"]; a = int(np.searchsorted(t, day0)); b = int(np.searchsorted(t, day0 + 86400))
        if b - a < 20 or a < 20: continue
        lv = [z for z in ol.find_levels(days[max(0, di - 800):di]) if z["touch"] >= 10 or z["w"] >= 3]
        if not lv: continue
        p_open = c[a - 1]; up200 = int(p_open > ma200[di - 1]) if ma200[di - 1] == ma200[di - 1] else -1
        for zi, z in enumerate(lv):
            if not (0.80 * p_open <= z["p"] <= 1.20 * p_open): continue
            for side in ((1,) if z["hi"] < p_open else ((-1,) if z["lo"] > p_open else ())):          # підтримка → LONG-сценарії; опір → SHORT-сценарії
                near, far = (z["hi"], z["lo"]) if side > 0 else (z["lo"], z["hi"])                    # near — край зони з боку ціни, far — дальній край
                done = set()
                for i in range(a, b):
                    if not A[i] > 0 or i + HOLD >= n: continue
                    ext = l[i] if side > 0 else h[i]; ext3 = l[i - 2:i + 1].min() if side > 0 else h[i - 2:i + 1].max()
                    cands = []
                    if "F" not in done and side * (ext3 - far) < 0 and side * (c[i] - far) > 0: cands.append(("F", side, ext3 - side * 0.05 * A[i]))
                    if "B" not in done and side * (ext - near) <= 0 and side * (ext - far) >= 0 and side * (c[i] - near) >= 0 and side * (pc[i] - near) > 0: cands.append(("B", side, far - side * 0.1 * A[i]))
                    if "K" not in done and side * (c[i] - far) < 0 and side * (pc[i] - far) >= 0: cands.append(("K", -side, near + side * 0.1 * A[i]))
                    for kind, sd, sl in cands:
                        done.add(kind); e = c[i]; risk = sd * (e - sl)
                        if risk <= 0 or not 0.0015 <= risk / e <= 0.05: continue
                        nx = [q for q in lv if q["lo"] > e][:1] if sd > 0 else [q for q in lv if q["hi"] < e][-1:]
                        tn = (nx[0]["lo"] if sd > 0 else nx[0]["hi"]) if nx else None
                        H_, L_ = h[i + 1:i + 1 + HOLD], l[i + 1:i + 1 + HOLD]; fav, adv = (H_, L_) if sd > 0 else (L_, H_); last = c[i + HOLD]
                        hs = (adv <= sl) if sd > 0 else (adv >= sl); isx = int(np.argmax(hs)) if hs.any() else 10**9; fee = 0.001 * e / risk; res = []
                        for tp in (e + sd * 2 * risk, e + sd * 3 * risk, tn if (tn is not None and sd * (tn - e) >= risk) else None):
                            if tp is None: res.append(np.nan); continue
                            ht = (fav >= tp) if sd > 0 else (fav <= tp); itx = int(np.argmax(ht)) if ht.any() else 10**9
                            res.append((-1.0 if (isx <= itx and isx < 10**9) else (sd * (tp - e) / risk if itx < 10**9 else sd * (last - e) / risk)) - fee)
                        trend = -1 if up200 < 0 else int((sd > 0) == (up200 == 1))
                        rows.append((s, grp, t[i], kind, sd, round(100 * risk / e, 3), trend, z["touch"], res[0], res[1], res[2]))
    print(s, len(days), flush=True)
E = pd.DataFrame(rows, columns=["sym", "grp", "te", "kind", "side", "sp", "trend", "touch", "r2", "r3", "rn"]); y = pd.to_datetime(E.te, unit="s").dt.year; E["y"] = y; E["P"] = np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3")); E.to_csv(OUT, index=False)
E["sb"] = pd.cut(E.sp, [0, 0.5, 1, 2, 5], labels=["<0,5%", "0,5–1%", "1–2%", ">2%"])
print(f"\n«ВХІД ВІД РІВНЯ»: записів {len(E):,}; монет {E.sym.nunique()}; медіанний стоп: " + ", ".join(f"{k} {v:.2f}%" for k, v in E.groupby('kind').sp.median().items()))
print("формат: $ на угоду при ризику $10, з комісією (n).   ПОШУК 42: P1 | P2 | P3   ||   КОНТРОЛЬ 30: P1 | P2 | P3")
KN = {"F": "ХИБНИЙ ПРОБІЙ", "B": "ВІДБІЙ", "K": "ПРОБІЙ"}; tot = okn = 0; BEST = []
def cells(x, col): return [(int(z[col].notna().sum()), 10 * z[col].mean() if z[col].notna().any() else np.nan) for g_ in "SC" for p in ("P1", "P2", "P3") for z in [x[(x.grp == g_) & (x.P == p)]]]
for kind in "FBK":
    for side, sn in ((1, "LONG"), (-1, "SHORT")):
        print(f"\n######## {KN[kind]} · {sn}")
        base = E[(E.kind == kind) & (E.side == side)]
        for lab, x in [("усі", base)] + [(f"стоп {v}", base[base.sb == v]) for v in ("<0,5%", "0,5–1%", "1–2%", ">2%")] + [("за трендом (200 діб)", base[base.trend == 1]), ("проти тренду", base[base.trend == 0]), ("стоп <1% і за трендом", base[(base.sp < 1) & (base.trend == 1)]), ("рівень 30+ днів", base[base.touch >= 30])]:
            for col, tn in (("r2", "2R"), ("r3", "3R"), ("rn", "наст. рівень")):
                cs = cells(x, col); ok = all(n_ >= 100 and v > 0 for n_, v in cs); tot += 1; okn += ok
                print(f" {lab:24s} ціль {tn:12s}: " + " | ".join(f"{v:+5.2f} ({n_})" if n_ else "   —  " for n_, v in cs[:3]) + "  ||  " + " | ".join(f"{v:+5.2f} ({n_})" if n_ else "   —  " for n_, v in cs[3:]) + ("   <<< ПЛЮС У ВСІХ 6" if ok else ""))
                if x[col].notna().sum() >= 500: BEST.append((10 * x[col].mean(), f"{KN[kind]} · {sn} · {lab} · ціль {tn}", x, col))
print(f"\nПІДСУМОК: варіантів {tot}; плюс у всіх 6 клітинках: {okn}")
print("\n######## 8 найкращих за середнім (n ≥ 500): по роках, сума $ (кількість)")
for per, lab, x, col in sorted(BEST, key=lambda z: -z[0])[:8]:
    x = x[x[col].notna()]; print(f" {lab}: {per:+.2f}$ на угоду, n={len(x)}, виграшних {100*(x[col]>0).mean():.0f}%, медіанний стоп {x.sp.median():.2f}%\n     " + ", ".join(f"{int(k)}: {10*z[col].sum():+.0f} ({len(z)})" for k, z in x.groupby("y")))
print("\nБез комісії (щоб бачити, скільки з'їдає комісія при короткому стопі), ціль 3R, $ на угоду: " + ", ".join(f"{KN[k]} {('LONG' if sd > 0 else 'SHORT')} {10*(z.r3 + 0.1/z.sp).mean():+.2f} (з комісією {10*z.r3.mean():+.2f})" for (k, sd), z in E.groupby(['kind', 'side'])))
