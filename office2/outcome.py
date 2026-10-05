"""Outcome-мітки (лише майбутнє; ніколи не features). Єдина функція для N2 і наступних досліджень.
Порядок руху (+k·R раніше −1R, стоп у ту саму хвилину — раніше), MFE/MAE у R, ATR і %, інвалідація, час до MFE/MAE, еталонна геометрія G2 (TP +2R / SL −1R) з комісією і slippage."""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

HORIZONS_H = (1, 4, 12, 24, 48)
ORDER_K = (0.5, 1.0, 1.5, 2.0)
FEE_RT_PCT = 0.10        # комісія кола, % (taker×2)
SLIP_RT_PCT = 0.05       # slippage кола, % (припущення; окремо від комісії)


def outcome_record(m1: Dict[str, np.ndarray], i0: int, direction: str, entry: float, sl: float, atr: float, horizon_sec: int = 48 * 3600,
                   fee_pct: float = FEE_RT_PCT, slip_pct: float = SLIP_RT_PCT) -> Optional[Dict[str, Any]]:
    sg = 1.0 if direction == "LONG" else -1.0
    risk = sg * (entry - sl)
    if risk <= 0 or atr <= 0 or entry <= 0:
        return None
    t = m1["t"]
    i1 = int(np.searchsorted(t, t[i0] + horizon_sec, side="right"))
    if i1 - i0 < 60:
        return None
    h, l, c = m1["h"][i0:i1], m1["l"][i0:i1], m1["c"][i0:i1]
    fav = (h - entry) if sg > 0 else (entry - l)
    adv = (entry - l) if sg > 0 else (h - entry)
    cf, ca = np.maximum.accumulate(fav), np.maximum.accumulate(adv)
    risk_pct = risk / entry * 100.0
    rec: Dict[str, Any] = {"risk": float(risk), "risk_pct": float(risk_pct), "risk_atr": float(risk / atr), "complete": bool(i1 - i0 >= horizon_sec / 60 * 0.98)}
    for hh in HORIZONS_H:
        k = min(hh * 60, len(h)) - 1
        rec[f"mfe_r_{hh}"], rec[f"mae_r_{hh}"] = float(cf[k] / risk), float(ca[k] / risk)
        rec[f"mfe_atr_{hh}"], rec[f"mae_atr_{hh}"] = float(cf[k] / atr), float(ca[k] / atr)
        rec[f"mfe_pct_{hh}"], rec[f"mae_pct_{hh}"] = float(cf[k] / entry * 100.0), float(ca[k] / entry * 100.0)
    hit_sl = adv >= risk
    k_inv = int(np.argmax(hit_sl)) if hit_sl.any() else -1
    rec["inval_min"] = k_inv if k_inv >= 0 else None
    rec["mfe_to_inval_r"] = float(cf[-1] / risk) if k_inv < 0 else (0.0 if k_inv == 0 else float(cf[k_inv - 1] / risk))
    for kr in ORDER_K:
        hit_up = fav >= kr * risk
        ku = int(np.argmax(hit_up)) if hit_up.any() else -1
        rec[f"order_{kr}"] = "none" if (ku < 0 and k_inv < 0) else ("up" if (ku >= 0 and (k_inv < 0 or ku < k_inv)) else "down")
    rec["t_mfe_min"], rec["t_mae_min"] = int(np.argmax(fav)), int(np.argmax(adv))
    # еталонна геометрія G2: TP +2R / SL −1R / інакше mark-to-market на кінець горизонту
    if rec["order_2.0"] == "up":
        rg, tag = 2.0, "TP"
    elif rec["order_2.0"] == "down":
        rg, tag = -1.0, "SL"
    else:
        rg, tag = float(sg * (c[-1] - entry) / risk), "TO"
    rec["g2_outcome"] = tag
    rec["r_gross_g2"] = float(rg)
    rec["r_net_g2"] = float(rg - (fee_pct + slip_pct) / max(risk_pct, 1e-9))
    return rec
