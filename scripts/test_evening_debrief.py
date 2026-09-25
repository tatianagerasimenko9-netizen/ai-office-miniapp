#!/usr/bin/env python3
"""Вечірній debrief: один звіт Лева, /position ≠ Desk ENTER, без фейкових 0%."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import (  # noqa: E402
    _execute,
    _fetchone,
    build_evening_journal_summary,
    init_office_db,
    is_confirmed_position_row,
    journal_open_trade,
    kyiv_calendar_date,
    office_evening_debrief,
)
from office_review_position import handle_position_command  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _desk_open(db: str, tid: str, symbol: str) -> None:
    journal_open_trade(
        db,
        trade_id=tid,
        symbol=symbol,
        direction="LONG",
        entry_price=1.0,
        stop_loss=0.9,
        entry_reason="Desk ENTER after agent chain",
        setup_name="SCANNER",
    )


NOW = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)  # 21:00 Київ


def main() -> int:
    if is_confirmed_position_row("Desk ENTER after agent chain"):
        return _fail("Desk ENTER must not be confirmed")
    if not is_confirmed_position_row("Explicit /position by owner"):
        return _fail("/position must be confirmed")
    if kyiv_calendar_date(NOW) != "2026-09-25":
        return _fail(f"kyiv date {kyiv_calendar_date(NOW)}")

    db = str(Path(tempfile.mkdtemp()) / "debrief.db")
    init_office_db(db)
    for i in range(20):
        _desk_open(db, f"relay-open-{i}", "BTCUSDT" if i == 0 else f"X{i}USDT")
    for i, day in enumerate(("2026-05-06", "2026-05-08", "2026-05-10")):
        tid = f"relay-closed-{i}"
        _desk_open(db, tid, f"OLD{i}USDT")
        _execute(
            db,
            "UPDATE trade_journal SET status=?, ts_close_utc=?, outcome=?, pnl_pct=?, r_multiple=? WHERE trade_id=?",
            ("CLOSED", f"{day}T10:00:00+00:00", "LOSS", -1.0, -0.9, tid),
        )
    n_before = int(_fetchone(db, "SELECT COUNT(*) FROM trade_journal", ())[0])
    if n_before != 23:
        return _fail(f"seed {n_before}")

    text = build_evening_journal_summary(db, now=NOW)
    if "WR 0.0%" in text or "Avg R: +0.00" in text:
        return _fail("must not fake zero WR/R")
    if "немає даних" not in text:
        return _fail("empty closed today needs немає даних")
    if "відкриті зараз: 0" not in text:
        return _fail("no confirmed open")
    if "OPEN 20" not in text or "Desk ENTER" not in text:
        return _fail("historical OPEN 20")
    if "реальними позиціями" not in text and "реальними позиціями без /position" not in text:
        return _fail("must refuse calling old OPEN positions")
    if "2026-09-25" not in text:
        return _fail("kyiv date in report")

    utc_edge = build_evening_journal_summary(db, now=NOW)
    _execute(
        db,
        "UPDATE trade_journal SET ts_close_utc=? WHERE trade_id=?",
        ("2026-09-24T22:30:00+00:00", "relay-closed-0"),
    )
    # 22:30 UTC 24.09 = 01:30 Київ 25.09 — сьогодні за Києвом, але не UTC CURRENT_DATE 25? wait UTC date of close is 24.
    edged = build_evening_journal_summary(db, now=NOW)
    if "історичні 1" not in edged and "усього 1" not in edged:
        return _fail(f"kyiv-not-utc close today\n{edged}")
    # повернути історичну дату, записи не «закривати як сьогоднішні позиції»
    _execute(
        db,
        "UPDATE trade_journal SET ts_close_utc=? WHERE trade_id=?",
        ("2026-05-06T10:00:00+00:00", "relay-closed-0"),
    )

    pos = handle_position_command(
        "/position DEBRIEFUSDT LONG entry=100 sl=95 status=CLOSED pnl=-1.2",
        db,
    )
    if not pos.get("ok"):
        return _fail(f"position {pos}")
    # дата закриття /position = now машини; підженемо під Київ 25.09
    _execute(
        db,
        "UPDATE trade_journal SET ts_close_utc=?, outcome=?, pnl_pct=?, r_multiple=? WHERE trade_id=?",
        ("2026-09-25T15:00:00+00:00", "LOSS", -1.2, -0.8, pos["trade_id"]),
    )
    with_pos = build_evening_journal_summary(db, now=NOW)
    if "закриті сьогодні: 1" not in with_pos:
        return _fail(f"confirmed closed today\n{with_pos}")
    block = with_pos.split("Підтверджені угоди (/position):")[1].split("Закриті сьогодні")[0]
    if "немає даних" in block:
        return _fail(f"confirmed closed should have stats\n{block}")
    if "W 0 · L 1" not in block:
        return _fail(f"expected 1 confirmed loss\n{block}")
    n_after = int(_fetchone(db, "SELECT COUNT(*) FROM trade_journal", ())[0])
    if n_after != 24:
        return _fail("must not delete historical rows")
    open_desk = int(
        _fetchone(
            db,
            "SELECT COUNT(*) FROM trade_journal WHERE status='OPEN' AND entry_reason LIKE ?",
            ("%Desk ENTER%",),
        )[0]
    )
    if open_desk != 20:
        return _fail("must not auto-close Desk ENTER OPEN")

    sent: list[str] = []

    async def _sender(msg: str) -> None:
        sent.append(msg)

    asyncio.run(office_evening_debrief(_sender, btc_change_pct=-0.35, journal_summary=text))
    if len(sent) != 1:
        return _fail(f"must be one message, got {len(sent)}")
    if "Олеся" in sent[0] or "Дарина" in sent[0] or "Віктор" in sent[0]:
        return _fail("no chorus templates")
    if "Лев" not in sent[0] and "лев" not in sent[0].lower() and "🦁" not in sent[0]:
        return _fail("must be Lev report")
    print("OK evening debrief")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
