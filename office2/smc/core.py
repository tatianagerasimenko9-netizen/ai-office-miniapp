"""SMC: спільне ядро. Лише закриті бари, жодного lookahead; усі детектори — чисті функції від масивів {t,o,h,l,c[,v]} (t — час ВІДКРИТТЯ бару, с).

Дзеркало: SHORT аналізується як LONG на дзеркальних барах (ціна → −ціна, high ↔ −low) — симетрія LONG/SHORT гарантована конструкцією й перевіряється property-тестом.
Тип події — Event (схема з Masterplan §3): event_id, symbol, timeframe, source_section_id, detector_version, first_seen_at, confirmed_at, expires_at, candle_open_times, anchor_price,
zone_low/high, confidence_calibration_status, state, evidence_for/against, invalidation_rule."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

Arr = Dict[str, np.ndarray]
DETECTOR_VERSION = "smc-1.0"
TF_SEC = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "h1": 3600, "4h": 14400, "h4": 14400, "1d": 86400, "d1": 86400, "1w": 604800, "w1": 604800}


def mirror(b: Arr) -> Arr:
    """Дзеркало цін: SHORT-логіка = LONG-логіка на цьому масиві."""
    out = {"t": b["t"], "o": -b["o"], "h": -b["l"], "l": -b["h"], "c": -b["c"]}
    if "v" in b:
        out["v"] = b["v"]
    return out


def closed_slice(b: Optional[Arr], width: int, now: float) -> Optional[Arr]:
    """Лише бари, закриті до now (t_open + width ≤ now). Повертає копію-зріз; None якщо порожньо."""
    if b is None or len(b["t"]) == 0:
        return None
    n = int(np.searchsorted(b["t"] + width, now, side="right"))
    if n <= 0:
        return None
    return {k: v[:n] for k, v in b.items()}


def atr_arr(b: Arr, n: int = 14) -> np.ndarray:
    """SMA(TR, n); значення на барі i використовує бари ≤ i (NaN поки недостатньо барів)."""
    h, l, c = b["h"], b["l"], b["c"]
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out = np.full(len(tr), np.nan)
    if len(tr) >= n:
        cs = np.cumsum(tr)
        out[n - 1:] = (cs[n - 1:] - np.r_[0.0, cs[:-n]]) / n
    return out


def atr_at(a: np.ndarray, i: int) -> float:
    """Остання скінченна ATR до індексу i включно (щоб не падати на NaN у перших барах)."""
    j = min(i, len(a) - 1)
    while j >= 0 and not np.isfinite(a[j]):
        j -= 1
    return float(a[j]) if j >= 0 else 0.0


def body(b: Arr, i: int) -> float:
    return float(abs(b["c"][i] - b["o"][i]))


def rng(b: Arr, i: int) -> float:
    return float(b["h"][i] - b["l"][i])


def is_bull(b: Arr, i: int) -> bool:
    return bool(b["c"][i] > b["o"][i])


def is_bear(b: Arr, i: int) -> bool:
    return bool(b["c"][i] < b["o"][i])


def eid(kind: str, tf: str, direction: str, times: List[float], extra: str = "") -> str:
    """Детермінований id події: ті самі свічки → той самий id (дедуп і повторюваність replay)."""
    raw = f"{kind}|{tf}|{direction}|{','.join(str(int(t)) for t in times)}|{extra}"
    return kind + ":" + hashlib.sha1(raw.encode()).hexdigest()[:12]


@dataclass
class Event:
    kind: str                       # SWING_H, BMS, MSS, CONFIRM, SWEEP, SFP, FVG, OB, BB, MB, RJB, SC, STB, BTS, RANGE, DEVIATION, ...
    tf: str
    direction: str                  # LONG (бичача подія) | SHORT
    source: str                     # source_section_id із реєстру джерел (office2.smc.sources)
    times: List[float]              # candle_open_times (UTC, с) — точні якорі свічок
    anchors: List[float] = field(default_factory=list)   # anchor_price[]
    zone: Optional[List[float]] = None                   # [low, high]
    confirmed_at: Optional[float] = None                 # момент, коли подія стала відома (закриття бару підтвердження)
    state: str = "ACTIVE"
    expires_at: Optional[float] = None
    evidence_for: List[str] = field(default_factory=list)
    evidence_against: List[str] = field(default_factory=list)
    invalidation: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    symbol: str = ""

    def to_dict(self) -> Dict[str, Any]:
        z = self.zone
        return {
            "event_id": eid(self.kind, self.tf, self.direction, self.times, str(round(self.anchors[0], 8)) if self.anchors else ""),
            "kind": self.kind, "symbol": self.symbol, "market_type": "futures", "timeframe": self.tf, "direction": self.direction,
            "source_section_id": self.source, "detector_version": DETECTOR_VERSION,
            "first_seen_at": self.confirmed_at, "confirmed_at": self.confirmed_at, "expires_at": self.expires_at,
            "candle_open_times": [float(t) for t in self.times], "anchor_price": [float(p) for p in self.anchors],
            "zone_low": float(z[0]) if z else None, "zone_high": float(z[1]) if z else None,
            "confidence_calibration_status": "uncalibrated", "state": self.state,
            "evidence_for": list(self.evidence_for), "evidence_against": list(self.evidence_against),
            "invalidation_rule": self.invalidation, "extra": self.extra,
        }


def unmirror_price(p: Optional[float], sg: int) -> Optional[float]:
    return None if p is None else float(sg * p)


def unmirror_zone(z: Optional[List[float]], sg: int) -> Optional[List[float]]:
    if z is None:
        return None
    a, b = sg * z[0], sg * z[1]
    return [float(min(a, b)), float(max(a, b))]
