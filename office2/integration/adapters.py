"""Read-only адаптери чинних Brain v2.1, SMC і Gerchik Layer-B shadow до єдиного контракту."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

import numpy as np

from office2 import brain2 as B2
from office2 import features as F
from office2.integration.contract import finalize, iso_utc
from office2.smc import engine as SMC

TF_SECONDS = {"M15": 900}


def _semantic_group(name: str) -> str:
    value = str(name or "").lower()
    if any(x in value for x in ("mss", "bos", "structure", "структур")):
        return "structure_break"
    if any(x in value for x in ("sweep", "raid", "false break", "ліквід")):
        return "liquidity_failure"
    if any(x in value for x in ("fvg", "imbalance", "strong candle", "displacement")):
        return "imbalance_impulse"
    if any(x in value for x in ("mirror", "retest", "role flip")):
        return "level_role_change"
    if any(x in value for x in ("compression", "піджат", "triangle")):
        return "compression"
    if any(x in value for x in ("range", "wyckoff", "діапаз")):
        return "range"
    return "other"


def _fact(item: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(item)
    out["semantic_group"] = _semantic_group(str(item.get("module") or item.get("kind") or item.get("step") or ""))
    return out


def _lineage(ctx: Dict[str, Any], now: float, *, fixture: bool, candle_source: str, market: str) -> Dict[str, Any]:
    bars = ctx["m15"]
    k = F.last_closed(bars, TF_SECONDS["M15"], now)
    if k < 0:
        raise ValueError("немає завершеної M15-свічки")
    close_ts = float(bars["t"][k]) + TF_SECONDS["M15"]
    return {
        "candle_source": candle_source,
        "market": market,
        "closed_only": True,
        "max_source_ts": iso_utc(close_ts),
        "fixture": bool(fixture),
        "last_bar_index": int(k),
    }


def _point(ctx: Dict[str, Any], ts: float, price: float, confirmed_ts: Optional[float] = None) -> Dict[str, Any]:
    bars = ctx["m15"]
    j = int(np.searchsorted(bars["t"], float(ts), side="right") - 1)
    j = max(0, min(j, len(bars["t"]) - 1))
    return {
        "bar_index": j,
        "ts": iso_utc(float(bars["t"][j])),
        "price": float(price),
        "confirmed_at": iso_utc(float(confirmed_ts if confirmed_ts is not None else bars["t"][j] + 900)),
    }


def _missing(evidence: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [
        {"module": str(item.get("module") or "unknown"), "status": str(item.get("status") or "UNAVAILABLE")}
        for item in evidence
        if str(item.get("status") or "").upper() in {"UNAVAILABLE", "NOT_CONNECTED", "DATA_UNAVAILABLE"}
    ]


def _brain_state(state: str, reason: str) -> str:
    if state == "READY":
        return "ENTRY_READY"
    if state == "WAIT":
        return "CONFIRMED" if "WAIT 3/3" in reason or "ARMED" in reason else "FORMING"
    if state == "EXPIRED":
        return "EXPIRED"
    if state in {"INVALIDATED", "MISSED", "NO_TRADE"}:
        return "INVALIDATED"
    return "CANDIDATE"


def _smc_state(state: str, stage: int) -> str:
    if state == "READY":
        return "ENTRY_READY"
    if state == "ARMED":
        return "CONFIRMED"
    if state == "CANDIDATE":
        return "CONFIRMED"
    if state == "WAIT":
        return "FORMING" if stage >= 3 else "CANDIDATE"
    if state == "EXPIRED":
        return "EXPIRED"
    if state in {"INVALIDATED", "MISSED", "TRIGGERED_EARLIER", "NO_CONTEXT", "NO_TRADE"}:
        return "INVALIDATED"
    return "CANDIDATE"


def from_brain(
    thesis: Dict[str, Any],
    ctx: Dict[str, Any],
    now: float,
    symbol: str,
    *,
    evidence: Optional[List[Dict[str, Any]]] = None,
    fixture: bool = False,
    candle_source: str = "binance_futures",
    market: str = "binance_usdm",
) -> Dict[str, Any]:
    """Нормалізує готову тезу Brain; сам Brain повторно не запускає."""
    evd = list(evidence or [])
    lineage = _lineage(ctx, now, fixture=fixture, candle_source=candle_source, market=market)
    direction = str(thesis.get("dir") or thesis.get("direction") or "NEUTRAL")
    points: List[Dict[str, Any]] = []
    event = thesis.get("event") or {}
    if event.get("ts") is not None and event.get("extreme") is not None:
        points.append(_point(ctx, float(event["ts"]), float(event["extreme"])))
    brk = thesis.get("break") or {}
    if brk.get("ts") is not None and brk.get("level") is not None:
        points.append(_point(ctx, float(brk["ts"]), float(brk["level"])))
    zone = thesis.get("entry_zone") or thesis.get("zone")
    entry = None
    if thesis.get("entry") is not None or zone:
        entry = {"price": thesis.get("entry"), "zone": deepcopy(zone)}
    invalidation = deepcopy(thesis.get("invalidation") or {})
    if invalidation and invalidation.get("price") is None and thesis.get("sl") is not None:
        invalidation["price"] = thesis["sl"]
    facts_for = [_fact(x) for x in evd if int(x.get("supports") or 0) > 0]
    facts_against = [_fact(x) for x in evd if int(x.get("supports") or 0) < 0]
    ambiguities = []
    if event.get("class") == "LATE_SWEEP":
        ambiguities.append({"code": "LATE_SWEEP", "detail": "рівень був прийнятий до повторного тесту"})
    payload = {
        "method": "BRAIN",
        "version": str(thesis.get("brain") or B2.VERSION),
        "source_rule_ids": ["BRAIN2-SEQUENCE"],
        "symbol": str(symbol).upper(),
        "market": market,
        "direction": direction,
        "timeframe": "M15",
        "decision_bar_close_utc": lineage["max_source_ts"],
        "state": _brain_state(str(thesis.get("state") or ""), str(thesis.get("reason") or "")),
        "lineage": lineage,
        "geometry": {
            "points": points,
            "levels": deepcopy([thesis.get("level")] if thesis.get("level") else []),
            "zone": deepcopy(zone),
            "mirror_kind": None,
        },
        "entry": entry,
        "invalidation": invalidation or None,
        "targets": deepcopy(thesis.get("targets") or []),
        "obstacles": deepcopy(thesis.get("obstacles_before_tp1") or []),
        "facts_for": facts_for,
        "facts_against": facts_against,
        "missing": _missing(evd),
        "ambiguities": ambiguities,
        "overlay": None,
    }
    return finalize(payload)


def from_smc(
    model: Dict[str, Any],
    ctx: Dict[str, Any],
    now: float,
    symbol: str,
    *,
    fixture: bool = False,
    candle_source: str = "binance_futures",
    market: str = "binance_usdm",
    overlay: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Нормалізує один уже обчислений SMC model verdict; детектори не запускає."""
    lineage = _lineage(ctx, now, fixture=fixture, candle_source=candle_source, market=market)
    bars = ctx["m15"]
    points: List[Dict[str, Any]] = []
    levels: List[Dict[str, Any]] = []
    for anchor in model.get("anchors") or []:
        if anchor.get("p") is not None and anchor.get("j") is not None:
            j = max(0, min(int(anchor["j"]), len(bars["t"]) - 1))
            points.append(_point(ctx, float(bars["t"][j]), float(anchor["p"])))
        elif anchor.get("zone"):
            levels.append({"kind": anchor.get("type"), "zone": deepcopy(anchor["zone"]), "confirmed_bar": anchor.get("conf")})
    sweep = model.get("sweep") or {}
    if sweep.get("level"):
        levels.append(deepcopy(sweep["level"]))
    zone = model.get("zone")
    entry = None
    if model.get("entry") is not None or zone:
        entry = {"price": model.get("entry"), "zone": deepcopy(zone)}
    invalidation = None
    if model.get("sl") is not None or model.get("extreme") is not None:
        invalidation = {
            "price": model.get("sl") if model.get("sl") is not None else model.get("extreme"),
            "structural_extreme": model.get("extreme"),
            "why": "структурний екстремум SMC-моделі з канонічним люфтом Brain",
        }
    facts_for = [
        {"finding": str(value), "semantic_group": _semantic_group(str(value)), "status": "USED"}
        for value in model.get("evidence_for") or []
    ]
    facts_against = [
        {"finding": str(value), "semantic_group": _semantic_group(str(value)), "status": "USED"}
        for value in model.get("evidence_against") or []
    ]
    ambiguities = []
    if sweep.get("class") in {"LATE_SWEEP", "ACCEPTED_BREAKOUT"}:
        ambiguities.append({"code": str(sweep["class"]), "detail": "подія не класифікується як fresh raid"})
    model_name = str(model.get("model") or "UNKNOWN")
    payload = {
        "method": "SMC",
        "version": SMC.VERSION,
        "source_rule_ids": ["S26"],
        "symbol": str(symbol).upper(),
        "market": market,
        "direction": str(model.get("dir_real") or model.get("dir") or "NEUTRAL"),
        "timeframe": "M15",
        "decision_bar_close_utc": lineage["max_source_ts"],
        "state": _smc_state(str(model.get("state") or ""), int(model.get("stage") or 0)),
        "lineage": lineage,
        "geometry": {
            "points": points,
            "levels": levels,
            "zone": deepcopy(zone),
            "mirror_kind": "symmetry_transform" if str(model.get("dir_real") or "") == "SHORT" else None,
        },
        "entry": entry,
        "invalidation": invalidation,
        "targets": deepcopy(model.get("targets") or []),
        "obstacles": deepcopy(model.get("obstacles_before_tp1") or []),
        "facts_for": facts_for,
        "facts_against": facts_against,
        "missing": [],
        "ambiguities": ambiguities,
        "overlay": deepcopy(overlay),
        "model": model_name,
    }
    return finalize(payload)


def from_gerchik(
    ops: Dict[str, Any],
    ctx: Dict[str, Any],
    now: float,
    symbol: str,
    direction: str,
    *,
    fixture: bool = False,
    candle_source: str = "binance_futures",
    market: str = "binance_usdm",
) -> Dict[str, Any]:
    """Нормалізує вже обчислений Layer-B score без повторного запуску API.

    Gerchik ops не має власних entry/SL/targets, тому цей адаптер принципово
    ніколи не повертає ENTRY_READY і не може вплинути на Brain READY.
    """
    source = deepcopy(ops)
    lineage = _lineage(ctx, now, fixture=fixture, candle_source=candle_source, market=market)
    raw_score = source.get("gerchik_ops_score")
    try:
        score = int(raw_score) if raw_score is not None else None
    except (TypeError, ValueError):
        score = None
    score = max(0, min(10, score)) if score is not None else None
    band = str(source.get("gerchik_ops_band") or "unknown")
    veto = bool(source.get("gerchik_atr_trend_veto"))
    reasons = [str(x) for x in source.get("gerchik_ops_reasons") or [] if str(x).strip()]
    if score is None:
        state = "CANDIDATE"
    elif score <= 4 or veto:
        state = "INVALIDATED"
    elif score <= 7:
        state = "FORMING"
    else:
        state = "CONFIRMED"
    findings = [
        {"finding": reason, "semantic_group": _semantic_group(reason), "status": "USED"}
        for reason in reasons
    ]
    facts_for = findings if state in {"FORMING", "CONFIRMED"} else []
    facts_against = findings if state == "INVALIDATED" else []
    missing = [] if score is not None else [{"module": "gerchik_ops_inputs", "status": "DATA_UNAVAILABLE"}]
    payload = {
        "method": "GERCHIK",
        "version": "gerchik-ops-layer-b-1",
        "source_rule_ids": ["GERCHIK-OPS-LAYER-B"] + (["GERCHIK-ATR-80"] if veto else []),
        "symbol": str(symbol).upper(),
        "market": market,
        "direction": str(direction).upper(),
        "timeframe": "M15",
        "decision_bar_close_utc": lineage["max_source_ts"],
        "state": state,
        "lineage": lineage,
        "geometry": {"points": [], "levels": [], "zone": None, "mirror_kind": None},
        "entry": None,
        "invalidation": None,
        "targets": [],
        "obstacles": [],
        "facts_for": facts_for,
        "facts_against": facts_against,
        "missing": missing,
        "ambiguities": [{
            "code": "LAYER_B_NOT_PRIMARY_SOURCE",
            "detail": "0–10 ops score є внутрішньою AI-формалізацією, не перевіреним правилом книги",
        }],
        "overlay": None,
        "score": {"value": score, "band": band, "atr_trend_veto": veto},
    }
    return finalize(payload)


def from_gerchik_scenario(
    verdict: Dict[str, Any],
    ctx: Dict[str, Any],
    now: float,
    symbol: str,
    *,
    fixture: bool = False,
    candle_source: str = "binance_futures",
    market: str = "binance_usdm",
) -> Dict[str, Any]:
    """Нормалізує source-backed сценарій у shadow contract без права READY."""
    source = deepcopy(verdict)
    lineage = _lineage(ctx, now, fixture=fixture, candle_source=candle_source, market=market)
    bars = ctx["m15"]
    decision_index = int(source.get("decision_index", -1))
    actual_index = F.last_closed(bars, TF_SECONDS["M15"], now)
    if decision_index != actual_index or not (0 <= decision_index < len(bars["t"])):
        raise ValueError("verdict decision_index не відповідає останньому закритому бару")
    expected_ts = float(bars["t"][decision_index] + TF_SECONDS["M15"])
    if abs(float(source.get("decision_ts", -1.0)) - expected_ts) > 1e-6:
        raise ValueError("verdict decision_ts не відповідає decision_index")
    confirmations = deepcopy(source.get("confirmation") or [])
    points = []
    for item in confirmations:
        if item.get("bar_index") is None or item.get("price") is None:
            continue
        index = int(item["bar_index"])
        if index < 0 or index > decision_index:
            raise ValueError("confirmation bar_index поза causal decision window")
        points.append(_point(ctx, float(bars["t"][index]), float(item["price"]), float(bars["t"][index] + 900)))
    rejected = [str(value) for value in source.get("rejection_reasons") or []]
    state = str(source.get("state") or "CANDIDATE")
    if state == "ENTRY_READY":
        state = "CONFIRMED"
    scenario = str(source.get("scenario") or "UNKNOWN")
    level = deepcopy(source.get("level") or {})
    entry_price = source.get("entry_reference")
    sl = source.get("structural_sl")
    target = source.get("potential_target")
    payload = {
        "method": "GERCHIK",
        "version": f"{source.get('version') or 'gerchik-source-shadow'}/{scenario}",
        "source_rule_ids": [str(source["source_rule_id"])],
        "symbol": str(symbol).upper(),
        "market": market,
        "direction": str(source.get("direction") or "NEUTRAL").upper(),
        "timeframe": "M15",
        "decision_bar_close_utc": lineage["max_source_ts"],
        "state": state,
        "lineage": lineage,
        "geometry": {
            "points": points,
            "levels": [level] if level else [],
            "zone": None,
            "mirror_kind": None,
        },
        "entry": {"price": entry_price, "zone": None, "activation": "SHADOW_REFERENCE_ONLY"} if entry_price is not None else None,
        "invalidation": {
            "price": sl,
            "structural_extreme": source.get("structural_extreme"),
            "why": "структурний екстремум source-backed Gerchik shadow-моделі",
        } if sl is not None else None,
        "targets": [{
            "p": target,
            "r": source.get("potential_rr"),
            "kind": "SOURCE_MINIMUM_RR_MODEL",
        }] if target is not None else [],
        "obstacles": deepcopy(source.get("obstacles") or []),
        "facts_for": [
            {"finding": item, "semantic_group": _semantic_group(str(item.get("name") or "")), "status": "USED"}
            for item in confirmations
        ],
        "facts_against": [
            {"finding": reason, "semantic_group": "rejection_reason", "status": "USED"}
            for reason in rejected
        ],
        "missing": [],
        "ambiguities": [
            {
                "code": "SHADOW_ONLY_NO_READY",
                "detail": "сценарій не змінює Brain READY і не є торговим рішенням",
            },
            {
                "code": "OPERATIONAL_THRESHOLDS_NOT_SOURCE_QUOTES",
                "detail": "ATR-допуски та impulse ratio є зафіксованою replay-операціоналізацією",
            },
        ],
        "overlay": {
            "scenario": scenario,
            "source_status": source.get("source_status"),
            "source_refs": deepcopy(source.get("source_refs") or []),
            "implementation_status": source.get("implementation_status"),
            "rejection_reasons": rejected,
            "operational_parameters": deepcopy(source.get("operational_parameters") or {}),
        },
    }
    return finalize(payload)
