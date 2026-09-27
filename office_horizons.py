"""Горизонти BTC D1/H4/H1. Немає свічок → DATA_UNAVAILABLE. Не в чат."""
from __future__ import annotations

from typing import Any, Dict, Optional


def _close(candles: Any) -> Optional[float]:
    if not isinstance(candles, list) or not candles:
        return None
    try:
        x = float((candles[-1] or {}).get("close"))
    except (TypeError, ValueError):
        return None
    if x != x or x <= 0:
        return None
    return x


def horizon_pack(candles_d1: Any, candles_h4: Any, candles_h1: Any) -> Dict[str, Any]:
    d1, h4, h1 = _close(candles_d1), _close(candles_h4), _close(candles_h1)
    ok = all(v is not None for v in (d1, h4, h1))
    return {
        "ok": ok,
        "status": "OK" if ok else "DATA_UNAVAILABLE",
        "d1": d1,
        "h4": h4,
        "h1": h1,
    }


def fetch_btc_horizons() -> Dict[str, Any]:
    try:
        from office_market_data import fetch_candles
    except Exception as exc:
        return {"ok": False, "status": "DATA_UNAVAILABLE", "reason": type(exc).__name__, "d1": None, "h4": None, "h1": None}
    return horizon_pack(
        fetch_candles("BTCUSDT", "1d", 3),
        fetch_candles("BTCUSDT", "4h", 3),
        fetch_candles("BTCUSDT", "1h", 3),
    )


def horizon_log_line(pack: Dict[str, Any]) -> str:
    if not pack.get("ok"):
        return "[horizon] BTC DATA_UNAVAILABLE"
    return f"[horizon] BTC D1={pack.get('d1')} H4={pack.get('h4')} H1={pack.get('h1')}"
