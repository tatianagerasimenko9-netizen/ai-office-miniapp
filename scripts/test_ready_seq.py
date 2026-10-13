"""READY sequence number: monotonic, unique, idempotent per scenario, restart- and race-safe."""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_bridge as OB
import office_ready_seq as RS


def main():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "o.db")
        OB.init_office_db(db)
        a, b, c = (RS.assign(db, f"O2|S{i}|1") for i in range(3))
        assert (a, b, c) == (1, 2, 3), (a, b, c)
        assert RS.assign(db, "O2|S1|1") == 2                   # idempotent: a retry never burns a number
        assert RS.number_of(db, "O2|S1|1") == 2 and RS.number_of(db, "nope") is None
        assert RS.label(7) == "№0007" and RS.label(12345) == "№12345" and RS.label(None) == ""
        RS._READY_DBS.clear()                                  # "restart": module state lost, DB state kept
        assert RS.assign(db, "O2|S1|1") == 2 and RS.assign(db, "O2|NEW|1") == 4
        # parallel assigners: unique numbers, no gaps for distinct scenarios
        db2 = os.path.join(td, "o2.db")
        OB.init_office_db(db2)
        RS._READY_DBS.discard(db2)
        res, errs = {}, []

        def work(i):
            try:
                res[i] = RS.assign(db2, f"O2|P{i}|1")
            except Exception as exc:  # noqa: BLE001
                errs.append(repr(exc))
        ts = [threading.Thread(target=work, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert not errs, errs
        assert sorted(res.values()) == list(range(1, 13)), sorted(res.values())
        import office_user_messages as M
        assert M.scenario_event(symbol="TIAUSDT", direction="LONG", level="TP1", price=0.6254, number=7).startswith("🎯 TIA · TP1 · №0007\n")
        assert M.scenario_event(symbol="TIAUSDT", direction="LONG", level="SL", price=0.5686, number=12).startswith("❌ TIA · СТОП · №0012\n")
        assert "№" not in M.scenario_event(symbol="TIAUSDT", direction="LONG", level="TP2", price=0.65)
        assert M.scenario_event(symbol="TIAUSDT", direction="LONG", level="ENTRY", price=0.59, number=3).startswith("🟡 TIA · ВХІД ТОРКНУТО · №0003")
        # the number is NOT a message id and never depends on one
        assert "message_id" not in open(RS.__file__, encoding="utf-8").read().replace("Not the Telegram message_id", "")
    print("OK test_ready_seq")


if __name__ == "__main__":
    main()
