#!/usr/bin/env python3
"""Legacy LLM path cannot create ACTIVE without Lev's SEND in the same direction. Offline."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_legacy_guard import legacy_requires_lev, legacy_scenario_status  # noqa: E402

os.environ.pop("OFFICE_LEGACY_ACTIVE_REQUIRES_LEV", None)
assert legacy_requires_lev() is True, "safe default is ON"
assert legacy_scenario_status({"send": True, "direction": "LONG", "action": "SEND"}, direction="long")["status"] == "ACTIVE"
w = legacy_scenario_status({"send": False, "direction": "LONG", "action": "WAIT", "reason": "RR 1.2"}, direction="LONG")
assert w["status"] == "WATCHING" and "RR 1.2" in w["note_prefix"]
opp = legacy_scenario_status({"send": True, "direction": "SHORT", "action": "SEND"}, direction="LONG")
assert opp["status"] == "WATCHING" and "SHORT" in opp["reason"]
assert legacy_scenario_status({}, direction="LONG")["status"] == "WATCHING", "no Lev verdict -> not a plan"
os.environ["OFFICE_LEGACY_ACTIVE_REQUIRES_LEV"] = "0"
assert legacy_requires_lev() is False
assert legacy_scenario_status({}, direction="LONG", enforce=False)["status"] == "ACTIVE"
os.environ.pop("OFFICE_LEGACY_ACTIVE_REQUIRES_LEV", None)

# The relay source really routes the legacy ACTIVE upsert through the guard.
src = (Path(__file__).resolve().parent.parent / "office_relay_wizard.py").read_text(encoding="utf-8")
i = src.index('signal_id = f"proactive-{symbol}-{int(time.time())}"')
block = src[i - 1500:i + 900]
assert "legacy_scenario_status" in block and 'status=legacy["status"]' in block
assert 'status="ACTIVE",\n                analysis_note=lev_final' not in src
print("OK legacy proactive path: ACTIVE only with Lev SEND, WATCHING otherwise, flag rollback")

# The relay helper runs end-to-end on empty market data and never returns SEND.
import ast  # noqa: E402

import office_market_data  # noqa: E402

tree = ast.parse(src)
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_lev_cycle_for_symbol")
mod = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
_orig = office_market_data.fetch_candles
office_market_data.fetch_candles = lambda s, iv, n: []
try:
    env = {"Dict": dict, "Any": object, "_lev_risk_review": lambda c, *a, **k: c, "_lev_record_thesis": lambda *a: None}
    exec(compile(mod, "office_relay_wizard.py", "exec"), env)
    res = env["_lev_cycle_for_symbol"]("SOLUSDT", None)
    assert not res.get("send"), res
    assert legacy_scenario_status(res, direction="LONG")["status"] == "WATCHING"
finally:
    office_market_data.fetch_candles = _orig
print("OK legacy helper runs on empty data and yields WATCHING")
