"""Ознаки з 1m-масивів без lookahead. Масив 1m: dict з numpy-масивами t (с, відкриття хвилини), o,h,l,c,v,tbv (taker buy base volume)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

Arr = Dict[str, np.ndarray]
DAY = 86400
WEEK_OFFSET = 4 * DAY   # epoch = четвер; понеділок 00:00 UTC = epoch + 4 дні


def resample(a: Arr, width: int, offset: int = 0) -> Arr:
    """1m → бари шириною width сек. Бар позначений часом ВІДКРИТТЯ; закритий, коли t_open + width ≤ now."""
    t = a["t"]
    g = ((t - offset) // width).astype(np.int64)
    cut = np.flatnonzero(np.diff(g)) + 1
    starts = np.r_[0, cut]
    ends = np.r_[cut - 1, len(t) - 1]
    return {
        "t": (g[starts] * width + offset).astype(np.float64),
        "o": a["o"][starts], "h": np.maximum.reduceat(a["h"], starts), "l": np.minimum.reduceat(a["l"], starts), "c": a["c"][ends],
        "v": np.add.reduceat(a["v"], starts), "tbv": np.add.reduceat(a["tbv"], starts),
        "n": np.diff(np.r_[starts, len(t)]).astype(np.float64),
    }


def last_closed(bars: Arr, width: int, now: float) -> int:
    """Індекс останнього бару, закритого до моменту now (open+width ≤ now); -1 якщо немає."""
    return int(np.searchsorted(bars["t"] + width, now, side="right")) - 1


def atr(bars: Arr, n: int = 14) -> np.ndarray:
    """SMA(TR, n); значення на барі i використовує лише бари ≤ i."""
    h, l, c = bars["h"], bars["l"], bars["c"]
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out = np.full(len(tr), np.nan)
    if len(tr) >= n:
        cs = np.cumsum(tr)
        out[n - 1:] = (cs[n - 1:] - np.r_[0.0, cs[:-n]]) / n
    return out


def swings(bars: Arr, n: int = 2) -> Tuple[List[Tuple[int, int, float]], List[Tuple[int, int, float]]]:
    """Фрактали n: [(індекс_бару, індекс_бару_підтвердження = i+n, ціна)] для highs і lows. Підтверджені лише після закриття бару i+n."""
    h, l = bars["h"], bars["l"]
    sh: List[Tuple[int, int, float]] = []
    sl: List[Tuple[int, int, float]] = []
    for i in range(n, len(h) - n):
        if h[i] > h[i - n:i].max() and h[i] > h[i + 1:i + n + 1].max():
            sh.append((i, i + n, float(h[i])))
        if l[i] < l[i - n:i].min() and l[i] < l[i + 1:i + n + 1].min():
            sl.append((i, i + n, float(l[i])))
    return sh, sl


def regime_by_bar(bars: Arr, n: int = 2) -> np.ndarray:
    """Режим ПІСЛЯ закриття кожного бару: +1 (HH+HL), -1 (LH+LL), 0 (діапазон/недостатньо даних). Лише підтверджені фрактали."""
    sh, sl = swings(bars, n)
    k = len(bars["t"])
    reg = np.zeros(k, dtype=np.int8)
    ih = il = 0
    hs: List[float] = []
    ls: List[float] = []
    for j in range(k):
        while ih < len(sh) and sh[ih][1] <= j:
            hs.append(sh[ih][2])
            ih += 1
        while il < len(sl) and sl[il][1] <= j:
            ls.append(sl[il][2])
            il += 1
        if len(hs) >= 2 and len(ls) >= 2:
            if hs[-1] > hs[-2] and ls[-1] > ls[-2]:
                reg[j] = 1
            elif hs[-1] < hs[-2] and ls[-1] < ls[-2]:
                reg[j] = -1
    return reg


def build_levels(h4: Arr, d1: Arr, w1: Arr, eq_tol: float = 0.0015) -> List[dict]:
    """Ключові рівні ліквідності з моментом, коли вони стали ВІДОМІ (known_from, сек). side: 'high' (BSL над ціною) або 'low' (SSL під ціною).
    kind: H4SW (фрактал H4), D1SW (фрактал D1), PDH/PDL (попередня доба), PWH/PWL (попередній тиждень). strength = 1 + число ПОПЕРЕДНІХ рівнів тієї ж сторони в межах eq_tol (EQH/EQL)."""
    out: List[dict] = []
    for bars, width, kind, n in ((h4, 4 * 3600, "H4SW", 2), (d1, DAY, "D1SW", 2)):
        sh, sl = swings(bars, n)
        for i, ki, p in sh:
            out.append({"p": p, "side": "high", "kind": kind, "known": float(bars["t"][ki] + width)})
        for i, ki, p in sl:
            out.append({"p": p, "side": "low", "kind": kind, "known": float(bars["t"][ki] + width)})
    for bars, width, kh, kl in ((d1, DAY, "PDH", "PDL"), (w1, 7 * DAY, "PWH", "PWL")):
        for i in range(len(bars["t"])):
            known = float(bars["t"][i] + width)
            out.append({"p": float(bars["h"][i]), "side": "high", "kind": kh, "known": known})
            out.append({"p": float(bars["l"][i]), "side": "low", "kind": kl, "known": known})
    out.sort(key=lambda x: x["known"])
    seen: Dict[str, List[float]] = {"high": [], "low": []}
    for lv in out:
        lv["strength"] = 1 + sum(1 for q in seen[lv["side"]] if abs(q - lv["p"]) / lv["p"] <= eq_tol)
        seen[lv["side"]].append(lv["p"])
    return out


def flow_delta(bars: Arr, i: int) -> float:
    """Taker-дельта бару: покупці − продавці (2·tbv − v). >0 агресивні покупці, <0 агресивні продавці."""
    return float(2.0 * bars["tbv"][i] - bars["v"][i])
