"""Deterministic, closed-bar source-rule evaluators (research/shadow only).

Inputs are explicitly supplied by a closed-candle feature builder. No future
bars, network calls, hidden default thresholds, or live trading side effects.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping


def _number(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if isfinite(value) else None


def evaluate(rule_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """PASS/FAIL/UNKNOWN with explicit required inputs.

    PASS is a condition observation, NOT a recommendation to open a position.
    """
    requirements = {
        "G-SIGNAL-CLOSE": ("close", "level", "direction"),
        "G-LVL-PARANORMAL": ("range", "average_range"),
        "G-ATR-DAYUSED": ("day_range", "daily_atr"),
        "G-RR-MIN3": ("reward", "risk"),
        "G-LVL-LIMIT": ("touches", "broken"),
        "D-NO-CONFIRMATION-NO-TRADE": ("confirmed",),
        "D-HTF-LTF-CONFIRM": ("htf_agrees", "ltf_confirms"),
        "G-RISK-TRADE": ("risk_usd", "risk_budget_usd"),
        "G-RISK-DAY": ("daily_loss_usd", "daily_limit_usd"),
        "S-RISK": ("risk_usd", "risk_budget_usd"),
        "G-LVL-FLOATING": ("fixed_level",),
        "D-STOP-STRUCTURE": ("stop", "invalidation", "direction"),
        "G-NO-CHASE": ("entry", "last_price", "max_chase_distance"),
        "G-IMPULSE": ("move", "daily_atr"),
        "G-FB-DEPTH": ("break_depth", "daily_atr"),
        "D-ENTRY-CLOSE-WITHIN-HALF-ATR": ("close", "level", "daily_atr", "direction"),
        "S-SWING3": ("left_high", "center_high", "right_high", "left_low", "center_low", "right_low"),
        "G-ATR-CALC": ("previous_ranges",),
        "D-STOP-ATR-MARGIN": ("margin", "average_range"),
        "G-LUFT": ("offset", "calculated_stop"),
        "G-CHANNEL": ("channel_width", "stop_distance", "distance_to_boundary"),
        "G-BE-2R": ("profit_r", "stop_at_entry"),
        "G-CRYPTO-SCORE": ("score",),
        "G-BE": ("profit_r", "stop_at_entry"),
        "S-OTE-PD": ("entry", "range_low", "range_high", "direction"),
        "S-FVG": ("first_high", "first_low", "third_high", "third_low"),
        "D-FIB-LEVELS": ("swing_low", "swing_high"),
        "G-STOP-CALC": ("entry_price", "stop_distance"),
        "G-STOP-ATR": ("stop_distance", "daily_atr"),
        "G-LUFT-FILL": ("offset", "calculated_stop"),
        "G-STOP-CRYPTO": ("stop_distance", "entry_price"),
        "G-STOP-TECH": ("stop", "level", "direction"),
        "G-STOP-CRYPTO-TECHNICAL": ("stop", "level", "direction"),
        "G-TRIAL-100": ("closed_trades",),
        "S-RANGE": ("range_low", "range_high", "close"),
        "S-LIQUIDITY-RAID": ("swept_level", "close", "direction"),
        "D-FALSE-BREAK": ("level", "high", "low", "close", "direction"),
        "G-FALSE-BREAK-DEF": ("level", "high", "low", "close", "direction"),
        "D-REACTION-AFTER-RETURN": ("returned_inside", "reaction_confirmed"),
        "D-FIB-REACTION-NOT-LIMITS": ("zone_touched", "reaction_confirmed"),
        "G-FB-COMPLEX": ("inside_bars",),
        "G-LVL-MIRROR": ("was_resistance", "now_support"),
        "G-LVL-CONSOLIDATION": ("bars_held", "level_broken"),
        "D-LEVEL-STICKING": ("retests", "normal_pullback"),
        "D-PRESSURE": ("rising_lows", "shrinking_pullbacks", "near_level"),
        "D-CANDLE-STRENGTH": ("open", "high", "low", "close"),
        "G-LVL-TRENDBREAK": ("trend_reversed", "reversal_bar_confirmed"),
        "D-PARANORMAL-IMPULSE": ("range", "average_range"),
        "G-LVL-CONFIRM-SIGNS": ("touches", "false_break", "long_wick"),
        "G-FB-1BAR": ("swept_level", "returned_inside", "bars"),
        "G-FB-2BAR": ("first_closed_beyond", "second_rejected", "bars"),
        "G-BOUNCE": ("level_tested", "rejection_confirmed"),
        "G-BREAKOUT": ("closed_beyond", "held_retest"),
        "D-POST-IMPULSE-BASE": ("base_in_expected_third", "retracement_complete"),
        "S-STRUCTURE": ("previous_high", "current_high", "previous_low", "current_low"),
        "D-FRACTAL-TF": ("htf_marked_first", "ltf_same_scale"),
        "D-HTF-STRONG-CANDLE-PULLBACK": ("strong_htf_candle", "pullback_into_range", "reaction_confirmed"),
        "S-REVERSAL-CONT": ("htf_poi", "liquidity_raid", "market_structure_shift"),
        "D-SCENARIO-CHECKLIST": ("level_context", "setup_confirmed", "risk_valid"),
        "G-PRESS": ("higher_lows", "level_tested", "pullbacks_shrinking"),
        "D-VOLUME-PRICE": ("current_volume", "average_volume", "price_change"),
        "G-PROGNOSTIC": ("bar_range", "average_range", "close", "high", "low"),
        "G-TP-TRAIL": ("profit_r", "trend_confirmed", "stop_behind_extremum"),
        "S-OB": ("body_open", "body_close", "latest_body_close", "direction"),
        "G-LVL-CONSTRUCTION": ("higher_timeframe", "level_confirmed", "touches"),
        "S-PO3": ("accumulation", "manipulation", "distribution"),
        "D-LEVEL-TYPES": ("level_type",),
        "D-ELLIOTT-RULES": ("wave_1", "wave_3", "wave_5", "wave_2_respects_start", "wave_4_no_overlap"),
        "S-KAVYA-CONCEPTS": ("body_size", "bar_range", "close", "high", "low"),
        "X-QA-RUNE": ("stop_candidates_valid",),
        "G-INDICATORS-NOT-USED": ("uses_oscillator_as_entry_trigger",),
        "D-WYCKOFF-CONTEXT": ("prior_trend", "range_position", "supply_demand"),
        "D-ATR-LIMITS": ("atr", "stop_distance", "structure_valid", "risk_within_budget"),
        "D-SESSIONS-NEWS": ("high_impact_news_soon", "session_label"),
        "S-SESSIONS": ("session_name", "timezone_verified"),
        "O-CANDLE-PATTERNS": ("pattern_name", "closed_bar_confirmed"),
        "X-UX-CRB-BTW": ("entry_zone_visible", "stop_visible", "targets_visible", "management_visible"),
        "S-BLOCKS-OTHER": ("block_type", "source_verified"),
    }
    if rule_id not in requirements:
        return {"status": "UNKNOWN", "reason": "No verified predicate implemented"}
    required = requirements[rule_id]
    missing = [key for key in required if data.get(key) is None]
    if missing:
        return {"status": "UNKNOWN", "missing_inputs": missing}
    if rule_id == "S-BLOCKS-OTHER":
        kind, verified = data["block_type"], data["source_verified"]
        if kind not in ("BREAKER", "MITIGATION", "REJECTION", "STB", "BTS") or not isinstance(verified, bool):
            return {"status": "UNKNOWN"}
        if not verified:
            return {"status": "UNKNOWN", "reason": "source diagrams inconsistent"}
        return {"status": "PASS", "block_type": kind, "note": "classification only"}
    elif rule_id == "X-UX-CRB-BTW":
        flags = [data[k] for k in ("entry_zone_visible", "stop_visible", "targets_visible", "management_visible")]
        if not all(isinstance(v, bool) for v in flags):
            return {"status": "UNKNOWN"}
        passed = all(flags)
    elif rule_id == "O-CANDLE-PATTERNS":
        name, closed = data["pattern_name"], data["closed_bar_confirmed"]
        allowed = ("ENGULFING", "HARAMI", "MORNING_STAR", "EVENING_STAR", "THREE_SOLDIERS", "THREE_CROWS")
        if name not in allowed or not isinstance(closed, bool):
            return {"status": "UNKNOWN"}
        return {"status": "PASS" if closed else "FAIL", "pattern": name,
                "note": "pattern must be independently detected from closed bars"}
    elif rule_id == "S-SESSIONS":
        name, verified = data["session_name"], data["timezone_verified"]
        if name not in ("ASIA", "LONDON", "NEW_YORK", "OFF_HOURS") or not isinstance(verified, bool):
            return {"status": "UNKNOWN"}
        if not verified:
            return {"status": "UNKNOWN", "reason": "source timezone ambiguous"}
        return {"status": "PASS", "session": name, "note": "session label only, not entry approval"}
    elif rule_id == "D-SESSIONS-NEWS":
        news, session = data["high_impact_news_soon"], data["session_label"]
        if not isinstance(news, bool) or session not in ("ASIA", "EUROPE", "US", "OFF_HOURS"):
            return {"status": "UNKNOWN"}
        return {"status": "FAIL" if news else "PASS", "session": session,
                "note": "news proximity must be supplied from a verified calendar"}
    elif rule_id == "D-ATR-LIMITS":
        atr, distance = _number(data, "atr"), _number(data, "stop_distance")
        structure, risk = data["structure_valid"], data["risk_within_budget"]
        if atr is None or distance is None or atr <= 0 or distance <= 0 or not isinstance(structure, bool) or not isinstance(risk, bool):
            return {"status": "UNKNOWN"}
        return {"status": "PASS" if structure and risk else "FAIL", "stop_atr_multiple": distance / atr}
    elif rule_id == "D-WYCKOFF-CONTEXT":
        trend, position, balance = (data[k] for k in ("prior_trend", "range_position", "supply_demand"))
        if trend not in ("UP", "DOWN", "RANGE") or position not in ("UPPER", "LOWER", "MIDDLE") or balance not in ("BUYERS", "SELLERS", "BALANCED"):
            return {"status": "UNKNOWN"}
        return {"status": "PASS", "prior_trend": trend, "range_position": position,
                "supply_demand": balance, "note": "context only, no phase prediction"}
    elif rule_id == "G-INDICATORS-NOT-USED":
        uses_indicator = data["uses_oscillator_as_entry_trigger"]
        if not isinstance(uses_indicator, bool):
            return {"status": "UNKNOWN"}
        passed = not uses_indicator
    elif rule_id == "X-QA-RUNE":
        flags = data["stop_candidates_valid"]
        if not isinstance(flags, (list, tuple)) or not flags or not all(isinstance(v, bool) for v in flags):
            return {"status": "UNKNOWN"}
        passed = any(flags)
    elif rule_id == "S-KAVYA-CONCEPTS":
        body, span, close, high, low = (_number(data, k) for k in ("body_size", "bar_range", "close", "high", "low"))
        if any(v is None for v in (body, span, close, high, low)) or span <= 0 or body < 0 or body > span or high <= low or not low <= close <= high:
            return {"status": "UNKNOWN"}
        return {"status": "PASS", "body_fraction": body / span,
                "close_location": (close - low) / (high - low),
                "note": "candle observations only"}
    elif rule_id == "D-ELLIOTT-RULES":
        lengths = [_number(data, k) for k in ("wave_1", "wave_3", "wave_5")]
        second, fourth = data["wave_2_respects_start"], data["wave_4_no_overlap"]
        if any(v is None or v <= 0 for v in lengths) or not isinstance(second, bool) or not isinstance(fourth, bool):
            return {"status": "UNKNOWN"}
        passed = second and fourth and lengths[1] >= min(lengths[0], lengths[2]) and lengths[2] >= min(lengths[0], lengths[1])
    elif rule_id == "D-LEVEL-TYPES":
        level_type = data["level_type"]
        allowed = ("trend_break", "limit_player", "paranormal_bar", "consolidation", "gap_false_break")
        if not isinstance(level_type, str) or level_type not in allowed:
            return {"status": "UNKNOWN", "reason": "unknown level classification"}
        return {"status": "PASS", "level_type": level_type, "note": "classification only"}
    elif rule_id == "S-PO3":
        stages = [data[k] for k in ("accumulation", "manipulation", "distribution")]
        if not all(isinstance(v, bool) for v in stages):
            return {"status": "UNKNOWN"}
        passed = all(stages)
    elif rule_id == "G-LVL-CONSTRUCTION":
        htf, confirmed = data["higher_timeframe"], data["level_confirmed"]
        touches = _number(data, "touches")
        if not isinstance(htf, bool) or not isinstance(confirmed, bool) or touches is None or touches < 0 or not touches.is_integer():
            return {"status": "UNKNOWN"}
        passed = htf and confirmed and touches > 0
    elif rule_id == "S-OB":
        op, cl, latest = (_number(data, k) for k in ("body_open", "body_close", "latest_body_close"))
        direction = data["direction"]
        if any(v is None for v in (op, cl, latest)) or op == cl or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        midpoint = (op + cl) / 2
        invalidated = latest < midpoint if direction == "LONG" else latest > midpoint
        return {"status": "FAIL" if invalidated else "PASS", "mean_threshold": midpoint,
                "note": "body-close threshold only; block detection upstream"}
    elif rule_id == "G-TP-TRAIL":
        profit = _number(data, "profit_r")
        trend = data["trend_confirmed"]
        stop = data["stop_behind_extremum"]
        if profit is None or not isinstance(trend, bool) or not isinstance(stop, bool):
            return {"status": "UNKNOWN"}
        passed = profit > 3 and trend and stop
    elif rule_id == "G-PROGNOSTIC":
        size, average, close, high, low = (_number(data, k) for k in ("bar_range", "average_range", "close", "high", "low"))
        if any(v is None for v in (size, average, close, high, low)) or average <= 0 or high <= low or not low <= close <= high:
            return {"status": "UNKNOWN"}
        return {"status": "PASS", "paranormal": size >= 2 * average,
                "close_position": (close-low)/(high-low),
                "note": "observations only; no invented combined score"}
    elif rule_id == "D-VOLUME-PRICE":
        volume, average, change = (_number(data, k) for k in ("current_volume", "average_volume", "price_change"))
        if volume is None or average is None or change is None or volume < 0 or average <= 0:
            return {"status": "UNKNOWN", "reason": "invalid volume/price"}
        return {"status": "PASS", "volume_ratio": volume / average, "price_direction": "UP" if change > 0 else "DOWN" if change < 0 else "FLAT", "note": "measurement only"}
    elif rule_id == "G-PRESS":
        flags = [data[k] for k in ("higher_lows", "level_tested", "pullbacks_shrinking")]
        if not all(isinstance(v, bool) for v in flags):
            return {"status": "UNKNOWN", "reason": "invalid pressure observations"}
        passed = all(flags)
    elif rule_id == "D-SCENARIO-CHECKLIST":
        flags = [data[k] for k in ("level_context", "setup_confirmed", "risk_valid")]
        if not all(isinstance(v, bool) for v in flags):
            return {"status": "UNKNOWN"}
        passed = all(flags)
    elif rule_id == "S-REVERSAL-CONT":
        flags = [data[k] for k in ("htf_poi", "liquidity_raid", "market_structure_shift")]
        if not all(isinstance(v, bool) for v in flags):
            return {"status": "UNKNOWN"}
        passed = all(flags)
    elif rule_id == "D-HTF-STRONG-CANDLE-PULLBACK":
        flags = [data[k] for k in ("strong_htf_candle", "pullback_into_range", "reaction_confirmed")]
        if not all(isinstance(v, bool) for v in flags):
            return {"status": "UNKNOWN"}
        passed = all(flags)
    elif rule_id == "D-FRACTAL-TF":
        first, scale = data["htf_marked_first"], data["ltf_same_scale"]
        if not isinstance(first, bool) or not isinstance(scale, bool):
            return {"status": "UNKNOWN"}
        passed = first and scale
    elif rule_id == "S-STRUCTURE":
        ph, ch, pl, cl = (_number(data, k) for k in ("previous_high", "current_high", "previous_low", "current_low"))
        if any(v is None for v in (ph, ch, pl, cl)):
            return {"status": "UNKNOWN"}
        trend = "UP" if ch > ph and cl > pl else "DOWN" if ch < ph and cl < pl else "RANGE"
        return {"status": "PASS", "structure": trend}
    elif rule_id == "D-POST-IMPULSE-BASE":
        in_third = data["base_in_expected_third"]
        retraced = data["retracement_complete"]
        if not isinstance(in_third, bool) or not isinstance(retraced, bool):
            return {"status": "UNKNOWN"}
        passed = in_third and not retraced
    elif rule_id == "G-BREAKOUT":
        closed, retest = data["closed_beyond"], data["held_retest"]
        if not isinstance(closed, bool) or not isinstance(retest, bool):
            return {"status": "UNKNOWN"}
        passed = closed and retest
    elif rule_id == "G-BOUNCE":
        tested, rejected = data["level_tested"], data["rejection_confirmed"]
        if not isinstance(tested, bool) or not isinstance(rejected, bool):
            return {"status": "UNKNOWN"}
        passed = tested and rejected
    elif rule_id == "G-FB-2BAR":
        first, second = data["first_closed_beyond"], data["second_rejected"]
        bars = _number(data, "bars")
        if not isinstance(first, bool) or not isinstance(second, bool) or bars is None:
            return {"status": "UNKNOWN"}
        passed = first and second and bars == 2
    elif rule_id == "G-FB-1BAR":
        swept, returned = data["swept_level"], data["returned_inside"]
        bars = _number(data, "bars")
        if not isinstance(swept, bool) or not isinstance(returned, bool) or bars is None:
            return {"status": "UNKNOWN"}
        passed = swept and returned and bars == 1
    elif rule_id == "G-LVL-CONFIRM-SIGNS":
        touches = _number(data, "touches")
        false_break, wick = data["false_break"], data["long_wick"]
        if touches is None or not isinstance(false_break, bool) or not isinstance(wick, bool):
            return {"status": "UNKNOWN"}
        passed = touches >= 2 or false_break or wick
    elif rule_id == "D-PARANORMAL-IMPULSE":
        size = _number(data, "range")
        average = _number(data, "average_range")
        if size is None or average is None or average <= 0:
            return {"status": "UNKNOWN"}
        return {"status": "PASS", "multiple": size / average, "note": "observed size; no unsupported threshold"}
    elif rule_id == "G-LVL-TRENDBREAK":
        reversed_trend = data["trend_reversed"]
        reversal_bar = data["reversal_bar_confirmed"]
        if not isinstance(reversed_trend, bool) or not isinstance(reversal_bar, bool):
            return {"status": "UNKNOWN"}
        passed = reversed_trend and reversal_bar
    elif rule_id == "D-CANDLE-STRENGTH":
        op, high, low, close = (_number(data, k) for k in ("open", "high", "low", "close"))
        if any(v is None for v in (op, high, low, close)) or high <= low or not low <= op <= high or not low <= close <= high:
            return {"status": "UNKNOWN"}
        return {"status": "PASS", "close_location": (close-low)/(high-low), "body_fraction": abs(close-op)/(high-low)}
    elif rule_id == "D-PRESSURE":
        flags = [data[k] for k in ("rising_lows", "shrinking_pullbacks", "near_level")]
        if not all(isinstance(v, bool) for v in flags):
            return {"status": "UNKNOWN"}
        passed = all(flags)
    elif rule_id == "D-LEVEL-STICKING":
        retests = _number(data, "retests")
        pullback = data["normal_pullback"]
        if retests is None or not isinstance(pullback, bool):
            return {"status": "UNKNOWN"}
        passed = retests >= 2 and not pullback
    elif rule_id == "G-LVL-CONSOLIDATION":
        bars = _number(data, "bars_held")
        broken = data["level_broken"]
        if bars is None or not isinstance(broken, bool):
            return {"status": "UNKNOWN"}
        passed = bars >= 2 and not broken
    elif rule_id == "G-LVL-MIRROR":
        before = data["was_resistance"]
        after = data["now_support"]
        if not isinstance(before, bool) or not isinstance(after, bool):
            return {"status": "UNKNOWN"}
        passed = before and after
    elif rule_id == "G-FB-COMPLEX":
        bars = _number(data, "inside_bars")
        if bars is None or bars < 0 or not bars.is_integer():
            return {"status": "UNKNOWN"}
        passed = bars >= 3
    elif rule_id == "D-FIB-REACTION-NOT-LIMITS":
        touched = data["zone_touched"]
        reaction = data["reaction_confirmed"]
        if not isinstance(touched, bool) or not isinstance(reaction, bool):
            return {"status": "UNKNOWN"}
        passed = touched and reaction
    elif rule_id == "D-REACTION-AFTER-RETURN":
        returned = data["returned_inside"]
        reaction = data["reaction_confirmed"]
        if not isinstance(returned, bool) or not isinstance(reaction, bool):
            return {"status": "UNKNOWN"}
        passed = returned and reaction
    elif rule_id == "G-FALSE-BREAK-DEF":
        level, high, low, close = (_number(data, k) for k in ("level", "high", "low", "close"))
        direction = data["direction"]
        if any(v is None for v in (level, high, low, close)) or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        passed = low < level < close if direction == "LONG" else high > level > close
    elif rule_id == "D-FALSE-BREAK":
        level, high, low, close = (_number(data, k) for k in ("level", "high", "low", "close"))
        direction = data["direction"]
        if any(v is None for v in (level, high, low, close)) or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        passed = low < level < close if direction == "LONG" else high > level > close
    elif rule_id == "S-LIQUIDITY-RAID":
        level = _number(data, "swept_level")
        close = _number(data, "close")
        direction = data["direction"]
        if level is None or close is None or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        passed = close > level if direction == "LONG" else close < level
    elif rule_id == "S-RANGE":
        low, high, close = (_number(data, k) for k in ("range_low", "range_high", "close"))
        if low is None or high is None or close is None or high <= low:
            return {"status": "UNKNOWN"}
        return {"status": "PASS", "position": (close-low)/(high-low), "equilibrium": (high+low)/2}
    elif rule_id == "G-TRIAL-100":
        count = _number(data, "closed_trades")
        if count is None or count < 0 or not count.is_integer():
            return {"status": "UNKNOWN"}
        passed = count >= 100
    elif rule_id == "G-IMPULSE":
        move = _number(data, "move")
        atr = _number(data, "daily_atr")
        if move is None or atr is None or atr <= 0:
            return {"status": "UNKNOWN"}
        passed = abs(move) >= 2 * atr
    elif rule_id == "G-STOP-CRYPTO-TECHNICAL":
        stop = _number(data, "stop")
        level = _number(data, "level")
        direction = data["direction"]
        if stop is None or level is None or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        passed = stop < level if direction == "LONG" else stop > level
    elif rule_id == "G-STOP-TECH":
        stop = _number(data, "stop")
        level = _number(data, "level")
        direction = data["direction"]
        if stop is None or level is None or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        passed = stop < level if direction == "LONG" else stop > level
    elif rule_id == "G-STOP-CRYPTO":
        distance = _number(data, "stop_distance")
        price = _number(data, "entry_price")
        if distance is None or price is None or price <= 0:
            return {"status": "UNKNOWN"}
        passed = distance <= .02 * price and distance > 0
    elif rule_id == "G-LUFT-FILL":
        offset = _number(data, "offset")
        stop = _number(data, "calculated_stop")
        if offset is None or stop is None or stop <= 0:
            return {"status": "UNKNOWN"}
        passed = offset >= .2 * stop
    elif rule_id == "G-STOP-ATR":
        distance = _number(data, "stop_distance")
        atr = _number(data, "daily_atr")
        if distance is None or atr is None or atr <= 0:
            return {"status": "UNKNOWN"}
        passed = .06 * atr <= distance <= .15 * atr
    elif rule_id == "G-STOP-CALC":
        price = _number(data, "entry_price")
        stop = _number(data, "stop_distance")
        if price is None or stop is None or price <= 0:
            return {"status": "UNKNOWN"}
        passed = .001 * price <= stop <= .002 * price
    elif rule_id == "D-FIB-LEVELS":
        low = _number(data, "swing_low")
        high = _number(data, "swing_high")
        if low is None or high is None or high <= low:
            return {"status": "UNKNOWN"}
        return {"status": "PASS", "levels": {str(k): low + (high-low)*k for k in (0, .236, .382, .5, .618, .786, 1)}}
    elif rule_id == "S-FVG":
        a, b, c, d = (_number(data, k) for k in ("first_high", "first_low", "third_high", "third_low"))
        if any(v is None for v in (a, b, c, d)):
            return {"status": "UNKNOWN"}
        passed = d > a or c < b
    elif rule_id == "S-OTE-PD":
        entry, low, high = (_number(data, k) for k in ("entry", "range_low", "range_high"))
        direction = data["direction"]
        if entry is None or low is None or high is None or high <= low or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        position = (entry - low) / (high - low)
        passed = position < 0.5 if direction == "LONG" else position > 0.5
    elif rule_id == "G-BE":
        profit = _number(data, "profit_r")
        moved = data["stop_at_entry"]
        if profit is None or not isinstance(moved, bool):
            return {"status": "UNKNOWN"}
        passed = profit >= 2 and moved
    elif rule_id == "G-CRYPTO-SCORE":
        score = _number(data, "score")
        if score is None or score < 0 or score > 10:
            return {"status": "UNKNOWN"}
        passed = score >= 5
    elif rule_id == "G-BE-2R":
        profit = _number(data, "profit_r")
        breakeven = data["stop_at_entry"]
        if profit is None or not isinstance(breakeven, bool):
            return {"status": "UNKNOWN"}
        passed = profit >= 2 and breakeven
    elif rule_id == "G-CHANNEL":
        width, stop, room = (_number(data, k) for k in ("channel_width", "stop_distance", "distance_to_boundary"))
        if width is None or stop is None or room is None or stop <= 0:
            return {"status": "UNKNOWN"}
        passed = width >= 6 * stop and room >= 4 * stop
    elif rule_id == "G-LUFT":
        offset = _number(data, "offset")
        stop = _number(data, "calculated_stop")
        if offset is None or stop is None or stop <= 0:
            return {"status": "UNKNOWN"}
        passed = abs(offset - 0.2 * stop) <= 1e-9 * max(1, stop)
    elif rule_id == "D-STOP-ATR-MARGIN":
        margin = _number(data, "margin")
        average = _number(data, "average_range")
        if margin is None or average is None or average <= 0:
            return {"status": "UNKNOWN"}
        passed = 0.10 * average <= margin <= 0.15 * average
    elif rule_id == "G-ATR-CALC":
        ranges = data["previous_ranges"]
        if not isinstance(ranges, (tuple, list)) or not 3 <= len(ranges) <= 5:
            return {"status": "UNKNOWN", "reason": "need 3-5 prior daily bars"}
        if any(not isinstance(v, (int, float)) or not isfinite(v) or v <= 0 for v in ranges):
            return {"status": "UNKNOWN", "reason": "invalid daily ranges"}
        return {"status": "PASS", "atr": sum(ranges) / len(ranges), "note": "previous bars only"}
    elif rule_id == "S-SWING3":
        values = [_number(data, k) for k in ("left_high", "center_high", "right_high", "left_low", "center_low", "right_low")]
        if any(v is None for v in values):
            return {"status": "UNKNOWN"}
        lh, ch, rh, ll, cl, rl = values
        passed = (ch > lh and ch > rh) or (cl < ll and cl < rl)
    elif rule_id == "D-ENTRY-CLOSE-WITHIN-HALF-ATR":
        close, level, atr = (_number(data, k) for k in ("close", "level", "daily_atr"))
        direction = data["direction"]
        if close is None or level is None or atr is None or atr <= 0 or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN"}
        distance = close - level if direction == "LONG" else level - close
        passed = 0 < distance < 0.5 * atr
    elif rule_id == "G-FB-DEPTH":
        depth = _number(data, "break_depth")
        atr = _number(data, "daily_atr")
        if depth is None or atr is None or atr <= 0 or depth < 0:
            return {"status": "UNKNOWN"}
        passed = depth <= 0.30 * atr
    elif rule_id == "G-NO-CHASE":
        entry = _number(data, "entry")
        last = _number(data, "last_price")
        limit = _number(data, "max_chase_distance")
        if entry is None or last is None or limit is None:
            return {"status": "UNKNOWN", "reason": "missing price"}
        passed = abs(last - entry) <= limit if limit >= 0 else False
    elif rule_id == "D-STOP-STRUCTURE":
        stop = _number(data, "stop")
        invalidation = _number(data, "invalidation")
        direction = data["direction"]
        if stop is None or invalidation is None or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN", "reason": "invalid structural stop"}
        passed = stop <= invalidation if direction == "LONG" else stop >= invalidation
    elif rule_id == "G-LVL-FLOATING":
        fixed = data["fixed_level"]
        if not isinstance(fixed, bool):
            return {"status": "UNKNOWN", "reason": "invalid level evidence"}
        passed = fixed
    elif rule_id == "S-RISK":
        risk = _number(data, "risk_usd")
        budget = _number(data, "risk_budget_usd")
        if risk is None or budget is None or risk < 0 or budget <= 0:
            return {"status": "UNKNOWN", "reason": "invalid SMC risk inputs"}
        passed = risk <= budget
    elif rule_id == "G-RISK-DAY":
        loss = _number(data, "daily_loss_usd")
        limit = _number(data, "daily_limit_usd")
        if loss is None or limit is None or loss < 0 or limit <= 0:
            return {"status": "UNKNOWN", "reason": "invalid daily risk inputs"}
        passed = loss < limit
    elif rule_id == "G-RISK-TRADE":
        risk = _number(data, "risk_usd")
        budget = _number(data, "risk_budget_usd")
        if risk is None or budget is None or risk < 0 or budget <= 0:
            return {"status": "UNKNOWN", "reason": "invalid risk inputs"}
        passed = risk <= budget
    elif rule_id == "D-HTF-LTF-CONFIRM":
        htf, ltf = data["htf_agrees"], data["ltf_confirms"]
        if not isinstance(htf, bool) or not isinstance(ltf, bool):
            return {"status": "UNKNOWN", "reason": "invalid timeframe evidence"}
        passed = htf and ltf
    elif rule_id == "D-NO-CONFIRMATION-NO-TRADE":
        confirmed = data["confirmed"]
        if not isinstance(confirmed, bool):
            return {"status": "UNKNOWN", "reason": "invalid confirmation"}
        passed = confirmed
    elif rule_id == "G-LVL-LIMIT":
        touches = _number(data, "touches")
        broken = data["broken"]
        if touches is None or not isinstance(broken, bool):
            return {"status": "UNKNOWN", "reason": "invalid touches/broken"}
        passed = touches >= 3 and not broken
    elif rule_id == "G-SIGNAL-CLOSE":
        close, level = _number(data, "close"), _number(data, "level")
        direction = data.get("direction")
        if close is None or level is None or direction not in ("LONG", "SHORT"):
            return {"status": "UNKNOWN", "reason": "invalid price or direction"}
        passed = close > level if direction == "LONG" else close < level
    elif rule_id == "G-LVL-PARANORMAL":
        bar_range, average = _number(data, "range"), _number(data, "average_range")
        if bar_range is None or average is None or bar_range < 0 or average <= 0:
            return {"status": "UNKNOWN", "reason": "invalid bar ranges"}
        passed = bar_range >= 2 * average
    elif rule_id == "G-ATR-DAYUSED":
        day_range, atr = _number(data, "day_range"), _number(data, "daily_atr")
        if day_range is None or atr is None or day_range < 0 or atr <= 0:
            return {"status": "UNKNOWN", "reason": "invalid daily range/ATR"}
        return {"status": "PASS", "ratio": day_range / atr, "note": "measurement only; source-specific threshold not asserted"}
    else:
        reward, risk = _number(data, "reward"), _number(data, "risk")
        if reward is None or risk is None or reward < 0 or risk <= 0:
            return {"status": "UNKNOWN", "reason": "invalid reward/risk"}
        passed = reward / risk >= 3.0
    return {"status": "PASS" if passed else "FAIL", "rule_id": rule_id}
