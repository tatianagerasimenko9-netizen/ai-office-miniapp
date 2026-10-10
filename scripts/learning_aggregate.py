#!/usr/bin/env python3
"""Зведення replay-результатів по символах: Brain vs SMC vs перетин (office2.smc.replay.summarize) + контрфактуальні варіанти ($ при ризику $10).
Використання: python scripts/learning_aggregate.py <каталог з *.json> <OUT.json>"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.learning import counterfactual as CF  # noqa: E402
from office2.smc import replay as RP  # noqa: E402


def main(src, out):
    runs, rows, quality, errors = [], [], {}, []
    for p in sorted(Path(src).glob("**/*.json")):
        j = json.loads(p.read_text())
        if j.get("error"):
            errors.append({"symbol": j.get("symbol"), "error": j["error"]})
            continue
        runs.append(j["run"])
        rows += j["counterfactual_rows"]
        quality[j["symbol"]] = j["data_quality"]
    summary = RP.summarize(runs) if runs else {}
    paired = {src: CF.paired(rows, src) for src in sorted({r["source"] for r in rows})}
    res = {"symbols": sorted(quality), "no_data": errors, "data_quality": quality, "summary": summary, "counterfactual": CF.aggregate(rows), "paired": paired, "filters": {src: CF.filter_table(rows, src) for src in sorted({r["source"] for r in rows})}}
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print(json.dumps({"symbols": res["symbols"], "no_data": errors, "engines": {k: {x: v.get(x) for x in ("ready", "scored", "missed_entry", "outcomes", "mean_r_net", "r_net_ci95", "recall")} for k, v in summary.get("engines", {}).items()},
                      "overlap": summary.get("overlap", {}) and {k: summary["overlap"][k] for k in ("both", "only_brain", "only_smc")},
                      "counterfactual": {s: {v: {x: st[x] for x in ("scored", "missed", "TP1", "SL", "mean_r_net", "usd_at_10")} for v, st in vs.items()} for s, vs in res["counterfactual"]["by_source"].items()}},
                     ensure_ascii=False, indent=1, default=float))
    print(json.dumps({"paired_vs_V0": paired, "BRAIN_by_session_and_direction": res["counterfactual"]["sessions"].get("BRAIN"), "BRAIN_by_model": summary.get("engines", {}).get("BRAIN", {}).get("by_model"), "filters": res["filters"]}, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
