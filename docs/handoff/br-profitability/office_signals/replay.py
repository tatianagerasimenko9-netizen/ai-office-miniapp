"""Прогін сигналів AI Office (картки №…, живі з 06.10.2026) на 1-хв свічках Binance Futures: базовий результат + варіанти виходу/входу/стопа + зрізи-фільтри.
Використання: python3 replay.py CANDLES_DIR SIGNALS_CSV [fee=0.0010]. $ = 10·R (ризик $10). SL-first усередині свічки, комісія+проковзування = fee за круг (в R: fee/ризик%).
Чесність: це ЛИШЕ 5 тижнів і майже суцільно ведмежий ринок; зрізи — після факту (ГІПОТЕЗА), показано перша/друга половина періоду."""
import sys, csv, math
import numpy as np
cd, sf = sys.argv[1], sys.argv[2]; FEE = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0010
def load(sym):
    a = np.loadtxt(f"{cd}/{sym}/1m.csv", delimiter=",", skiprows=1, usecols=(0, 1, 2, 3, 4))
    return a
C = {}
def cand(sym):
    if sym not in C: C[sym] = load(sym)
    return C[sym]
sigs = []
for r in csv.DictReader(open(sf)):
    r["ts"] = int(r["ts"]); 
    for k in ("entry", "sl", "tp1"): r[k] = float(r[k])
    r["tp2"] = float(r["tp2"]) if r["tp2"] else None
    sigs.append(r)
sigs.sort(key=lambda x: x["ts"]); T0, T1 = sigs[0]["ts"], sigs[-1]["ts"]; MID = (T0 + T1) / 2

def walk(a, side, t0, entry, sl, tp, maxh, be_at=None, exit_cost=None):
    """повертає (R_gross, reason, bars) від t0 (вхід за entry на початку свічки t0). side=+1 long."""
    i0 = int(np.searchsorted(a[:, 0], t0)); i1 = int(np.searchsorted(a[:, 0], t0 + maxh * 3600))
    risk = abs(entry - sl); cur_sl = sl; moved = False
    for i in range(i0, min(i1, len(a))):
        t, o, h, l, c = a[i]
        hit_sl = (l <= cur_sl) if side > 0 else (h >= cur_sl)
        hit_tp = (tp is not None) and ((h >= tp) if side > 0 else (l <= tp))
        if hit_sl: return side * (cur_sl - entry) / risk, "SL" if not moved else "BE", i - i0
        if hit_tp: return side * (tp - entry) / risk, "TP", i - i0
        if be_at is not None and not moved:
            fav = (h - entry) / risk if side > 0 else (entry - l) / risk
            if fav >= be_at: cur_sl = entry; moved = True
    j = min(i1, len(a)) - 1
    if j < i0: return None
    return side * (a[j, 4] - entry) / risk, "TIME", j - i0

def run(variant):
    out = []
    for s in sigs:
        if s["sym"] not in C and not __import__("os").path.exists(f"{cd}/{s['sym']}/1m.csv"): continue
        a = cand(s["sym"]); side = 1 if s["d"] == "L" else -1
        res = variant(s, a, side)
        if res is None: continue
        out.append((s["ts"], s, res))
    return out
def ctx(s):
    """ретурн монети і BTC за 24 год до сигналу з 1-хв"""
    a = cand(s["sym"]); b = cand("BTCUSDT"); t = s["ts"]
    def ret(x):
        i = int(np.searchsorted(x[:, 0], t)); j = int(np.searchsorted(x[:, 0], t - 86400))
        return (x[min(i, len(x) - 1), 4] / x[min(j, len(x) - 1), 4] - 1) * 100
    return ret(a), ret(b)
def stats(rows, name):
    if not rows: print(f"{name:52s} n=0"); return
    R = np.array([r for _, _, r in rows]); h1 = np.array([r for t, _, r in rows if t < MID]); h2 = np.array([r for t, _, r in rows if t >= MID])
    eq = np.cumsum(R); dd = (eq - np.maximum.accumulate(eq)).min()
    print(f"{name:52s} n={len(R):3d}  сума {R.sum():+7.1f}R (${10*R.sum():+6.0f})  сер {R.mean():+.2f}R  виграш {100*(R>0).mean():3.0f}%  | 1-ша пол {h1.sum():+6.1f}R  2-га {h2.sum():+6.1f}R  | просадка {dd:+.1f}R")
def net(gross, risk_pct, win=None, fee=None):
    return gross - (fee if fee is not None else FEE) / (risk_pct / 100)
def mk(tpkey="tp1", tp_r=None, sl_mult=1.0, maxh=48, be=None, entry_shift_r=None, fill_h=6, maker=False, tp_mult=None):
    def v(s, a, side):
        e0 = s["entry"]; risk0 = abs(e0 - s["sl"]); sl = e0 - side * risk0 * sl_mult
        if tp_r is not None: tp = e0 + side * tp_r * risk0
        elif tp_mult is not None: tp = e0 + side * abs(s["tp1"] - e0) * tp_mult
        else: tp = s[tpkey] if s.get(tpkey) else s["tp1"]
        t0 = s["ts"] + 60; entry = e0
        if entry_shift_r:                                          # лімітний вхід кращою ціною на entry_shift_r·R; чекаємо fill_h год
            lim = e0 - side * entry_shift_r * risk0; i0 = int(np.searchsorted(a[:, 0], t0)); i1 = int(np.searchsorted(a[:, 0], t0 + fill_h * 3600)); got = None
            for i in range(i0, min(i1, len(a))):
                t, o, h, l, c = a[i]
                if (l <= lim) if side > 0 else (h >= lim): got = t; break
                stop_first = (l <= sl) if side > 0 else (h >= sl)
                if stop_first: return None
            if got is None: return None
            entry = lim; t0 = got
        else:
            i0 = int(np.searchsorted(a[:, 0], t0)); 
            if i0 < len(a): entry = a[i0, 1]                      # ринковий вхід за відкриттям наступної хвилини
        risk = abs(entry - sl)
        if risk <= 0: return None
        w = walk(a, side, t0, entry, sl, tp, maxh, be_at=be)
        if w is None: return None
        g, why, _ = w; rp = risk / entry * 100
        fee = (0.0004 if why == "TP" else 0.0007) if (maker and entry_shift_r) else FEE
        return net(g, rp, fee=fee)
    return v
def feat_rows(base):
    rows = []
    for t, s, r in base:
        rc, rb = ctx(s); side = 1 if s["d"] == "L" else -1; risk = abs(s["entry"] - s["sl"]); rp = risk / s["entry"] * 100; rr = abs(s["tp1"] - s["entry"]) / risk
        rows.append(dict(t=t, s=s, r=r, side=side, rc=rc, rb=rb, rp=rp, rr=rr))
    return rows
def cut(rows, name, f):
    stats([(x["t"], x["s"], x["r"]) for x in rows if f(x)], name)

print(f"=== ПРОГІН {len(sigs)} сигналів AI Office, період {__import__('datetime').datetime.utcfromtimestamp(T0):%d.%m}–{__import__('datetime').datetime.utcfromtimestamp(T1):%d.%m.%Y}, комісія+проковзування {FEE*100:.2f}% за круг ===")
base = run(mk()); stats(base, "БАЗА: як є (вхід ринком, SL, TP1, до 48 год)")
paper = [(s["ts"], s, float(s["r"])) for s in sigs if s["r"]]; stats(paper, "для звірки: paper-результат з бази (TP1/SL/EXPIRED)")
print("\n-- Виходи (ціль) --")
stats(run(mk(tp_r=1.0)), "ціль 1R"); stats(run(mk(tp_r=1.5)), "ціль 1.5R"); stats(run(mk(tp_r=2.0)), "ціль 2R"); stats(run(mk(tp_r=3.0)), "ціль 3R")
stats(run(mk(tpkey="tp2")), "ціль TP2"); stats(run(mk(tp_mult=0.7)), "ціль 70% шляху до TP1"); stats(run(mk(tp_mult=1.5)), "ціль 1,5× шляху до TP1")
print("\n-- Таймаут --")
for h in (12, 24, 72, 120): stats(run(mk(maxh=h)), f"утримання до {h} год")
print("\n-- Стоп --")
for m in (0.7, 1.3, 1.6, 2.0): stats(run(mk(sl_mult=m)), f"стоп ×{m} (ціль та сама)")
print("\n-- Безубиток --")
for b in (0.5, 1.0): stats(run(mk(be=b)), f"стоп у беззбиток після +{b}R")
print("\n-- Лімітний вхід кращою ціною (комісія maker 0,04%/0,07% — ГІПОТЕЗА; пропущені входи = 0R) --")
for sh in (0.25, 0.5): stats(run(mk(entry_shift_r=sh, maker=True)), f"ліміт на {sh}R краще, чекаємо 6 год")
print("\n-- ЗРІЗИ по базі (що було прибутковим/збитковим) --")
rows = feat_rows(base)
cut(rows, "усі", lambda x: True)
cut(rows, "LONG", lambda x: x["side"] > 0); cut(rows, "SHORT", lambda x: x["side"] < 0)
cut(rows, "монета за напрямом (24год ретурн по напряму >0)", lambda x: x["rc"] * x["side"] > 0); cut(rows, "монета проти напряму (24год)", lambda x: x["rc"] * x["side"] <= 0)
cut(rows, "BTC 24год за напрямом", lambda x: x["rb"] * x["side"] > 0); cut(rows, "BTC 24год проти напряму", lambda x: x["rb"] * x["side"] <= 0)
cut(rows, "ризик (стоп) <0,8%", lambda x: x["rp"] < 0.8); cut(rows, "ризик 0,8–1,5%", lambda x: 0.8 <= x["rp"] < 1.5); cut(rows, "ризик 1,5–2,5%", lambda x: 1.5 <= x["rp"] < 2.5); cut(rows, "ризик >2,5%", lambda x: x["rp"] >= 2.5)
cut(rows, "R/R до TP1 <1,5", lambda x: x["rr"] < 1.5); cut(rows, "R/R до TP1 1,5–2", lambda x: 1.5 <= x["rr"] < 2); cut(rows, "R/R до TP1 ≥2", lambda x: x["rr"] >= 2)
for ses in ("ASIA", "LONDON", "LONDON_NY_OVERLAP", "NEW_YORK", "OFF_HOURS", "PRE_LONDON"): cut(rows, f"сесія {ses}", lambda x, ses=ses: x["s"]["sess"] == ses)
big = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "DOTUSDT")
cut(rows, "великі монети", lambda x: x["s"]["sym"] in big); cut(rows, "дрібні монети", lambda x: x["s"]["sym"] not in big)
print("\n-- по монетах (сума R) --")
by = {}
for x in rows: by.setdefault(x["s"]["sym"], []).append(x["r"])
for k, v in sorted(by.items(), key=lambda kv: sum(kv[1])): print(f"{k:14s} n={len(v):2d} сума {sum(v):+6.1f}R  виграш {100*np.mean([r>0 for r in v]):3.0f}%")
print("\n-- Комбінації-кандидати (після факту, ГІПОТЕЗА; дивитись обидві половини) --")
cut(rows, "тільки SHORT", lambda x: x["side"] < 0)
cut(rows, "SHORT + R/R≥1,5", lambda x: x["side"] < 0 and x["rr"] >= 1.5)
cut(rows, "за напрямом BTC 24год", lambda x: x["rb"] * x["side"] > 0)
cut(rows, "за напрямом BTC і монети 24год", lambda x: x["rb"] * x["side"] > 0 and x["rc"] * x["side"] > 0)
cut(rows, "не LONG проти BTC", lambda x: not (x["side"] > 0 and x["rb"] < 0))
cut(rows, "ризик ≥0,8% і R/R≥1,5", lambda x: x["rp"] >= 0.8 and x["rr"] >= 1.5)
