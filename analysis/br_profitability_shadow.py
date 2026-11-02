"""A7: pure observational B&R shadow flags. NEVER called from LIVE without separate review.

All thresholds are HYPOTHESES, not source-author rules.
None means unavailable evidence, NEVER means rejection.
"""
from __future__ import annotations

from datetime import datetime, timezone


def evaluate_shadow(plan: dict, *, previous_sl_ts=None, previous_same_ts=None,
                    htf_swing_price=None, min_stop_pct=None, allowed_utc_hours=None,
                    pause_seconds=None, dedup_seconds=None) -> dict:
    """Return hypothesis flags; does not persist, suppress, or route signals.

    previous_* timestamps must be computed exclusively from earlier known events.
    htf_swing_price must derive from CONFIRMED HTF candles available at plan time.
    """
    created = float(plan["created_ts"])
    entry, sl = float(plan["entry"]), float(plan["sl"])
    direction = plan["direction"]
    if entry <= 0 or direction not in ("LONG", "SHORT"):
        raise ValueError("invalid plan")
    stop_pct = 100.0 * abs(entry - sl) / entry
    hour = datetime.fromtimestamp(created, timezone.utc).hour
    f_min_stop = None if min_stop_pct is None else stop_pct >= min_stop_pct
    f_hour = None if allowed_utc_hours is None else hour in allowed_utc_hours
    f_pause_sl = (None if pause_seconds is None or previous_sl_ts is None
                  else created - float(previous_sl_ts) >= pause_seconds)
    f_dedup = (None if dedup_seconds is None or previous_same_ts is None
               else created - float(previous_same_ts) >= dedup_seconds)
    sl_htf = None
    if htf_swing_price is not None:
        candidate = float(htf_swing_price)
        if (direction == "LONG" and candidate < sl) or (direction == "SHORT" and candidate > sl):
            sl_htf = candidate
    return {"f_min_stop": f_min_stop, "f_hour": f_hour, "f_pause_sl": f_pause_sl,
            "f_dedup": f_dedup, "sl_htf_price": sl_htf,
            "stop_pct": stop_pct, "hour_utc": hour,
            "mode": "SHADOW_ONLY", "threshold_status": "HYPOTHESIS"}
