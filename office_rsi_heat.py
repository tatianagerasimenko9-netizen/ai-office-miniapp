"""RSI-перегрів H1/H4. В індикаторі PUMP/DUMP цього немає — окреме правило офісу."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


RSI_LONG_HOT = 85.0
RSI_LONG_EXTREME = 92.0
RSI_SHORT_HOT = 15.0
RSI_SHORT_EXTREME = 8.0
RSI_PERIOD = 14


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def rsi_wilder(closes: List[float], period: int = RSI_PERIOD) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    if len(gains) < period:
        return None
    avg_g = sum(gains[:period]) / float(period)
    avg_l = sum(losses[:period]) / float(period)
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / float(period)
        avg_l = (avg_l * (period - 1) + losses[i]) / float(period)
    if avg_l <= 1e-18:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def rsi_from_candles(candles: Any, period: int = RSI_PERIOD) -> Optional[float]:
    if not isinstance(candles, list):
        return None
    closes: List[float] = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        v = _f(c.get("close"))
        if v is not None:
            closes.append(v)
    return rsi_wilder(closes, period)


def rsi_heat(
    *,
    direction: str,
    rsi_h1: Any,
    rsi_h4: Any = None,
    in_position: bool = False,
    exhaustion: bool = False,
) -> Dict[str, Any]:
    """≥85 заборона LONG по ринку; ≥92 — фіксуй частину. Дзеркало 15/8."""
    side = str(direction or "").upper()
    vals = [x for x in (_f(rsi_h1), _f(rsi_h4)) if x is not None]
    peak = max(vals) if vals else None
    floor = min(vals) if vals else None
    out: Dict[str, Any] = {
        "peak": peak,
        "floor": floor,
        "allow_market": True,
        "pullback_only": False,
        "fix_partial": False,
        "dump_candidate": False,
        "pump_candidate": False,
        "message": "",
        "kind": "",
    }
    if side == "LONG":
        if peak is not None and peak >= RSI_LONG_HOT:
            out["allow_market"] = False
            out["pullback_only"] = True
            out["kind"] = "RSI_HOT"
            out["message"] = f"RSI {peak:.1f} ≥ {RSI_LONG_HOT:.0f} — LONG по ринку ні, лише відкат у зону"
        if in_position and peak is not None and peak >= RSI_LONG_EXTREME:
            out["fix_partial"] = True
            out["kind"] = "RSI_EXTREME"
            out["message"] = (
                f"RSI {peak:.1f} ≥ {RSI_LONG_EXTREME:.0f} — фіксуй частину, підтягни стоп"
            )
            if exhaustion:
                out["dump_candidate"] = True
                out["message"] += " · свічка виснаження → кандидат DUMP"
    elif side == "SHORT":
        if floor is not None and floor <= RSI_SHORT_HOT:
            out["allow_market"] = False
            out["pullback_only"] = True
            out["kind"] = "RSI_HOT"
            out["message"] = f"RSI {floor:.1f} ≤ {RSI_SHORT_HOT:.0f} — SHORT по ринку ні, лише відкат у зону"
        if in_position and floor is not None and floor <= RSI_SHORT_EXTREME:
            out["fix_partial"] = True
            out["kind"] = "RSI_EXTREME"
            out["message"] = (
                f"RSI {floor:.1f} ≤ {RSI_SHORT_EXTREME:.0f} — фіксуй частину, підтягни стоп"
            )
            if exhaustion:
                out["pump_candidate"] = True
                out["message"] += " · свічка виснаження → кандидат PUMP"
    return out


def exhaustion_candle(candle: Any, *, side: str) -> bool:
    """Велика свічка виснаження: тіло >1.5% проти позиції або довгий ґніт."""
    if not isinstance(candle, dict):
        return False
    o, h, l, c = _f(candle.get("open")), _f(candle.get("high")), _f(candle.get("low")), _f(candle.get("close"))
    if None in (o, h, l, c) or o == 0:
        return False
    d = str(side or "").upper()
    if d == "LONG":
        big = c > o and (c - o) / o > 0.015
        wick = (h - c) > (c - l) * 1.5
        return bool(big or wick)
    if d == "SHORT":
        big = c < o and (o - c) / o > 0.015
        wick = (o - l) > (h - c) * 1.5
        return bool(big or wick)
    return False
