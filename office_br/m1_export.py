"""Export B&R closed signals and paper events for independent historical M1 replay.

Read-only SQL. Database URL comes from environment, never logged or exported.
Usage: DATABASE_URL=... python -m office_br.m1_export /tmp/br-replay-input
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable


SIGNAL_COLUMNS = ("sig_id","symbol","direction","confirm_ts","entry","sl",
                  "targets_json","created_ts","status")
EVENT_COLUMNS = ("sig_id","level","touched_ts")
SIGNAL_SQL = ("SELECT "+", ".join(SIGNAL_COLUMNS)+" FROM br_test_signal "
              "WHERE status IN ('SL','TP3','AMBIGUOUS','TIMEOUT','DATA_GAP') "
              "ORDER BY confirm_ts,sig_id")
EVENT_SQL = ("SELECT "+", ".join(EVENT_COLUMNS)+" FROM br_test_event "
             "WHERE sig_id IN (SELECT sig_id FROM br_test_signal "
             "WHERE status IN ('SL','TP3','AMBIGUOUS','TIMEOUT','DATA_GAP')) "
             "ORDER BY sig_id,touched_ts")


def extract(db: str, *, query: Callable[..., list[tuple]] | None = None) -> tuple[list[dict],list[dict]]:
    if query is None:
        from office_bridge import _fetchall
        query = _fetchall
    signals = [dict(zip(SIGNAL_COLUMNS, row)) for row in query(db, SIGNAL_SQL)]
    events = [dict(zip(EVENT_COLUMNS, row)) for row in query(db, EVENT_SQL)]
    return signals, events


def main() -> None:
    if len(sys.argv)!=2:
        raise SystemExit("usage: python -m office_br.m1_export output_directory")
    db = os.environ.get("DATABASE_URL") or os.environ.get("OFFICE_DB_URL")
    if not db:
        raise SystemExit("DATABASE_URL or OFFICE_DB_URL required")
    output = Path(sys.argv[1])
    output.mkdir(parents=True,exist_ok=True)
    signals,events = extract(db)
    (output/"signals.json").write_text(json.dumps(signals,ensure_ascii=False),encoding="utf-8")
    (output/"events.json").write_text(json.dumps(events,ensure_ascii=False),encoding="utf-8")
    print(f"Exported {len(signals)} signals, {len(events)} events; no DB changes")


if __name__=="__main__":
    main()
