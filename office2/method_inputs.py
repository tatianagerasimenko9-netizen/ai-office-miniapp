"""Single assembly point of methodology inputs from a decision context (SHADOW only).

Used by the live engine and by the historical replay, so both evaluate the same rules on the
same inputs. Closed candles only (ctx arrays are already cut to bars closed before `now`).
Never places orders and never alters READY / risk / LIVE gates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


def _bars(arr: Optional[Mapping[str, Any]], keys=("o", "h", "l", "c", "v")) -> Optional[List[Dict[str, float]]]:
    if not isinstance(arr, Mapping) or not all(k in arr for k in keys):
        return None
    n = min(len(arr[k]) for k in keys)
    return [{"open": float(arr["o"][i]), "high": float(arr["h"][i]), "low": float(arr["l"][i]),
             "close": float(arr["c"][i]), "volume": float(arr["v"][i])} for i in range(n)]


def _closed(arr: Optional[Mapping[str, Any]], width: float, now: float) -> Optional[Dict[str, Any]]:
    """Slice every array to bars whose close time (open + width) is <= now: no forming and no future bar."""
    if not isinstance(arr, Mapping) or "t" not in arr:
        return None
    n = sum(1 for t in arr["t"] if float(t) + width <= now) if len(arr["t"]) < 64 else _count_closed(arr["t"], width, now)
    return {k: v[:n] for k, v in arr.items() if hasattr(v, "__len__") and len(v) == len(arr["t"])}


def _count_closed(t, width: float, now: float) -> int:
    lo, hi = 0, len(t)
    while lo < hi:                      # bars are chronological: binary search for the first not-yet-closed bar
        mid = (lo + hi) // 2
        if float(t[mid]) + width <= now:
            lo = mid + 1
        else:
            hi = mid
    return lo


def build_inputs(ctx: Mapping[str, Any], now: float, plan_th: Optional[Mapping[str, Any]] = None, *,
                 equity_usd: Optional[float] = None, journal: Optional[Mapping[str, Any]] = None,
                 news_state: Optional[str] = None, smc_res: Optional[Mapping[str, Any]] = None,
                 topdown: Optional[Mapping[str, Any]] = None, rules: Optional[List[Mapping[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    from office2 import method_context_features as MC
    from office2 import method_plan_features as MP
    from office2.method_closed_bar_features import from_closed_bars

    out: Dict[str, Dict[str, Any]] = {}
    m15 = _closed(ctx.get("m15"), 900.0, now)
    asof = float(m15["t"][-1]) if m15 is not None and len(m15["t"]) else None
    ranges = None
    d1 = _closed(ctx.get("d1"), 86400.0, now)
    if isinstance(d1, Mapping) and all(k in d1 for k in ("h", "l")):
        n = min(len(d1["h"]), len(d1["l"]))
        daily = [{"high": float(d1["h"][i]), "low": float(d1["l"][i])} for i in range(n)]
        if n >= 4:
            last = daily[max(0, n - 5):n]
            if all(b["high"] > b["low"] for b in last):
                ranges = [b["high"] - b["low"] for b in last]
                out["G-ATR-CALC"] = {"previous_ranges": ranges,
                                     "_provenance": MC._prov("closed D1 bars (last 3-5 closed days)", "SOURCE", asof)}
    closed = _bars(m15)
    if closed:
        day_start = (float(m15["t"][-1]) // 86400) * 86400
        day_bars = [closed[i] for i in range(len(closed)) if float(m15["t"][i]) >= day_start]
        feats = from_closed_bars(closed, len(closed) - 1, daily_ranges=ranges, day_bars=day_bars or None)
        for rid, vals in feats.items():
            out[rid] = dict(vals, _provenance=MC._prov("closed M15 bars (office2.method_closed_bar_features)", "SOURCE", asof))
    if d1 is not None:
        out.update(MC.d1_base_after_impulse(d1, asof))
    atr = MP.daily_atr_from_ranges(ranges) if ranges else None
    j = journal or {}
    out.update(MP.from_thesis(plan_th, daily_atr=atr, equity_usd=equity_usd, closed_trades=j.get("closed_trades"),
                              daily_loss_usd=j.get("daily_loss_usd"), asof_bar_ts=asof))
    out.update(MC.session_news(now, news_state))
    if plan_th is not None:
        out.update(MC.from_topdown(topdown, asof))
        out.update(MC.from_smc(smc_res, str(plan_th.get("dir")), asof))
    if rules:
        out.update(MC.scope_resolution(list(rules)))
    return out
