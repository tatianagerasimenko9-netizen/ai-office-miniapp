"""Versioned, causal B&R feature rows for Hugging Face-style offline datasets.

No HF account or external upload. No orders or production gates.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "br_features_v1"
FEATURES = ("breakout_strength", "close_location", "volume_ratio",
            "retest_depth_r", "obstacle_r", "spread_bps", "atr_pct")
OUTCOMES = ("SL", "TP3", "AMBIGUOUS", "TIMEOUT", "DATA_GAP")


def build_row(signal: Mapping[str, Any], features: Mapping[str, Any],
              *, observed_at: float, label: str | None = None) -> dict[str, Any]:
    """Freeze features known at observation time; labels must be joined later."""
    signal_ts = float(signal["confirm_ts"])
    if not isfinite(signal_ts) or not isfinite(observed_at) or observed_at < signal_ts:
        raise ValueError("invalid feature observation time")
    if label is not None and label not in OUTCOMES:
        raise ValueError("unsupported outcome")
    clean = {}
    for name in FEATURES:
        val = features.get(name)
        if val is None:
            clean[name] = None
        else:
            val = float(val)
            if not isfinite(val):
                raise ValueError("non-finite feature: " + name)
            clean[name] = val
    sid = str(signal["sig_id"])
    row = {"schema_version": SCHEMA_VERSION, "sig_id": sid,
           "symbol": str(signal["symbol"]), "direction": str(signal["direction"]),
           "confirm_ts": signal_ts, "observed_at": float(observed_at),
           "features": clean, "label": label, "mode": "SHADOW_ONLY"}
    row["row_hash"] = hashlib.sha256(json.dumps(
        {k:v for k,v in row.items() if k != "row_hash"},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return row


def chronological_split(rows: Sequence[Mapping[str, Any]], *, train_fraction: float = 0.6,
                        validation_fraction: float = 0.2) -> dict[str, list[dict]]:
    """Group same confirmation timestamps; never split simultaneous signals."""
    if not (0 < train_fraction < 1 and 0 < validation_fraction < 1
            and train_fraction + validation_fraction < 1):
        raise ValueError("invalid split")
    ordered = sorted(rows, key=lambda r: (float(r["confirm_ts"]), str(r["sig_id"])))
    timestamps = sorted({float(r["confirm_ts"]) for r in ordered})
    if len(timestamps) < 5:
        raise ValueError("insufficient independent timestamp groups")
    n = len(timestamps)
    a = max(1, int(n * train_fraction))
    b = max(a+1, int(n * (train_fraction+validation_fraction)))
    if b >= n:
        raise ValueError("no test timestamps")
    t1, t2 = timestamps[a], timestamps[b]
    result = {"train": [], "validation": [], "test": []}
    for r in ordered:
        part = "train" if float(r["confirm_ts"]) < t1 else (
            "validation" if float(r["confirm_ts"]) < t2 else "test")
        result[part].append(dict(r))
    return result
