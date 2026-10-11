#!/usr/bin/env python3
"""Дослідження денного ліміту «3 стопи за добу UTC» (Actions, лише читання публічного архіву Binance; production не чіпає).
Використання: python scripts/gate_counterfactual.py <OUT.json>"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import binance_vision_fetch as BV  # noqa: E402
from office2.learning import gate_study as G  # noqa: E402

FX = Path(__file__).resolve().parent.parent / "fixtures" / "learning"


def main(out: str) -> None:
    events = G.load_events(str(FX / "gate_blocked_2026-10.json"), str(FX / "gate_delivered_2026-10.json"))
    mil = json.loads((FX / "gate_milestones_2026-10.json").read_text())["rows"]
    syms = sorted({e["sym"] for e in events})
    t0 = min(e["decision_ts"] for e in events)
    d0 = datetime.fromtimestamp(t0, timezone.utc).date()
    d1 = datetime.now(timezone.utc).date()
    bars, data_end, missing = {}, 0.0, []
    for s in syms:
        a = BV.fetch(s, "1m", d0, d1)
        if not a:
            missing.append(s)
            continue
        bars[s] = list(zip((float(x) for x in a["t"]), a["o"].tolist(), a["h"].tolist(), a["l"].tolist(), a["c"].tolist()))
        data_end = max(data_end, bars[s][-1][0] + 60)
    print(f"[gate] символів {len(bars)}/{len(syms)}, дані до {datetime.fromtimestamp(data_end, timezone.utc).isoformat()}; без даних: {missing}", flush=True)
    for e in events:
        sim = G.simulate_event(e, bars.get(e["sym"], []), data_end if bars.get(e["sym"]) else 0)
        # межа даних: подія без даних після рішення → NO_DATA
        e.update(sim)
        if not sim["entered"] and sim["miss_reason"] and sim["miss_reason"].startswith("NO_DATA"):
            e["no_data"] = True
    blocked = [e for e in events if e["source"] == "BLOCKED"]
    deliv = [e for e in events if e["source"] == "DELIVERED"]
    # фактичні стопи доставлених: час SL-milestone з production (а не симульований) — саме його бачить лічильник ліміту
    real_sl = {}
    for r in mil:
        if r["level"] == "SL":
            real_sl[r["sid"]] = float(r["sent"])
    for e in deliv:
        if e["id"] in real_sl:
            e["sl_milestone_ts"] = real_sl[e["id"]]
    for e in events:
        e["after_data_end"] = bool(e["decision_ts"] >= data_end - 3600)
    # валідація симуляції проти реального трекера Office2 (milestones): перший результат TP1/SL
    ms = {}
    for r in sorted(mil, key=lambda r: float(r["sent"])):
        ms.setdefault(r["sid"], []).append((r["level"], float(r["sent"])))
    agree = comp = 0
    mism = []
    for e in deliv:
        lv = [m for m in ms.get(e["id"], [])]
        first = next((m[0] for m in lv if m[0] in ("TP1", "SL")), None)
        if first is None or e.get("a_outcome") not in ("TP", "SL"):
            continue
        comp += 1
        mine = "TP1" if e["a_outcome"] == "TP" else "SL"
        if mine == first:
            agree += 1
        else:
            mism.append({"id": e["id"], "sym": e["sym"], "tracker": first, "sim": mine})
    res = {"data": {"symbols": len(bars), "missing": missing, "data_end": data_end, "events": len(events), "blocked": len(blocked), "delivered": len(deliv)},
           "validation_vs_tracker": {"compared": comp, "agree": agree, "mismatches": mism[:10]},
           "gate_timeline": G.gate_timeline(mil),
           "actual_delivered_baseline": G.metrics(deliv, "actual_delivered"),
           "blocked_summary": G.metrics([e for e in blocked if not e["after_data_end"]], "blocked_with_data"),
           "blocked_no_data_after_archive_end": sum(1 for e in blocked if e["after_data_end"]),
           "blocked_by_day": {},
           "rules": {k: G.run_rule(k, events) for k in G.RULES},
           "flags_blocked": G.flag_table(blocked), "flags_all": G.flag_table([e for e in events if e["source"] in ("BLOCKED", "DELIVERED")]),
           "blocked_rows": [{"id": e["id"], "sym": e["sym"], "dir": e["dir"], "ts": e["decision_ts"], "entered": e.get("entered"), "a": e.get("a_outcome"), "pnl_a": e.get("pnl_a"), "pnl_b": e.get("pnl_b"), "miss": (e.get("miss_reason") or "")[:60],
                            "kind": e.get("kind"), "flags": G.risk_flag_count(e)} for e in blocked]}
    for d in sorted({G._day(e["decision_ts"]) for e in blocked}):
        res["blocked_by_day"][datetime.fromtimestamp(d * 86400, timezone.utc).date().isoformat()] = G.metrics([e for e in blocked if G._day(e["decision_ts"]) == d])
    xs = [e["r_a"] for e in blocked if e.get("a_outcome") in ("TP", "SL") and e.get("r_a") is not None]
    res["blocked_expectancy_ci95"] = G.bootstrap_mean_ci(xs)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    c = {k: {x: v[x] for x in ("admitted", "entered", "tp1_first", "sl_first", "unresolved", "pnl_a_usd", "pnl_b_usd", "expectancy_r_a", "profit_factor_a", "max_drawdown_usd")} for k, v in res["rules"].items()}
    print(json.dumps({"data": res["data"], "validation": res["validation_vs_tracker"], "timeline": res["gate_timeline"], "actual_delivered": res["actual_delivered_baseline"], "blocked": res["blocked_summary"], "blocked_no_data": res["blocked_no_data_after_archive_end"], "blocked_ci95": res["blocked_expectancy_ci95"],
                      "blocked_by_day": res["blocked_by_day"], "rules": c, "flags_blocked": res["flags_blocked"], "flags_all": res["flags_all"]}, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1])
