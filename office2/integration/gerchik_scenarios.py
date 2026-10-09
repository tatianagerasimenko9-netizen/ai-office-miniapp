"""П'ять сценаріїв Герчика як read-only shadow-детектори.

Детектори працюють лише із завершеними M15-барами та рівнями, відомими до
початку моделі. Числові допуски нижче є явною операціоналізацією для replay,
а не цитатою з книги і не production CONFIG.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2 import features as F
from office2.integration.gerchik_source_rules import gerchik_source_rules

VERSION = "gerchik-source-shadow-1"
SOURCE_STATUS = "PRIMARY_TEXT_VERIFIED"
DAILY_LEVEL_KINDS = {"D1SW", "PDH", "PDL", "PWH", "PWL"}

SCENARIOS = {
    "BOUNCE": "GERCHIK-08-VIDBIY",
    "BREAKOUT": "GERCHIK-09-PROBIY",
    "FALSE_BREAK_1BAR": "GERCHIK-06-LP-1BAR",
    "FALSE_BREAK_2BAR": "GERCHIK-06-LP-2BAR",
    "FALSE_BREAK_COMPLEX": "GERCHIK-06-LP-COMPLEX",
}


@dataclass(frozen=True)
class ShadowParams:
    touch_atr: float = 0.05
    luft_atr: float = 0.10
    stop_buffer_atr: float = 0.10
    false_break_max_depth_atr: float = 0.30
    approach_bars: int = 3
    small_bar_ratio: float = 0.80
    breakout_impulse_ratio: float = 1.50
    min_rr: float = 3.0
    level_near_atr: float = 3.0
    bsu_lookback: int = 96


_SOURCE = {rule["id"]: rule for rule in gerchik_source_rules()}


def _plane(close: float, price: float) -> int:
    return 1 if close > price else -1


def _beyond(value: float, price: float, side: str) -> bool:
    return value > price if side == "high" else value < price


def _initial(value: float, price: float, side: str) -> bool:
    return value <= price if side == "high" else value >= price


def _extreme(bars: F.Arr, index: int, side: str) -> float:
    return float(bars["h"][index] if side == "high" else bars["l"][index])


def _direction_fade(side: str) -> str:
    return "SHORT" if side == "high" else "LONG"


def _direction_break(side: str) -> str:
    return "LONG" if side == "high" else "SHORT"


def _known_levels(ctx: Dict[str, Any], first_open: float, close: float, atr: float, p: ShadowParams) -> List[Dict[str, Any]]:
    levels: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for raw in ctx.get("levels") or []:
        known = raw.get("known")
        if known is None or not np.isfinite(float(known)):
            continue
        if raw.get("kind") not in DAILY_LEVEL_KINDS or float(known) > first_open:
            continue
        price = float(raw["p"])
        if price <= 0 or abs(price - close) > p.level_near_atr * atr:
            continue
        key = (str(raw["side"]), round(price, 8))
        old = levels.get(key)
        if old is None or int(raw.get("strength") or 1) > int(old.get("strength") or 1):
            levels[key] = dict(raw)
    return sorted(levels.values(), key=lambda value: (abs(float(value["p"]) - close), -int(value.get("strength") or 1)))


def _source(scenario: str) -> Dict[str, Any]:
    rule = _SOURCE[SCENARIOS[scenario]]
    return {"source_rule_id": rule["id"], "source_refs": list(rule["refs"]), "source_status": SOURCE_STATUS}


def _nearest_obstacle(
    levels: List[Dict[str, Any]], direction: str, entry: float, target: float, decision_ts: float, own_price: float
) -> Optional[Dict[str, Any]]:
    options = []
    for level in levels:
        price = float(level["p"])
        if float(level.get("known") or 0.0) > decision_ts or abs(price - own_price) <= max(abs(own_price) * 1e-9, 1e-12):
            continue
        if direction == "LONG" and entry < price < target:
            options.append(level)
        if direction == "SHORT" and target < price < entry:
            options.append(level)
    if not options:
        return None
    return min(options, key=lambda value: abs(float(value["p"]) - entry))


def _verdict(
    scenario: str,
    bars: F.Arr,
    level: Dict[str, Any],
    decision_index: int,
    start_index: int,
    direction: str,
    structural_extreme: float,
    atr: float,
    confirmations: List[Dict[str, Any]],
    all_levels: List[Dict[str, Any]],
    params: ShadowParams,
    *,
    state: str = "CONFIRMED",
    rejection_reasons: Optional[List[str]] = None,
) -> Dict[str, Any]:
    sg = 1.0 if direction == "LONG" else -1.0
    decision_ts = float(bars["t"][decision_index] + 900)
    entry = float(bars["c"][decision_index])
    sl = structural_extreme - sg * params.stop_buffer_atr * atr
    risk = (entry - sl) if direction == "LONG" else (sl - entry)
    rejected = list(rejection_reasons or [])
    if not np.isfinite(risk) or risk <= 0:
        rejected.append("INVALID_STRUCTURAL_RISK")
        risk = max(abs(entry) * 1e-9, 1e-12)
    target = entry + sg * params.min_rr * risk
    obstacle = _nearest_obstacle(all_levels, direction, entry, target, decision_ts, float(level["p"]))
    if obstacle is not None:
        rejected.append("INSUFFICIENT_ROOM_BEFORE_3R")
    if rejected:
        state = "INVALIDATED"
    out = {
        "scenario": scenario,
        "version": VERSION,
        "symbol": None,
        "direction": direction,
        "state": state,
        "decision_index": int(decision_index),
        "decision_ts": decision_ts,
        "start_index": int(start_index),
        "level": dict(level),
        "confirmation": confirmations,
        "entry_reference": entry,
        "structural_sl": float(sl),
        "structural_extreme": float(structural_extreme),
        "potential_target": float(target),
        "potential_rr": float(params.min_rr),
        "obstacles": [dict(obstacle)] if obstacle is not None else [],
        "rejection_reasons": rejected,
        "implementation_status": "SHADOW_EXECUTABLE",
        "operational_parameters": {
            "touch_atr": params.touch_atr,
            "luft_atr": params.luft_atr,
            "stop_buffer_atr": params.stop_buffer_atr,
            "false_break_max_depth_atr": params.false_break_max_depth_atr,
            "approach_bars": params.approach_bars,
            "small_bar_ratio": params.small_bar_ratio,
            "breakout_impulse_ratio": params.breakout_impulse_ratio,
            "min_rr": params.min_rr,
        },
    }
    out.update(_source(scenario))
    return out


def _bounce(
    bars: F.Arr, level: Dict[str, Any], k: int, atr: float, all_levels: List[Dict[str, Any]], p: ShadowParams
) -> Optional[Dict[str, Any]]:
    if k < 2:
        return None
    price = float(level["p"])
    bpu1, bpu2 = k - 1, k
    plane1, plane2 = _plane(float(bars["c"][bpu1]), price), _plane(float(bars["c"][bpu2]), price)
    if plane1 != plane2:
        return None
    side_ext = "high" if plane1 < 0 else "low"
    ext1, ext2 = _extreme(bars, bpu1, side_ext), _extreme(bars, bpu2, side_ext)
    no_break = ext1 <= price and ext2 <= price if plane1 < 0 else ext1 >= price and ext2 >= price
    if not no_break or abs(ext1 - price) > p.touch_atr * atr or abs(ext2 - price) > p.luft_atr * atr:
        return None
    bsu = None
    for i in range(max(0, bpu1 - p.bsu_lookback), bpu1):
        ext = float(bars["h"][i] if float(bars["c"][i]) <= price else bars["l"][i])
        if abs(ext - ext1) <= p.touch_atr * atr:
            bsu = i
            break
    if bsu is None:
        return None
    if float(level.get("known") or 0.0) > float(bars["t"][bsu]):
        return None
    bsu_ext = float(bars["h"][bsu] if float(bars["c"][bsu]) <= price else bars["l"][bsu])
    approach = [abs(float(bars["c"][i]) - price) for i in range(max(bsu + 1, bpu1 - p.approach_bars), bpu1 + 1)]
    compression = len(approach) >= 3 and all(approach[i] < approach[i - 1] for i in range(1, len(approach)))
    equalizer = abs(float(bars["c"][bpu2]) - price) > abs(float(bars["c"][bpu1]) - price)
    rejected = ["COMPRESSION_WITHOUT_EQUALIZING_BAR"] if compression and not equalizer else []
    direction = "SHORT" if plane1 < 0 else "LONG"
    structural = max(float(bars["h"][bpu1]), float(bars["h"][bpu2])) if direction == "SHORT" else min(float(bars["l"][bpu1]), float(bars["l"][bpu2]))
    return _verdict(
        "BOUNCE", bars, level, k, bsu, direction, structural, atr,
        [
            {"name": "BSU", "bar_index": bsu, "price": bsu_ext},
            {"name": "BPU1", "bar_index": bpu1, "price": ext1},
            {"name": "BPU2", "bar_index": bpu2, "price": ext2},
            {"name": "compression", "value": compression},
            {"name": "equalizing_bar", "value": equalizer},
        ],
        all_levels, p, rejection_reasons=rejected,
    )


def _breakout(
    bars: F.Arr, level: Dict[str, Any], k: int, atr: float, all_levels: List[Dict[str, Any]], p: ShadowParams
) -> Optional[Dict[str, Any]]:
    if k < p.approach_bars + 10:
        return None
    price, side = float(level["p"]), str(level["side"])
    if not _beyond(float(bars["c"][k]), price, side) or not _initial(float(bars["c"][k - 1]), price, side):
        return None
    indexes = list(range(k - p.approach_bars, k))
    if float(level.get("known") or 0.0) > float(bars["t"][indexes[0]]):
        return None
    if not all(_initial(float(bars["c"][i]), price, side) for i in indexes):
        return None
    ranges = bars["h"] - bars["l"]
    baseline = float(np.median(ranges[max(0, indexes[0] - 10):indexes[0]]))
    approach_mean = float(np.mean(ranges[indexes]))
    distances = [abs(float(bars["c"][i]) - price) for i in indexes]
    compression = all(distances[i] <= distances[i - 1] for i in range(1, len(distances)))
    small_bars = baseline > 0 and approach_mean <= p.small_bar_ratio * baseline
    impulse = approach_mean > 0 and float(ranges[k]) >= p.breakout_impulse_ratio * approach_mean
    rejected = []
    if not (compression or small_bars):
        rejected.append("NO_SMALL_BAR_OR_COMPRESSION_APPROACH")
    if not impulse:
        rejected.append("NO_BREAKOUT_IMPULSE")
    direction = _direction_break(side)
    return _verdict(
        "BREAKOUT", bars, level, k, indexes[0], direction, price, atr,
        [
            {"name": "approach_small_bars", "value": small_bars, "ratio": approach_mean / baseline if baseline > 0 else None},
            {"name": "compression", "value": compression},
            {"name": "breakout_close", "bar_index": k, "price": float(bars["c"][k])},
            {"name": "impulse", "value": impulse, "range_ratio": float(ranges[k]) / approach_mean if approach_mean > 0 else None},
        ],
        all_levels, p, rejection_reasons=rejected,
    )


def _false_break_1bar(
    bars: F.Arr,
    level: Dict[str, Any],
    k: int,
    atr: float,
    daily_atr: Optional[float],
    all_levels: List[Dict[str, Any]],
    p: ShadowParams,
) -> Optional[Dict[str, Any]]:
    price, side = float(level["p"]), str(level["side"])
    if float(level.get("known") or 0.0) > float(bars["t"][k]):
        return None
    pierced = _beyond(_extreme(bars, k, side), price, side)
    if not pierced or not _initial(float(bars["c"][k]), price, side):
        return None
    ext = _extreme(bars, k, side)
    depth = abs(ext - price) / daily_atr if daily_atr is not None and daily_atr > 0 else None
    rejected = []
    if depth is None:
        rejected.append("DAILY_ATR_UNAVAILABLE")
    elif depth > p.false_break_max_depth_atr:
        rejected.append("FALSE_BREAK_DEPTH_ABOVE_0_30_DAILY_ATR")
    return _verdict(
        "FALSE_BREAK_1BAR", bars, level, k, k, _direction_fade(side), ext, atr,
        [{"name": "pierce_and_close_back", "bar_index": k, "depth_daily_atr": depth}],
        all_levels, p, rejection_reasons=rejected,
    )


def _false_break_2bar(
    bars: F.Arr, level: Dict[str, Any], k: int, atr: float, all_levels: List[Dict[str, Any]], p: ShadowParams
) -> Optional[Dict[str, Any]]:
    if k < 1:
        return None
    price, side = float(level["p"]), str(level["side"])
    first, second = k - 1, k
    if float(level.get("known") or 0.0) > float(bars["t"][first]):
        return None
    if not _beyond(float(bars["c"][first]), price, side):
        return None
    if not _beyond(float(bars["o"][second]), price, side) or not _initial(float(bars["c"][second]), price, side):
        return None
    ext = max(float(bars["h"][first]), float(bars["h"][second])) if side == "high" else min(float(bars["l"][first]), float(bars["l"][second]))
    return _verdict(
        "FALSE_BREAK_2BAR", bars, level, k, first, _direction_fade(side), ext, atr,
        [
            {"name": "first_close_beyond", "bar_index": first, "price": float(bars["c"][first])},
            {"name": "second_open_beyond", "bar_index": second, "price": float(bars["o"][second])},
            {"name": "second_close_returned", "bar_index": second, "price": float(bars["c"][second])},
        ],
        all_levels, p,
    )


def _false_break_complex(
    bars: F.Arr, level: Dict[str, Any], k: int, atr: float, all_levels: List[Dict[str, Any]], p: ShadowParams
) -> Optional[Dict[str, Any]]:
    price, side = float(level["p"]), str(level["side"])

    def plane_bar(index: int) -> bool:
        return _beyond(float(bars["o"][index]), price, side) and _beyond(float(bars["c"][index]), price, side)

    def no_reverse(index: int) -> bool:
        return float(bars["l"][index]) >= price if side == "high" else float(bars["h"][index]) <= price

    end = k - 1 if _initial(float(bars["c"][k]), price, side) else k
    start = end
    while start >= 0 and plane_bar(start):
        start -= 1
    start += 1
    count = end - start + 1
    if count < 3:
        return None
    if float(level.get("known") or 0.0) > float(bars["t"][start]):
        return None
    reverse_pierce = any(not no_reverse(i) for i in range(start, end + 1))
    returned = end == k - 1
    ext = max(float(x) for x in bars["h"][start:end + 1]) if side == "high" else min(float(x) for x in bars["l"][start:end + 1])
    rejected = ["REVERSE_PIERCE_DURING_BREAKOUT_PLANE"] if reverse_pierce else []
    state = "CONFIRMED" if returned else "FORMING"
    decision = k
    confirmations = [
        {"name": "bars_open_and_close_beyond", "count": count, "start_bar": start, "end_bar": end},
        {"name": "no_reverse_pierce", "value": not reverse_pierce},
        {"name": "return_to_initial_plane", "value": returned, "bar_index": k if returned else None},
    ]
    return _verdict(
        "FALSE_BREAK_COMPLEX", bars, level, decision, start, _direction_fade(side), ext, atr,
        confirmations, all_levels, p, state=state, rejection_reasons=rejected,
    )


def detect_gerchik_scenarios(
    ctx: Dict[str, Any], now: float, symbol: str, params: ShadowParams = ShadowParams()
) -> List[Dict[str, Any]]:
    """Повертає verdict-и, які завершуються останнім закритим M15-баром."""
    bars = ctx["m15"]
    k = F.last_closed(bars, 900, now)
    if k < max(14, params.approach_bars + 10):
        return []
    atrs = ctx.get("atr15")
    if atrs is None or len(atrs) <= k:
        atrs = F.atr(bars, 14)
    atr = float(atrs[k])
    if not np.isfinite(atr) or atr <= 0:
        return []
    first_open = float(bars["t"][k])
    daily_atr: Optional[float] = None
    if ctx.get("daily_atr") is not None:
        value = float(ctx["daily_atr"])
        daily_atr = value if np.isfinite(value) and value > 0 else None
    elif ctx.get("d1") is not None:
        d1 = ctx["d1"]
        kd = F.last_closed(d1, F.DAY, now)
        daily_values = F.atr(d1, 14)
        if 0 <= kd < len(daily_values) and np.isfinite(daily_values[kd]) and daily_values[kd] > 0:
            daily_atr = float(daily_values[kd])
    all_levels = [
        dict(level)
        for level in ctx.get("levels") or []
        if level.get("known") is not None
        and np.isfinite(float(level["known"]))
        and float(level["known"]) <= float(bars["t"][k])
    ]
    levels = _known_levels(ctx, first_open, float(bars["c"][k]), atr, params)
    out: List[Dict[str, Any]] = []
    for level in levels:
        level_rows: List[Dict[str, Any]] = []
        for detector in (_bounce, _breakout, _false_break_2bar, _false_break_complex):
            verdict = detector(bars, level, k, atr, all_levels, params)
            if verdict is not None:
                verdict["symbol"] = str(symbol).upper()
                level_rows.append(verdict)
        one_bar = _false_break_1bar(bars, level, k, atr, daily_atr, all_levels, params)
        if one_bar is not None:
            one_bar["symbol"] = str(symbol).upper()
            level_rows.append(one_bar)
        scenarios = {row["scenario"] for row in level_rows}
        # ЛП-класи взаємовиключні: найдовша підтверджена геометрія має пріоритет.
        if "FALSE_BREAK_COMPLEX" in scenarios:
            level_rows = [row for row in level_rows if row["scenario"] not in {"FALSE_BREAK_1BAR", "FALSE_BREAK_2BAR"}]
        elif "FALSE_BREAK_2BAR" in scenarios:
            level_rows = [row for row in level_rows if row["scenario"] != "FALSE_BREAK_1BAR"]
        out.extend(level_rows)
    return out
