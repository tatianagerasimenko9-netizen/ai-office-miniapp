"""Канонічний read-only контракт спостереження єдиного Trading Office.

Модуль нічого не вирішує, не пише в БД і не викликає delivery. Він лише
перевіряє форму вже отриманого результату Brain або shadow-детектора.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

UNIVERSAL_STATES = {
    "CANDIDATE",
    "FORMING",
    "CONFIRMED",
    "ENTRY_READY",
    "ACTIVE",
    "TP",
    "SL",
    "EXPIRED",
    "INVALIDATED",
}
METHODS = {"BRAIN", "SMC", "GERCHIK", "BULKOWSKI", "WYCKOFF", "STRONG_CANDLE"}
MIRROR_KINDS = {"mixed_touch_zone", "symmetry_transform", "role_flip_retest"}
REQUIRED = {
    "observation_id",
    "method",
    "version",
    "source_rule_ids",
    "symbol",
    "market",
    "direction",
    "timeframe",
    "decision_bar_close_utc",
    "state",
    "lineage",
    "geometry",
    "entry",
    "invalidation",
    "targets",
    "obstacles",
    "facts_for",
    "facts_against",
    "missing",
    "ambiguities",
    "overlay",
}


def iso_utc(ts: float) -> str:
    """UTC timestamp з явним часовим поясом."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp без timezone")
    return dt.astimezone(timezone.utc)


def observation_id(payload: Dict[str, Any]) -> str:
    """Стабільний id за методикою, версією, символом, напрямом і decision bar."""
    identity = {k: payload.get(k) for k in ("method", "version", "symbol", "market", "direction", "timeframe", "decision_bar_close_utc")}
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "OBS|" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def finalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out["observation_id"] = observation_id(out)
    return out


def _missing_modules(facts: Iterable[Dict[str, Any]]) -> set[str]:
    return {
        str(f.get("module") or f.get("name") or "")
        for f in facts
        if str(f.get("status") or "").upper() in {"UNAVAILABLE", "NOT_CONNECTED", "DATA_UNAVAILABLE"}
    } - {""}


def validate_observation(obs: Dict[str, Any]) -> List[str]:
    """Повертає всі порушення contract; порожній список означає валідність."""
    errors: List[str] = []
    absent = sorted(REQUIRED - set(obs))
    if absent:
        errors.append("missing fields: " + ", ".join(absent))
        return errors
    if obs["method"] not in METHODS:
        errors.append(f"unknown method: {obs['method']}")
    if obs["state"] not in UNIVERSAL_STATES:
        errors.append(f"unknown state: {obs['state']}")
    if obs["direction"] not in {"LONG", "SHORT", "NEUTRAL"}:
        errors.append(f"unknown direction: {obs['direction']}")
    if not obs["source_rule_ids"] or not all(isinstance(x, str) and x for x in obs["source_rule_ids"]):
        errors.append("source_rule_ids must be non-empty strings")

    lineage = obs.get("lineage") or {}
    if lineage.get("closed_only") is not True:
        errors.append("lineage.closed_only must be true")
    try:
        decision = parse_utc(obs["decision_bar_close_utc"])
        source_max = parse_utc(lineage["max_source_ts"])
        if source_max > decision:
            errors.append("max_source_ts is after decision_bar_close_utc")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid lineage timestamp: {exc}")
        decision = None

    geometry = obs.get("geometry") or {}
    if not isinstance(geometry.get("points"), list) or not isinstance(geometry.get("levels"), list):
        errors.append("geometry points/levels must be lists")
    for index, point in enumerate(geometry.get("points") or []):
        missing = {"bar_index", "ts", "price", "confirmed_at"} - set(point)
        if missing:
            errors.append(f"point[{index}] missing: {', '.join(sorted(missing))}")
            continue
        try:
            if decision is not None and parse_utc(point["confirmed_at"]) > decision:
                errors.append(f"point[{index}] confirmed after decision")
        except (TypeError, ValueError) as exc:
            errors.append(f"point[{index}] invalid timestamp: {exc}")
    mirror_kind = geometry.get("mirror_kind")
    if mirror_kind is not None and mirror_kind not in MIRROR_KINDS:
        errors.append(f"unknown mirror_kind: {mirror_kind}")

    if obs["state"] == "ENTRY_READY":
        if not obs.get("entry"):
            errors.append("ENTRY_READY requires entry")
        invalidation = obs.get("invalidation") or {}
        if invalidation.get("price") is None:
            errors.append("ENTRY_READY requires structural invalidation price")
        if not obs.get("targets"):
            errors.append("ENTRY_READY requires targets")

    unavailable = _missing_modules(list(obs.get("facts_for") or []) + list(obs.get("facts_against") or []))
    declared = {str(x.get("module") if isinstance(x, dict) else x) for x in obs.get("missing") or []}
    undeclared = sorted(unavailable - declared)
    if undeclared:
        errors.append("unavailable facts absent from missing: " + ", ".join(undeclared))
    return errors
