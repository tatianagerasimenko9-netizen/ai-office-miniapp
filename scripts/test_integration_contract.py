#!/usr/bin/env python3
"""Єдиний read-only contract Brain/SMC: schema, lineage, no-lookahead і відсутність впливу на READY."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_office2_brain2 as TB  # noqa: E402
from office2.integration import from_brain, from_smc, validate_observation  # noqa: E402
from office2.smc import engine as SE  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402


def brain_ready():
    closes, seq = TB.closes_long()
    bars, ctx = TB.mk(closes, seq["trigger"])
    now = float(bars["t"][-1] + 900)
    thesis = TB.B2.thesis(ctx, "LONG", now, TB.LEVELS, 10.0)
    assert thesis and thesis["state"] == "READY"
    return thesis, ctx, now


def smc_run(bars, now=None):
    htf = FX.htf_up()
    ctx = {"m15": bars, "h1": htf, "h4": htf, "d1": htf, "w1": htf, "mn": None}
    at = float(bars["t"][-1]) + 900 if now is None else now
    result = SE.analyze(ctx, at, "TESTUSDT", real_levels=FX.REAL_LEVELS_LONG)
    return result, ctx, at


def test_brain_ready_contract_and_no_mutation():
    thesis, ctx, now = brain_ready()
    before = copy.deepcopy(thesis)
    evidence = [
        {"module": "MSS/BOS + displacement", "status": "USED", "supports": 1, "finding": "зсув підтверджено"},
        {"module": "DOM / order book", "status": "NOT_CONNECTED", "supports": 0, "finding": "немає джерела"},
    ]
    obs = from_brain(thesis, ctx, now, "XUSDT", evidence=evidence, fixture=True)
    assert thesis == before, "адаптер змінив вихід Brain"
    assert obs["method"] == "BRAIN" and obs["state"] == "ENTRY_READY"
    assert obs["entry"]["price"] == thesis["entry"] and obs["targets"] == thesis["targets"]
    assert obs["lineage"]["fixture"] is True and obs["lineage"]["closed_only"] is True
    assert obs["facts_for"][0]["semantic_group"] == "structure_break"
    assert obs["missing"] == [{"module": "DOM / order book", "status": "NOT_CONNECTED"}]
    assert validate_observation(obs) == []


def test_brain_wait_is_not_entry_ready():
    closes, seq = TB.closes_long()
    bars, ctx = TB.mk(closes, seq["top"])
    now = float(bars["t"][-1] + 900)
    thesis = TB.B2.thesis(ctx, "LONG", now, TB.LEVELS, 10.0)
    obs = from_brain(thesis, ctx, now, "XUSDT", fixture=True)
    assert thesis["state"] == "WAIT" and obs["state"] == "FORMING"
    assert obs["state"] != "ENTRY_READY" and validate_observation(obs) == []


def test_smc_ready_contract_and_short_mirror_taxonomy():
    result, ctx, now = smc_run(FX.reversal_long())
    model = result["models"]["LONG"]["REVERSAL"]
    before = copy.deepcopy(model)
    obs = from_smc(model, ctx, now, "TESTUSDT", fixture=True)
    assert model == before and obs["state"] == "ENTRY_READY" and obs["model"] == "REVERSAL"
    assert obs["geometry"]["points"] and obs["geometry"]["mirror_kind"] is None
    assert validate_observation(obs) == []

    short_bars = FX.reflect(FX.reversal_long(), 300.0)
    short_levels = [dict(x, p=300.0 - x["p"], side="low") for x in FX.REAL_LEVELS_LONG]
    htf = FX.reflect(FX.htf_up(), 300.0)
    short_ctx = {"m15": short_bars, "h1": htf, "h4": htf, "d1": htf, "w1": htf, "mn": None}
    short_now = float(short_bars["t"][-1]) + 900
    short_result = SE.analyze(short_ctx, short_now, "TESTUSDT", real_levels=short_levels)
    short_obs = from_smc(short_result["models"]["SHORT"]["REVERSAL"], short_ctx, short_now, "TESTUSDT", fixture=True)
    assert short_obs["direction"] == "SHORT"
    assert short_obs["geometry"]["mirror_kind"] == "symmetry_transform"
    assert validate_observation(short_obs) == []


def test_smc_observation_is_prefix_invariant():
    full = FX.reversal_long()
    cut = len(full["t"]) - 3
    part = {key: value[:cut] for key, value in full.items()}
    now = float(full["t"][cut - 1]) + 900
    a, ctx_a, _ = smc_run(part, now)
    b, ctx_b, _ = smc_run(full, now)
    oa = from_smc(a["models"]["LONG"]["REVERSAL"], ctx_a, now, "TESTUSDT", fixture=True)
    ob = from_smc(b["models"]["LONG"]["REVERSAL"], ctx_b, now, "TESTUSDT", fixture=True)
    assert oa == ob, "майбутні бари змінили observation минулого рішення"
    assert validate_observation(oa) == []


def test_validator_rejects_future_and_incomplete_ready():
    thesis, ctx, now = brain_ready()
    obs = from_brain(thesis, ctx, now, "XUSDT", fixture=True)
    future = copy.deepcopy(obs)
    future["lineage"]["max_source_ts"] = "2999-01-01T00:00:00+00:00"
    assert "max_source_ts is after decision_bar_close_utc" in validate_observation(future)
    incomplete = copy.deepcopy(obs)
    incomplete["targets"] = []
    incomplete["invalidation"] = None
    errors = validate_observation(incomplete)
    assert "ENTRY_READY requires targets" in errors
    assert "ENTRY_READY requires structural invalidation price" in errors


def main() -> int:
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
