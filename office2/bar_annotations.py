"""Source-neutral OHLC bar pattern annotations for candlestick overlays.

Names BU/BPU/BPR are *provisional display labels*, not claimed to be verbatim
Daria rules. Thresholds are implementation heuristics until source-traced.
No trade decisions or orders are emitted by this module.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Sequence

VERSION = "bar-annotations-v1"


def annotate_bars(candles: Sequence[Mapping[str, Any]], *, level: float, direction: str, decision_ts: float, interval_sec: int, tolerance_pct: float = 0.12, abnormal_multiple: float = 2.0) -> list[dict[str, Any]]:
    """Return chart annotations for *closed* bars only.

    Candle ts is opening time in epoch seconds; OHLCV input can be rendered
    either as candlesticks or OHLC bars. Does not validate exchange provenance:
    callers must use a trusted futures feed for live charts.
    """
    if not level or level <= 0 or interval_sec <= 0 or direction.upper() not in {"LONG", "SHORT"}:
        return []
    rows: list[dict[str, float]] = []
    for c in candles:
        try:
            row = {k: float(c[k]) for k in ("ts", "open", "high", "low", "close")}
        except (KeyError, ValueError, TypeError):
            continue
        if row["ts"] + interval_sec > decision_ts or not (0 < row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]):
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["ts"])
    out: list[dict[str, Any]] = []
    tol = level * tolerance_pct / 100
    sign = 1 if direction.upper() == "LONG" else -1
    for i, c in enumerate(rows):
        labels: list[str] = []
        span = c["high"] - c["low"]
        prior = [r["high"] - r["low"] for r in rows[max(0, i - 20):i]]
        if len(prior) >= 10 and median(prior) > 0 and span >= abnormal_multiple * median(prior):
            labels.append("ABNORMAL")
        touches = c["low"] - tol <= level <= c["high"] + tol
        if touches and abs(c["close"] - level) <= tol:
            labels.append("BU_CANDIDATE")
        if i + 1 < len(rows):
            nxt = rows[i + 1]
            if touches and abs(nxt["open"] - level) <= tol:
                labels.append("BPU_CANDIDATE")
        if sign * (c["close"] - level) > tol and sign * (c["open"] - level) <= tol:
            labels.append("BPR_CANDIDATE")
        if labels:
            out.append({"ts": c["ts"], "labels": labels, "high": c["high"], "low": c["low"], "version": VERSION, "verified_method": False})
    return out
