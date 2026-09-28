#!/usr/bin/env python3
"""Scenario reply chain: first card is the root, later events reply to it.

Executes the real relay send_proactive AST with fake Telegram and temporary
SQLite. No credentials, production DB, network, or Telegram.
"""
import ast
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from office_telegram_delivery_ledger import (  # noqa: E402
    finish_delivery, get_scenario_root, mark_delivery_uncertain, migrate_delivery_ledger,
    remember_scenario_root, renew_delivery, reserve_delivery,
)

ROOT = Path(__file__).resolve().parent.parent
tree = ast.parse((ROOT / "office_relay_wizard.py").read_text(encoding="utf-8"))
fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "send_proactive")
module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))


def _load_sender(db: str, sent: list, next_id: list, photo: dict):
    """Fresh relay function instance, as after a Worker restart (no memory kept)."""

    async def send_text(message, reply_to_message_id=None, **kwargs):
        next_id[0] += 1
        sent.append(("text", message, reply_to_message_id, next_id[0]))
        return next_id[0]

    async def send_photo(path, message, stream="general", *, reply_to_message_id=None, **kwargs):
        next_id[0] += 1
        sent.append(("photo", message, reply_to_message_id, next_id[0]))
        return next_id[0]

    env = {
        "__builtins__": __builtins__, "asyncio": asyncio, "os": os,
        "Optional": Optional, "Any": Any,
        "EVENT_TRADE_UPDATE": "TRADE_UPDATE", "EVENT_TRADE_CLOSED": "TRADE_CLOSED",
        "EVENT_SIGNAL_ENTRY": "SIGNAL_ENTRY", "TRADE_UPDATE_STREAM": "trade",
        "db_path": db, "may_send_proactive": lambda event: True,
        "gate_outbound_telegram": lambda *a, **k: {"send": True},
        "should_send_trade_telegram": lambda *a, **k: {"send": True, "key": k["canonical_id"] + "|" + k["event"]},
        "trade_update_streams": lambda: ("trade",),
        "reserve_delivery": reserve_delivery, "renew_delivery": renew_delivery,
        "finish_delivery": finish_delivery, "mark_delivery_uncertain": mark_delivery_uncertain,
        "get_scenario_root": get_scenario_root, "remember_scenario_root": remember_scenario_root,
        "finish_trade_telegram": lambda **k: None, "send_office": send_text,
        "send_office_photo": send_photo,
        "_render_entry_chart": lambda *a: {"ok": bool(photo.get("on")), "path": "/tmp/fake.png"},
        "_strip_agent_tag": lambda msg: msg,
        "_extract_first_usdt_symbol": lambda msg: "ETHUSDT",
    }
    exec(compile(module, str(ROOT / "office_relay_wizard.py"), "exec"), env)
    return env["send_proactive"]


async def exercise() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "thread.sqlite3")
        migrate_delivery_ledger(db)
        sent: list = []
        next_id = [100]
        photo = {"on": True}
        os.environ["OFFICE_TG_PERSISTENT_DEDUP"] = "1"
        try:
            send = _load_sender(db, sent, next_id, photo)
            base = dict(symbol="ETHUSDT", direction="SHORT", canonical_id="ETH|S1")

            # 1. First card (photo) starts the chain and is not a reply.
            root = await send("SIGNAL_ENTRY", "plan", scenario_event="WATCHING", **base)
            assert root == 101 and sent[-1][0] == "photo" and sent[-1][2] is None, sent
            assert get_scenario_root(db, "ETH|S1") == 101

            # 2. Later event of the same scenario replies to the root.
            photo["on"] = False
            upd = await send("TRADE_UPDATE", "confirmed", scenario_event="CONFIRMED", **base)
            assert upd == 102 and sent[-1][2] == 101, sent

            # 3. Worker restart: fresh function, chain restored from DB.
            send = _load_sender(db, sent, next_id, photo)
            await send("TRADE_UPDATE", "cancel", scenario_event="CANCELLED", **base)
            assert sent[-1][2] == 101, sent
            assert get_scenario_root(db, "ETH|S1") == 101, "root must never be overwritten"

            # 4. Re-delivered stable event is still silent (ledger dedup intact).
            n = len(sent)
            assert await send("TRADE_UPDATE", "confirmed", scenario_event="CONFIRMED", **base) is None
            assert len(sent) == n

            # 5. Another scenario gets its own chain.
            other = await send("TRADE_UPDATE", "new", scenario_event="WATCHING",
                               **dict(base, canonical_id="ETH|S2"))
            assert sent[-1][2] is None and get_scenario_root(db, "ETH|S2") == other

            # 6. Explicit reply target from caller wins and does not become a root.
            await send("TRADE_UPDATE", "manual", reply_to_message_id=55, scenario_event="NOTE",
                       **dict(base, canonical_id="ETH|S3"))
            assert sent[-1][2] == 55 and get_scenario_root(db, "ETH|S3") is None
        finally:
            os.environ.pop("OFFICE_TG_PERSISTENT_DEDUP", None)

        # 7. Ledger off: no DB lookups, no replies invented.
        sent.clear()
        send = _load_sender(str(Path(tmp) / "unmigrated.sqlite3"), sent, next_id, photo)
        await send("TRADE_UPDATE", "x", scenario_event="CONFIRMED",
                   symbol="ETHUSDT", direction="SHORT", canonical_id="ETH|S1")
        assert sent and sent[-1][2] is None, sent

        # Migration is additive and idempotent.
        migrate_delivery_ledger(db)
        assert get_scenario_root(db, "ETH|S1") == 101
    print("OK scenario Telegram chain: root, replies, restart-safe, dedup intact, ledger-off inert")


if __name__ == "__main__":
    asyncio.run(exercise())
