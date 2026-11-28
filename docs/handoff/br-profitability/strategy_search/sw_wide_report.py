"""READ-ONLY. Підсумок sw_wide.py: СВІНГ на всіх ф'ючерсах, день тижня сигналу, спокійні монети. Використання: sw_wide_report.py DATA_DIR"""
import sys, glob
import pandas as pd, numpy as np
S42 = set("BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,BNBUSDT,LTCUSDT,DOTUSDT,ATOMUSDT,TRXUSDT,NEARUSDT,OPUSDT,FILUSDT,ETCUSDT,UNIUSDT,AAVEUSDT,MKRUSDT,SANDUSDT,MANAUSDT,AXSUSDT,GALAUSDT,RUNEUSDT,LDOUSDT,CRVUSDT,SNXUSDT,ICPUSDT,XLMUSDT,BCHUSDT,ALGOUSDT,VETUSDT,GRTUSDT,APEUSDT,IMXUSDT,INJUSDT,APTUSDT,EOSUSDT,HBARUSDT,THETAUSDT,DYDXUSDT".split(","))
fs = sorted(glob.glob(sys.argv[1] + "/sw_wide_*.csv.gz")); d = pd.concat([pd.read_csv(f) for f in fs]); d["usd"] = 10 * d.r
k = pd.to_datetime(d.ts, unit="s", utc=True); d["y"] = k.dt.year; d["dow"] = k.dt.tz_convert("Europe/Kyiv").dt.day_of_week; d["our"] = d.sym.isin(S42); d["calm"] = d.atr_pct < 0.023
d["P"] = np.where(d.y <= 2021, "P1", np.where(d.y <= 2023, "P2", "P3")); D = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"]; d["good"] = d.dow.isin([2, 3, 4])
print(f"частин {len(fs)}, монет {d.sym.nunique()} (наших {d[d.our].sym.nunique()}), угод {len(d)}, {d.y.min()}–{d.y.max()}; ризик $10, комісія 0,10%")
def line(nm, x):
    if not len(x): return
    z = x.sort_values("ts"); eq = z.usd.cumsum(); mo = (z.ts.max() - z.ts.min()) / 86400 / 30.4; m = z.groupby(pd.to_datetime(z.ts, unit="s").dt.to_period("M")).usd.sum()
    print(f"{nm:44s} монет {z.sym.nunique():4d} n={len(z):6d} ({len(z)/mo:5.0f}/міс) на сигнал {z.usd.mean():+.2f} сума {z.usd.sum():+8.0f} ({z.usd.sum()/mo:+5.0f}/міс) просадка {(eq-eq.cummax()).min():7.0f} стопів {100*(z.r<=-0.95).mean():.0f}% мінус-місяців {int((m<0).sum())}/{len(m)} | " + " ".join(f"{p}:{z[z.P==p].usd.mean():+.2f}" for p in ("P1", "P2", "P3")) + " | " + ", ".join(f"{y}:{v:+.0f}" for y, v in z.groupby("y").usd.sum().items()))
for nm, x in (("НАШІ 42", d[d.our]), ("ІНШІ", d[~d.our])):
    print(f"\n== {nm}: за днем сигналу (київський час), $ на сигнал: P1 / P2 / P3 / усі (n)")
    for i in range(7):
        g = x[x.dow == i]; print(f"   {D[i]}: " + " / ".join(f"{g[g.P==p].usd.mean():+.2f}" for p in ("P1", "P2", "P3")) + f" / {g.usd.mean():+.2f} ({len(g)})")
print()
for our, on in ((True, "НАШІ 42"), (False, "ІНШІ")):
    x = d[d.our == our]
    line(f"{on}: усі дні", x); line(f"{on}: ср–пт", x[x.good]); line(f"{on}: решта днів", x[~x.good])
    line(f"{on}: спокійні, усі дні", x[x.calm]); line(f"{on}: спокійні, ср–пт", x[x.calm & x.good]); line(f"{on}: рухливі, ср–пт", x[~x.calm & x.good]); print()
line("УСІ МОНЕТИ: ср–пт", d[d.good]); line("УСІ МОНЕТИ: спокійні, ср–пт", d[d.calm & d.good]); line("УСІ МОНЕТИ: чт–пт", d[d.dow.isin([3, 4])]); line("УСІ МОНЕТИ: спокійні, чт–пт", d[d.calm & d.dow.isin([3, 4])])
o = d[~d.our]; h = o.sym.map(lambda s: sum(map(ord, s)) % 2)
print("\n== ІНШІ, дві випадкові половини монет (ср–пт / решта, $ на сигнал): " + " | ".join(f"половина {i}: {o[(h==i)&o.good].usd.mean():+.2f} / {o[(h==i)&~o.good].usd.mean():+.2f}" for i in (0, 1)))
