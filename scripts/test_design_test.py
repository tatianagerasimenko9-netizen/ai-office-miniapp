"""One-off design test: inert without the env flag, one attempt only, new 1000x1230 card, no gate/READY/lifecycle side effects."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_bridge as OB
import office_design_test as DT


class Sender:
    def __init__(self, mid=777):
        self.calls, self.mid = [], mid

    async def __call__(self, path, caption, stream="general", **kw):
        self.calls.append((path, caption, stream, kw))
        return self.mid


def run(coro):
    return asyncio.run(coro)


def main():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "o.db")
        OB.init_office_db(db)
        os.environ.pop(DT.ENV, None)
        s = Sender()
        assert run(DT.run_once_if_enabled(s, db, -100123, log=lambda m: None)) is None and not s.calls       # inert without flag
        os.environ[DT.ENV] = "wrong-id"
        assert run(DT.run_once_if_enabled(s, db, -100123, log=lambda m: None)) is None and not s.calls       # wrong id: inert
        os.environ[DT.ENV] = DT.TEST_ID
        logs = []
        mid = run(DT.run_once_if_enabled(s, db, -100123, log=logs.append))
        assert mid == 777 and len(s.calls) == 1
        path, cap, stream, kw = s.calls[0]
        assert cap.startswith("🧪 ТЕСТ ДИЗАЙНУ — НЕ ТОРГОВИЙ СИГНАЛ") and "#TIAUSDT" in cap and "Не торгувати" in cap
        assert kw["skip_gate"] is True and kw["intent"] == "DESIGN_TEST" and kw["link_scenario_id"].startswith("O2|")
        assert "scenario_id" not in kw                      # no ledger/lifecycle scenario binding
        from PIL import Image
        assert Image.open(path).size == DT.CARD_SIZE         # the NEW compact ENTRY/TP1/SL template
        assert any("SENT chat_id=-100123 message_id=777" in l and "png_sha256=" in l for l in logs)
        assert 1 <= len(cap) <= 1024
        # restart: never sent twice
        assert run(DT.run_once_if_enabled(s, db, -100123, log=lambda m: None)) is None and len(s.calls) == 1
        # a failed attempt is marked and NOT retried automatically
        db2 = os.path.join(td, "o2.db")
        OB.init_office_db(db2)
        s2 = Sender(mid=None)
        assert run(DT.run_once_if_enabled(s2, db2, -100123, log=lambda m: None)) is None and len(s2.calls) == 1
        assert run(DT.run_once_if_enabled(s2, db2, -100123, log=lambda m: None)) is None and len(s2.calls) == 1
        # nothing but the marker table was written
        tables = {r[0] for r in OB._fetchall(db, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "office_design_test_once" in tables
        assert not OB._fetchall(db, "SELECT 1 FROM office2_live_signal") if "office2_live_signal" in tables else True
    src = open(os.path.join(os.path.dirname(DT.__file__), "office_design_test.py"), encoding="utf-8").read()
    for bad in ("TG_BOT_TOKEN", "bot{token}", "emit_ready", "office2_live_signal"):
        assert bad not in src, bad
    print("OK test_design_test")


if __name__ == "__main__":
    main()
