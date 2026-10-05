"""Строгий first-touch на 1m від моменту входу. Стоп раніше цілі в одній хвилині (консервативно, як lifecycle). Горизонт обмежений; після нього — вихід за close."""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from office2 import features as F

FEE_RT_DEFAULT = 0.10   # % кола (taker×2); slippage окремо в evaluate


def first_touch(m1: F.Arr, i0: int, direction: str, entry: float, sl: float, tp: float, horizon_sec: int = 24 * 3600) -> Dict[str, object]:
    """Результат: outcome TP/SL/TO, ttr_sec, r_gross (у ризиках; TP = +tdist/risk, SL = -1, TO = mark-to-market), mfe_r, mae_r."""
    t = m1["t"]
    i1 = int(np.searchsorted(t, t[i0] + horizon_sec, side="right"))
    h, l = m1["h"][i0:i1], m1["l"][i0:i1]
    risk = abs(entry - sl)
    long_ = direction == "LONG"
    hit_sl = (l <= sl) if long_ else (h >= sl)
    hit_tp = (h >= tp) if long_ else (l <= tp)
    isl = int(np.argmax(hit_sl)) if hit_sl.any() else -1
    itp = int(np.argmax(hit_tp)) if hit_tp.any() else -1
    if isl >= 0 and (itp < 0 or isl <= itp):
        k, out, rg = isl, "SL", -1.0
    elif itp >= 0:
        k, out, rg = itp, "TP", abs(tp - entry) / risk
    else:
        k = len(h) - 1
        out = "TO"
        last = float(m1["c"][i0 + k])
        rg = ((last - entry) if long_ else (entry - last)) / risk
    seg_h, seg_l = h[:k + 1], l[:k + 1]
    fav = (seg_h.max() - entry) if long_ else (entry - seg_l.min())
    adv = (entry - seg_l.min()) if long_ else (seg_h.max() - entry)
    return {"outcome": out, "ttr_sec": float(t[i0 + k] - t[i0]), "r_gross": float(rg), "mfe_r": float(fav / risk), "mae_r": float(adv / risk),
            "complete": bool(i1 - i0 >= horizon_sec / 60 * 0.98 or out != "TO")}


def net_r(r_gross: float, risk_pct: float, fee_rt_pct: float = FEE_RT_DEFAULT) -> float:
    """R після комісій: при фіксованому $-ризику витрати кола = fee_rt / risk_pct (у R)."""
    return r_gross - fee_rt_pct / max(risk_pct, 1e-9)
