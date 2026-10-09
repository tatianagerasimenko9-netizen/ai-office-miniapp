"""Один «вигляд» (view) аналізу: усі детектори на масиві b у координатах LONG. SHORT = той самий view на дзеркалі, потім зворотне відображення (engine).
Так симетрія LONG/SHORT гарантована конструкцією."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from office2.smc import blocks as BL
from office2.smc import core as K
from office2.smc import imbalance as IM
from office2.smc import liquidity as LQ
from office2.smc import structure as ST
from office2.smc.core import Arr


def analyze_view(b: Arr, htf: Optional[Dict[str, Optional[Arr]]] = None, swing_n: int = 1, extra_levels: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Повний набір детекторів на закритих барах b (LONG-координати). htf: {'d1','w1','mn'} для PDH/PDL… (у координатах цього view)."""
    a = K.atr_arr(b, 14)
    st = ST.analyze(b, n=swing_n, atr=a)
    hs, ls = st["swings_h"], st["swings_l"]
    N = len(b["t"])
    levels = LQ.swing_levels(b, hs, ls, a)
    if htf:
        levels += LQ.htf_levels(b, htf.get("d1"), htf.get("w1"), htf.get("mn"))
    levels += LQ.range_levels(st.get("range"), N - 1) if st.get("range") else []
    levels += LQ.trendline_levels(hs, ls, N)
    if extra_levels:
        levels += extra_levels
    led = LQ.ledger(b, levels, a)
    sweeps = LQ.sweeps_of(led)
    sw_long = [s for s in sweeps if s["dir"] == "LONG"]       # прокол SSL → бичачий розворот
    sw_short = [s for s in sweeps if s["dir"] == "SHORT"]
    fv = IM.fvgs(b, a)
    fv_short = [f for f in fv if f["dir"] == "SHORT"]
    fv_long = [f for f in fv if f["dir"] == "LONG"]
    # дзеркальний view потрібен для пропозицій (supply OB) у координатах цього view
    m = K.mirror(b)
    obs_demand = BL.order_blocks_bull(b, a, sw_long, fv_long)
    obs_supply = BL.unmirror_events(BL.order_blocks_bull(m, a, [dict(s, dir="LONG") for s in sw_short], [dict(f, dir="LONG") for f in fv_short]))
    breakers = BL.breakers_bull(b, a, obs_supply, sw_long, st["events"], fv_long)
    rjb = BL.rejection_blocks_bull(b, a, sw_long)
    sc = BL.sponsored_bull(b, a, obs_demand, sw_long)
    stb = BL.stb_bull(b, a, sw_long, st["events"], obs_demand)
    return {"atr": a, "structure": st, "levels": led, "sweeps": sweeps, "fvg": fv, "vi": IM.volume_imbalances(b, a), "void": IM.liquidity_voids(b, a), "gap": IM.opening_gaps(b, a), "bpr": IM.bprs(fv),
            "ob_demand": obs_demand, "ob_supply": obs_supply, "breaker": breakers, "rjb": rjb, "sc": sc, "stb": stb}
