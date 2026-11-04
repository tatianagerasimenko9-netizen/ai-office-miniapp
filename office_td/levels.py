"""TD-V1 · рівні зі свічок для ТИХОЇ позначки «рівень біля стопа» (ГІПОТЕЗА; у сигнал/стоп/ціль не втручається).
Рівні: вчорашній і минулотижневий high/low (UTC; тиждень пн-нд), 4-годинні свінг-піки (3 бари з кожного боку, підтверджені, останні 60 барів H4).
Визначення збігається з docs/handoff/br-profitability/strategy_search/magnets.py."""
from __future__ import annotations

from typing import List

import numpy as np

DAY = 86400


def levels_from_h1(t, h, l, te: float) -> List[float]:
    """t/h/l — масиви ЗАКРИТИХ H1-барів (epoch сек, open_time). te — момент, на який беремо рівні."""
    t = np.asarray(t, float); h = np.asarray(h, float); l = np.asarray(l, float); out: List[float] = []
    if len(t) < 24 * 8: return out
    day = (t // DAY) * DAY; wk = (t + 3 * DAY) // (7 * DAY) * (7 * DAY) - 3 * DAY
    d0 = (te // DAY) * DAY - DAY; w0 = ((te + 3 * DAY) // (7 * DAY) * (7 * DAY) - 3 * DAY) - 7 * DAY
    for key, k0 in ((day, d0), (wk, w0)):
        m = key == k0
        if m.any(): out += [float(h[m].max()), float(l[m].min())]
    k4 = (t // 14400) * 14400; ks = np.unique(k4)
    hh = []; ll = []; kk = []
    for k in ks:
        m = k4 == k
        if m.sum() < 4: continue                       # неповний H4
        hh.append(float(h[m].max())); ll.append(float(l[m].min())); kk.append(float(k))
    n = len(kk)
    for i in range(3, n - 3):
        conf = kk[i + 3] + 14400                       # підтвердження після закриття 3-го бару праворуч
        if conf > te or conf <= te - 60 * 14400: continue
        if hh[i] == max(hh[i - 3:i + 4]): out.append(hh[i])
        if ll[i] == min(ll[i - 3:i + 4]): out.append(ll[i])
    return out


def stop_tag(levels: List[float], side: int, ent: float, sl: float) -> str:
    """BETWEEN — рівень між входом і стопом; BEYOND — рівень одразу за стопом (до 0,5 ризику) і нічого між; NONE — рівнів біля стопа немає."""
    risk = abs(ent - sl)
    if risk <= 0 or not levels: return "NONE"
    zone = any(0.05 * risk < (ent - p) * side < risk for p in levels)
    if zone: return "BETWEEN"
    guard = any(risk <= (ent - p) * side <= 1.5 * risk for p in levels)
    return "BEYOND" if guard else "NONE"
