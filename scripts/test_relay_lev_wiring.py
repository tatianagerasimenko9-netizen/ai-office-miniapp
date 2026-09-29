#!/usr/bin/env python3
"""The relay's Lev call sites really run feed gate -> shadow Risk Officer -> thesis journal.

Extracts the real closures `_ltf_interval`, `_lev_risk_review`, `_lev_record_thesis` from
office_relay_wizard.py by AST and executes them against a temporary SQLite. Offline, no Telegram.
"""
import ast
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ.pop("OFFICE_RISK_OFFICER_ENFORCE", None)

from office_bridge import _fetchall, init_office_db  # noqa: E402
from office_lev_verdict import finalize_lev  # noqa: E402

src = (ROOT / "office_relay_wizard.py").read_text(encoding="utf-8")
tree = ast.parse(src)
want = {"_ltf_interval", "_lev_risk_review", "_lev_record_thesis"}
fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in want]
assert {f.name for f in fns} == want, [f.name for f in fns]

db = str(Path(tempfile.mkdtemp()) / "wiring.db")
init_office_db(db)
env: Dict[str, Any] = {"db_path": db, "Dict": dict, "Any": Any, "datetime": datetime, "print": print}
exec(compile(ast.fix_missing_locations(ast.Module(body=fns, type_ignores=[])), "office_relay_wizard.py", "exec"), env)

now = datetime.now(timezone.utc)
fresh = [{"ts": (now - timedelta(minutes=20)).isoformat()}, {"ts": (now - timedelta(minutes=5)).isoformat()}]
stale = [{"ts": (now - timedelta(hours=3, minutes=15)).isoformat()}, {"ts": (now - timedelta(hours=3)).isoformat()}]
assert env["_ltf_interval"](fresh) == "15m" and env["_ltf_interval"]([{"ts": "x"}]) == "15m"

draft = {"symbol": "SOLUSDT", "direction": "LONG", "send_card": True, "entry": 100.0, "sl": 98.0, "tp1": 104.0,
         "rr": 2.0, "invalidation": 98.0, "zone_lo": 99.0, "zone_hi": 101.0, "timeframe": "H1",
         "confluence": {"tags": ["H1"], "n": 3, "setup_key": "SOLUSDT|LONG|99|101"},
         "atr": {}, "liquidity": {}, "alternative": {"direction": "SHORT", "eligible": False},
         "market_context": {"data_status": "DATA_UNAVAILABLE"}}
cycle = finalize_lev(draft)
assert cycle["send"]

# Fresh data: decision unchanged, shadow review journaled with the scenario id.
out = env["_lev_risk_review"](cycle, "SOLUSDT", candles_ltf=fresh, market_context={"data_status": "DATA_OK"})
assert out["send"] and out["risk_mode"] == "shadow" and out["scenario_id"] == "SOLUSDT|LONG|99|101"
# Stale data: the feed gate turns SEND into WAIT before anything else.
blocked = env["_lev_risk_review"](cycle, "SOLUSDT", candles_ltf=stale, market_context={"data_status": "DATA_OK"})
assert blocked["action"] == "WAIT" and not blocked["send"] and "STALE_SNAPSHOT" in blocked["reason"], blocked

env["_lev_record_thesis"](out, {"H1": fresh})
kinds = [r[0] for r in _fetchall(db, "SELECT event_type FROM office_events ORDER BY id", ())]
assert kinds == ["RISK_SHADOW_REVIEW", "THESIS_VERSION"], kinds

# Journal failure never changes the decision (closure swallows and logs).
env["_lev_record_thesis"]({"draft": None}, {"H1": fresh})

# Both relay call sites pass through the closures right after lev_cycle, before the decision is used.
for marker in ("cycle = _lev_risk_review(", "_lev_record_thesis(cycle,"):
    assert src.count(marker) >= 2, marker
first = src.index("cycle = lev_cycle(")
assert src.index("_lev_risk_review(", first) < src.index("hold lev_cycle", first)
print("OK relay wiring: feed gate, shadow Risk Officer and thesis journal run in the real closures")
