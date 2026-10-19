"""Read-only real B&R production training-row extraction.

Features are causally available at confirmation; terminal labels are attached
only with recorded outcome time. Never exports credentials or trades.
"""
from __future__ import annotations
import json
from typing import Any, Callable
from office_br.learning_dataset import build_row

SQL = """
SELECT s.sig_id,s.symbol,s.direction,s.confirm_ts,s.entry,s.sl,s.level,
       s.break_ts,s.retest_ts,s.status,
       e.touched_ts AS terminal_ts
FROM br_test_signal s
JOIN LATERAL (
 SELECT touched_ts FROM br_test_event
 WHERE sig_id=s.sig_id AND level=s.status
 ORDER BY touched_ts ASC LIMIT 1
) e ON TRUE
WHERE s.status IN ('SL','TP3')
ORDER BY s.confirm_ts,s.sig_id
"""

def extract(db: str, *, query: Callable[..., list[tuple]] | None = None) -> dict[str, Any]:
    if query is None:
        from office_bridge import _fetchall
        query = _fetchall
    rows = query(db, SQL)
    data, skipped = [], {}
    for (sid,symbol,direction,confirm,entry,sl,level,break_ts,retest_ts,
         status,terminal_ts) in rows:
        try:
            confirm,entry,sl,level = map(float,(confirm,entry,sl,level))
            if entry <= 0 or sl == entry or break_ts is None or retest_ts is None:
                raise ValueError("invalid geometry")
            # Use only fields present at signal confirmation. No future candle.
            features = {"risk_pct": 100*abs(entry-sl)/entry,
                        "break_to_retest_minutes": (float(retest_ts)-float(break_ts))/60,
                        "retest_to_confirm_minutes": (confirm-float(retest_ts))/60,
                        "break_level_distance_r": abs(entry-level)/abs(entry-sl)}
            if not (float(break_ts) <= float(retest_ts) <= confirm):
                raise ValueError("noncausal timestamps")
            row = build_row({"sig_id":sid,"symbol":symbol,"direction":direction,
                             "confirm_ts":confirm},features,observed_at=confirm,
                            label=status,label_observed_at=float(terminal_ts))
            data.append(row)
        except (ValueError,TypeError,OverflowError) as exc:
            name=type(exc).__name__
            skipped[name]=skipped.get(name,0)+1
    return {"schema_version":"br_features_v2","rows":data,
            "skipped":skipped,"source_rows":len(rows),
            "mode":"READ_ONLY_OFFLINE","production_changed":False}


def main() -> None:
    import os
    import sys
    from pathlib import Path
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m office_br.production_ml_export dataset.json")
    db = os.environ.get("DATABASE_URL") or os.environ.get("OFFICE_DB_URL")
    if not db:
        raise SystemExit("DATABASE_URL or OFFICE_DB_URL required")
    result = extract(db)
    Path(sys.argv[1]).write_text(json.dumps(result,ensure_ascii=False,indent=2),
                                 encoding="utf-8")
    if result["skipped"] or len(result["rows"]) != result["source_rows"]:\n        raise SystemExit("FAIL_CLOSED: production rows missing or invalid; no dataset published")\n    print(json.dumps({"source_rows":result["source_rows"],
                      "usable_rows":len(result["rows"]),
                      "skipped":result["skipped"]}))

if __name__ == "__main__":
    main()
