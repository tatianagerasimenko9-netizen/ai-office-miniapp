"""Strong Candle (імпульсна свічка) для Office2.

PROVENANCE: OUR_IMPLEMENTATION. Правило взято з нашого Pine-порту `ict_smc_hunter_v9_9` (office_trade_steer.last_strong_candle): обсяг > 2×SMA(vol,20) і range > 1.2×ATR(14), тіло в бік імпульсу.
Документ «Strong Candle Probability Levels Tester [SYNC & TRADE]» внутрішню формулу сильної свічки НЕ розкриває; з нього взято лише опис: ознаки (обсяг, Volume Delta, ATR-фільтр), «маніпуляція» = дельта протилежна кольору свічки,
Fibonacci-ретрейсмент входу 0–78,6 %, розширення TP 127,2–462 %. Авторську формулу не вигадуємо. Параметри й версія пишуться в decision trace.
Лише ЗАКРИТІ бари. Роль: EVIDENCE (не hard gate: edge не доведено)."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from office2 import features as F

VERSION = "sc-ours-1"
PARAMS = {"vol_sma": 20, "vol_x": 2.0, "atr_period": 14, "range_atr_x": 1.2, "ote": [0.618, 0.786], "ext": [1.272, 1.618, 2.618]}


def _sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def detect(bars: Dict[str, np.ndarray], k: int, lookback: int = 64) -> List[Dict[str, Any]]:
    """Сильні свічки в (k-lookback, k]; кожна з повним набором полів для trace."""
    a = F.atr(bars, PARAMS["atr_period"])
    vs = _sma(bars["v"], PARAMS["vol_sma"])
    out: List[Dict[str, Any]] = []
    for i in range(max(PARAMS["vol_sma"], k - lookback), k + 1):
        if not (np.isfinite(a[i]) and np.isfinite(vs[i])) or a[i] <= 0 or vs[i] <= 0:
            continue
        o, h, l, c, v = (float(bars[x][i]) for x in ("o", "h", "l", "c", "v"))
        rng = h - l
        if v <= vs[i] * PARAMS["vol_x"] or rng <= a[i] * PARAMS["range_atr_x"] or c == o:
            continue
        up = c > o
        tbv = float(bars["tbv"][i]) if "tbv" in bars and np.isfinite(bars["tbv"][i]) else None
        delta = (2.0 * tbv - v) if tbv is not None else None
        out.append({"ts": float(bars["t"][i]), "i": int(i), "direction": "LONG" if up else "SHORT", "open": o, "high": h, "low": l, "close": c, "body": abs(c - o), "range": rng, "atr": float(a[i]),
                    "body_atr": abs(c - o) / float(a[i]), "volume": v, "vol_rel": v / float(vs[i]), "delta": delta, "delta_dir": (None if delta is None else ("LONG" if delta > 0 else "SHORT")),
                    "manipulation": (None if delta is None else bool((delta > 0) != up)),   # за описом документа: дельта протилежна кольору свічки
                    "tf": "M15", "provenance": "OUR_IMPLEMENTATION", "version": VERSION, "params": PARAMS})
    return out


def fib(sc: Dict[str, Any]) -> Dict[str, Any]:
    """Ретрейсмент/розширення від свічки: LONG — ретрейс вниз від high; SHORT — вгору від low. Розширення — від кінця імпульсу."""
    hi, lo = sc["high"], sc["low"]
    span = hi - lo
    if sc["direction"] == "LONG":
        ote = [hi - span * PARAMS["ote"][1], hi - span * PARAMS["ote"][0]]
        ext = [{"level": e, "price": lo + span * e} for e in PARAMS["ext"]]
    else:
        ote = [lo + span * PARAMS["ote"][0], lo + span * PARAMS["ote"][1]]
        ext = [{"level": e, "price": hi - span * e} for e in PARAMS["ext"]]
    return {"ote": ote, "extensions": ext, "anchors": {"high": hi, "low": lo}}


def for_thesis(bars: Dict[str, np.ndarray], k: int, direction: str, since_ts: float, zone: List[float]) -> Dict[str, Any]:
    """Остання сильна свічка за напрямом ТЕЗИ з моменту події: чи є в нозі зміщення, маніпуляція, і чи зона входу перетинає її OTE."""
    cands = [s for s in detect(bars, k) if s["direction"] == direction and s["ts"] >= since_ts - 900 * 8]
    if not cands:
        return {}
    sc = cands[-1]
    fb = fib(sc)
    zl, zh = min(zone), max(zone)
    overlap = not (zh < fb["ote"][0] or zl > fb["ote"][1])
    return {"candle": sc, "fib": fb, "zone_overlaps_ote": bool(overlap)}
