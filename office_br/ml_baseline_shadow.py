"""Dependency-free, interpretable B&R ML baseline. Offline only.

Learns smoothed TP3 frequency in bins of ONE pre-declared causal feature.
No model promotion, orders, online updates, or production gates.
"""
from __future__ import annotations
from math import isfinite
from typing import Any, Mapping, Sequence
from office_br.learning_dataset import FEATURES

def train(rows: Sequence[Mapping[str, Any]], *, feature: str,
          threshold: float, prior_strength: float = 10.0) -> dict[str, Any]:
    if feature not in FEATURES or not isfinite(threshold):
        raise ValueError("feature/threshold must be predeclared and finite")
    if not isfinite(prior_strength) or prior_strength <= 0:
        raise ValueError("invalid smoothing")
    bins = {"low": [0,0], "high": [0,0]}
    for row in rows:
        if row.get("label") not in ("SL","TP3"):
            continue
        value = row.get("features",{}).get(feature)
        if value is None or not isfinite(float(value)):
            continue
        b = "high" if float(value) >= threshold else "low"
        bins[b][0] += 1
        bins[b][1] += int(row["label"] == "TP3")
    total = sum(v[0] for v in bins.values())
    if total == 0:
        raise ValueError("no labeled training rows")
    base = sum(v[1] for v in bins.values()) / total
    probabilities = {k: (v[1] + prior_strength*base)/(v[0]+prior_strength)
                     for k,v in bins.items()}
    return {"feature":feature,"threshold":float(threshold),
            "probabilities":probabilities,"base_rate":base,
            "counts":{k:v[0] for k,v in bins.items()},
            "mode":"SHADOW_ONLY","trained_on":"TRAIN_ONLY"}

def predict(model: Mapping[str, Any], row: Mapping[str, Any]) -> float:
    value = row.get("features",{}).get(model["feature"])
    if value is None:
        return float(model["base_rate"])
    value = float(value)
    if not isfinite(value):
        raise ValueError("non-finite prediction feature")
    return float(model["probabilities"]["high" if value >= model["threshold"] else "low"])

def evaluate(model: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scored = [(predict(model,r),int(r["label"]=="TP3")) for r in rows
              if r.get("label") in ("SL","TP3")]
    if not scored:
        return {"n":0,"brier":None,"constant_brier":None,
                "improvement":None,"mode":"SHADOW_ONLY"}
    baseline = float(model["base_rate"])
    brier = sum((p-y)**2 for p,y in scored)/len(scored)
    constant = sum((baseline-y)**2 for _,y in scored)/len(scored)
    return {"n":len(scored),"brier":round(brier,8),
            "constant_brier":round(constant,8),
            "improvement":round(constant-brier,8),
            "mode":"SHADOW_ONLY",
            "caution":"Classification calibration is not trading net expectancy"}
