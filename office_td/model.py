"""Інференс ансамблю дерев без sklearn (чистий Python): модель експортується з навчання в JSON (scripts/td_export_model.py)."""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Dict, List, Sequence

_DEFAULT = Path(__file__).with_name("model_v1.json")


class Model:
    def __init__(self, spec: dict):
        self.spec = spec
        self.features: List[str] = list(spec["features"])
        self.baseline = float(spec["baseline"])
        self.threshold = float(spec["threshold"])
        self.trees = spec["trees"]          # кожне: {"f":[], "t":[], "l":[], "r":[], "v":[], "m":[], "leaf":[]}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Model":
        return cls(json.loads(Path(path or _DEFAULT).read_text(encoding="utf-8")))

    def predict_row(self, x: Sequence[float]) -> float:
        s = self.baseline
        for tr in self.trees:
            i = 0
            while not tr["leaf"][i]:
                val = x[tr["f"][i]]
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    i = tr["l"][i] if tr["m"][i] else tr["r"][i]
                else:
                    i = tr["l"][i] if val <= tr["t"][i] else tr["r"][i]
            s += tr["v"][i]
        return s

    def predict_dict(self, feats: Dict[str, float]) -> float:
        return self.predict_row([feats.get(k, float("nan")) for k in self.features])


def export_sklearn(model, features: Sequence[str], threshold: float, meta: dict | None = None, ndigits: int = 8) -> dict:
    trees = []
    for it in model._predictors:
        nd = it[0].nodes
        trees.append({
            "f": [int(x) for x in nd["feature_idx"]],
            "t": [float(x) if math.isfinite(float(x)) else 0.0 for x in nd["num_threshold"]],   # пороги — без округлення (збіг із sklearn до біта)
            "l": [int(x) for x in nd["left"]], "r": [int(x) for x in nd["right"]],
            "v": [round(float(x), ndigits) for x in nd["value"]],
            "m": [bool(x) for x in nd["missing_go_to_left"]], "leaf": [bool(x) for x in nd["is_leaf"]],
        })
    return {"version": "TD_V1", "features": list(features), "baseline": float(model._baseline_prediction.ravel()[0]),
            "threshold": float(threshold), "trees": trees, "meta": meta or {}}
