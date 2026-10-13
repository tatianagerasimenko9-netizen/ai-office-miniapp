"""Offline chronological replay of causal methodology observations.

Input JSON: list of fully closed OHLCV dictionaries ordered oldest to newest.
No exchange requests, database writes, or Telegram calls.
"""
from __future__ import annotations

import argparse
import json

from office2.method_closed_bar_features import from_closed_bars
from office2.method_predicates import evaluate


def replay(bars, warmup=20):
    results = []
    for cutoff in range(max(2, warmup), len(bars)):
        evidence = from_closed_bars(bars, cutoff)
        rules = {rule: evaluate(rule, values) for rule, values in evidence.items()}
        results.append({"bar_index": cutoff, "rules": rules})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ohlcv_json", help="Ordered, fully closed OHLCV array")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    with open(args.ohlcv_json, encoding="utf-8") as handle:
        bars = json.load(handle)
    if not isinstance(bars, list):
        raise ValueError("Expected a JSON array of closed bars")
    result = replay(bars)
    payload = {"bars": len(bars), "evaluations": len(result), "results": result}
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
    else:
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
