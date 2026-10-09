"""Real-data shadow replay для Brain, SMC і п'яти сценаріїв Герчика.

Gerchik-події лишаються підтримкою/діагностикою: вони не стають READY. Усі
рушії отримують однакову модель fee, round-trip slippage, entry delay і TTL.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

import numpy as np

from office2 import features as F
from office2 import sim as SIM
from office2.integration.gerchik_scenarios import ShadowParams, detect_gerchik_scenarios
from office2.smc import replay as BASE

FEE_RT_PCT = SIM.FEE_RT_DEFAULT
SLIPPAGE_RT_BPS = 4.0
ENTRY_DELAY_SEC = 30.0
ENTRY_TTL_SEC = 6 * 3600.0
HORIZON_BARS = BASE.HORIZON_BARS


def validate_ohlcv(bars: F.Arr, width: int) -> List[str]:
    """Строга якість replay-входу: без пропусків, дублів та неможливих OHLC."""
    errors: List[str] = []
    required = ("t", "o", "h", "l", "c", "v")
    if any(key not in bars for key in required):
        return ["missing OHLCV arrays"]
    lengths = {len(bars[key]) for key in required}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        return ["OHLCV arrays have unequal or zero lengths"]
    if any(not np.isfinite(np.asarray(bars[key], dtype=float)).all() for key in required):
        errors.append("OHLCV contains non-finite values")
    times = np.asarray(bars["t"], dtype=float)
    if len(times) > 1 and not np.all(np.diff(times) == float(width)):
        errors.append("timestamps are not unique contiguous bars")
    o, h, l, c = (np.asarray(bars[key], dtype=float) for key in ("o", "h", "l", "c"))
    if np.any(l > h) or np.any(o < l) or np.any(o > h) or np.any(c < l) or np.any(c > h):
        errors.append("invalid OHLC geometry")
    return errors


def simulate_execution(
    m15: F.Arr,
    decision_index: int,
    direction: str,
    entry_reference: float,
    sl: float,
    target: float,
    *,
    fee_rt_pct: float = FEE_RT_PCT,
    slippage_rt_bps: float = SLIPPAGE_RT_BPS,
    entry_delay_sec: float = ENTRY_DELAY_SEC,
    entry_ttl_sec: float = ENTRY_TTL_SEC,
    horizon_bars: int = HORIZON_BARS,
) -> Dict[str, Any]:
    """Консервативний M15 first-touch після затримки; SL перший в одному барі."""
    sg = 1.0 if direction == "LONG" else -1.0
    delay = max(0.0, float(entry_delay_sec))
    ttl = max(0.0, float(entry_ttl_sec))
    costs = max(0.0, float(fee_rt_pct)) + max(0.0, float(slippage_rt_bps)) / 100.0
    common = {
        "entry_delay_sec": delay,
        "entry_ttl_sec": ttl,
        "fee_rt_pct": float(fee_rt_pct),
        "slippage_rt_bps": float(slippage_rt_bps),
        "cost_rt_pct": costs,
        "bar_resolution_sec": 900,
    }
    if delay > ttl:
        return common | {"outcome": "MISSED_ENTRY_TTL", "r_gross": None, "r_net": None, "bars": 0, "fill_entry": None}
    delay_bars = int(delay // 900)
    fill_index = int(decision_index) + 1 + delay_bars
    if fill_index >= len(m15["t"]):
        return common | {"outcome": "NO_DATA", "r_gross": None, "r_net": None, "bars": 0, "fill_entry": None}
    pre_h = m15["h"][decision_index + 1:fill_index]
    pre_l = m15["l"][decision_index + 1:fill_index]
    pre_sl = bool(((pre_l <= sl) if sg > 0 else (pre_h >= sl)).any())
    pre_tp = bool(((pre_h >= target) if sg > 0 else (pre_l <= target)).any())
    if pre_sl or pre_tp:
        reason = "MISSED_SL_BEFORE_ENTRY" if pre_sl else "MISSED_TP_BEFORE_ENTRY"
        return common | {"outcome": reason, "r_gross": None, "r_net": None, "bars": 0, "fill_entry": None}
    fill = float(m15["o"][fill_index]) if delay > 0 else float(entry_reference)
    if (sg > 0 and fill <= sl) or (sg < 0 and fill >= sl):
        return common | {"outcome": "MISSED_SL_BEFORE_ENTRY", "r_gross": None, "r_net": None, "bars": 0, "fill_entry": None}
    if (sg > 0 and fill >= target) or (sg < 0 and fill <= target):
        return common | {"outcome": "MISSED_TP_BEFORE_ENTRY", "r_gross": None, "r_net": None, "bars": 0, "fill_entry": None}
    risk = (fill - sl) if sg > 0 else (sl - fill)
    if risk <= 0:
        return common | {"outcome": "NO_DATA", "r_gross": None, "r_net": None, "bars": 0, "fill_entry": fill}
    h = m15["h"][fill_index:fill_index + horizon_bars]
    l = m15["l"][fill_index:fill_index + horizon_bars]
    c = m15["c"][fill_index:fill_index + horizon_bars]
    if len(h) == 0:
        return common | {"outcome": "NO_DATA", "r_gross": None, "r_net": None, "bars": 0, "fill_entry": fill}
    hit_sl = (l <= sl) if sg > 0 else (h >= sl)
    hit_tp = (h >= target) if sg > 0 else (l <= target)
    i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else -1
    i_tp = int(np.argmax(hit_tp)) if hit_tp.any() else -1
    if i_sl >= 0 and (i_tp < 0 or i_sl <= i_tp):
        index, outcome, gross = i_sl, "SL", -1.0
    elif i_tp >= 0:
        index, outcome = i_tp, "TP1"
        gross = abs(target - fill) / risk
    else:
        index, outcome = len(h) - 1, "OPEN"
        gross = float(sg * (c[-1] - fill) / risk)
    risk_pct = risk / max(abs(fill), 1e-12) * 100.0
    return common | {
        "outcome": outcome,
        "r_gross": float(gross),
        "r_net": SIM.net_r(float(gross), risk_pct, costs),
        "bars": index + 1,
        "complete": len(h) >= horizon_bars or outcome != "OPEN",
        "fill_entry": fill,
        "risk_pct_at_fill": risk_pct,
    }


def _gerchik_events(
    symbol: str,
    ctx: Dict[str, Any],
    t_from: float,
    t_to: float,
    execution: Dict[str, float],
    params: ShadowParams,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    m15 = ctx["m15"]
    ends = m15["t"] + 900
    events: List[Dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen = set()
    last_bounce: Dict[float, int] = {}
    for index in np.flatnonzero((ends > t_from) & (ends <= t_to)):
        now = float(ends[index])
        for verdict in detect_gerchik_scenarios(ctx, now, symbol, params):
            level_key = round(float(verdict["level"]["p"]), 8)
            key = (verdict["scenario"], level_key, int(verdict["decision_index"]))
            if key in seen:
                continue
            seen.add(key)
            if verdict["scenario"] == "BOUNCE":
                previous = last_bounce.get(level_key)
                if previous is not None and int(verdict["decision_index"]) - previous <= params.bounce_refractory_bars:
                    continue
                last_bounce[level_key] = int(verdict["decision_index"])
            if verdict["state"] == "INVALIDATED":
                rejected.update(verdict["rejection_reasons"])
                continue
            if verdict["state"] != "CONFIRMED":
                continue
            event = {
                "source": "GERCHIK_SHADOW",
                "model": verdict["scenario"],
                "key": "|".join(map(str, key)),
                "symbol": symbol,
                "dir": verdict["direction"],
                "ts_bar": int(now),
                "i": int(index),
                "entry": float(verdict["entry_reference"]),
                "sl": float(verdict["structural_sl"]),
                "tp1": float(verdict["potential_target"]),
                "source_rule_id": verdict["source_rule_id"],
                "source_refs": verdict["source_refs"],
                "detector_version": verdict["version"],
                "operational_parameters": verdict["operational_parameters"],
                "level_kind": verdict["level"]["kind"],
                "level_price": verdict["level"]["p"],
                "state": "SHADOW_CONFIRMED",
            }
            event["sim"] = simulate_execution(
                m15, int(index), event["dir"], event["entry"], event["sl"], event["tp1"], **execution
            )
            events.append(event)
    return events, {"detected": len(events), "rejected": int(sum(rejected.values())), "rejection_reasons": dict(sorted(rejected.items()))}


def replay_arrays(
    symbol: str,
    arrs: Dict[str, Optional[F.Arr]],
    t_from: float,
    t_to: float,
    *,
    btc: Optional[F.Arr] = None,
    fee_rt_pct: float = FEE_RT_PCT,
    slippage_rt_bps: float = SLIPPAGE_RT_BPS,
    entry_delay_sec: float = ENTRY_DELAY_SEC,
    entry_ttl_sec: float = ENTRY_TTL_SEC,
    params: ShadowParams = ShadowParams(),
) -> Dict[str, Any]:
    """Однакове frozen-time вікно для Brain, SMC і Gerchik shadow."""
    m15 = arrs["m15"]
    if m15 is None or arrs.get("h4") is None or arrs.get("d1") is None or arrs.get("w1") is None:
        raise ValueError("m15/h4/d1/w1 arrays required")
    for key, width in (("m15", 900), ("h4", 14400), ("d1", F.DAY), ("w1", 7 * F.DAY)):
        errors = validate_ohlcv(arrs[key], width)
        if errors:
            raise ValueError(f"{key}: {'; '.join(errors)}")
    if btc is not None:
        errors = validate_ohlcv(btc, 900)
        if errors:
            raise ValueError(f"btc: {'; '.join(errors)}")
    base = BASE.replay_arrays(symbol, arrs, t_from, t_to, btc=btc)
    execution = {
        "fee_rt_pct": max(0.0, float(fee_rt_pct)),
        "slippage_rt_bps": max(0.0, float(slippage_rt_bps)),
        "entry_delay_sec": max(0.0, float(entry_delay_sec)),
        "entry_ttl_sec": max(0.0, float(entry_ttl_sec)),
    }
    for event in base["events"]:
        if "error" in event or event.get("tp1") is None:
            continue
        event["sim"] = simulate_execution(
            m15, int(event["i"]), event["dir"], float(event["entry"]), float(event["sl"]), float(event["tp1"]), **execution
        )
    context = {
        "m15": m15,
        "atr15": F.atr(m15, 14),
        "d1": arrs["d1"],
        "levels": F.build_levels(arrs["h4"], arrs["d1"], arrs["w1"]),
    }
    gerchik, funnel = _gerchik_events(symbol, context, t_from, t_to, execution, params)
    base["events"].extend(gerchik)
    base["gerchik_funnel"] = funnel
    base["execution_assumptions"] = execution | {"bar_resolution_sec": 900, "decision_data": "closed_ohlcv_only"}
    return base


def _cluster_ci(events: List[Dict[str, Any]], seed: int = 19, rounds: int = 1000) -> Optional[List[float]]:
    resolved = [event for event in events if event.get("sim", {}).get("outcome") in {"TP1", "SL"} and event["sim"].get("r_net") is not None]
    clusters: Dict[tuple[str, int], List[float]] = {}
    for event in resolved:
        key = (str(event["symbol"]), int(event["ts_bar"]) // F.DAY)
        clusters.setdefault(key, []).append(float(event["sim"]["r_net"]))
    if len(resolved) < 10 or len(clusters) < 3:
        return None
    keys = list(clusters)
    random = np.random.RandomState(seed)
    values = []
    for _ in range(rounds):
        sample = [value for key in (keys[i] for i in random.randint(0, len(keys), len(keys))) for value in clusters[key]]
        values.append(float(np.mean(sample)))
    return [round(float(np.percentile(values, 2.5)), 3), round(float(np.percentile(values, 97.5)), 3)]


def _block(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    sims = [event["sim"] for event in events if event.get("sim")]
    resolved_events = [event for event in events if event.get("sim", {}).get("outcome") in {"TP1", "SL"} and event["sim"].get("r_net") is not None]
    scored = [event["sim"] for event in resolved_events]
    missed = [sim for sim in sims if str(sim.get("outcome") or "").startswith("MISSED_")]
    values = [float(sim["r_net"]) for sim in scored]
    outcomes = {name: sum(1 for sim in scored if sim["outcome"] == name) for name in ("TP1", "SL", "OPEN")}
    return {
        "events": len(events),
        "scored_resolved": len(scored),
        "missed_entry": len(missed),
        "missed_entry_reasons": dict(Counter(sim["outcome"] for sim in missed)),
        "outcomes": outcomes,
        "mean_r_net": round(float(np.mean(values)), 3) if values else None,
        "r_net_ci95_clustered": _cluster_ci(events),
        "sample_warning": "N_LT_10_NO_INFERENCE" if len(scored) < 10 else None,
    }


def summarize(runs: List[Dict[str, Any]], support_bars: int = 4) -> Dict[str, Any]:
    events = [event for run in runs for event in run["events"] if "error" not in event]
    by_source = {source: [event for event in events if event["source"] == source] for source in ("BRAIN", "SMC", "GERCHIK_SHADOW")}

    def supports(decision: Dict[str, Any], evidence: Dict[str, Any]) -> bool:
        return (
            decision["symbol"] == evidence["symbol"]
            and decision["dir"] == evidence["dir"]
            and 0 <= int(decision["ts_bar"]) - int(evidence["ts_bar"]) <= support_bars * 900
        )

    brain, smc, gerchik = by_source["BRAIN"], by_source["SMC"], by_source["GERCHIK_SHADOW"]
    brain_smc = [event for event in brain if any(supports(event, other) for other in smc)]
    brain_gerchik = [event for event in brain if any(supports(event, other) for other in gerchik)]
    triple = [event for event in brain_smc if any(supports(event, other) for other in gerchik)]
    joint = [event for event in brain if event in brain_smc or event in brain_gerchik]
    brain_only = [event for event in brain if event not in joint]
    smc_only = [event for event in smc if not any(supports(other, event) for other in brain)]
    return {
        "symbols": [run["symbol"] for run in runs],
        "decision_bars": sum(int(run["bars"]) for run in runs),
        "errors": sum(1 for run in runs for event in run["events"] if "error" in event),
        "execution_assumptions": runs[0].get("execution_assumptions") if runs else {},
        "engines": {source: _block(rows) for source, rows in by_source.items()},
        "joint_shadow": {
            "support_window_bars": support_bars,
            "brain_only": _block(brain_only),
            "smc_only": _block(smc_only),
            "brain_with_any_shadow_support": _block(joint),
            "brain_with_smc_support": _block(brain_smc),
            "brain_with_gerchik_support": _block(brain_gerchik),
            "brain_smc_gerchik_triple": _block(triple),
            "decision_changed": False,
        },
        "gerchik_by_scenario": {
            scenario: _block([event for event in gerchik if event["model"] == scenario])
            for scenario in sorted({event["model"] for event in gerchik})
        },
        "gerchik_detector": {
            "version": next((event.get("detector_version") for event in gerchik), None),
            "operational_parameters": next((event.get("operational_parameters") for event in gerchik), None),
        },
        "gerchik_rejections": {
            "total": sum(run["gerchik_funnel"]["rejected"] for run in runs),
            "reasons": dict(Counter(
                reason
                for run in runs
                for reason, count in run["gerchik_funnel"]["rejection_reasons"].items()
                for _ in range(count)
            )),
        },
        "caveats": [
            "експлоративний shadow replay, не доказ прибутковості",
            "Gerchik shadow не створює ENTRY_READY і не змінює угоди Brain",
            "30 с затримки на M15 апроксимується open наступного доступного бара",
            "SL першим, якщо SL і TP торкнулися в одному M15-барі",
            "живі CVD/OI/funding/DOM у closed-OHLCV replay відсутні",
            "bootstrap CI показується лише при N>=10; малі групи мають N_LT_10_NO_INFERENCE",
        ],
    }
