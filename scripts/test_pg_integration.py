#!/usr/bin/env python3
"""PostgreSQL integration for PR68/69 tables and queries (real PG, not SQLite).

Runs only when OFFICE_TEST_PG_URL points to a throwaway database, e.g.
  OFFICE_TEST_PG_URL=postgresql://postgres@127.0.0.1:55432/office
Never point it at production: the test creates and drops its own schema.
Without the variable it prints SKIP and exits 0 (explicitly not a pass).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

URL = os.getenv("OFFICE_TEST_PG_URL", "").strip()
if not URL:
    print("SKIP PG integration: OFFICE_TEST_PG_URL not set (not a pass)")
    raise SystemExit(0)
if "render.com" in URL or "dpg-" in URL:
    raise SystemExit("refusing to run against a Render/production database")

import psycopg  # noqa: E402

SCHEMA = "t_" + uuid.uuid4().hex[:10]
with psycopg.connect(URL, autocommit=True) as c:
    c.execute(f"CREATE SCHEMA {SCHEMA}")
sep = "&" if "?" in URL else "?"
DB = f"{URL}{sep}options=-csearch_path%3D{SCHEMA}"

try:
    from office_bridge import _fetchall, init_office_db, log_event, signal_upsert
    from office_telegram_delivery_ledger import (
        finish_delivery, get_scenario_root, mark_delivery_uncertain, migrate_delivery_ledger,
        remember_scenario_root, reserve_delivery,
    )

    # 1. Schema creation is idempotent on PG.
    init_office_db(DB)
    init_office_db(DB)
    migrate_delivery_ledger(DB)
    migrate_delivery_ledger(DB)
    tables = {r[0] for r in _fetchall(DB, "SELECT table_name FROM information_schema.tables WHERE table_schema = ?", (SCHEMA,))}
    for t in ("office_events", "office_signals", "trade_journal", "office_telegram_delivery", "office_telegram_scenario_thread"):
        assert t in tables, (t, tables)

    # 2. Delivery ledger semantics on PG.
    tok = reserve_delivery(DB, "S1|SIGNAL_ENTRY", stable=True)
    assert tok and reserve_delivery(DB, "S1|SIGNAL_ENTRY", stable=True) is None, "second reservation must fail"
    assert finish_delivery(DB, "S1|SIGNAL_ENTRY", tok, delivered=True, stable=True)
    assert reserve_delivery(DB, "S1|SIGNAL_ENTRY", stable=True) is None, "stable delivered never resent"
    t2 = reserve_delivery(DB, "S1|CONFIRM", stable=True)
    assert mark_delivery_uncertain(DB, "S1|CONFIRM", t2)
    assert reserve_delivery(DB, "S1|CONFIRM", stable=True, now=9e12) is None, "UNCERTAIN not reclaimed"

    # 3. Scenario reply root: first wins, restart-safe (fresh connections every call).
    assert get_scenario_root(DB, "S1") is None
    assert remember_scenario_root(DB, "S1", 101) == 101
    assert remember_scenario_root(DB, "S1", 202) == 101
    assert get_scenario_root(DB, "S1") == 101

    # 4. Journals and Mini App queries through the same code paths as Web.
    os.environ["DATABASE_URL"] = DB
    signal_upsert(DB, signal_id="SOLUSDT|LONG|140|142", symbol="SOLUSDT", direction="LONG", entry_low=140,
                  entry_high=142, sl=136, tp1=150, tp2=None, rr=None, status="ACTIVE", analysis_note="Чекаю ретесту")
    import office_thesis_journal as tj
    now = datetime.now(timezone.utc)
    cyc = {"action": "SEND", "send": True, "reason": "pg", "draft": {
        "symbol": "SOLUSDT", "direction": "LONG", "timeframe": "H1", "zone_lo": 140.0, "zone_hi": 142.0,
        "invalidation": 136.0, "confluence": {"setup_key": "SOLUSDT|LONG|140|142", "tags": ["OB H1"]},
        "alternative": {"direction": "SHORT", "eligible": False}, "market_context": {"regime": "RANGE"}}}
    rec = tj.record_thesis(DB, cyc, candles_by_tf={"H1": [{"ts": (now - timedelta(minutes=10)).isoformat()}]}, now_utc=now)
    assert rec and tj.latest_thesis(DB, "SOLUSDT|LONG|140|142")["version_hash"] == rec["version_hash"]
    tj._LAST.clear(); tj._LAST_RAW.clear()
    assert tj.record_thesis(DB, cyc, candles_by_tf={"H1": [{"ts": (now - timedelta(minutes=10)).isoformat()}]}, now_utc=now) is None

    from office_lev_verdict import finalize_lev
    from office_risk_context import apply_risk_officer, existing_risk_usdt
    os.environ["OFFICE_DEPO_USDT"] = "1000"
    send = finalize_lev({"symbol": "SOLUSDT", "direction": "LONG", "send_card": True, "entry": 141.0, "sl": 136.0,
                         "tp1": 150.0, "rr": 1.8, "invalidation": 136.0,
                         "confluence": {"tags": ["H1"], "n": 3, "setup_key": "SOLUSDT|LONG|140|142"},
                         "atr": {}, "liquidity": {}})
    out = apply_risk_officer(send, db_path=DB, symbol="SOLUSDT",
                             candles_ltf=[{"ts": (now - timedelta(minutes=3)).isoformat()}],
                             market_context={"data_status": "DATA_OK"})
    assert out["send"] and out["risk_mode"] == "shadow" and out["scenario_id"] == "SOLUSDT|LONG|140|142"
    assert existing_risk_usdt(DB)["status"] == "OK"

    from office_mini_v2 import audit_payload, risk_payload, scenario_detail
    det = scenario_detail("SOLUSDT|LONG|140|142")
    assert det["ok"] and det["thesis"] and det["scenario"]["display"]["zone"] == "140–142"
    rp = risk_payload()
    assert rp["shadow"] and rp["shadow"][0]["scenario_id"] == "SOLUSDT|LONG|140|142" and rp["vetoes"] == []
    au = audit_payload()
    assert au["counts"]["THESIS_VERSION"] == 1 and au["counts"]["RISK_SHADOW_REVIEW"] == 1, au
    # 5. Manual position ledger on PostgreSQL (explicit migration, idempotent, real transactions).
    import office_positions as POS
    assert not POS.schema_present(DB)
    POS.migrate_positions(DB); POS.migrate_positions(DB)
    pos = POS.open_position(DB, symbol="ETHUSDT", direction="LONG", entry="2600", qty="2", sl="2550", tp1="2700",
                            fee_usdt="1", idem_key="pg-open")
    try:
        POS.open_position(DB, symbol="ETHUSDT", direction="LONG", entry="2600", qty="2", sl="2550", idem_key="pg-open")
        raise AssertionError("duplicate idem_key must be refused")
    except POS.PositionError as e:
        assert e.code == "duplicate"
    POS.partial_exit(DB, pos["trade_id"], price="2650", qty="1", fee_usdt="0.5")
    POS.move_sl(DB, pos["trade_id"], sl="2605")
    assert existing_risk_usdt(DB)["value"] == 0.0
    closed = POS.close_position(DB, pos["trade_id"], price="2640", fee_usdt="0.5")
    assert closed["status"] == "CLOSED" and closed["outcome"] == "WIN" and closed["realized_gross_usdt"] == 90.0, closed
    assert [e["kind"] for e in closed["events"]] == ["OPEN", "PARTIAL_EXIT", "MOVE_SL", "CLOSE"]
    assert POS.stats(DB)["n"] == 1
    from office_mini_v2 import trades_payload
    assert trades_payload("closed")["positions"][0]["trade_id"] == pos["trade_id"]
    log_event(DB, "PG_PROBE", {"x": 1}, "p")
    assert json.loads(_fetchall(DB, "SELECT payload_json FROM office_events ORDER BY id DESC LIMIT 1", ())[0][0]) == {"x": 1}
finally:
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
print("OK PostgreSQL integration: idempotent schema, ledger, reply root, thesis, shadow risk, manual positions, Mini App queries")
