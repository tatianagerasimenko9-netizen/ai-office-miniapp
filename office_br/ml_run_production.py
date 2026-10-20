"""One-command real B&R read-only dataset extraction and offline model evaluation.

Run with DATABASE_URL/ OFFICE_DB_URL set, from isolated worker or secure shell.
No Telegram, orders, production model gates, or credential output.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from office_br.production_ml_export import extract
from office_br.ml_baseline_shadow import walk_forward

def execute(db: str, *, query=None) -> dict:
    dataset = extract(db, query=query)
    if len(dataset["rows"]) < 50:
        return {"status":"INSUFFICIENT_ROWS","source_rows":dataset["source_rows"],
                "usable_rows":len(dataset["rows"]),"promotion_approved":False}
    report = walk_forward(dataset["rows"],feature="risk_pct",
                          threshold=1.0,embargo_seconds=900)
    return {"status":"RESEARCH_ONLY","dataset_rows":len(dataset["rows"]),
            "source_rows":dataset["source_rows"],"skipped":dataset["skipped"],
            "report":report,"promotion_approved":False,
            "live_signal_delivery_changed":False}

def main() -> None:
    if len(sys.argv)!=2:
        raise SystemExit("usage: python -m office_br.ml_run_production output.json")
    db=os.environ.get("DATABASE_URL") or os.environ.get("OFFICE_DB_URL")
    if not db:
        raise SystemExit("DATABASE_URL or OFFICE_DB_URL required")
    result=execute(db)
    Path(sys.argv[1]).write_text(json.dumps(result,ensure_ascii=False,indent=2),
                                 encoding="utf-8")
    print(json.dumps({"status":result["status"],
                      "dataset_rows":result.get("dataset_rows"),
                      "promotion_approved":False}))

if __name__=="__main__":
    main()
