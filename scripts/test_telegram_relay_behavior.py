#!/usr/bin/env python3
"""Execute the actual relay send_proactive AST with fake Telegram and temporary SQLite.

No credentials, production DB, network, Telegram, or relay main loop.
"""
import ast
import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from office_telegram_delivery_ledger import (
    migrate_delivery_ledger, reserve_delivery, renew_delivery,
    finish_delivery, mark_delivery_uncertain,
)

ROOT = Path(__file__).resolve().parent.parent
tree = ast.parse((ROOT / "office_relay_wizard.py").read_text(encoding="utf-8"))
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "send_proactive")
module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))


async def exercise():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "ledger.sqlite3")
        migrate_delivery_ledger(db)
        calls = []
        photo_result = None
        text_result = 7001
        text_cancel = False
        photo_enabled = True

        async def send_text(*args, **kwargs):
            calls.append("text")
            if text_cancel:
                raise asyncio.CancelledError()
            return text_result

        async def send_photo(*args, **kwargs):
            calls.append("photo")
            return photo_result

        def gate(*args, **kwargs):
            return {"send": True}

        def trade_gate(*args, **kwargs):
            return {"send": True, "key": kwargs["canonical_id"] + "|" + kwargs["event"]}

        def finish_memory(*args, **kwargs):
            calls.append(("memory", kwargs["delivered"]))

        def render(*args):
            return {"ok": True, "path": "/tmp/fake-chart.png"} if photo_enabled else {"ok": False, "reason": "fixture"}

        env = {
            "__builtins__": __builtins__, "asyncio": asyncio, "os": os,
            "Optional": Optional, "Any": Any,
            "EVENT_TRADE_UPDATE": "TRADE_UPDATE", "EVENT_TRADE_CLOSED": "TRADE_CLOSED",
            "EVENT_SIGNAL_ENTRY": "SIGNAL_ENTRY", "TRADE_UPDATE_STREAM": "trade",
            "db_path": db, "may_send_proactive": lambda event: True,
            "gate_outbound_telegram": gate, "should_send_trade_telegram": trade_gate,
            "trade_update_streams": lambda: ("trade",),
            "reserve_delivery": reserve_delivery, "renew_delivery": renew_delivery,
            "finish_delivery": finish_delivery, "mark_delivery_uncertain": mark_delivery_uncertain,
            "finish_trade_telegram": finish_memory, "send_office": send_text,
            "send_office_photo": send_photo, "_render_entry_chart": render,
            "_strip_agent_tag": lambda msg: msg,
            "_extract_first_usdt_symbol": lambda msg: "MANTAUSDT",
        }
        exec(compile(module, str(ROOT / "office_relay_wizard.py"), "exec"), env)
        send = env["send_proactive"]
        os.environ["OFFICE_TG_PERSISTENT_DEDUP"] = "1"
        common = dict(symbol="MANTAUSDT", direction="LONG", intent="SIGNAL_ENTRY",
                      canonical_id="MANTA|fixture", scenario_event="SIGNAL_ENTRY")
        try:
            # Photo API outcome is ambiguous: never send fallback; quarantine DB.
            assert await send("SIGNAL_ENTRY", "fixture", **common) is None
            assert calls.count("photo") == 1 and "text" not in calls, calls
            assert reserve_delivery(db, "MANTA|fixture|SIGNAL_ENTRY", stable=True) is None
            assert await send("SIGNAL_ENTRY", "fixture", **common) is None
            assert calls.count("photo") == 1, "quarantined event resent"

            # Successful text commits stable delivery; a second worker cannot resend.
            calls.clear()
            photo_enabled = False
            ok = dict(common, canonical_id="MANTA|successful")
            assert await send("SIGNAL_ENTRY", "fixture", **ok) == 7001
            assert await send("SIGNAL_ENTRY", "fixture", **ok) is None
            assert calls.count("text") == 1, calls

            # Cancellation is propagated, not suppressed by finally; uncertain
            # delivery remains quarantined rather than being retried.
            calls.clear()
            text_cancel = True
            cancelled = dict(common, canonical_id="MANTA|cancelled")
            try:
                await send("SIGNAL_ENTRY", "fixture", **cancelled)
                raise AssertionError("CancelledError was swallowed")
            except asyncio.CancelledError:
                pass
            assert reserve_delivery(db, "MANTA|cancelled|SIGNAL_ENTRY", stable=True) is None

            # Missing migration must fail closed without touching Telegram.
            calls.clear()
            env["db_path"] = str(Path(tmp) / "unmigrated.sqlite3")
            assert await send("SIGNAL_ENTRY", "fixture", **dict(common, canonical_id="MANTA|missing")) is None
            assert "text" not in calls and "photo" not in calls
        finally:
            os.environ.pop("OFFICE_TG_PERSISTENT_DEDUP", None)
    print("OK behavioral relay integration: ambiguous, stable, cancellation, missing migration (fake Telegram)")


if __name__ == "__main__":
    asyncio.run(exercise())
