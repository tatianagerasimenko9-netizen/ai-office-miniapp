"""Point-in-time market data quality gates; never infer missing feed health.

Separate freshness and source provenance from a trading signal. A passing
snapshot is evidence for review, not authorization to trade.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

DEFAULT_MAX_AGE_SECONDS = {"ticker": 30, "orderbook": 5, "liquidations": 120, "news": 300, "ohlcv": 900}


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def assess_feed(
    snapshot: Mapping[str, Any],
    *,
    now_utc: datetime,
    max_age_seconds: int | None = None,
) -> Dict[str, Any]:
    """Fail closed on missing provenance, stale/future timestamps, invalid age."""
    reasons = []
    kind = str(snapshot.get("kind") or "").lower()
    source = str(snapshot.get("source") or "").strip()
    observed = _parse_utc(snapshot.get("observed_at"))
    now = now_utc.astimezone(timezone.utc) if now_utc.tzinfo else None
    if now is None:
        raise ValueError("now_utc must be timezone aware")
    if kind not in DEFAULT_MAX_AGE_SECONDS:
        reasons.append("UNKNOWN_FEED_KIND")
    if not source:
        reasons.append("MISSING_SOURCE")
    if snapshot.get("complete") is not True:
        reasons.append("INCOMPLETE_SNAPSHOT")
    if snapshot.get("is_estimate") is True and kind == "liquidations":
        reasons.append("ESTIMATED_LIQUIDATIONS_NOT_VERIFIED")
    limit = max_age_seconds if max_age_seconds is not None else DEFAULT_MAX_AGE_SECONDS.get(kind)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        reasons.append("INVALID_FRESHNESS_LIMIT")
    if observed is None:
        reasons.append("INVALID_TIMESTAMP")
        age = None
    else:
        age = (now - observed).total_seconds()
        if age < 0:
            reasons.append("FUTURE_TIMESTAMP")
        elif isinstance(limit, int) and limit > 0 and age > limit:
            reasons.append("STALE_SNAPSHOT")
    return {
        "quality": "OK" if not reasons else "UNAVAILABLE",
        "usable_for_review": not reasons,
        "order_authorized": False,
        "age_seconds": age,
        "reasons": reasons,
        "source": source or None,
        "kind": kind,
    }


FEED_GATE_ENV = "OFFICE_FEED_GATE"
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def last_candle_observed_at(candles: Any, interval: str, now_utc: datetime) -> str | None:
    """min(відкриття + інтервал, now): формована свічка свіжа, завислий фід старіє."""
    if not isinstance(candles, list) or not candles or not isinstance(candles[-1], Mapping):
        return None
    opened = _parse_utc(candles[-1].get("ts"))
    if opened is None:
        return None
    from datetime import timedelta

    close = opened + timedelta(seconds=TF_SECONDS.get(interval, 300))
    return min(close, now_utc.astimezone(timezone.utc)).isoformat()


def gate_send_on_fresh_data(
    cycle: Mapping[str, Any],
    candles_ltf: Any,
    *,
    interval: str = "15m",
    now_utc: datetime | None = None,
    source: str = "binance_futures",
) -> Dict[str, Any]:
    """Без свіжих LTF-даних новий SEND не створюється (SEND → WAIT). Інші рішення не змінює.

    Вимикається лише явно: OFFICE_FEED_GATE=0 (відкат).
    """
    import os

    out = dict(cycle)
    if not out.get("send") or os.getenv(FEED_GATE_ENV, "1").strip() == "0":
        return out
    now = now_utc or datetime.now(timezone.utc)
    res = assess_feed(
        {"kind": "ohlcv", "source": source,
         "observed_at": last_candle_observed_at(candles_ltf, interval, now),
         "complete": bool(isinstance(candles_ltf, list) and candles_ltf)},
        now_utc=now,
    )
    out["feed_check"] = res
    if not res["usable_for_review"]:
        out.update({
            "action": "WAIT",
            "send": False,
            "reason": "дані не підтверджені (" + ", ".join(res["reasons"]) + ") — новий вхід не формую",
            "recheck": "після відновлення свіжих свічок",
        })
    return out
