#!/usr/bin/env python3
"""Збирає replay-частини (parts/*/*.json) всіх вікон і друкує «ознака → результат» з перевіркою на незалежному періоді.
Використання: python scripts/feature_study_report.py <parts_dir> <OUT.json>"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.learning import feature_study as FS  # noqa: E402


def main(src, out):
    rows, runs = [], 0
    for p in sorted(Path(src).glob("**/*.json")):
        j = json.loads(p.read_text())
        if j.get("error"):
            continue
        runs += 1
        rows += j["counterfactual_rows"]
    res = {"parts": runs, "events": len(rows), "brain": FS.study(rows, "BRAIN"), "smc": FS.study(rows, "SMC")}
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    b = res["brain"]
    slim = {"parts": runs, "events": len(rows), "brain_n": b.get("n"), "span": b.get("span"), "overall_mean_r": b.get("overall_mean_r"), "overall_win": b.get("overall_win"),
            "cells_tested": b.get("cells_tested"), "stable": b.get("stable"), "worst": b.get("worst"), "best": b.get("best"), "oos_filter": b.get("oos_filter")}
    print(json.dumps(slim, ensure_ascii=False, indent=1, default=float))
    print("=== УСІ КЛІТИНКИ (feature=value: n, TP/SL, mean R, train→test, status)")
    for c in b.get("all", []):
        print(f'{c["feature"]}={c["value"]}: n={c["n"]} {c["tp"]}/{c["sl"]} mean={c["mean_r"]} rest={c["rest_mean_r"]} train={c["train_mean"]}({c["train_n"]}) test={c["test_mean"]}({c["test_n"]}) {c["status"]}')


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
