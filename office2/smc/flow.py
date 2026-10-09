"""Order Flow / HRLR / LRLR — СТРУКТУРНИЙ proxy (S16, S17): напрямок «доставки» за структурою і повагою FVG; опір шляху — за ефективністю ходу й кількістю перешкод.
Біржових агресорів, дельти, DOM методичка не дає і тут не імітується: коли ці дані є (CVD/OI/DOM) — вони йдуть окремим доказом Brain, не сюди."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from office2.smc import core as K
from office2.smc.core import Arr


def order_flow(structure: Dict[str, Any], fvgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Висхідний flow = структура UP (або TRANSITION→UP) + остання бичача FVG не зламана тілом; низхідний — дзеркально. Інакше NEUTRAL."""
    tr = structure.get("trend")
    want = "LONG" if tr == "UP" or (tr == "TRANSITION" and (structure.get("transition") or {}).get("to") == "UP") else "SHORT" if tr in ("DOWN",) or (tr == "TRANSITION" and (structure.get("transition") or {}).get("to") == "DOWN") else None
    if not want:
        return {"state": "NEUTRAL", "proxy": True}
    mine = [f for f in fvgs if f["dir"] == want][-3:]
    alive = [f for f in mine if f["state"] != "BROKEN"]
    state = ("BULL_FLOW" if want == "LONG" else "BEAR_FLOW") if alive else "WEAK_" + ("BULL" if want == "LONG" else "BEAR")
    return {"state": state, "dir": want, "fvg_alive": len(alive), "fvg_total": len(mine), "proxy": True}


def path_resistance(b: Arr, i0: int, i1: int, a: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """HRLR/LRLR для відрізка [i0, i1]: ефективність ER=|чистий рух|/сума |Δclose| і кількість розворотів ≥ 0,5 ATR (перешкоди)."""
    seg = b["c"][i0:i1 + 1]
    if len(seg) < 3:
        return {"label": "UNKNOWN", "er": None, "reversals": 0, "proxy": True}
    d = np.abs(np.diff(seg))
    er = float(abs(seg[-1] - seg[0]) / d.sum()) if d.sum() > 0 else 0.0
    ia = K.atr_at(a if a is not None else K.atr_arr(b, 14), i1)
    rev = 0
    last_ext = seg[0]
    direction = 0
    for x in seg[1:]:
        if direction >= 0 and x < last_ext - 0.5 * ia:
            if direction == 1:
                rev += 1
            direction, last_ext = -1, x
        elif direction <= 0 and x > last_ext + 0.5 * ia:
            if direction == -1:
                rev += 1
            direction, last_ext = 1, x
        elif (direction == 1 and x > last_ext) or (direction == -1 and x < last_ext) or direction == 0:
            last_ext = x if direction != 0 else last_ext
    label = "LRLR" if er >= 0.45 and rev <= 1 else ("HRLR" if er <= 0.25 or rev >= 3 else "MIXED")
    return {"label": label, "er": round(er, 3), "reversals": int(rev), "proxy": True}
