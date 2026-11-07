"""READ-ONLY. Розбір живих TD-угод 3-7 листопада 2026: що було до входу, до стопа і після нього (свічки M15 Binance Futures), контекст BTC/ETH/золота.
Використання: postmortem_td.py CANDLES_DIR"""
import sys
from datetime import datetime, timezone
import numpy as np, pandas as pd
CD = sys.argv[1]
def ts(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()
# seq, символ, напрям, відкриття підтверджувальної M15-свічки (UTC), вхід, SL, TP, час спрацювання SL (UTC) або None
T = [
 (1, "ATOMUSDT", 1, "2026-11-03T06:15", 1.424, 1.41715, 1.4829857, "2026-11-03T06:47"),
 (2, "SOLUSDT", 1, "2026-11-03T09:00", 92.12, 91.4810714, 94.1512857, "2026-11-04T02:26"),
 (3, "ATOMUSDT", 1, "2026-11-03T23:00", 1.416, 1.4104, 1.4481571, "2026-11-03T23:45"),
 (4, "DOTUSDT", 1, "2026-11-05T23:45", 0.9079, 0.8933379, 1.0234057, None),
 (5, "XRPUSDT", -1, "2026-11-06T06:00", 1.1897, 1.2078693, 1.1097707, None),
 (6, "LTCUSDT", -1, "2026-11-06T08:45", 52.29, 52.5840714, 50.7171429, "2026-11-06T09:08"),
 (7, "ETHUSDT", -1, "2026-11-06T09:30", 2239.34, 2247.3609286, 2157.7815714, "2026-11-06T11:51"),
 (8, "DOGEUSDT", -1, "2026-11-06T09:30", 0.07226, 0.0725532, 0.0699736, "2026-11-06T11:35"),
 (9, "SOLUSDT", -1, "2026-11-06T09:45", 90.01, 90.4106429, 86.7179286, "2026-11-06T11:33"),
 (10, "ATOMUSDT", -1, "2026-11-06T10:30", 1.409, 1.4240571, 1.3775857, "2026-11-06T14:40"),
 (11, "BTCUSDT", -1, "2026-11-06T10:45", 76033.4, 76294.0329, 72996.2586, "2026-11-06T12:24"),
 (12, "BTCUSDT", -1, "2026-11-06T20:15", 75790.8, 76008.0321, 74245.9279, "2026-11-06T22:02"),
 (13, "ETHUSDT", -1, "2026-11-06T20:15", 2231.17, 2238.0747, 2184.2136, "2026-11-06T21:57"),
 (14, "SOLUSDT", -1, "2026-11-06T20:15", 89.79, 90.6183571, 85.5572857, "2026-11-06T22:02"),
 (15, "LTCUSDT", -1, "2026-11-06T20:15", 52.64, 52.9892143, 50.5568571, "2026-11-06T22:01"),
 (16, "BNBUSDT", -1, "2026-11-06T22:45", 694.15, 696.9658571, 675.9595714, "2026-11-07T02:07"),
 (17, "DOGEUSDT", -1, "2026-11-06T23:00", 0.0723, 0.0730701, 0.0696355, None),
 (18, "ADAUSDT", -1, "2026-11-06T23:00", 0.1846, 0.1870771, 0.1725829, None),
 (19, "ATOMUSDT", -1, "2026-11-06T23:30", 1.387, 1.4107143, 1.2456, None),
 (20, "SOLUSDT", -1, "2026-11-07T09:00", 90.18, 90.3638571, 88.6656429, None),
 (21, "AVAXUSDT", -1, "2026-11-07T09:00", 8.309, 8.3599357, 8.1786286, None),
]
def load(s):
    d = pd.read_csv(f"{CD}/{s}/15m.csv").drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True); return d
D = {}
for s in sorted({t[1] for t in T} | {"BTCUSDT", "ETHUSDT", "XAUUSDT"}):
    try: D[s] = load(s)
    except Exception: D[s] = None
end_ts = max(float(D["BTCUSDT"].open_time.max()) + 900, 0)
print(f"Дані M15 до {datetime.fromtimestamp(end_ts, timezone.utc):%Y-%m-%d %H:%M} UTC (кінець архіву)\n")
def atr(d, i): 
    h, l, c = d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy(); pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return tr[max(0, i - 14):i].mean() if i >= 14 else np.nan
def at(d, t): return int(np.searchsorted(d.open_time.to_numpy(), t))
def ret(d, t0, hrs, side=1):
    i = at(d, t0); j = i - int(hrs * 4)
    return side * (d.close.iloc[i - 1] / d.close.iloc[j - 1] - 1) * 100 if j > 0 and i < len(d) else float("nan")
print("| № | монета | напрям | вхід (UTC) | стоп за (хв) | найбільший рух у плюс до стопа (R) | стоп/ATR | свічка підтв./ATR | рух монети за 4 год до входу в бік угоди % | за 24 год % | положення в діапазоні 24 год (0=низ,1=верх) | BTC за 4 год до входу % | після стопа: макс. у плюс за 4/12/24 год (R, ціль =) | чи повернулась до входу | ціна через 4/24 год після стопа (R) |")
print("|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|")
rows = []
for seq, sym, side, c0, ent, sl, tp, slt in T:
    d = D[sym]; t_c = ts(c0); t_in = t_c + 900; risk = abs(ent - sl); planR = abs(tp - ent) / risk
    i_in = at(d, t_in); a = atr(d, at(d, t_c)); body = abs(d.close.iloc[at(d, t_c)] - d.open.iloc[at(d, t_c)]) / a if a == a else float("nan")
    hi24 = d.high.iloc[max(0, i_in - 96):i_in].max(); lo24 = d.low.iloc[max(0, i_in - 96):i_in].min(); pos = (ent - lo24) / (hi24 - lo24) if hi24 > lo24 else float("nan")
    r4 = ret(d, t_in, 4, side); r24 = ret(d, t_in, 24, side); b4 = ret(D["BTCUSDT"], t_in, 4, side)
    if slt:
        t_sl = ts(slt); i_sl = at(d, t_sl); seg = d.iloc[i_in:i_sl + 1]
        mfe = ((seg.high.max() - ent) if side > 0 else (ent - seg.low.min())) / risk
        dur = (t_sl - t_in) / 60
        out = []; ret_entry = False
        for h in (4, 12, 24):
            j = min(len(d), i_sl + 1 + h * 4); s2 = d.iloc[i_sl + 1:j]
            if len(s2) == 0: out.append("н/д"); continue
            m = ((s2.high.max() - ent) if side > 0 else (ent - s2.low.min())) / risk
            out.append(f"{m:+.1f}{'*' if m >= planR else ''}" + ("" if len(s2) >= h * 4 - 1 else "(неповн.)"))
            if h == 24 or len(s2) > 0: ret_entry = ret_entry or ((s2.high.max() >= ent) if side > 0 else (s2.low.min() <= ent))
        cl = []
        for h in (4, 24):
            j = i_sl + h * 4
            cl.append(f"{side * (d.close.iloc[j - 1] - ent) / risk:+.1f}" if j - 1 < len(d) else "н/д")
        aft = "/".join(out); clo = "/".join(cl); mfe_s = f"{mfe:+.2f}"; dur_s = f"{dur:.0f}"; ret_s = "так" if ret_entry else "ні"
    else:
        seg = d.iloc[i_in:]; mfe = (((seg.high.max() - ent) if side > 0 else (ent - seg.low.min())) / risk) if len(seg) else float("nan")
        last = d.close.iloc[-1]; cur = side * (last - ent) / risk
        aft = f"ще відкрита; зараз у архіві {cur:+.2f}R"; clo = "—"; mfe_s = f"{mfe:+.2f}"; dur_s = "відкрита"; ret_s = "—"
    print(f"| {seq} | {sym[:-4]} | {'LONG' if side > 0 else 'SHORT'} | {datetime.fromtimestamp(t_in, timezone.utc):%m-%d %H:%M} | {dur_s} | {mfe_s} | {risk/a:.1f} | {body:.1f} | {r4:+.1f} | {r24:+.1f} | {pos:.2f} | {b4:+.1f} | {aft} | {ret_s} | {clo} |")
print("\n(* = ціль плану досягнута в цьому вікні після стопа; ціль плану в R: " + ", ".join(f"№{t[0]}: {abs(t[6]-t[4])/abs(t[4]-t[5]):.1f}" for t in T) + ")")
# ринок: BTC, ETH, золото погодинно 6 листопада і добові зміни
def hourly(sym, day):
    d = D[sym]
    if d is None: return None
    t0 = ts(day + "T00:00"); g = d[(d.open_time >= t0) & (d.open_time < t0 + 86400)]
    return g.groupby((g.open_time - t0) // 3600).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"))
print("\nДОБОВІ ЗМІНИ (UTC, close до close), %:")
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUUSDT"):
    d = D.get(sym)
    if d is None: print(sym, "немає даних"); continue
    out = []
    for day in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"):
        t0 = ts(day + "T00:00"); g = d[(d.open_time >= t0) & (d.open_time < t0 + 86400)]
        if len(g) > 90: out.append(f"{day[5:]}: {(g.close.iloc[-1]/g.open.iloc[0]-1)*100:+.1f}% (діапазон {(g.high.max()/g.low.min()-1)*100:.1f}%)")
    print(f"  {sym[:-4]}: " + "; ".join(out))
print("\nBTC 6 листопада, ціна на початок години (UTC) і хід за годину %:")
h = hourly("BTCUSDT", "2026-11-06")
if h is not None: print("  " + "; ".join(f"{k:02d}:00 {r.o:,.0f} ({(r.c/r.o-1)*100:+.1f}%)" for k, r in h.iterrows()))
print("\nЗолото (XAUUSDT) 6 листопада, ціна на початок години і хід %:")
h = hourly("XAUUSDT", "2026-11-06")
if h is not None: print("  " + "; ".join(f"{k:02d}:00 {r.o:,.0f} ({(r.c/r.o-1)*100:+.1f}%)" for k, r in h.iterrows()))
print("\nBTC 5 і 7 листопада (до кінця архіву):")
for day in ("2026-11-05", "2026-11-07"):
    h = hourly("BTCUSDT", day)
    if h is not None and len(h): print(f"  {day[5:]}: " + "; ".join(f"{k:02d}:00 {r.o:,.0f}" for k, r in h.iterrows()))
print("\n##### ПІДСУМОК postmortem завершено")
