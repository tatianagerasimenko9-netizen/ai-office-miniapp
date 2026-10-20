"""Transparent, causal B&R Price Action / structure metrics.

All features use M15 candles through confirmation ONLY. These are our
operational definitions, not verified rules of Gerchik, ICT, Wyckoff or a blogger.
No signal filtering, no orders, no price-target adjustment.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence


def metrics(signal: Mapping[str, Any], bars: Sequence[Mapping[str, Any]],
            *, atr_n: int = 14, volume_lookback: int = 20) -> dict[str, Any]:
    bi, ri, ci = (int(signal[k]) for k in ("break_i","retest_i","confirm_i"))
    if not (0 <= bi < ri <= ci < len(bars)):
        raise ValueError("invalid breakout/retest/confirmation indices")
    direction = str(signal["direction"]).upper()
    if direction not in ("LONG","SHORT"):
        raise ValueError("invalid direction")
    level = float(signal["level"])
    if bi < max(atr_n, volume_lookback):
        raise ValueError("insufficient pre-breakout history")
    closed = bars[:ci+1]
    def tr(i: int) -> float:
        b,prev=closed[i],closed[i-1]
        hi,lo,pc=float(b["high"]),float(b["low"]),float(prev["close"])
        return max(hi-lo,abs(hi-pc),abs(lo-pc))
    atr=sum(tr(i) for i in range(bi-atr_n+1,bi+1))/atr_n
    if atr<=0: raise ValueError("zero ATR")
    sg=1 if direction=="LONG" else -1
    breakout=closed[bi]
    op,cl,hi,lo=(float(breakout[k]) for k in ("open","close","high","low"))
    span=hi-lo
    if span<=0: raise ValueError("zero breakout range")
    body=abs(cl-op)
    close_location=(cl-lo)/span if sg>0 else (hi-cl)/span
    volumes=[float(closed[i].get("volume",0) or 0) for i in range(bi-volume_lookback,bi)]
    current_volume=float(breakout.get("volume",0) or 0)
    mean_vol=sum(volumes)/len(volumes) if all(v>0 for v in volumes) else 0
    retest=closed[ri]
    retest_extreme=min(float(closed[i]["low"]) for i in range(ri,ci+1)) if sg>0 else max(float(closed[i]["high"]) for i in range(ri,ci+1))
    entry,stop=float(signal["entry"]),float(signal["sl"])
    risk=abs(entry-stop)
    if risk<=0: raise ValueError("zero risk")
    return {
        "mode":"SHADOW_ONLY",
        "source":"OUR_OPERATIONAL_DEFINITIONS",
        "confirm_i":ci,
        "breakout_body_fraction":round(body/span,6),
        "breakout_close_location":round(close_location,6),
        "breakout_body_atr":round(body/atr,6),
        "breakout_close_beyond_level_atr":round(sg*(cl-level)/atr,6),
        "breakout_volume_ratio":round(current_volume/mean_vol,6) if mean_vol>0 else None,
        "retest_delay_m15_bars":ri-bi,
        "retest_depth_atr":round(sg*(level-retest_extreme)/atr,6),
        "confirm_delay_m15_bars":ci-ri,
        "risk_atr":round(risk/atr,6),
        "risk_pct":round(100*risk/entry,6),
        "tp3_r":round(sg*(float(signal["targets"][2]["p"])-entry)/risk,6) if len(signal.get("targets",[]))>=3 else None,
        "limitations":["NO_HTF_BOS_CHOCH","NO_FVG_ORDER_BLOCK","NO_WYCKOFF_PHASE",
                       "NO_LIQUIDITY_MAP","NO_AUTHOR_THRESHOLD_VERIFICATION"],
    }
