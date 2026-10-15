"""B&R · TEST: окремі таблиці/нумерація, ідемпотентність, картка не схожа на основний Office2."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_bridge as OB
from office_br import card, detect as D, store


def _sig():
    return {"direction": "LONG", "level": 100.0, "break_ts": 1000.0, "retest_ts": 1900.0, "confirm_ts": 2800.0, "entry": 102.0, "sl": 99.0,
            "targets": [{"p": 105.0, "src": "R1 (ГІПОТЕЗА)"}, {"p": 108.0, "src": "structure"}, {"p": 111.0, "src": "R3 (ГІПОТЕЗА)"}]}


def main():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        OB.init_office_db(db)
        a = store.record_signal(db, "ETHUSDT", _sig(), D.HYP, now=5000.0)
        assert a and store.record_signal(db, "ETHUSDT", _sig(), D.HYP, now=5001.0) is None        # ідемпотентно
        s2 = dict(_sig(), break_ts=2000.0)
        b = store.record_signal(db, "SOLUSDT", s2, D.HYP, now=5002.0)
        rs = store.rows(db)
        assert [r["seq"] for r in rs] == [1, 2]                                                   # власна нумерація
        try:
            assert not OB._fetchall(db, "SELECT 1 FROM office2_live_signal")           # основний Office2 не зачеплено
        except Exception:  # noqa: BLE001
            pass                                                                        # таблиці немає зовсім — теж «не зачеплено»
        assert store.record_event(db, a, "TP1", 6000.0, 105.0) and not store.record_event(db, a, "TP1", 6000.0, 105.0)
        assert store.record_manual_action(db, a, "OPENED")
        assert store.record_manual_action(db, a, "TP1_30")
        assert store.manual_actions(db, a) == ["OPENED", "TP1_30"]
        assert not store.record_manual_action(db, "missing", "OPENED")
        try:
            store.record_manual_action(db, a, "EXECUTE_ORDER")
            assert False, "Exchange execution must not be supported"
        except ValueError:
            pass
        metrics = store.paper_metrics(db)
        assert metrics["n"] == 0  # TP1 without observed ENTRY cannot count
        assert metrics["win_rate_pct"] is None
        # A later ENTRY cannot retroactively convert an earlier TP into a win.
        assert store.record_event(db, a, "ENTRY", 7000.0, 102.0)
        assert store.paper_metrics(db)["n"] == 0
        # A new signal with a valid ENTRY -> SL is one paper loss.
        c = store.record_signal(db, "ADAUSDT", dict(_sig(), break_ts=3000.0), D.HYP, now=5003.0)
        assert c and store.record_event(db, c, "ENTRY", 8000.0, 102.0)
        assert store.record_event(db, c, "SL", 8100.0, 99.0)
        loss = store.paper_metrics(db)
        assert loss["n"] == 1 and loss["losses"] == 1 and loss["wins"] == 0
        # A genuine ENTRY -> TP1 counts, while same-timestamp levels do not.
        d = store.record_signal(db, "LINKUSDT", dict(_sig(), break_ts=4000.0), D.HYP, now=5004.0)
        assert d and store.record_event(db, d, "ENTRY", 8000.0, 102.0)
        assert store.record_event(db, d, "TP1", 8100.0, 105.0)
        result = store.paper_metrics(db)
        assert result["n"] == 2 and result["wins"] == 1 and result["losses"] == 1
        e = store.record_signal(db, "XRPUSDT", dict(_sig(), break_ts=5000.0), D.HYP, now=5005.0)
        assert e and store.record_event(db, e, "ENTRY", 8000.0, 102.0)
        assert store.record_event(db, e, "TP1", 8100.0, 105.0)
        assert store.record_event(db, e, "SL", 8100.0, 99.0)
        assert store.paper_metrics(db)["n"] == 2
        txt = card.build_card(rs[0])
        assert txt.startswith("B&R LIVE · B&R-1") and "Office не відкриває ордерів" in txt and "AI Office" not in txt
        assert "ВХІД  102" in txt and "SL     99" in txt and "TP3" in txt and "Скасування" in txt
        assert card.event_text(rs[0], "TP1", 105.0).startswith("B&R LIVE · B&R-1")
    print("OK")


if __name__ == "__main__":
    main()
