"""One-command read-only B&R historical replay from configured production database.

Usage:
  DATABASE_URL=postgresql://... python -m office_br.m1_run_production report.json

Reads only terminal signals/events, fetches Binance USD-M public M1 candles,
writes a local report, and never modifies production tables or live filters.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from office_br.m1_export import extract
from office_br.m1_batch_replay import run


def execute(db: str, *, query: Callable[..., list[tuple]] | None = None,
            fetch: Callable[..., list[dict]] | None = None) -> dict[str, Any]:
    signals, events = extract(db, query=query)
    kwargs = {"fetch":fetch} if fetch is not None else {}
    result = run(signals, events, **kwargs)
    result["source_signal_count"] = len(signals)
    result["source_event_count"] = len(events)
    result["db_write_count"] = 0
    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m office_br.m1_run_production report.json")
    db = os.environ.get("DATABASE_URL") or os.environ.get("OFFICE_DB_URL")
    if not db:
        raise SystemExit("DATABASE_URL or OFFICE_DB_URL required")
    report = execute(db)
    output = Path(sys.argv[1])
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["summary"],ensure_ascii=False))


if __name__ == "__main__":
    main()
