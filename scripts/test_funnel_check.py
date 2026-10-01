#!/usr/bin/env python3
"""Shadow-перевірка воронки: шлях до READY технічно проходить; одноразовий запис у БД без мережі."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"
import office_bridge as B  # noqa: E402
import office_funnel_check as FC  # noqa: E402
import office_market_data as MD  # noqa: E402

p = FC.ready_path_proof()
assert p["targets_ok"] and p["final_gate_pass"] and p["ready_state"] == "READY" and p["legacy_1_5R_gross_rejected"], p
assert p["rr_weighted_net"] >= 1.5 and p["rr_tp1_net"] >= 1.0, p

tk = [{"symbol": f"C{i:03d}USDT", "lastPrice": "1.0", "priceChangePercent": str((i % 5 - 2) * 0.3), "quoteVolume": str(6e6 + i * 1e5), "highPrice": "1.02", "lowPrice": "0.98"} for i in range(120)]
tk += [{"symbol": "GAINUSDT", "lastPrice": "2.0", "priceChangePercent": "14", "quoteVolume": "40000000", "highPrice": "2.1", "lowPrice": "1.7"}]
FC._tickers = lambda: tk
MD.fetch_candles = lambda *a, **k: []
db = os.path.join(tempfile.mkdtemp(), "t.db")
B.init_office_db(db)
assert FC.run_once(db, printer=lambda *a: None) is True
assert FC.run_once(db, printer=lambda *a: None) is False, "одноразово"
rows = B._fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ?", ("LAUNCH_DIAG",))
tasks = {json.loads(r[0])["task"]: json.loads(r[0]) for r in rows}
chk = tasks["funnel_check"]
assert chk["universe"] == 121 and chk["covered_distinct"] >= 120 and chk["pullback_watch"]["total"] == 1, chk
assert tasks["funnel_ready_path"]["ready_state"] == "READY" and "funnel_deep_pass" in tasks

print("OK funnel check: шлях до READY, покриття universe, PULLBACK WATCH, одноразовий запис")
