"""READ-ONLY. СВІНГ: ЯК НЕ ВІДДАВАТИ ПРИБУТОК — усі варіанти виходу на одній історії (27.11.2026, прохання власниці: «я втратила весь прибуток зі свінгу… рахуй усі можливі варіанти»).
Входи СВІНГ ідентичні sw_mfe.py (H4, 3 рукави + MA200, стоп 3×ATR, ціль 6R, ≤60 барів, одна позиція на монету, комісія FEE). Міняється ЛИШЕ правило виходу. СПИСОК ВАРІАНТІВ ЗАПИСАНО ДО ЗАПУСКУ (ГІПОТЕЗА), нічого не підбирається:
 BASE            як зараз.
 BE@k            після +kR стоп у беззбиток (k = 1, 2, 3).
 LOCK a>m        після +aR стоп на +mR (2>1, 3>1.5, 3>2, 4>2, 4>3).
 TRAIL a/d       після +aR стоп іде за найкращою ціною на відстані dR (2/1.5, 2/2, 3/1.5, 3/2, 4/2).
 GIVE a/f        після +aR вихід на закритті бару, якщо від найкращого результату лишилось ≤ f (2/0.5, 3/0.5, 2/0.33, 3/0.66).
 STALL a/n       після +aR вихід, якщо n барів немає нового максимуму прибутку (2/12, 2/18, 3/12, 3/24).
 TURTLE n        вихід, коли бар закрився за протилежним екстремумом закриттів за n барів (10, 20); варіант +P — лише якщо угода в плюсі.
 MKT r           «ринок розвернувся»: BTC на H1 зробив 72-годинний мінімум після падіння ≥3 ATR і за ≤6 барів закрився вище того бару (для LONG — дзеркально); у цей момент закриваємо угоди з результатом ≥ rR (r = 0, 1, 2). MKTB r — те саме, але лише якщо ≥50% монет зробили свій 72-год мінімум за останні 6 год.
 TP k            ціль kR замість 6R (3, 4, 8, 10).   TIME n — утримання n барів замість 60 (30, 90).
Стоп, перенесений правилом, діє з НАСТУПНОГО бару; у спірному барі — стоп першим. Показники: сума $ (ризик $10), на угоду, по періодах P1 2020–21 / P2 2022–23 / P3 2024–26, у скількох роках краще за BASE, найбільше падіння,
 «біль» = частка угод, що були ≥ +2R, а закінчились ≤ +0,5R; «віддано» = середня різниця між найкращим і кінцевим результатом таких угод. Окремо: усі монети і «спокійні» (ATR/ціна < 2,3%).
Використання: sw_exitlab.py CANDLES_DIR SYMS FEE OUT_CSV"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, FEE, OUT = sys.argv[1], [s for s in sys.argv[2].split(",") if os.path.exists(f"{sys.argv[1]}/{s}/15m.csv")], float(sys.argv[3]), sys.argv[4]
PER = 14400; H = 60; K = 6.0; S = 3.0
def sma(x, n): return pd.Series(x).rolling(n).mean().to_numpy()
def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; return pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(n).mean().to_numpy()
def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
def ev(state): s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]
B = {}; FL = {1: {}, -1: {}}; REV = {1: None, -1: None}
for s in SYMS:
    d = pd.read_csv(f"{CD}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // PER * PER).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    b = {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}; c = b["close"]; b["A"] = atr(b["high"], b["low"], c); b["m200"] = sma(c, 200); B[s] = b
    g1 = d.groupby(d.open_time // 3600 * 3600).agg(n=("open", "size"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g1 = g1[g1.n == 4]
    t1, h1, l1, c1 = (g1[k].to_numpy(float) for k in ("open_time", "high", "low", "close")); A1 = atr(h1, l1, c1); n1 = len(c1)
    for side in (1, -1):                                    # side=+1: злив униз і повернення (це ПРОТИ шортів)
        lo = pd.Series(l1).rolling(72).min().to_numpy(); hi = pd.Series(h1).rolling(72).max().to_numpy(); hi24 = pd.Series(h1).rolling(24).max().to_numpy(); lo24 = pd.Series(l1).rolling(24).min().to_numpy()
        fl = np.flatnonzero(((l1 == lo) & (hi24 - l1 >= 3 * A1)) if side > 0 else ((h1 == hi) & (h1 - lo24 >= 3 * A1))); FL[side][s] = t1[fl]
        if s == "BTCUSDT":
            out = []
            for f in fl:
                for j in range(f + 1, min(n1, f + 7)):
                    if (l1[j] < l1[f]) if side > 0 else (h1[j] > h1[f]): break
                    if (c1[j] > h1[f]) if side > 0 else (c1[j] < l1[f]): out.append(t1[j] + 3600); break
            REV[side] = np.array(sorted(set(out)))
def breadth_ok(side, te):
    tot = hit = 0
    for s, ft in FL[side].items():
        if not len(ft) or ft[0] > te: continue
        tot += 1; i = np.searchsorted(ft, te - 3600, side="right") - 1; hit += int(i >= 0 and ft[i] >= te - 7 * 3600)
    return tot >= 10 and hit / tot >= 0.5
REVB = {sd: np.array([te for te in REV[sd] if breadth_ok(sd, te)]) for sd in (1, -1)}
print(f"монет {len(SYMS)}; розворотів ринку (BTC): проти шортів {len(REV[1])}, проти лонгів {len(REV[-1])}; із «весь ринок»: {len(REVB[1])} / {len(REVB[-1])}", flush=True)
V = [("BASE", {})] + [(f"BE@{k}", {"lock": [(k, 0.0)]}) for k in (1, 2, 3)] + [(f"LOCK {a}>{m}", {"lock": [(a, m)]}) for a, m in ((2, 1), (3, 1.5), (3, 2), (4, 2), (4, 3))] \
    + [(f"TRAIL {a}/{d}", {"trail": (a, d)}) for a, d in ((2, 1.5), (2, 2), (3, 1.5), (3, 2), (4, 2))] + [(f"GIVE {a}/{f}", {"give": (a, f)}) for a, f in ((2, 0.5), (3, 0.5), (2, 0.33), (3, 0.66))] \
    + [(f"STALL {a}/{n}", {"stall": (a, n)}) for a, n in ((2, 12), (2, 18), (3, 12), (3, 24))] + [(f"TURTLE {n}", {"turtle": (n, False)}) for n in (10, 20)] + [(f"TURTLE {n}+P", {"turtle": (n, True)}) for n in (10, 20)] \
    + [(f"MKT {r}", {"mkt": (r, False)}) for r in (0, 1, 2)] + [(f"MKTB {r}", {"mkt": (r, True)}) for r in (0, 1, 2)] + [(f"TP {k}", {"tp": float(k)}) for k in (3, 4, 8, 10)] + [(f"TIME {n}", {"hold": n}) for n in (30, 90)]
def run(P):
    rows = []; tpR = P.get("tp", K); hold = P.get("hold", H)
    for sym in SYMS:
        b = B[sym]; o, h, l, c, A, m200, t = b["open"], b["high"], b["low"], b["close"], b["A"], b["m200"], b["open_time"]; n = len(c)
        up, dn = c > m200, c < m200; hi20 = pd.Series(h).rolling(20).max().shift(1).to_numpy(); lo20 = pd.Series(l).rolling(20).min().shift(1).to_numpy()
        r2 = rsi(c, 2); mb = sma(c, 20); sb = pd.Series(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
        L = (ev(c > hi20) & up) | ev((r2 < 10) & up) | ev((c < lb) & up); Sx = (ev(c < lo20) & dn) | ev((r2 > 90) & dn) | ev((c > ub) & dn)
        if "turtle" in P: nT = P["turtle"][0]; cmx = pd.Series(c).rolling(nT).max().shift(1).to_numpy(); cmn = pd.Series(c).rolling(nT).min().shift(1).to_numpy()
        i = 201
        while i < n - 2:
            if L[i] == Sx[i] or not A[i] > 0: i += 1; continue
            side = 1 if L[i] else -1; e = o[i + 1]; risk = S * A[i]
            if risk <= 0 or risk / e < 0.0005: i += 1; continue
            stopR = -1.0; peak = 0.0; pk_bar = 0; res = None; why = "TIME"; j = i + 1
            mk = (REVB if P.get("mkt", (0, False))[1] else REV)[-side] if "mkt" in P else None
            while j < n and j <= i + hold:
                adv = side * ((l[j] if side > 0 else h[j]) - e) / risk; fav = side * ((h[j] if side > 0 else l[j]) - e) / risk; cR = side * (c[j] - e) / risk
                if adv <= stopR: res = stopR; why = "SL" if stopR <= -1 else "LOCK"; break
                if fav >= tpR: res = tpR; why = "TP"; peak = max(peak, tpR); break
                if fav > peak: peak = fav; pk_bar = j
                for a_, m_ in P.get("lock", ()):
                    if peak >= a_: stopR = max(stopR, m_)
                if "trail" in P and peak >= P["trail"][0]: stopR = max(stopR, peak - P["trail"][1])
                if "give" in P and peak >= P["give"][0] and cR <= P["give"][1] * peak: res = cR; why = "GIVE"; break
                if "stall" in P and peak >= P["stall"][0] and j - pk_bar >= P["stall"][1]: res = cR; why = "STALL"; break
                if "turtle" in P and ((c[j] < cmn[j]) if side > 0 else (c[j] > cmx[j])) and (not P["turtle"][1] or cR > 0): res = cR; why = "TURTLE"; break
                if mk is not None and len(mk) and cR >= P["mkt"][0]:
                    q = np.searchsorted(mk, t[j], side="right")
                    if q < len(mk) and mk[q] <= t[j] + PER: res = cR; why = "MKT"; break
                j += 1
            if res is None: jj = min(j, n - 1); res = side * (c[jj] - e) / risk
            rows.append((sym, side, t[i + 1], t[min(j, n - 1)] + PER, res - FEE / (risk / e), peak, A[i] / c[i], why))
            i = max(j, i + 1)
    return pd.DataFrame(rows, columns=["sym", "side", "ts", "tx", "r", "peak", "atr_pct", "why"])
def per(y): return np.where(y <= 2021, "P1", np.where(y <= 2023, "P2", "P3"))
RES = {}; OUTR = []
for name, P in V:
    T = run(P); T["usd"] = 10 * T.r; T["y"] = pd.to_datetime(T.tx, unit="s").dt.year; T["P"] = per(T.y); RES[name] = T; print(name, len(T), round(T.usd.sum()), flush=True)
def block(title, flt):
    base = flt(RES["BASE"]); by = base.groupby("y").usd.sum(); print(f"\n######## {title}: BASE {len(base)} угод, ${base.usd.sum():+.0f}")
    print(f"{'варіант':13s} {'угод':>6s} {'сума $':>9s} {'проти BASE':>10s} {'на угоду':>8s} | {'P1':>7s} {'P2':>7s} {'P3':>7s} | років краще | {'падіння':>8s} | біль%  віддано$")
    out = []
    for name, _ in V:
        T = flt(RES[name]); yv = T.groupby("y").usd.sum().reindex(by.index, fill_value=0.0); better = int((yv > by).sum()); pp = T.groupby("P").usd.sum().reindex(["P1", "P2", "P3"], fill_value=0.0)
        d = T.usd.groupby((T.tx // 86400).astype(int)).sum().sort_index(); eq = d.cumsum(); dd = (eq - eq.cummax()).min(); big = T[T.peak >= 2]; pain = 100 * (big.r <= 0.5).mean() if len(big) else 0.0; gb = 10 * (big.peak - big.r).mean() if len(big) else 0.0
        out.append((T.usd.sum(), name, len(T), T.usd.sum() - base.usd.sum(), T.usd.mean(), pp, better, len(by), dd, pain, gb))
        OUTR.append((title, name, len(T), round(T.usd.sum()), round(T.usd.mean(), 3), round(pp["P1"]), round(pp["P2"]), round(pp["P3"]), better, round(dd), round(pain, 1), round(gb, 1)))
    for tot, name, n, dlt, pt, pp, better, ny, dd, pain, gb in sorted(out, key=lambda x: -x[0]):
        allp = all(pp[p] >= RES_base_p[title][p] for p in ("P1", "P2", "P3")) if name != "BASE" else False
        print(f"{name:13s} {n:6d} {tot:+9.0f} {dlt:+10.0f} {pt:+8.2f} | {pp['P1']:+7.0f} {pp['P2']:+7.0f} {pp['P3']:+7.0f} | {better}/{ny}         | {dd:+8.0f} | {pain:4.0f}%  {gb:6.1f}" + ("   <<< не гірше BASE в усіх трьох періодах" if allp else ""))
RES_base_p = {}
for title, flt in (("УСІ МОНЕТИ", lambda T: T), ("СПОКІЙНІ МОНЕТИ", lambda T: T[T.atr_pct < 0.023]), ("ЛИШЕ ШОРТИ", lambda T: T[T.side < 0])):
    RES_base_p[title] = flt(RES["BASE"]).groupby("P").usd.sum().reindex(["P1", "P2", "P3"], fill_value=0.0); block(title, flt)
pd.DataFrame(OUTR, columns=["set", "variant", "n", "usd", "per_trade", "P1", "P2", "P3", "years_better", "dd", "pain_pct", "giveback_usd"]).to_csv(OUT, index=False)
