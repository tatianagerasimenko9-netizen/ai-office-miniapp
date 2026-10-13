"""Audit: which of the 82 registry rules receive inputs from real feature builders (fixture run).

Counts only what the code produces; a rule is `formed` when some builder emits its inputs,
`verified` when it also has a passing unit test (see TESTED), NOT_APPLICABLE comes from the registry.
Usage: PYTHONPATH=. python3 scripts/method_coverage_audit.py [--json]
"""
import json
import sys
from datetime import datetime, timezone

from office2 import method_context_features as MC
from office2 import method_plan_features as MP
from office2.method_closed_bar_features import daily_atr_observation, from_closed_bars
from office2.method_evidence import load_rules
from office2.method_predicates import evaluate


def bar(o, h, l, c, v=100):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def fixture_inputs():
    bars = [bar(10, 12, 9, 11) for _ in range(12)] + [bar(10, 11, 8, 10)]
    inputs = dict(from_closed_bars(bars, len(bars) - 1, daily_ranges=[4, 4, 4], day_bars=bars[-3:]))
    days = [{"high": 10 + i, "low": 5} for i in range(6)]
    inputs.update(daily_atr_observation(days, 5))
    engulf = [bar(10, 12, 8, 11), bar(11, 12, 9, 10), bar(9, 13, 8, 12)]
    for rid, val in from_closed_bars(engulf, 2).items():
        inputs.setdefault(rid, val)
    th = {"state": "READY", "dir": "LONG", "entry": 100.0, "sl": 99.0, "trigger_level": 99.5,
          "invalidation": {"price": 99.2}, "targets": [{"p": 103.0}], "sizing": {"risk_usd": 10.0}, "sequence": [{"step": "sweep"}]}
    inputs.update(MP.from_thesis(th, daily_atr=10.0, equity_usd=1000.0, closed_trades=120, daily_loss_usd=1.0, asof_bar_ts=1.0))
    ts = datetime(2026, 10, 13, 8, tzinfo=timezone.utc).timestamp()
    inputs.update(MC.session_news(ts, "OK"))
    inputs.update(MC.from_topdown({"stages": [{"tf": "D1", "state": "CONFIRMS"}, {"tf": "H1", "state": "CONFIRMS"},
                                              {"tf": "M15", "state": "CONFIRMS"}]}, 1.0))
    model = {"steps": [{"step": "MS", "ok": True}], "sweep": {"x": 1}, "htf_context": {"htf_poi": [1]},
             "pois": [{"kind": "OB", "open": 100.0, "mt": 99.0}]}
    inputs.update(MC.from_smc({"models": {"LONG": {"REVERSAL": model}}, "price": 101.0, "amd": {"stage": "D"}}, "LONG", 1.0))
    d1 = {k: [100.0] * 30 for k in "ohlc"}
    d1["h"] = [102.0] * 30
    d1["l"] = [98.0] * 30
    d1["o"][24], d1["h"][24], d1["l"][24], d1["c"][24] = 110, 111, 90, 91
    for i in range(25, 30):
        d1["o"][i], d1["h"][i], d1["l"][i], d1["c"][i] = 92, 95, 90, 92
    inputs.update(MC.d1_base_after_impulse(d1, 1.0))
    return inputs


def main():
    rules = load_rules()
    inputs = fixture_inputs()
    na = MC.scope_resolution(rules)
    rows = []
    for r in rules:
        rid = r["rule_id"]
        if rid in na:
            rows.append((rid, "NOT_APPLICABLE", na[rid]["_not_applicable"]))
        elif rid in inputs:
            basis = (inputs[rid].get("_provenance") or {}).get("basis", "SOURCE")
            res = evaluate(rid, {k: v for k, v in inputs[rid].items() if not k.startswith("_")})
            rows.append((rid, "FORMED_" + basis, res["status"]))
        else:
            rows.append((rid, "BLOCKED", "; ".join(r.get("missing_parameters") or []) or "no builder"))
    summary = {}
    for _, kind, _ in rows:
        summary[kind] = summary.get(kind, 0) + 1
    if "--json" in sys.argv:
        print(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
        return
    for rid, kind, note in rows:
        print(f"{kind:18} {rid:36} {note[:90]}")
    print(summary, "formed total:", summary.get("FORMED_SOURCE", 0) + summary.get("FORMED_HYPOTHESIS", 0))


if __name__ == "__main__":
    main()
