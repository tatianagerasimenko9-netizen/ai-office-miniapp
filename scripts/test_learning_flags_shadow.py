#!/usr/bin/env python3
"""Shadow-мітки READY: AGAINST_BTC_24H / RISK_LT_1PCT додаються лише як позначки; COST_HEAVY/OFF_HOURS без змін."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.engine import learning_flag_codes as F  # noqa: E402

bad = []


def check(n, c):
    if not c:
        bad.append(n)
        print("FAIL", n)


check("LONG при BTC 24h<0 → проти", "AGAINST_BTC_24H" in F(0.1, None, {"btc_ret_24h": -0.4}, "LONG", 1.5))
check("LONG при BTC 24h>0 → за", "AGAINST_BTC_24H" not in F(0.1, None, {"btc_ret_24h": 0.4}, "LONG", 1.5))
check("SHORT при BTC 24h>0 → проти", "AGAINST_BTC_24H" in F(0.1, None, {"btc_ret_24h": 0.4}, "SHORT", 1.5))
check("SHORT при BTC 24h<0 → за", "AGAINST_BTC_24H" not in F(0.1, None, {"btc_ret_24h": -0.4}, "SHORT", 1.5))
check("немає BTC → без мітки і без винятку", F(0.1, None, {}, "LONG", 1.5) == [] and F(0.1, None, None, "LONG", None) == [])
check("ризик <1% → мітка", "RISK_LT_1PCT" in F(0.1, None, {}, "LONG", 0.76))
check("ризик ≥1% → без мітки", "RISK_LT_1PCT" not in F(0.1, None, {}, "LONG", 1.2))
check("старі мітки лишились", F(0.3, {"session": "OFF_HOURS"}, {}, "LONG", 0.5)[:2] == ["COST_HEAVY", "OFF_HOURS"])
print("OK" if not bad else f"FAIL {bad}")
sys.exit(1 if bad else 0)
