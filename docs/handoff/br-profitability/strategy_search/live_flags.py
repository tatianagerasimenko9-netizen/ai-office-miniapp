"""READ-ONLY. На яких живих сигналах TD (№1-86) спрацювали б 3 правила «слабкого сигналу» і що було з цими угодами. Використання: live_flags.py CANDLES_DIR SIGNALS_CSV
Правила (ГІПОТЕЗА): (1) стоп < 0,2%; (2) шорт проти сильного росту: ret36h>=4 і (ret6h>=2 або ret12h>=2); (3) лонг після падіння: ret6h<=-2,4 або ret12h<=-2,5 або (ret36h<=-3,5 і BTC 24 год < 0). ret = рух ціни до входу за 6/12/36 год за ЗАКРИТИМИ H1-барами."""
import sys, numpy as np, pandas as pd
CD, SIG = sys.argv[1], sys.argv[2]
def h1(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    return d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
S = pd.read_csv(SIG); S["sym"] = S.sym.where(S.sym.str.endswith("USDT"), S.sym + "USDT"); H = {}; res = []
for r in S.itertuples():
    try:
        if r.sym not in H: H[r.sym] = h1(r.sym)
        if "BTCUSDT" not in H: H["BTCUSDT"] = h1("BTCUSDT")
        h = H[r.sym]; t = h.open_time.to_numpy(float); i = int(np.searchsorted(t, r.t0 // 3600 * 3600))   # H1-бар, у якому видано картку (він ще не закритий)
        if i < 36 or i >= len(t) or t[i] != r.t0 // 3600 * 3600: print(f"пропуск №{r.seq} {r.sym}: i={i} з {len(t)}, перший H1 {t[0]:.0f}, останній {t[-1]:.0f}, t0 {r.t0}"); res.append(None); continue
        ent = r.entry; c = h.close.to_numpy(float)
        ret = lambda k: (ent / c[i - k] - 1) * 100            # рух від закриття k годин тому до входу
        b = H["BTCUSDT"]; bt = b.open_time.to_numpy(float); bi = int(np.searchsorted(bt, r.t0 // 3600 * 3600)) - 1; bc = b.close.to_numpy(float)
        btc24 = (bc[bi] / bc[bi - 24] - 1) * 100
        sp = abs(ent - r.sl) / ent * 100; r6, r12, r36 = ret(6), ret(12), ret(35)
        f1 = sp < 0.2; f2 = r.side < 0 and r36 >= 4 and (r6 >= 2 or r12 >= 2); f3 = r.side > 0 and (r6 <= -2.4 or r12 <= -2.5 or (r36 <= -3.5 and btc24 < 0))
        R = abs(r.tp - ent) / abs(ent - r.sl); usd = {"SL": -10.0, "TP1": 10 * R}.get(r.status)
        res.append(dict(seq=r.seq, sym=r.sym[:-4], side="L" if r.side > 0 else "S", stop=round(sp, 2), r6=round(r6, 1), r12=round(r12, 1), r36=round(r36, 1), btc24=round(btc24, 1), why=("стоп<0.2 " if f1 else "") + ("шорт-проти-росту " if f2 else "") + ("лонг-після-падіння" if f3 else ""), status=r.status, usd=usd))
    except Exception as e:
        print(f"помилка №{r.seq} {r.sym}: {type(e).__name__}: {e}"); res.append(None)
D = pd.DataFrame([x for x in res if x]); D["flag"] = D["why"].str.strip() != ""
print(f"Сигналів з даними: {len(D)} із {len(S)}")
print(D[D.flag][["seq", "sym", "side", "stop", "r6", "r12", "r36", "btc24", "why", "status", "usd"]].to_string(index=False))
def tot(x): return f"{x.usd.dropna().sum():+.0f}$ (закритих {x.usd.notna().sum()}, виграшних {(x.usd.dropna() > 0).sum()})"
print(f"\nЗ попередженням: {D.flag.sum()} сигналів ({D.flag.mean()*100:.0f}%): {tot(D[D.flag])}")
print(f"Без попередження: {(~D.flag).sum()} сигналів: {tot(D[~D.flag])}")
print(f"Усі: {tot(D)}")
print("\nСтатуси (з попередженням):", D[D.flag].status.value_counts().to_dict(), "; без:", D[~D.flag].status.value_counts().to_dict())
