#!/usr/bin/env python3
"""Fixtures п'яти Gerchik shadow-сценаріїв, негативи й no-lookahead."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Dict

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from office2.integration import (  # noqa: E402
    SCENARIOS,
    ShadowParams,
    detect_gerchik_scenarios,
    from_gerchik_scenario,
    gerchik_scenario_inventory,
    gerchik_source_rules,
    validate_observation,
)


def base_ctx(n: int = 48) -> Dict:
    t = np.arange(n, dtype=float) * 900.0
    o = np.full(n, 98.0)
    h = np.full(n, 98.5)
    l = np.full(n, 97.5)
    c = np.full(n, 98.0)
    v = np.full(n, 10.0)
    bars = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "tbv": v / 2.0}
    return {
        "m15": bars,
        "atr15": np.ones(n),
        "daily_atr": 1.0,
        "daily_atr_known_ts": 0.0,
        "levels": [{"p": 100.0, "side": "high", "kind": "D1SW", "known": 0.0, "strength": 2}],
    }


def set_bar(ctx: Dict, i: int, o: float, h: float, l: float, c: float) -> None:
    for key, value in (("o", o), ("h", h), ("l", l), ("c", c)):
        ctx["m15"][key][i] = value


def at(ctx: Dict, k: int) -> float:
    return float(ctx["m15"]["t"][k] + 900)


def only(ctx: Dict, k: int, scenario: str) -> Dict:
    rows = [row for row in detect_gerchik_scenarios(ctx, at(ctx, k), "TESTUSDT") if row["scenario"] == scenario]
    assert rows, f"{scenario}: fixture не розпізнано"
    return rows[0]


def fixture_bounce() -> tuple[Dict, int]:
    ctx, k = base_ctx(), 39
    set_bar(ctx, 30, 99.0, 100.0, 98.7, 99.1)
    set_bar(ctx, 38, 99.0, 100.0, 98.8, 99.2)
    set_bar(ctx, 39, 99.0, 99.95, 98.6, 98.8)
    return ctx, k


def fixture_breakout() -> tuple[Dict, int]:
    ctx, k = base_ctx(), 39
    for i, close in zip((36, 37, 38), (98.8, 99.2, 99.6)):
        set_bar(ctx, i, close - 0.1, close + 0.2, close - 0.2, close)
    set_bar(ctx, 39, 99.6, 101.3, 99.4, 101.0)
    return ctx, k


def fixture_false_1bar(depth: float = 0.20) -> tuple[Dict, int]:
    ctx, k = base_ctx(), 39
    set_bar(ctx, k, 99.0, 100.0 + depth, 98.7, 99.2)
    return ctx, k


def fixture_false_2bar() -> tuple[Dict, int]:
    ctx, k = base_ctx(), 39
    set_bar(ctx, 38, 99.2, 100.4, 99.0, 100.2)
    set_bar(ctx, 39, 100.1, 100.3, 99.4, 99.7)
    return ctx, k


def fixture_false_complex(reverse_pierce: bool = False) -> tuple[Dict, int]:
    ctx, k = base_ctx(), 39
    for i, close in zip((36, 37, 38), (100.3, 100.4, 100.2)):
        set_bar(ctx, i, 100.2, close + 0.2, 99.9 if reverse_pierce and i == 37 else 100.0, close)
    set_bar(ctx, 39, 100.2, 100.3, 99.3, 99.6)
    return ctx, k


def fixtures() -> Dict[str, tuple[Dict, int]]:
    return {
        "BOUNCE": fixture_bounce(),
        "BREAKOUT": fixture_breakout(),
        "FALSE_BREAK_1BAR": fixture_false_1bar(),
        "FALSE_BREAK_2BAR": fixture_false_2bar(),
        "FALSE_BREAK_COMPLEX": fixture_false_complex(),
    }


def test_all_five_scenarios_have_source_geometry_and_shadow_contract():
    rules = {rule["id"]: rule for rule in gerchik_source_rules()}
    for scenario, (ctx, k) in fixtures().items():
        before = copy.deepcopy(ctx)
        verdict = only(ctx, k, scenario)
        assert verdict["state"] == "CONFIRMED", (scenario, verdict["rejection_reasons"])
        assert verdict["source_rule_id"] == SCENARIOS[scenario]
        assert verdict["source_refs"] == rules[SCENARIOS[scenario]]["refs"]
        assert verdict["source_status"] == "PRIMARY_TEXT_VERIFIED"
        assert verdict["level"]["kind"] == "D1SW"
        assert verdict["confirmation"] and verdict["structural_sl"] is not None
        assert verdict["potential_target"] is not None and verdict["potential_rr"] == 3.0
        obs = from_gerchik_scenario(verdict, ctx, at(ctx, k), "TESTUSDT", fixture=True)
        assert obs["state"] == "CONFIRMED" and obs["state"] != "ENTRY_READY"
        assert obs["overlay"]["scenario"] == scenario
        assert obs["source_rule_ids"] == [SCENARIOS[scenario]]
        assert validate_observation(obs) == []
        for key in ("t", "o", "h", "l", "c", "v", "tbv"):
            assert np.array_equal(ctx["m15"][key], before["m15"][key])
        assert ctx["levels"] == before["levels"]


def test_detectors_are_prefix_invariant_and_ignore_future_levels():
    for scenario, (ctx, k) in fixtures().items():
        prefix = copy.deepcopy(ctx)
        for key in prefix["m15"]:
            prefix["m15"][key] = prefix["m15"][key][:k + 1]
        prefix["atr15"] = prefix["atr15"][:k + 1]
        future = copy.deepcopy(ctx)
        future["levels"].append({"p": 99.5, "side": "high", "kind": "D1SW", "known": at(ctx, k) + 900, "strength": 9})
        a = [x for x in detect_gerchik_scenarios(prefix, at(ctx, k), "TESTUSDT") if x["scenario"] == scenario]
        b = [x for x in detect_gerchik_scenarios(future, at(ctx, k), "TESTUSDT") if x["scenario"] == scenario]
        assert a == b, f"{scenario}: майбутні бари/рівні змінили verdict"


def test_negative_depth_impulse_complex_and_room_rejections():
    deep, k = fixture_false_1bar(0.50)
    one = only(deep, k, "FALSE_BREAK_1BAR")
    assert one["state"] == "INVALIDATED"
    assert one["rejection_reasons"] == ["FALSE_BREAK_DEPTH_ABOVE_0_30_DAILY_ATR"]

    breakout, k = fixture_breakout()
    set_bar(breakout, k, 99.9, 100.15, 99.8, 100.1)
    weak = only(breakout, k, "BREAKOUT")
    assert weak["state"] == "INVALIDATED" and "NO_BREAKOUT_IMPULSE" in weak["rejection_reasons"]

    complex_ctx, k = fixture_false_complex(reverse_pierce=True)
    complex_row = only(complex_ctx, k, "FALSE_BREAK_COMPLEX")
    assert complex_row["state"] == "INVALIDATED"
    assert "REVERSE_PIERCE_DURING_BREAKOUT_PLANE" in complex_row["rejection_reasons"]

    bounce, k = fixture_bounce()
    bounce["levels"].append({"p": 96.0, "side": "low", "kind": "PDL", "known": 0.0, "strength": 1})
    blocked = only(bounce, k, "BOUNCE")
    assert blocked["state"] == "INVALIDATED"
    assert "INSUFFICIENT_ROOM_BEFORE_3R" in blocked["rejection_reasons"]


def test_complex_needs_three_closed_plane_bars_and_return():
    ctx, k = fixture_false_complex()
    set_bar(ctx, 36, 99.5, 100.3, 99.4, 100.2)
    rows = [x for x in detect_gerchik_scenarios(ctx, at(ctx, k), "TESTUSDT") if x["scenario"] == "FALSE_BREAK_COMPLEX"]
    assert rows == []

    forming, _ = fixture_false_complex()
    rows = [x for x in detect_gerchik_scenarios(forming, at(forming, 38), "TESTUSDT") if x["scenario"] == "FALSE_BREAK_COMPLEX"]
    assert rows and rows[0]["state"] == "FORMING"
    obs = from_gerchik_scenario(rows[0], forming, at(forming, 38), "TESTUSDT", fixture=True)
    assert obs["state"] == "FORMING" and validate_observation(obs) == []


def test_false_break_classes_are_mutually_exclusive():
    two, k = fixture_false_2bar()
    scenarios = {row["scenario"] for row in detect_gerchik_scenarios(two, at(two, k), "TESTUSDT")}
    assert "FALSE_BREAK_2BAR" in scenarios and "FALSE_BREAK_1BAR" not in scenarios

    complex_ctx, k = fixture_false_complex()
    scenarios = {row["scenario"] for row in detect_gerchik_scenarios(complex_ctx, at(complex_ctx, k), "TESTUSDT")}
    assert "FALSE_BREAK_COMPLEX" in scenarios
    assert not scenarios.intersection({"FALSE_BREAK_1BAR", "FALSE_BREAK_2BAR"})


def test_levels_without_valid_known_timestamp_are_rejected():
    ctx, k = fixture_false_1bar()
    ctx["levels"][0].pop("known")
    assert detect_gerchik_scenarios(ctx, at(ctx, k), "TESTUSDT") == []
    ctx["levels"][0]["known"] = float("nan")
    assert detect_gerchik_scenarios(ctx, at(ctx, k), "TESTUSDT") == []
    ctx["levels"][0]["known"] = "not-a-timestamp"
    assert detect_gerchik_scenarios(ctx, at(ctx, k), "TESTUSDT") == []


def test_one_bar_requires_prior_closed_daily_atr():
    ctx, k = fixture_false_1bar()
    ctx.pop("daily_atr")
    ctx.pop("daily_atr_known_ts")
    verdict = only(ctx, k, "FALSE_BREAK_1BAR")
    assert verdict["state"] == "INVALIDATED"
    assert verdict["rejection_reasons"] == ["DAILY_ATR_UNAVAILABLE"]

    ctx, k = fixture_false_1bar()
    ctx["daily_atr_known_ts"] = float(ctx["m15"]["t"][k] + 1)
    verdict = only(ctx, k, "FALSE_BREAK_1BAR")
    assert verdict["rejection_reasons"] == ["DAILY_ATR_UNAVAILABLE"]


def test_adapter_rejects_stale_verdict_and_future_confirmation():
    ctx, k = fixture_bounce()
    verdict = only(ctx, k, "BOUNCE")
    try:
        from_gerchik_scenario(verdict, ctx, at(ctx, k + 1), "TESTUSDT", fixture=True)
        raise AssertionError("stale verdict accepted")
    except ValueError as exc:
        assert "decision_index" in str(exc)

    future = copy.deepcopy(verdict)
    future["confirmation"].append({"name": "future", "bar_index": k + 1, "price": 100.0})
    try:
        from_gerchik_scenario(future, ctx, at(ctx, k), "TESTUSDT", fixture=True)
        raise AssertionError("future confirmation accepted")
    except ValueError as exc:
        assert "causal decision window" in str(exc)


def test_repeated_bounce_keeps_original_bsu_episode_id():
    ctx, k = fixture_bounce()
    first = only(ctx, k, "BOUNCE")
    set_bar(ctx, k + 1, 99.0, 99.95, 98.7, 98.9)
    second = only(ctx, k + 1, "BOUNCE")
    assert first["start_index"] == second["start_index"] == 30


def test_all_five_scenarios_have_low_side_mirror_symmetry():
    for scenario, (ctx, k) in fixtures().items():
        reflected = copy.deepcopy(ctx)
        original_h = reflected["m15"]["h"].copy()
        original_l = reflected["m15"]["l"].copy()
        for key in ("o", "c"):
            reflected["m15"][key] = 200.0 - reflected["m15"][key]
        reflected["m15"]["h"] = 200.0 - original_l
        reflected["m15"]["l"] = 200.0 - original_h
        reflected["levels"][0] = dict(reflected["levels"][0], side="low", p=100.0)
        high_side = only(ctx, k, scenario)
        low_side = only(reflected, k, scenario)
        assert low_side["direction"] != high_side["direction"], scenario
        assert low_side["source_rule_id"] == high_side["source_rule_id"]
        assert low_side["state"] == high_side["state"] == "CONFIRMED"
        assert set(low_side["operational_parameters"]) == set(vars(ShadowParams()))


def test_inventory_marks_execution_as_shadow_not_ready_gate():
    inventory = gerchik_scenario_inventory()
    assert len(inventory) == 5
    assert all(row["implementation_status"] == "SHADOW_EXECUTABLE" for row in inventory)
    assert all(row["primary_source_status"] == "PRIMARY_TEXT_VERIFIED" for row in inventory)
    assert all(row["office2_ready_impact"] != "GERCHIK_GATE" for row in inventory)


def main() -> int:
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
