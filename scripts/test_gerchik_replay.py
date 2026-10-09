#!/usr/bin/env python3
"""Execution costs і joint-shadow aggregation для Gerchik replay."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from office2.integration import gerchik_replay as RP  # noqa: E402


def bars(n: int = 10):
    t = np.arange(n, dtype=float) * 900
    o = np.full(n, 100.0)
    h = np.full(n, 100.5)
    l = np.full(n, 99.5)
    c = np.full(n, 100.0)
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": np.ones(n), "tbv": np.ones(n) / 2}


def test_execution_applies_delay_fee_slippage_and_conservative_touch():
    data = bars()
    data["h"][2] = 103.1
    result = RP.simulate_execution(data, 0, "LONG", 100.0, 99.0, 103.0)
    assert result["fill_entry"] == 100.0 and result["outcome"] == "TP1"
    assert result["cost_rt_pct"] == 0.14
    assert abs(result["r_net"] - 2.86) < 1e-9
    assert result["entry_delay_sec"] == 30.0 and result["bar_resolution_sec"] == 900

    both = bars()
    both["h"][1], both["l"][1] = 103.1, 98.9
    result = RP.simulate_execution(both, 0, "LONG", 100.0, 99.0, 103.0)
    assert result["outcome"] == "SL", "один бар торкнувся SL і TP — консервативно SL"


def test_execution_marks_ttl_and_gap_missed_entries():
    data = bars()
    ttl = RP.simulate_execution(data, 0, "LONG", 100.0, 99.0, 103.0, entry_delay_sec=400, entry_ttl_sec=300)
    assert ttl["outcome"] == "MISSED_ENTRY_TTL" and ttl["r_net"] is None

    data["o"][1] = 103.2
    data["h"][1] = 103.3
    gap = RP.simulate_execution(data, 0, "LONG", 100.0, 99.0, 103.0)
    assert gap["outcome"] == "MISSED_TP_BEFORE_ENTRY" and gap["fill_entry"] is None


def event(source: str, ts: int, sim: dict, model: str = "X") -> dict:
    return {"source": source, "symbol": "XUSDT", "dir": "LONG", "ts_bar": ts, "model": model, "sim": sim}


def test_summary_separates_brain_smc_and_joint_shadow_without_decision():
    win = {"outcome": "TP1", "r_net": 1.5}
    loss = {"outcome": "SL", "r_net": -1.1}
    events = [
        event("BRAIN", 900, win),
        event("SMC", 900, loss),
        event("GERCHIK_SHADOW", 900, win, "BOUNCE"),
        event("BRAIN", 9000, loss),
        event("SMC", 18000, loss),
    ]
    report = RP.summarize([{
        "symbol": "XUSDT",
        "bars": 100,
        "events": events,
        "gerchik_funnel": {"rejected": 2, "rejection_reasons": {"NO_BREAKOUT_IMPULSE": 2}},
        "execution_assumptions": {"fee_rt_pct": 0.1},
    }])
    assert report["engines"]["BRAIN"]["events"] == 2
    assert report["engines"]["SMC"]["events"] == 2
    assert report["engines"]["GERCHIK_SHADOW"]["events"] == 1
    assert report["joint_shadow"]["brain_only"]["events"] == 1
    assert report["joint_shadow"]["smc_only"]["events"] == 1
    assert report["joint_shadow"]["brain_smc_gerchik_triple"]["events"] == 1
    assert report["joint_shadow"]["decision_changed"] is False
    assert report["gerchik_rejections"]["reasons"] == {"NO_BREAKOUT_IMPULSE": 2}


def test_future_shadow_event_is_not_hindsight_support():
    win = {"outcome": "TP1", "r_net": 1.5}
    report = RP.summarize([{
        "symbol": "XUSDT",
        "bars": 10,
        "events": [event("BRAIN", 900, win), event("GERCHIK_SHADOW", 1800, win, "BOUNCE")],
        "gerchik_funnel": {"rejected": 0, "rejection_reasons": {}},
        "execution_assumptions": {},
    }])
    assert report["joint_shadow"]["brain_with_gerchik_support"]["events"] == 0
    assert report["joint_shadow"]["brain_only"]["events"] == 1


def test_replay_input_validation_rejects_gaps_and_impossible_ohlc():
    data = bars()
    assert RP.validate_ohlcv(data, 900) == []
    data["t"][3] += 60
    assert "timestamps are not unique contiguous bars" in RP.validate_ohlcv(data, 900)
    data = bars()
    data["o"][2] = data["h"][2] + 1
    assert "invalid OHLC geometry" in RP.validate_ohlcv(data, 900)


def test_open_outcomes_are_descriptive_not_inferential():
    opened = {"outcome": "OPEN", "r_net": 9.0}
    report = RP.summarize([{
        "symbol": "XUSDT",
        "bars": 10,
        "events": [event("BRAIN", 900, opened)],
        "gerchik_funnel": {"rejected": 0, "rejection_reasons": {}},
        "execution_assumptions": {},
    }])
    block = report["engines"]["BRAIN"]
    assert block["events"] == 1 and block["scored_resolved"] == 0
    assert block["mean_r_net"] is None and block["r_net_ci95_clustered"] is None


def main() -> int:
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
