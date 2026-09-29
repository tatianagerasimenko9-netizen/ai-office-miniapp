"""Режим ринку з OHLCV: TREND / RANGE / TRANSITION / COMPRESSION / EXPANSION / UNKNOWN.

Лише інформація для тези Лева й екрана. Рішень SEND/WAIT не змінює, ризикових
порогів (ATR 80/90, Edge 85, RR 1.5, TP1) не торкається.

Правила v1 (евристика, потребує перевірки на історії — не статистично каліброване):
- волатильність: ATR(14) останньої свічки / медіана ATR(14) за всі доступні свічки.
  > EXPANSION_RATIO → EXPANSION, < COMPRESSION_RATIO → COMPRESSION;
- напрямок: efficiency ratio за ER_WINDOW свічок = |Δclose| / Σ|Δclose_i|.
  ≥ TREND_ER і структура HH/HL (або LL/LH) → TREND; ≤ RANGE_ER → RANGE; інакше TRANSITION;
- менше MIN_BARS свічок або дірки в даних → UNKNOWN (DATA_UNAVAILABLE), не вгадуємо.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, List, Optional

VERSION = "regime-v1"
ATR_N = 14
ER_WINDOW = 30
MIN_BARS = ER_WINDOW + ATR_N + 1  # 45: вистачає 48 H1 або 96 M15, які relay вже завантажує
TREND_ER = 0.35
RANGE_ER = 0.20
EXPANSION_RATIO = 1.6
COMPRESSION_RATIO = 0.6


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def _clean(candles: Any) -> List[Dict[str, float]]:
    out = []
    for c in candles or []:
        if not isinstance(c, dict):
            return []
        h, l, cl = _f(c.get("high")), _f(c.get("low")), _f(c.get("close"))
        if h is None or l is None or cl is None or h < l:
            return []
        out.append({"high": h, "low": l, "close": cl, "ts": c.get("ts")})
    return out


def _atr_series(bars: List[Dict[str, float]], n: int = ATR_N) -> List[float]:
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return [sum(trs[i - n + 1:i + 1]) / n for i in range(n - 1, len(trs))]


def _structure(bars: List[Dict[str, float]]) -> str:
    """Порівняння двох половин вікна: вищі максимуми й мінімуми / нижчі."""
    half = len(bars) // 2
    a, b = bars[:half], bars[half:]
    ha, hb = max(x["high"] for x in a), max(x["high"] for x in b)
    la, lb = min(x["low"] for x in a), min(x["low"] for x in b)
    if hb > ha and lb > la:
        return "UP"
    if hb < ha and lb < la:
        return "DOWN"
    return "MIXED"


def classify_regime(candles: Any, *, timeframe: str = "H1") -> Dict[str, Any]:
    bars = _clean(candles)
    base = {"version": VERSION, "timeframe": timeframe, "order_authorized": False}
    if len(bars) < MIN_BARS:
        return {**base, "regime": "UNKNOWN", "data_status": "DATA_UNAVAILABLE",
                "reason": f"потрібно ≥{MIN_BARS} свічок {timeframe}, є {len(bars)}", "evidence": []}
    atr = _atr_series(bars)
    med = median(atr)
    ratio = atr[-1] / med if med > 0 else None
    win = bars[-(ER_WINDOW + 1):]
    moves = sum(abs(win[i]["close"] - win[i - 1]["close"]) for i in range(1, len(win)))
    er = abs(win[-1]["close"] - win[0]["close"]) / moves if moves > 0 else 0.0
    struct = _structure(bars[-ER_WINDOW:])
    direction = "UP" if win[-1]["close"] > win[0]["close"] else "DOWN"
    if ratio is not None and ratio > EXPANSION_RATIO:
        regime = "EXPANSION"
    elif ratio is not None and ratio < COMPRESSION_RATIO:
        regime = "COMPRESSION"
    elif er >= TREND_ER and struct == direction:
        regime = "TREND"
    elif er <= RANGE_ER:
        regime = "RANGE"
    else:
        regime = "TRANSITION"
    return {
        **base,
        "regime": regime,
        "data_status": "DATA_OK",
        "direction": direction if regime == "TREND" else None,
        "atr_ratio": None if ratio is None else round(ratio, 3),
        "efficiency_ratio": round(er, 3),
        "structure": struct,
        "as_of": bars[-1].get("ts"),
        "reason": (
            f"ER {er:.2f} за {ER_WINDOW} св., ATR/медіана {ratio:.2f}, структура {struct}"
            if ratio is not None else f"ER {er:.2f}, структура {struct}"
        ),
        "evidence": [f"{timeframe}: ER={er:.2f}", f"{timeframe}: ATR ratio={ratio:.2f}" if ratio else f"{timeframe}: ATR ratio n/a",
                     f"{timeframe}: структура {struct}"],
    }
