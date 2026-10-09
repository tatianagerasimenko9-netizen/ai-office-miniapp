"""Regression: Office2 reporting separates exclusive outcomes from overlapping metrics."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import office_bridge as OB  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import stats as ST  # noqa: E402
from office2.webview import parent_id  # noqa: E402


CREATED_TS = 1_700_000_000.0


def _put(db: str, sid: str, milestones: tuple[tuple[str, int], ...], created_offset: int = 0) -> None:
    snapshot = {
        "version_id": "o2-brain-2.1",
        "thesis": {"targets": [{"r": 1.5}, {"r": 2.5}, {"r": 3.5}]},
    }
    OB._execute(
        db,
        "INSERT INTO office2_live_signal"
        "(scenario_id,symbol,direction,created_ts,valid_until_ts,status,snapshot_json,version)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (sid, "TESTUSDT", "LONG", CREATED_TS + created_offset, CREATED_TS + 21_600, "DELIVERED", json.dumps(snapshot), "test"),
    )
    for level, offset in milestones:
        touched = CREATED_TS + offset
        OB.log_event(
            db,
            "SCENARIO_MILESTONE",
            {"scenario_id": sid, "level": level, "touched_ts": touched, "sent_ts": touched + 1},
            sid,
        )


def test_exclusive_reporting_buckets() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "office2-stats.db")
        OB.init_office_db(db)
        EN.init_db(db)

        _put(db, "O2|tp-open|1", (("ENTRY", 10), ("TP1", 20)))
        _put(db, "O2|sl-final|1", (("ENTRY", 10), ("SL", 20)))
        _put(db, "O2|tp-sl-final|1", (("ENTRY", 10), ("TP1", 20), ("SL", 30)))
        _put(db, "O2|active|1", (("ENTRY", 10),))
        _put(db, "O2|same-parent|1", (("ENTRY", 10), ("SL", 20)), created_offset=1)
        _put(db, "O2|same-parent|2", (), created_offset=2)

        stats = ST.collect(db)
        brain = stats["by_brain"]["o2-brain-2.1"]
        items = [item for item in stats["items"] if item["brain"] == "o2-brain-2.1"]
        buckets = brain["outcome_buckets"]

        assert len(items) == 5
        assert len({parent_id(item["id"]) for item in items}) == 5
        assert brain["delivered"] == 5
        assert brain["tp1_first"] == 2 and brain["sl_first"] == 2 and brain["unresolved"] == 2
        assert buckets == {
            "final_tp_first": 1,
            "final_sl_first": 2,
            "final_no_first": 0,
            "open_tp_first": 1,
            "open_sl_first": 0,
            "open_no_first": 1,
        }
        assert sum(buckets.values()) == brain["delivered"]
        assert stats["total"]["outcome_buckets"] == buckets
        assert stats["counter_semantics"]["outcome_buckets"] == "mutually_exclusive_sum_to_delivered"

        tp_open = next(item for item in items if item["id"] == "O2|tp-open|1")
        assert tp_open["first"] == "TP" and tp_open["final"] is False
        html = (ROOT / "office_web" / "mini_v2.html").read_text(encoding="utf-8")
        assert "Взаємовиключно:" in html and "p99 ${sec(st[k].p99)}" in html


if __name__ == "__main__":
    test_exclusive_reporting_buckets()
    print("OK: Office2 outcome buckets are exclusive and preserve first-touch metrics")
