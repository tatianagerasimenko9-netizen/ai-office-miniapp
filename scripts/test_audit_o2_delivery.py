#!/usr/bin/env python3
"""Read-only аудит outbox: stale/expired PENDING, event parity і timing contract."""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_o2_delivery as A  # noqa: E402
import office_bridge as OB  # noqa: E402
from office2 import engine as EN  # noqa: E402

NOW = 2_000_000.0


def _signal(db, sid, created, valid, status, delivered=None, error=None):
    OB._execute(
        db,
        "INSERT INTO office2_live_signal "
        "(scenario_id,symbol,direction,created_ts,valid_until_ts,status,msg_id,delivered_ts,last_error,snapshot_json,version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sid, "BTCUSDT", "LONG", created, valid, status, 1 if delivered else None, delivered, error, "{}", "o2-brain-2.1"),
    )


def _event(db, sid, timing, seconds_ago):
    ts = datetime.fromtimestamp(NOW - seconds_ago, tz=timezone.utc).isoformat()
    OB._execute(
        db,
        "INSERT INTO office_events(ts_utc,event_type,signal_id,payload_json) VALUES (?,?,?,?)",
        (ts, "OFFICE2_READY_SENT", sid, json.dumps({"scenario_id": sid, "timing": timing})),
    )


def test_collect_is_readonly_and_reports_delivery_truth():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "audit.db")
        OB.init_office_db(db)
        EN.init_db(db)
        _signal(db, "pending-stale", NOW - 1200, NOW + 100, "PENDING", error="retry")
        _signal(db, "pending-expired", NOW - 800, NOW - 10, "PENDING")
        _signal(db, "delivered-new", NOW - 300, NOW + 100, "DELIVERED", NOW - 280)
        _signal(db, "delivered-mismatch", NOW - 250, NOW + 100, "DELIVERED", NOW - 230)
        _signal(db, "delivered-old", NOW - 200, NOW + 100, "DELIVERED", NOW - 190)
        _signal(db, "delivered-missing", NOW - 100, NOW + 100, "DELIVERED", NOW - 90)
        _signal(db, "suppressed", NOW - 50, NOW + 100, "SUPPRESSED", error="STALE: test")
        _event(
            db,
            "delivered-new",
            {"decision_to_sent_ms": 5000, "queue_ms": 1000, "send_ms": 2000, "emit_to_sent_s": 5, "pickup_s": 1, "send_s": 2},
            280,
        )
        _event(
            db,
            "delivered-mismatch",
            {"decision_to_sent_ms": 9000, "queue_ms": 7000, "send_ms": 1000, "emit_to_sent_s": 2, "pickup_s": 1, "send_s": 1},
            230,
        )
        _event(db, "delivered-old", {"emit_to_sent_s": 4, "pickup_s": 1, "send_s": 2}, 190)
        before = OB._fetchall(db, "SELECT scenario_id,status,last_error FROM office2_live_signal ORDER BY scenario_id")
        report = A.collect(db, now=NOW, days=1, stale_pending_sec=600)
        after = OB._fetchall(db, "SELECT scenario_id,status,last_error FROM office2_live_signal ORDER BY scenario_id")

        assert before == after, "аудит змінив outbox"
        assert report["readonly"] is True and report["signals"] == 7
        assert report["statuses"] == {"PENDING": 2, "DELIVERED": 4, "SUPPRESSED": 1}
        assert report["pending"]["stale_count"] == 2 and report["pending"]["expired_count"] == 1
        assert report["delivered_without_ready_sent_event"] == ["delivered-missing"]
        timing = report["timing_contract"]
        assert timing["new_format"] == 2 and timing["old_format"] == 1
        assert timing["post_hardening_evidence"] == "AVAILABLE"
        assert any(item["code"] == "TIMING_MISMATCH" and item["scenario_id"] == "delivered-mismatch" for item in timing["issues"])
        assert report["latency"]["new_format_n"] == 2
        assert report["latency"]["suppressed"] == {"STALE": 1}


def test_no_new_format_is_explicit():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "old.db")
        OB.init_office_db(db)
        EN.init_db(db)
        _signal(db, "old", NOW - 100, NOW + 100, "DELIVERED", NOW - 90)
        _event(db, "old", {"emit_to_sent_s": 8}, 90)
        report = A.collect(db, now=NOW, days=1)
        assert report["timing_contract"]["post_hardening_evidence"] == "NO_NEW_FORMAT_EVIDENCE"
        assert report["latency"]["new_format_n"] == 0


def main() -> int:
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
