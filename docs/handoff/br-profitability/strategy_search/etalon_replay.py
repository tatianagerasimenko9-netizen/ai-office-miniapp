"""READ-ONLY. БОТ-ЕТАЛОН: незалежна перевірка всіх його сигналів на свічках Binance (28.11.2026, прохання власниці: «прожени на історії все, що він давав; дієвий він чи закрити; що покращити»).
Сигнали — data/etalon_signals.csv (з експорту Telegram: час, монета, напрям, вхід, стоп, TP1–TP3). Свічки 5 хв USDⓈ-M (data.binance.vision: місячні архіви + денні за поточний місяць).
ПРАВИЛА ВІДТВОРЕННЯ ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА; логіка супроводу — з коду бота bot.py: вхід майже одразу, після TP1 стоп у беззбиток, далі TP2, TP3):
 Вхід:  E0 «за ринком» — відкриття першої 5-хв свічки після сигналу (так фактично робить бот: для SHORT він позначає вхід за будь-якої ціни). Пропуск, якщо ціна вже за стопом або за TP1.
        E1 «лімітом» — лише якщо ціна торкнулась рівня входу з картки протягом 6 год; інакше угоди немає.
 Вихід: X1 «як бот» — 50% на TP1 і стоп у беззбиток; 25% на TP2; 25% на TP3; залишок — беззбиток або закриття за ринком через 7 діб.
        X2 усе на TP1.   X3 усе на TP2 (без беззбитку).   X4 50% на TP1, решта до TP2 зі стопом у беззбитку.
 У спірній свічці — стоп першим. Ризик $10 = відстань від ФАКТИЧНОГО входу до стопа з картки. Комісія 0,10% від суми позиції. «Добір» не моделюється (одна позиція).
 Звірка: наш підсумок проти того, що бот сам повідомив (SL / TP1+ / без входу).
Використання: etalon_replay.py fetch SIGNALS_CSV DIR | run SIGNALS_CSV DIR OUT_CSV"""
import os, sys, io, zipfile, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
mode, SIG, DIR = sys.argv[1], sys.argv[2], sys.argv[3]
S = pd.read_csv(SIG); S["dt"] = pd.to_datetime(S.ts, unit="s")
def get(u):
    for _ in range(3):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "office-research"}), timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception: pass
    return None
def rows_of(raw):
    out = []
    for ln in zipfile.ZipFile(io.BytesIO(raw)).read(zipfile.ZipFile(io.BytesIO(raw)).namelist()[0]).decode().splitlines():
        p = ln.split(",")
        if p[0].isdigit(): out.append((int(p[0]) // 1000 if int(p[0]) > 10**11 else int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[7]) if len(p) > 7 else 0.0))
    return out
if mode == "fetch":
    last = pd.Timestamp.utcnow().tz_localize(None).normalize()
    def one(sym):
        g = S[S.sym == sym] if sym in set(S.sym) else S; t0 = (g.dt.min() - pd.Timedelta(days=int(os.environ.get("PRE_DAYS", "0")))).normalize(); t1 = min(g.dt.max() + pd.Timedelta(days=8), last); rows = []
        for mo in pd.period_range(t0, t1, freq="M"):
            raw = get(f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}/5m/{sym}-5m-{mo}.zip")
            if raw: rows += rows_of(raw); continue
            for d in pd.date_range(max(t0, mo.start_time), min(t1, mo.end_time), freq="D"):
                raw = get(f"https://data.binance.vision/data/futures/um/daily/klines/{sym}/5m/{sym}-5m-{d.date()}.zip")
                if raw: rows += rows_of(raw)
        if rows:
            os.makedirs(DIR, exist_ok=True); pd.DataFrame(sorted(set(rows)), columns=["t", "o", "h", "l", "c", "v"]).drop_duplicates("t").to_csv(f"{DIR}/{sym}.csv", index=False)
        return sym, len(rows)
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(one, sorted(set(S.sym.unique()) | {"BTCUSDT", "ETHUSDT"})))
    print("монет", len(res), "з даними", sum(1 for _, n in res if n), "без даних:", [s for s, n in res if not n][:40]); sys.exit(0)
OUT = sys.argv[4]; FEE = 0.001; LIFE = 7 * 288; out = []
for sym, g in S.groupby("sym"):
    if not os.path.exists(f"{DIR}/{sym}.csv"): continue
    d = pd.read_csv(f"{DIR}/{sym}.csv"); t, o, h, l, c = (d[k].to_numpy(float) for k in "tohlc")
    for r in g.itertuples():
        side = 1 if r.dir == "LONG" else -1; i0 = int(np.searchsorted(t, r.ts, side="left"))
        if i0 >= len(t) - 2 or t[i0] - r.ts > 900: continue                                  # немає свічок на момент сигналу
        res = dict(ts=r.ts, sym=sym, id=r.id, p0=o[i0])
        for E in ("E0", "E1"):
            if E == "E0": ie, e = i0, o[i0]
            else:
                hit = np.flatnonzero((l[i0:i0 + 72] <= r.entry) & (h[i0:i0 + 72] >= r.entry)); ie, e = (i0 + int(hit[0]), r.entry) if len(hit) else (None, None)
            risk = side * (e - r.sl) if e is not None else 0
            if e is None or risk <= 0 or side * (r.tp1 - e) <= 0:
                for X in ("X1", "X2", "X3", "X4"): res[f"{E}{X}"] = np.nan
                res[f"{E}_st"] = "NOENTRY" if e is None else "SKIP"; continue
            H, L = h[ie:ie + LIFE], l[ie:ie + LIFE]; fav = (H if side > 0 else L); adv = (L if side > 0 else H)
            def first(px, arr, up):                                                          # перший бар, де ціна дійшла до px
                m = (arr >= px) if up else (arr <= px); return int(np.argmax(m)) if m.any() else 10**9
            isl = first(r.sl, adv, side < 0); it1 = first(r.tp1, fav, side > 0); it2 = first(r.tp2, fav, side > 0); it3 = first(r.tp3, fav, side > 0)
            R = lambda px: side * (px - e) / risk; fee = FEE * e / risk; last = c[min(ie + LIFE, len(c)) - 1]; closed_all = ie + LIFE <= len(c)
            def after_be(i_from, target_i):                                                  # після TP1: беззбиток (ціна входу) чи ціль
                ibe = first(e, adv[i_from + 1:], side < 0) + i_from + 1 if i_from + 1 < len(adv) else 10**9
                return "T" if target_i < ibe and target_i < 10**9 else ("B" if ibe < 10**9 else "O")
            if isl <= it1 and isl < 10**9: st = "SL"; x1 = x2 = x4 = -1.0
            elif it1 < 10**9:
                a2 = after_be(it1, it2); x2 = R(r.tp1)
                if a2 == "T":
                    a3 = after_be(it2, it3); st = "TP3" if a3 == "T" else "TP2"
                    x1 = 0.5 * R(r.tp1) + 0.25 * R(r.tp2) + 0.25 * (R(r.tp3) if a3 == "T" else (0.0 if a3 == "B" else R(last)))
                    x4 = 0.5 * R(r.tp1) + 0.5 * R(r.tp2)
                else:
                    st = "TP1"; rest = 0.0 if a2 == "B" else R(last); x1 = 0.5 * R(r.tp1) + 0.5 * rest; x4 = x1
            else: st = "OPEN" if not closed_all else "TIME"; x1 = x2 = x4 = R(last)
            x3 = -1.0 if (isl <= it2 and isl < 10**9) else (R(r.tp2) if it2 < 10**9 else R(last))
            for X, v in (("X1", x1), ("X2", x2), ("X3", x3), ("X4", x4)): res[f"{E}{X}"] = round(v - fee, 4)
            res[f"{E}_st"] = st; res[f"{E}_sp"] = round(100 * risk / e, 3)
            if E == "E0": res["mfe"] = round(R(fav.max() if side > 0 else fav.min()), 2) if len(fav) else 0.0; res["hrs_sl"] = round(isl / 12, 1) if isl < 10**9 else np.nan
        out.append(res)
Rr = pd.DataFrame(out); M = S.merge(Rr, on=["ts", "sym", "id"], how="left"); M.to_csv(OUT, index=False)
print(f"сигналів {len(S)}; зі свічками {Rr.shape[0]}; монет зі свічками {Rr.sym.nunique()} із {S.sym.nunique()}")
M["mo"] = M.dt.dt.strftime("%Y-%m")
for E in ("E0", "E1"):
    x = M[M[f"{E}X1"].notna()]; print(f"\n######## {'ВХІД ЗА РИНКОМ (як бот)' if E == 'E0' else 'ВХІД ЛІМІТОМ за ціною з картки (6 год)'}: угод {len(x)}; статуси {x[E + '_st'].value_counts().to_dict()}; не ввійшло/пропуск {int(M[E + '_st'].isin(['NOENTRY', 'SKIP']).sum())}; медіанний стоп {x[E + '_sp'].median():.2f}%")
    for X, nm in (("X1", "як бот: 50% TP1 → беззбиток, 25% TP2, 25% TP3"), ("X2", "усе на TP1"), ("X3", "усе на TP2, без беззбитку"), ("X4", "50% TP1, решта до TP2 з беззбитком")):
        v = 10 * x[E + X]; print(f"   {nm:48s} сума ${v.sum():+8.0f}  на угоду ${v.mean():+6.2f}  виграшних {100*(v>0).mean():3.0f}%  | по місяцях: " + ", ".join(f"{k[5:]}: {s:+.0f}" for k, s in (10 * x.groupby('mo')[E + X].sum()).items()))
x = M[M.E0X1.notna()].copy(); x["u"] = 10 * x.E0X1
print("\n######## ЗВІРКА з тим, що повідомляв сам бот (рядки — бот, стовпці — наша перевірка, вхід за ринком)"); x["bot"] = x.status.str.replace(r"\+OPEN", "", regex=True); print(pd.crosstab(x.bot, x.E0_st).to_string())
print(f"   збіг «стоп / не стоп»: {100*((x.bot=='SL')==(x.E0_st=='SL')).mean():.0f}% сигналів")
def tab(col, lab=None, minn=20):
    g = x.groupby(col).agg(n=("u", "size"), usd=("u", "sum"), per=("u", "mean"), win=("u", lambda s: 100 * (s > 0).mean()), tp1=("E0X2", lambda s: 10 * s.sum())).round(1); g = g[g.n >= minn]
    print(f"\n--- {lab or col} (як бот; останній стовпець — «усе на TP1»)"); print(g.to_string())
for c_, lab in (("mo", "місяць"), ("dir", "напрям"), ("tf", "таймфрейм"), ("kind", "вид"), ("tier", "клас"), ("ses", "сесія"), ("regime", "режим ринку"), ("kz", "kill zone"), ("against", "проти денного тренду"), ("ai", "вердикт AI")): tab(c_, lab)
x["h"] = pd.to_datetime(x.ts + 2 * 3600, unit="s").dt.hour // 3 * 3; tab("h", "година за Києвом (блоки по 3 год)", 15)
x["dow"] = pd.to_datetime(x.ts, unit="s").dt.dayofweek; tab("dow", "день тижня (0 = понеділок)", 15)
for col, bins, lab in (("score", [-2, 11, 15, 17, 18, 19, 20], "бал"), ("E0_sp", [0, 1, 2, 3, 4, 6, 50], "стоп %"), ("rr1", [0, 1, 1.5, 2, 3, 99], "R/R до TP1"), ("rsi", [-2, 30, 45, 55, 70, 101], "RSI"), ("adx", [-2, 20, 30, 40, 101], "ADX"), ("atr", [-2, 1, 2, 3, 50], "ATR %")):
    x["b"] = pd.cut(x[col], bins); tab("b", lab, 15)
x["slip"] = (np.where(x.dir == "LONG", 1, -1) * (x.p0 - x.entry) / x.entry * 100); x["b"] = pd.cut(x.slip, [-50, -1, -0.3, 0.3, 1, 50]); tab("b", "ціна в момент сигналу відносно входу з картки, % (плюс = уже гірше за картку)", 15)
x["cnt"] = x.groupby("sym").sym.transform("size"); x["b"] = pd.cut(x.cnt, [0, 1, 3, 6, 99]); tab("b", "скільки сигналів було по цій монеті", 15)
for dname, sub in (("SHORT", x[x.dir == "SHORT"]), ("LONG", x[x.dir == "LONG"])):
    print(f"\n{dname} по місяцях: " + ", ".join(f"{k[5:]}: {v:+.0f} ({n})" for (k, v), n in zip(sub.groupby('mo').u.sum().items(), sub.groupby('mo').size())))
d = x.assign(day=pd.to_datetime(x.ts, unit="s").dt.date).groupby("day").u.sum(); eq = d.cumsum(); print(f"\nднів {len(d)}, у плюсі {int((d>0).sum())}; найгірший день {d.min():+.0f}, найкращий {d.max():+.0f}; найбільше падіння {(eq-eq.cummax()).min():+.0f}; без 5 найкращих днів сума {d.sum()-d.nlargest(5).sum():+.0f}")
print(f"MFE: дійшли до +1R {100*(x.mfe>=1).mean():.0f}%, до +2R {100*(x.mfe>=2).mean():.0f}%; стопи: медіана {x[x.E0_st=='SL'].hrs_sl.median():.1f} год до стопа; стоп за першу годину {100*(x[x.E0_st=='SL'].hrs_sl<=1).mean():.0f}% стопів")
