"""One-off Telegram DESIGN TEST (inert unless OFFICE_DESIGN_TEST_ONCE == TEST_ID).

Sends exactly ONE clearly-labelled message with the production PNG card (office_ready_card.render, #242) built from the FROZEN levels
of an earlier TIA LONG (fixture). It creates NO READY, trade, scenario, ledger-lifecycle event or alert, changes no decision,
risk or gate, and never logs the token. At most one attempt per TEST_ID (marker row is written BEFORE sending; restarts never resend).
Remove the env var after use; delete this module in a follow-up.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

TEST_ID = "tia-bbce25e-design"
ENV = "OFFICE_DESIGN_TEST_ONCE"
TITLE = "🧪 ТЕСТ ДИЗАЙНУ — НЕ ТОРГОВИЙ СИГНАЛ"
FIXTURE = Path(__file__).resolve().parent / "office2" / "fixtures" / "design_test_tia_long.json"
CARD_SIZE = (1000, 1230)      # compact ENTRY/TP1/SL graphic of #242; the plain chart is 1000x800
DDL = "CREATE TABLE IF NOT EXISTS office_design_test_once (test_id TEXT PRIMARY KEY, status TEXT NOT NULL, msg_id BIGINT, chat_id BIGINT, sent_ts DOUBLE PRECISION, png_sha256 TEXT)"


def enabled() -> bool:
    return os.getenv(ENV, "").strip() == TEST_ID


def _num(x: Any) -> str:
    import office_ready_card as card

    return card._num(x, "TIAUSDT")


def build() -> Dict[str, Any]:
    """Render the card and caption from the frozen fixture. Raises if the new template was not produced (never falls back to the old card)."""
    import office_ready_card as card
    from PIL import Image

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tg = fx["targets"]
    path = os.path.join(tempfile.gettempdir(), f"o2_design_test_{int(time.time())}.png")
    res = card.render(symbol=fx["symbol"], direction=fx["direction"], candles=fx["chart_candles"], entry=fx["entry"], zone=fx["zone"], sl=fx["sl"],
                      tp1=tg[0]["p"], tp2=None, tp3=None, ready_price=fx["entry"], key_level=fx["trigger_level"], key_label="рівень", path=path)
    if not res.get("ok"):
        raise RuntimeError("card render failed: " + str(res.get("reason")))
    size = Image.open(path).size
    if size != CARD_SIZE:
        raise RuntimeError(f"new card template not produced: {size}, expected {CARD_SIZE}")
    data = Path(path).read_bytes()
    entry, sl, tp1 = float(fx["entry"]), float(fx["sl"]), float(tg[0]["p"])
    cap = (f"{TITLE}\n\n#TIAUSDT · LONG — заморожені рівні попереднього сигналу, новий READY не створювався.\n"
           f"Вхід {_num(fx['zone'][0])}–{_num(fx['zone'][1])} · SL {_num(sl)} · TP1 {_num(tp1)} · R/R 1:{abs(tp1 - entry) / abs(entry - sl):.2f}\n"
           "Лише перевірка вигляду картки в Telegram. Не торгувати.")
    return {"path": path, "caption": cap, "sha256": hashlib.sha256(data).hexdigest(), "size": size, "scenario_id": fx["scenario_id"]}


def _marker(db: str, sql: str, params: tuple = (), fetch: bool = False):
    from office_bridge import _execute, _fetchall

    return _fetchall(db, sql, params) if fetch else _execute(db, sql, params)


async def run_once_if_enabled(send_photo: Callable[..., Awaitable[Optional[int]]], db: str, chat_id: Any, log: Callable[[str], None] = print) -> Optional[int]:
    if not enabled():
        return None
    from office_bridge import _execute

    _execute(db, DDL)
    if _marker(db, "SELECT status FROM office_design_test_once WHERE test_id = ?", (TEST_ID,), fetch=True):
        log(f"[design_test] {TEST_ID}: already attempted — not sending again")
        return None
    card = build()
    _marker(db, "INSERT INTO office_design_test_once (test_id, status, chat_id, sent_ts, png_sha256) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
            (TEST_ID, "ATTEMPT", int(chat_id), time.time(), card["sha256"]))
    msg_id = await send_photo(card["path"], card["caption"], "general", intent="DESIGN_TEST", event_type="DESIGN_TEST", symbol="TIAUSDT", direction="LONG",
                              link_scenario_id=card["scenario_id"], skip_gate=True)
    now = time.time()
    if msg_id:
        _marker(db, "UPDATE office_design_test_once SET status = ?, msg_id = ?, sent_ts = ? WHERE test_id = ?", ("SENT", int(msg_id), now, TEST_ID))
        log(f"[design_test] SENT chat_id={chat_id} message_id={msg_id} sent_at_utc={datetime.fromtimestamp(now, timezone.utc):%Y-%m-%d %H:%M:%S} "
            f"png_sha256={card['sha256']} png_size={card['size'][0]}x{card['size'][1]} button=📊 Сценарій scenario={card['scenario_id']} telegram_api_ok=True")
    else:
        _marker(db, "UPDATE office_design_test_once SET status = ? WHERE test_id = ?", ("FAILED_OR_UNCONFIRMED", TEST_ID))
        log("[design_test] send returned no message_id (failed or unconfirmed) — NOT retried automatically")
    return msg_id
