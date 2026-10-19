"""Read-only B&R production export replay. No DB writes, orders or live gates.

Usage:
 python -m office_br.m1_batch_replay signals.json events.json report.json
Input signals: list of br_test_signal rows with targets_json.
Input events: list of br_test_event rows with sig_id and level.
Binance public USD-M Futures M1 endpoint is contacted only on CLI execution.
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from office_br.binance_m1_history import fetch_m1
from office_br.ledger_m1_compare import compare, summarize


def run(signals: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]],
        *, fetch: Callable[..., list[dict]] = fetch_m1, max_signals: int = 500) -> dict[str, Any]:
    if len(signals) > max_signals:
        raise ValueError("signal count exceeds explicit batch limit")
    ledger = defaultdict(list)
    for event in events:
        ledger[str(event["sig_id"])].append(event)
    results = []
    for row in sorted(signals, key=lambda s: (float(s["confirm_ts"]), str(s["sig_id"]))):
        sid = str(row["sig_id"])
        if str(row.get("status")) not in ("SL", "TP3", "AMBIGUOUS", "TIMEOUT", "DATA_GAP"):
            continue
        eligible = float(row["confirm_ts"]) + 900
        if eligible % 60:
            results.append({"sig_id":sid,"verdict":"INVALID_TIMESTAMP"})
            continue
        try:
            targets = row.get("targets")
            if targets is None:
                targets = json.loads(row["targets_json"])
            signal = dict(row, targets=targets)
            candles = fetch(str(row["symbol"]), eligible, eligible+48*3600)
            results.append(compare(signal, ledger[sid], candles))
        except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
            results.append({"sig_id":sid,"verdict":"FETCH_OR_INPUT_ERROR",
                            "error_type":type(exc).__name__})
    return {"summary":summarize(results),"results":results,
            "data_source":"BINANCE_USDM_PUBLIC_M1",
            "caution":"M1 OHLC cannot resolve within-minute ordering or actual fills",
            "production_changed":False}


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: python -m office_br.m1_batch_replay signals.json events.json report.json")
    signals = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    events = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    result = run(signals, events)
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
