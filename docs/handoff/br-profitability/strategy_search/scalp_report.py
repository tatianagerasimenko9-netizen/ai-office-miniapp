"""READ-ONLY. Зводить scalp_pat_g*_trades.csv (фігури на M15/H1) у підсумок: за фігурою/боком, з трендом/проти, по роках, чутливість до комісії. Використання: scalp_report.py DIR"""
import sys, glob, pandas as pd
D = sys.argv[1]
W = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f"{D}/scalp_pat_g*_trades.csv"))], ignore_index=True)
print(f"угод усього {len(W)}, монет {W.sym.nunique()}")
for tf in ("M15", "H1"):
    x = W[W.tf == tf]
    if x.empty: continue
    x = x.assign(usd5=10 * (x.r + 0.001 / x.risk_pct - 0.0005 / x.risk_pct))
    print(f"\n######## {tf} (комісія 0.10% за круг / якби 0.05%)")
    g = x.groupby(["kind", "side"]).agg(n=("usd", "size"), total=("usd", "sum"), mean=("usd", "mean"), win=("usd", lambda v: 100 * (v > 0).mean()), tot05=("usd5", "sum")).round(1)
    print(g.sort_values("total", ascending=False).to_string())
    print("  -- по роках (топ-6 за сумою):")
    for (kd, sd), gg in list(x.groupby(["kind", "side"]))[:0]: pass
    top = g.sort_values("total", ascending=False).head(6).index
    for kd, sd in top:
        gg = x[(x.kind == kd) & (x.side == sd)]
        print(f"  {kd:24s} {sd:+d}: " + ", ".join(f"{y}: {v:+.0f}" for y, v in gg.groupby("y").usd.sum().items()) + f"  | з трендом ${gg[gg.ctx=='з трендом'].usd.sum():+.0f}, проти ${gg[gg.ctx!='з трендом'].usd.sum():+.0f}")
