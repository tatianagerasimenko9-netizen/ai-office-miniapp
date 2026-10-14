"""Симуляція результату B&R-сигналу на наступних барах (market-вхід на open наступного бару після підтвердження). Витрати як у решті replay: комісія 0,10% кола + прослизання 5 б.п. кола.
SL перед ціллю в одному барі. Вихід: TP1 (повністю) або SL; таймаут → mark-to-market. Це НЕ та сама модель виходу, що в replay Brain — порівняння з Brain наближене."""
from __future__ import annotations

from typing import Any, Dict, Sequence

FEE_RT = 0.0010
SLIP_RT = 0.0005
HORIZON_BARS = 288      # 72 год M15


def simulate(sig: Dict[str, Any], t: Sequence[float], o, h, l, c, horizon: int = HORIZON_BARS) -> Dict[str, Any]:
    sg = 1 if sig["direction"] == "LONG" else -1
    i0 = sig["confirm_i"] + 1
    if i0 >= len(c):
        return {"status": "PENDING", "r_net": None}
    entry = float(o[i0])
    sl, tp1 = sig["sl"], sig["targets"][0]["p"]
    risk = abs(entry - sl)
    if risk <= 0 or sg * (entry - sl) <= 0 or sg * (tp1 - entry) <= 0:
        return {"status": "INVALID", "r_net": None}
    cost = (FEE_RT + SLIP_RT) * entry
    end = min(len(c), i0 + horizon)
    for j in range(i0, end):
        hit_sl = (l[j] <= sl) if sg > 0 else (h[j] >= sl)
        hit_tp = (h[j] >= tp1) if sg > 0 else (l[j] <= tp1)
        if hit_sl:
            return {"status": "SL", "r_net": (-risk - cost) / risk, "exit_i": j, "entry": entry}
        if hit_tp:
            return {"status": "TP1", "r_net": (abs(tp1 - entry) - cost) / risk, "exit_i": j, "entry": entry}
    if end - i0 < horizon:
        return {"status": "OPEN", "r_net": None, "entry": entry}
    last = float(c[end - 1])
    return {"status": "TIMEOUT", "r_net": (sg * (last - entry) - cost) / risk, "exit_i": end - 1, "entry": entry}
