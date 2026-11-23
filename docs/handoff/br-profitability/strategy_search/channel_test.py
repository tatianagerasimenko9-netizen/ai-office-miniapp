"""READ-ONLY. Гіпотеза власниці (22.11.2026): у каналі ціна 3 рази ходить від лінії до лінії, на 4-те торкання часто хибний пробій, після якого рух іде далі «туди, куди треба». Перевіряємо на історії 42 монет (H4, D1), 2022–2026.
Канал = дві майже паралельні лінії (МНК по 3–4 свінгах кожна; нахили різняться ≤0,01 ATR/свічку), ширина 2–12 ATR, свінги в межах 0,5 ATR від ліній (ГІПОТЕЗА допусків). Свінг = локальний max/min за 2 свічки з боків (підтверджується через 2 свічки).
Угоди: (A) «відбій»: після k-го торкання лінії входимо проти торкання (верхня → SHORT, нижня → LONG) на відкритті наступної свічки після підтвердження свінга; стоп за лінію +0,5 ATR; ціль = протилежна лінія; утримання 30 свічок.
(B) «хибний пробій»: після k-го торкання, якщо за ≤5 свічок ціна проколює лінію й закриття повертається усередину — входимо проти проколу (до протилежної лінії); стоп за екстремум проколу.
Комісія за круг; ризик $10; SL-першим. Результат по k = номер торкання цієї лінії (2,3,4,5+). Використання: channel_test.py CANDLES_DIR SYMS FEE OUT_PREFIX"""
import os, sys
import numpy as np, pandas as pd
CD, SYMS, FEE, OUT = sys.argv[1], sys.argv[2].split(","), float(sys.argv[3]), sys.argv[4]
PER = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}; HOLD = 30; K = 2
TFS = os.environ.get("TFS", "H4,D1").split(",")

def bars(sym, per):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // per * per).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return {k: g[k].to_numpy(float) for k in ("open_time", "open", "high", "low", "close")}
def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))); return pd.Series(tr).rolling(14).mean().to_numpy()
def walk(h, l, c, i0, side, e, sl, tp):
    risk = abs(e - sl)
    for j in range(i0, min(len(c), i0 + HOLD)):
        if (l[j] <= sl) if side > 0 else (h[j] >= sl): return -1.0, "SL"
        if (h[j] >= tp) if side > 0 else (l[j] <= tp): return side * (tp - e) / risk, "TP"
    j = min(len(c) - 1, i0 + HOLD - 1); return side * (c[j] - e) / risk, "TIME"

rows = []
for tf in TFS:
    for sym in SYMS:
        b = bars(sym, PER[tf]); o, h, l, c = b["open"], b["high"], b["low"], b["close"]; t = b["open_time"]; A = atr14(h, l, c); n = len(c)
        SH, SL_ = [], []
        for j in range(K, n - K - 6):
            is_h = h[j] > h[j - K:j].max() and h[j] > h[j + 1:j + K + 1].max(); is_l = l[j] < l[j - K:j].min() and l[j] < l[j + 1:j + K + 1].min()
            if not (is_h or is_l): continue
            a = A[j + K]
            if not a > 0: continue
            if is_h: SH.append((j, h[j]))
            if is_l: SL_.append((j, l[j]))
            hi = [p for p in SH if p[0] >= j - 150][-4:]; lo = [p for p in SL_ if p[0] >= j - 150][-4:]
            if len(hi) < 3 or len(lo) < 3: continue
            ph = np.polyfit([p[0] for p in hi], [p[1] for p in hi], 1); pl = np.polyfit([p[0] for p in lo], [p[1] for p in lo], 1)
            if abs(ph[0] - pl[0]) > 0.01 * a: continue
            now = j + K
            wid = (np.polyval(ph, now) - np.polyval(pl, now)) / a
            if not (2 <= wid <= 12): continue
            th_ = [p for p in hi if abs(p[1] - np.polyval(ph, p[0])) <= 0.5 * a]; tl_ = [p for p in lo if abs(p[1] - np.polyval(pl, p[0])) <= 0.5 * a]
            if len(th_) < 2 or len(tl_) < 2: continue
            up = is_h and abs(h[j] - np.polyval(ph, j)) <= 0.5 * a; dn = is_l and abs(l[j] - np.polyval(pl, j)) <= 0.5 * a
            if not (up or dn): continue
            side = -1 if up else 1; line = ph if up else pl; opp = pl if up else ph; k = len(th_) if up else len(tl_)
            i0 = now + 1; e = o[i0]
            sl = np.polyval(line, i0) + side * -1 * 0.5 * a if False else (np.polyval(line, i0) + 0.5 * a if up else np.polyval(line, i0) - 0.5 * a)
            tp = np.polyval(opp, i0); risk = (e - sl) * side
            if risk > 0 and risk / e >= 0.0005 and risk / e <= 0.25 and (tp - e) * side > 0:
                R, why = walk(h, l, c, i0, side, e, sl, tp); R -= FEE / (risk / e)
                rows.append((tf, sym, "відбій", min(k, 5), side, float(t[i0]), R, why))
            for bb in range(i0, min(n - 2, i0 + 5)):                                  # хибний пробій: прокол лінії й закриття назад усередину
                lv = np.polyval(line, bb)
                if (up and h[bb] > lv and c[bb] < lv) or ((not up) and l[bb] < lv and c[bb] > lv):
                    ex = h[bb] if up else l[bb]; ee = o[bb + 1]; sl2 = ex; tp2 = np.polyval(opp, bb + 1); rk = (ee - sl2) * side
                    if rk > 0 and rk / ee >= 0.0005 and rk / ee <= 0.25 and (tp2 - ee) * side > 0:
                        R2, w2 = walk(h, l, c, bb + 1, side, ee, sl2, tp2); R2 -= FEE / (rk / ee)
                        rows.append((tf, sym, "хибний пробій", min(k, 5), side, float(t[bb + 1]), R2, w2))
                    break
W = pd.DataFrame(rows, columns=["tf", "sym", "type", "k", "side", "ts", "r", "why"]); W["usd"] = 10 * W.r; W["y"] = pd.to_datetime(W.ts, unit="s").dt.year
W.to_csv(OUT + "_trades.csv", index=False)
print(f"КАНАЛ: гіпотеза 4-го торкання; комісія {FEE*100:.2f}% за круг, ризик $10, монет {len(SYMS)}")
for tf in TFS:
    for tp_ in ("відбій", "хибний пробій"):
        print(f"\n== {tf} · {tp_}")
        x = W[(W.tf == tf) & (W.type == tp_)]
        for k, g in x.groupby("k"):
            print(f"   торкання №{k}{'+' if k == 5 else ''}: {len(g):5d} угод, ${g.usd.sum():+8.0f}, на угоду ${g.usd.mean():+.2f}, виграшних {100*(g.usd>0).mean():3.0f}%, ціль {(g.why=='TP').sum()}, по роках {dict((int(a), round(b)) for a, b in g.groupby('y').usd.sum().items())}")
