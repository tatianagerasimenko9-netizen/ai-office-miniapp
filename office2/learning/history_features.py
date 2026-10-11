"""Ознаки угоди ЛИШЕ зі свічок до моменту рішення (без майбутнього): для старих планів Лева/Office, де знімка Brain немає.
Все, що не обчислюється (мало історії) → "UNKNOWN" (не вигадуємо). Вхід — масиви {t,o,h,l,c,v} (t — секунди відкриття 15m)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np

FEATURES = ("dir", "tf", "session", "weekend", "stop_class", "rr1_class", "trend_h4", "trend_d1", "pd_24h", "chase_4h", "btc_h4", "vol_regime", "near_pdh_pdl", "rej")


def _bucket(x: Optional[float], cuts, names) -> str:
    if x is None:
        return "UNKNOWN"
    for c, n in zip(cuts, names):
        if x < c:
            return n
    return names[-1]


def _upto(a: Dict[str, Any], ts: float) -> int:
    """Індекс (виключно) першого 15m-бару, що ще не закритий на ts → усі бари [0:i] закриті."""
    return int(np.searchsorted(a["t"] + 900, ts, side="right"))


def _trend(c: np.ndarray, fast: int, slow: int) -> str:
    if len(c) < slow + 1:
        return "UNKNOWN"
    f, s = float(np.mean(c[-fast:])), float(np.mean(c[-slow:]))
    return "UP" if f > s * 1.002 else ("DOWN" if f < s * 0.998 else "FLAT")


def _h4_closes(a: Dict[str, Any], i: int, n: int = 40) -> np.ndarray:
    t, c = a["t"][:i], a["c"][:i]
    if len(t) < 16:
        return np.array([])
    blk = (t // 14400).astype(int)
    last = {}
    for k, b in enumerate(blk):
        last[b] = k
    keys = sorted(last)[:-1][-n:]          # без останнього (незавершеного) 4h-блоку
    return np.array([c[last[b]] for b in keys])


def session_of(ts: float) -> str:
    h = datetime.fromtimestamp(ts, timezone.utc).hour
    return "ASIA" if h < 7 else ("LONDON" if h < 13 else ("NY" if h < 21 else "LATE"))


def extract(p: Dict[str, Any], a: Dict[str, Any], d1: Optional[Dict[str, Any]], btc: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """p: {dir, tf, entry, sl, tp1, ts, rej}. Повертає ознаки на момент ts."""
    ts, long_ = float(p["ts"]), p["dir"] == "LONG"
    sg = 1.0 if long_ else -1.0
    e, sl, tp1 = float(p["entry"]), float(p["sl"]), float(p["tp1"])
    risk = abs(e - sl)
    i = _upto(a, ts)
    f: Dict[str, str] = {"dir": p["dir"], "tf": str(p.get("tf") or "UNKNOWN"), "session": session_of(ts), "rej": "Y" if p.get("rej") else "N",
                         "weekend": "Y" if datetime.fromtimestamp(ts, timezone.utc).weekday() >= 5 else "N"}
    stop_pct = risk / e * 100.0 if e else None
    f["stop_class"] = _bucket(stop_pct, (0.7, 1.5, 3.0), ("<0.7%", "0.7-1.5%", "1.5-3%", ">3%"))
    f["rr1_class"] = _bucket(abs(tp1 - e) / risk if risk else None, (1.0, 1.5, 2.5), ("<1R", "1-1.5R", "1.5-2.5R", ">2.5R"))
    if i < 100:
        f.update(trend_h4="UNKNOWN", pd_24h="UNKNOWN", chase_4h="UNKNOWN", vol_regime="UNKNOWN", near_pdh_pdl="UNKNOWN")
    else:
        h4 = _h4_closes(a, i)
        tr = _trend(h4, 6, 20)
        f["trend_h4"] = "UNKNOWN" if tr == "UNKNOWN" else ("FLAT" if tr == "FLAT" else ("WITH" if (tr == "UP") == long_ else "AGAINST"))
        hi24, lo24 = float(a["h"][i - 96:i].max()), float(a["l"][i - 96:i].min())
        pos = (e - lo24) / (hi24 - lo24) if hi24 > lo24 else None
        f["pd_24h"] = "UNKNOWN" if pos is None else ("DISCOUNT" if pos < 0.33 else ("PREMIUM" if pos > 0.67 else "MID"))
        mv = (float(a["c"][i - 1]) - float(a["c"][i - 17])) / float(a["c"][i - 17]) * 100.0 * sg      # рух 4 год. у бік угоди
        f["chase_4h"] = _bucket(mv, (-1.5, 1.5), ("COUNTER_MOVE", "NEUTRAL", "CHASING"))
        tr14 = np.maximum(a["h"][i - 14:i] - a["l"][i - 14:i], 1e-12)
        tr96 = np.maximum(a["h"][i - 96:i] - a["l"][i - 96:i], 1e-12)
        r = float(tr14.mean() / tr96.mean())
        f["vol_regime"] = _bucket(r, (0.8, 1.3), ("LOW", "NORMAL", "HIGH"))
        near = "N"
        if d1 is not None and len(d1["t"]):
            day0 = int(ts // 86400) * 86400
            k = int(np.searchsorted(d1["t"], day0, side="left"))
            if k >= 1:
                pdh, pdl = float(d1["h"][k - 1]), float(d1["l"][k - 1])
                tgt = pdh if long_ else pdl
                near = "Y" if abs(tgt - e) / e * 100.0 < 0.5 or (0 < (tgt - e) * sg < 1.0 * risk) else "N"
            else:
                near = "UNKNOWN"
        f["near_pdh_pdl"] = near
    if d1 is not None and len(d1["t"]):
        day0 = int(ts // 86400) * 86400
        k = int(np.searchsorted(d1["t"], day0, side="left"))
        tr = _trend(d1["c"][:k], 5, 20) if k >= 21 else "UNKNOWN"
        f["trend_d1"] = "UNKNOWN" if tr == "UNKNOWN" else ("FLAT" if tr == "FLAT" else ("WITH" if (tr == "UP") == long_ else "AGAINST"))
    else:
        f["trend_d1"] = "UNKNOWN"
    if btc is not None:
        j = _upto(btc, ts)
        tb = _trend(_h4_closes(btc, j), 6, 20) if j >= 100 else "UNKNOWN"
        f["btc_h4"] = "UNKNOWN" if tb == "UNKNOWN" else ("FLAT" if tb == "FLAT" else ("WITH" if (tb == "UP") == long_ else "AGAINST"))
    else:
        f["btc_h4"] = "UNKNOWN"
    return f
