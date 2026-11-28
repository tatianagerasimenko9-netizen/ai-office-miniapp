"""READ-ONLY. КОЛИ ЗАХОДИТИ ЗА СИГНАЛОМ: одразу, із затримкою, після закриття свічки, на відкритті сесії, на відкаті (28.11.2026, питання власниці).
Усе записано ДО запуску. ГІПОТЕЗА (наша автоматизація). Нічого не вмикає і не змінює в живих сигналах.

СИГНАЛИ: ті самі, що в попередніх тестах.
  sw : СВІНГ як у sw_exitlab.py BASE (H4, 3 рукави + MA200, стоп 3×ATR, ціль 6R, до 60 барів H4, одна позиція на монету), 42 монети, 2020–2026.
  td : ІНТРАДЕЙ як у td_pairs.py (12 монет, модель навчена ≤2023, поріг 2024, вхід M15, ціль 3R, до 48 год), 2024–2026.
СТОП І ЦІЛЬ — ЦІНИ З КАРТКИ СИГНАЛУ, вони НЕ зсуваються. Змінюється лише момент і ціна входу; розмір позиції — так, щоб до стопа було $10.
Якщо до входу ціна вже торкнулась стопа або цілі — входу немає (сигнал пропущено, результат 0). Кінцевий строк рахується від сигналу, а не від входу.
У спірному барі стоп першим. Комісія 0,10% за круг. Усе рахується на барах M15.
ВАРІАНТИ ВХОДУ:
  ОДРАЗУ          за ціною відкриття першого бару після сигналу (як зараз).
  ЧЕРЕЗ 15хв / 30хв / 1год / 2год / 4год / 8год / 24год — за ринком через цей час.
  СВІЧКА 1г       чекати закриття годинної свічки в бік сигналу (до 4 годин); немає такої — пропустити.
  СВІЧКА 4г       чекати закриття наступної 4-годинної свічки в бік сигналу; закрилась проти — пропустити.
  СЕСІЯ Азія      увійти о 00:00 UTC (це ж і закриття дня);  СЕСІЯ Лондон — о 07:00 UTC;  СЕСІЯ Нью-Йорк — о 13:30 UTC (найближча після сигналу).
  ВІДКАТ 0,25 / 0,5   лімітна заявка на 0,25 / 0,5 відстані до стопа кращу за ціну сигналу; чекати W (sw: 24 год, td: 4 год); не дійшло — пропустити.
  ПІДТВЕРДЖЕННЯ 0,5   увійти, лише коли ціна пройшла 0,5 відстані до стопа В БІК сигналу (чекати W); не пройшла — пропустити.
ПОКАЗНИКИ: скільки сигналів узято, сума $, $ на СИГНАЛ (пропущені = 0) і $ на угоду, % виграшних, сума по періодах. Варіант «кращий», лише якщо сума більша
за ОДРАЗУ в КОЖНОМУ періоді. Окремо: результат ОДРАЗУ залежно від сесії, в яку прийшов сигнал.
Використання: entry_lab.py sw CANDLES_DIR SYMS  |  entry_lab.py td CANDLES_DIR TRAIN"""
import os, sys
import numpy as np, pandas as pd
MODE, CD, SYMS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
FEE = 0.001


def load15(s):
    d = pd.read_csv(f"{CD}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    return {k: d[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}


def sw_signals():
    def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
    def rsi(c, n):
        d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
        return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
    def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
    out = []; PER = 14400; H = 60; K = 6.0; S = 3.0
    for sym in SYMS:
        if not os.path.exists(f"{CD}/{sym}/15m.csv"): continue
        d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
        g = d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
        t, o, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")); n = len(c)
        pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); m200 = sma(c, 200)
        up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
        r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
        L = (ev(c > hi20) & up) | ev((r2 < 10) & up) | ev((c < lb) & up); Sx = (ev(c < lo20) & dn) | ev((r2 > 90) & dn) | ev((c > ub) & dn)
        i = 201
        while i < n - 2:
            if L[i] == Sx[i] or not A[i] > 0: i += 1; continue
            side = 1 if L[i] else -1; e = o[i + 1]; risk = S * A[i]
            if risk <= 0 or risk / e < 0.0005: i += 1; continue
            j = i + 1
            while j < n and j <= i + H:                                   # базовий вихід — лише щоб визначити «одна позиція на монету»
                adv = side * ((l[j] if side > 0 else h[j]) - e) / risk; fav = side * ((h[j] if side > 0 else l[j]) - e) / risk
                if adv <= -1 or fav >= K: break
                j += 1
            out.append((sym, side, t[i + 1], e, e - side * risk, e + side * K * risk)); i = max(j, i + 1)
    return out, 960, 96


def td_signals():
    sys.argv = ["x", CD, ",".join(SYMS), ",".join(SYMS), "0.0010"]
    import newcoins as nc
    from sklearn.ensemble import HistGradientBoostingRegressor
    md, td = nc.md, nc.td
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    A = nc.rows(SYMS, btc); A["year"] = pd.to_datetime(A.t, unit="s").dt.year
    X = [c for c in A.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr = A[A.year <= 2023]; va = A[A.year == 2024]
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97)); parts = []
    for y in (2024, 2025, 2026):
        z = A[A.year == y].copy()
        if len(z): z["s"] = m.predict(z[X]); parts.append(z[z.s >= thr])
    sel = md.dedupe(pd.concat(parts)); out = []; cache = {}
    for _, x in sel.iterrows():
        if x.sym not in cache:
            a = td.load15(x.sym); cache[x.sym] = (a, td.atr_arr(a["high"], a["low"], a["close"]))
        a, at_ = cache[x.sym]; side = int(x.side); i0 = int(np.searchsorted(a["open_time"], x.t + 3600)); tp = x.ent + side * 3 * abs(x.ent - x.sl)
        o_, h_, l_, c_ = a["open"], a["high"], a["low"], a["close"]
        for k in range(16):
            j = i0 + k
            if j < 9 or j >= len(c_) - 2: break
            if not ((c_[j] > o_[j] and c_[j] > h_[j - 1]) if side > 0 else (c_[j] < o_[j] and c_[j] < l_[j - 1])): continue
            at = at_[j]
            if not at == at: break
            ext = l_[j - 7:j + 1].min() if side > 0 else h_[j - 7:j + 1].max(); sl = ext - side * 0.1 * at; ent = c_[j]; sp = abs(ent - sl) / ent
            if (ent - sl) * side <= 0 or not (0.0015 <= sp <= 0.03) or (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): break
            out.append((x.sym, side, float(a["open_time"][j]) + 900, float(ent), float(sl), float(tp))); break
    return out, 192, 16


SIG, HZ, W = sw_signals() if MODE == "sw" else td_signals()
C = {}
VARS = ["ОДРАЗУ"] + [f"ЧЕРЕЗ {n}" for n in ("15хв", "30хв", "1год", "2год", "4год", "8год", "24год")] + ["СВІЧКА 1г", "СВІЧКА 4г", "СЕСІЯ Азія", "СЕСІЯ Лондон", "СЕСІЯ Нью-Йорк", "ВІДКАТ 0,25", "ВІДКАТ 0,5", "ПІДТВЕРДЖЕННЯ 0,5"]
DEL = {"15хв": 1, "30хв": 2, "1год": 4, "2год": 8, "4год": 16, "8год": 32, "24год": 96}
SES = {"Азія": 0, "Лондон": 7 * 3600, "Нью-Йорк": 13 * 3600 + 1800}


def dead(a, side, sl, tp, k0, k1):
    """Чи торкнулась ціна стопа або цілі на барах [k0, k1)."""
    if k1 <= k0: return False
    return bool(((a["low"][k0:k1] <= sl).any() or (a["high"][k0:k1] >= tp).any()) if side > 0 else ((a["high"][k0:k1] >= sl).any() or (a["low"][k0:k1] <= tp).any()))


def entry(a, v, side, e0, sl, tp, s0, dl):
    """→ (індекс бару входу, ціна, True якщо вхід усередині бару — тоді цей бар перевіряється лише на стоп) або None."""
    t, o, h, l, c = a["open_time"], a["open"], a["high"], a["low"], a["close"]; risk0 = abs(e0 - sl)
    if v == "ОДРАЗУ": return s0, o[s0], False
    if v.startswith("ЧЕРЕЗ"):
        k = s0 + DEL[v.split()[1]]
        return None if k >= dl or dead(a, side, sl, tp, s0, k) else (k, o[k], False)
    if v.startswith("СЕСІЯ"):
        off = SES[v.split()[1]]; k = s0
        while k < dl and t[k] % 86400 != off: k += 1
        return None if k >= dl or dead(a, side, sl, tp, s0, k) else (k, o[k], False)
    if v.startswith("СВІЧКА"):
        per = 3600 if "1г" in v else 14400; nb = per // 900; tries = 4 if per == 3600 else 1
        k = s0
        while k < dl and t[k] % per != 0: k += 1
        for _ in range(tries):
            if k + nb >= dl: return None
            if side * (c[k + nb - 1] - o[k]) > 0:
                return None if dead(a, side, sl, tp, s0, k + nb) else (k + nb, o[k + nb], False)
            k += nb
        return None
    f = float(v.split()[1].replace(",", ".")); px = e0 - side * f * risk0 if v.startswith("ВІДКАТ") else e0 + side * f * risk0
    for k in range(s0, min(dl, s0 + W)):
        hit = (l[k] <= px <= h[k]) or ((o[k] - px) * (1 if v.startswith("ВІДКАТ") else -1) * side <= 0)      # торкання або розрив через ціну заявки
        if hit:
            p = px if l[k] <= px <= h[k] else o[k]
            return None if dead(a, side, sl, tp, s0, k) else (k, p, True)
        if dead(a, side, sl, tp, k, k + 1): return None
    return None


rows = []
for sym, side, ts, e0, sl, tp in SIG:
    if sym not in C: C[sym] = load15(sym)
    a = C[sym]; t = a["open_time"]; s0 = int(np.searchsorted(t, ts)); dl = s0 + HZ
    if s0 >= len(t) - 2 or dl >= len(t) or t[s0] - ts > 3600: continue
    hr = int(ts // 3600 % 24); ses = "Азія 00–07" if hr < 7 else ("Лондон 07–13" if hr < 13 else ("Нью-Йорк 13–21" if hr < 21 else "ніч 21–24"))
    for v in VARS:
        en = entry(a, v, side, e0, sl, tp, s0, dl)
        if en is None: rows.append((sym, ts, v, 0, 0.0, ses)); continue
        k, e, inbar = en; risk = side * (e - sl)
        if risk <= 0 or side * (tp - e) <= 0 or risk / e < 0.0005: rows.append((sym, ts, v, 0, 0.0, ses)); continue
        h, l, c = a["high"], a["low"], a["close"]; res = None
        for q in range(k, dl):
            if (l[q] <= sl) if side > 0 else (h[q] >= sl): res = -1.0; break
            if (q > k or not inbar) and ((h[q] >= tp) if side > 0 else (l[q] <= tp)): res = side * (tp - e) / risk; break
        if res is None: res = side * (c[dl - 1] - e) / risk
        rows.append((sym, ts, v, 1, 10 * (res - FEE / (risk / e)), ses))
T = pd.DataFrame(rows, columns=["sym", "ts", "v", "in", "usd", "ses"]); T["y"] = pd.to_datetime(T.ts, unit="s").dt.year
T["P"] = (np.where(T.y <= 2021, "P1 2020–21", np.where(T.y <= 2023, "P2 2022–23", "P3 2024–26")) if MODE == "sw" else T.y.astype(str))
N = T[T.v == "ОДРАЗУ"].shape[0]; PS = sorted(T.P.unique()); base = T[T.v == "ОДРАЗУ"].groupby("P").usd.sum()
print(f"{'СВІНГ' if MODE == 'sw' else 'ІНТРАДЕЙ'}: сигналів {N}, монет {T.sym.nunique()}, {int(T.y.min())}–{int(T.y.max())}; ризик $10, комісія 0,10%")
print(f"{'варіант входу':20s} {'узято':>6s} {'сума $':>9s} {'на сигнал':>9s} {'на угоду':>8s} {'вигр.%':>6s} | " + " ".join(f"{p:>11s}" for p in PS) + " | краще за ОДРАЗУ в усіх періодах")
best = []
for v in VARS:
    x = T[T.v == v]; e = x[x["in"] == 1]; by = x.groupby("P").usd.sum().reindex(PS).fillna(0); ok = v != "ОДРАЗУ" and all(by[p] > base[p] for p in PS)
    if ok: best.append(v)
    print(f"{v:20s} {100*len(e)/N:5.0f}% {x.usd.sum():+9.0f} {x.usd.sum()/N:+9.2f} {(e.usd.mean() if len(e) else 0):+8.2f} {(100*(e.usd>0).mean() if len(e) else 0):6.0f} | " + " ".join(f"{by[p]:+11.0f}" for p in PS) + (" | ТАК" if ok else " |"))
print("\nКращі за ОДРАЗУ в усіх періодах: " + (", ".join(best) if best else "НЕМАЄ"))
print("\n== ОДРАЗУ: залежно від того, в яку сесію (UTC) прийшов сигнал — $ на сигнал по періодах (n)")
x = T[T.v == "ОДРАЗУ"]
for s, g in x.groupby("ses"):
    print(f"  {s:16s}: усього {g.usd.mean():+.2f} (n={len(g)}) | " + " | ".join(f"{p}: {g[g.P == p].usd.mean():+.2f} ({int((g.P == p).sum())})" for p in PS))
print("\n== найкраща сесія для входу залежно від сесії сигналу ($ на сигнал): ОДРАЗУ / чекати Азії / Лондона / Нью-Йорка")
for s in sorted(x.ses.unique()):
    print(f"  сигнал у «{s}»: " + " / ".join(f"{T[(T.v == v) & (T.ses == s)].usd.mean():+.2f}" for v in ("ОДРАЗУ", "СЕСІЯ Азія", "СЕСІЯ Лондон", "СЕСІЯ Нью-Йорк")))
