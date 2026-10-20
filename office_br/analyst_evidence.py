"""B&R analyst evidence: immutable outcome labels and time-split evaluation.

Never claim a trained model or edge when the observed cohort is too small.
No order placement and no Office2 modifications.
"""
from __future__ import annotations

from collections import defaultdict


def labels(signals, events):
    """Resolve only unambiguous ENTRY -> first TP1 or SL.

    Each event is a dict with sig_id, level, touched_ts. Signals have
    sig_id, confirm_ts, symbol, direction, entry, sl and tp1.
    """
    by_id = defaultdict(list)
    for e in events:
        by_id[e["sig_id"]].append(e)
    out = []
    for s in signals:
        es = sorted(by_id[s["sig_id"]], key=lambda e: e["touched_ts"])
        entries = [e for e in es if e["level"] == "ENTRY"]
        if len(entries) != 1 or any(e["level"] in ("AMBIGUOUS", "DATA_GAP") for e in es):
            continue
        start = entries[0]["touched_ts"]
        outcomes = [e for e in es if e["level"] in ("TP1", "SL") and e["touched_ts"] > start]
        if not outcomes:
            continue
        first = min(e["touched_ts"] for e in outcomes)
        tied = [e for e in outcomes if e["touched_ts"] == first]
        if len(tied) != 1:
            continue
        risk = abs(float(s["entry"]) - float(s["sl"]))
        reward = (float(s["tp1"]) - float(s["entry"])) * (1 if s["direction"] == "LONG" else -1)
        if risk <= 0 or reward <= 0:
            continue
        out.append({"sig_id": s["sig_id"], "symbol": s["symbol"],
                    "confirm_ts": float(s["confirm_ts"]), "outcome_ts": first,
                    "r": reward / risk if tied[0]["level"] == "TP1" else -1.0,
                    "won": tied[0]["level"] == "TP1"})
    return sorted(out, key=lambda r: (r["confirm_ts"], r["sig_id"]))


def evaluate(records, *, min_train=100, min_test=50, cost_r=0.15):
    """Walk-forward holdout; report NO_EDGE_UNVERIFIED until enough observations.

    No fitting of a classifier without time-stamped causal features.
    """
    rows = sorted(records, key=lambda r: (r["confirm_ts"], r["sig_id"]))
    split = int(len(rows) * 0.7)
    train, test = rows[:split], rows[split:]
    if not rows or len(train) < min_train or len(test) < min_test:
        return {"status": "INSUFFICIENT_EVIDENCE", "n": len(rows),
                "train_n": len(train), "test_n": len(test),
                "trained": False, "edge_verified": False}
    # Purge training outcomes that were not known at test-period start.
    boundary = test[0]["confirm_ts"]
    train = [r for r in train if r["outcome_ts"] < boundary]
    if len(train) < min_train:
        return {"status": "INSUFFICIENT_EVIDENCE", "n": len(rows),
                "train_n": len(train), "test_n": len(test),
                "trained": False, "edge_verified": False}
    avg_train = sum(r["r"] - cost_r for r in train) / len(train)
    avg_test = sum(r["r"] - cost_r for r in test) / len(test)
    return {"status": "EVALUATED_NO_MODEL", "n": len(rows),
            "train_n": len(train), "test_n": len(test),
            "train_net_r": round(avg_train, 4), "test_net_r": round(avg_test, 4),
            "trained": False, "edge_verified": False,
            "reason": "No causal feature snapshots, fees/slippage only assumed; no proven edge"}


def evaluate_database(db, *, cost_r=0.15):
    """Read actual B&R paper events from database; never use synthetic labels."""
    import json
    from office_bridge import _fetchall
    from office_br.store import init
    init(db)
    signals = []
    for sid, symbol, direction, confirm_ts, entry, sl, targets_raw in _fetchall(
        db, "SELECT sig_id,symbol,direction,confirm_ts,entry,sl,targets_json FROM br_test_signal"
    ):
        try:
            targets = json.loads(targets_raw)
            tp1 = float(targets[0]["p"])
            signals.append({"sig_id":sid,"symbol":symbol,"direction":direction,
                            "confirm_ts":confirm_ts,"entry":entry,"sl":sl,"tp1":tp1})
        except (ValueError, TypeError, KeyError, IndexError):
            continue
    events = [{"sig_id":sid,"level":level,"touched_ts":ts} for sid,level,ts in _fetchall(
        db, "SELECT sig_id,level,touched_ts FROM br_test_event"
    )]
    return evaluate(labels(signals, events), cost_r=cost_r)
