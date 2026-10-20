"""Adapt Binance Futures closed-candle rows for causal HTF research.

Caller supplies the same read-only futures fetcher used by B&R live.
No network requests, no orders, no production signal gating here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from office_br.htf_shadow import classify

TF_SECONDS = {"1d": 86400, "4h": 14400, "1h": 3600}


def _ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def snapshot(symbol: str, confirm_ts: float, fetch: Callable,
             *, limit: int = 80, lookback: int = 20) -> dict[str, Any]:
    """Only fully closed bars at the signal's confirmation close are admissible.

    This is NOT a historical as-of API. If the returned latest bars cannot
    cover the historical confirmation, returns UNKNOWN instead of pretending.
    """
    frames = {}
    diagnostics = {}
    for tf, seconds in TF_SECONDS.items():
        try:
            raw = fetch(symbol, tf, limit, closed_only=True)
            if not isinstance(raw, list):
                raise ValueError("not a list")
            selected = []
            for row in raw:
                start = _ts(row["ts"])
                if start + seconds <= confirm_ts:
                    selected.append({"ts": start, "close": float(row["close"])})
            selected.sort(key=lambda b: b["ts"])
            # Must include the last HTF bar closed at/before signal; reject
            # missing/stale data instead of a plausible-looking older trend.
            if not selected or confirm_ts - (selected[-1]["ts"] + seconds) >= seconds:
                frames[tf] = []
                diagnostics[tf] = "MISSING_ASOF_BAR"
            else:
                frames[tf] = selected
                diagnostics[tf] = "OK" if len(selected) >= lookback+1 else "INSUFFICIENT_HISTORY"
        except (ValueError, KeyError, TypeError, OverflowError):
            frames[tf] = []
            diagnostics[tf] = "FETCH_OR_PARSE_ERROR"
    result = classify(frames, confirm_ts=confirm_ts, lookback=lookback)
    result["data_health"] = diagnostics
    result["mode"] = "SHADOW_ONLY"
    return result
