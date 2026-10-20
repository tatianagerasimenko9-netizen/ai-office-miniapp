import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.outcome_audit import audit

BASE = {"direction": "LONG", "entry": 100, "sl": 99,
        "targets": [{"p": 101}, {"p": 102}, {"p": 103}]}


def test_valid_ledger():
    events = [{"level": "ENTRY", "touched_ts": 1}, {"level": "TP1", "touched_ts": 2},
              {"level": "TP2", "touched_ts": 3}, {"level": "SL", "touched_ts": 4}]
    assert audit(BASE, events)["valid"]


def test_outcome_before_entry():
    x = audit(BASE, [{"level": "ENTRY", "touched_ts": 3},
                     {"level": "SL", "touched_ts": 2}])
    assert "SL_NOT_AFTER_ENTRY" in x["issues"]


def test_missing_entry_and_targets():
    x = audit(BASE, [{"level": "TP2", "touched_ts": 3}])
    assert "OUTCOME_WITHOUT_ENTRY" in x["issues"]
    assert "TP2_WITHOUT_TP1" in x["issues"]


def test_invalid_geometry_and_ambiguous():
    bad = dict(BASE, sl=101)
    x = audit(bad, [{"level": "ENTRY", "touched_ts": 1},
                    {"level": "AMBIGUOUS", "touched_ts": 2},
                    {"level": "TP1", "touched_ts": 3}])
    assert "INVALID_STOP_GEOMETRY" in x["issues"]
    assert "AMBIGUOUS_WITH_DETERMINISTIC_OUTCOME" in x["issues"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
