#!/usr/bin/env python3
"""T1: /review не створює позицію; /position лише з entry+SL+status."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import init_office_db, _fetchone  # noqa: E402
from office_review_position import (  # noqa: E402
    build_review_card,
    handle_position_command,
    handle_review_command,
    parse_t1_command,
    scanner_enter_opens_position,
    scanner_review_notice,
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if parse_t1_command("/review BTCUSDT LONG")[0] != "review":
        return _fail("parse review")
    if parse_t1_command("/position ETHUSDT SHORT entry=1 sl=2 status=OPEN")[0] != "position":
        return _fail("parse position")
    if parse_t1_command("hello LONG BTCUSDT") is not None:
        return _fail("plain text is not a T1 command")

    if scanner_enter_opens_position("ENTER") is not False:
        return _fail("scanner ENTER must not open my position")
    notice = scanner_review_notice("solusdt", "ENTER")
    if "не твоя позиція" not in notice.lower() and "не твоя позиція" not in notice:
        return _fail("scanner notice")
    if "ордер" not in notice.lower() and "не ордер" not in notice:
        return _fail("scanner notice no order")

    card = build_review_card("SOLUSDT LONG SIGNAL")
    if card["opens_position"]:
        return _fail("review opens_position")
    if card["entry"] is not None or card["sl"] is not None:
        return _fail("review must not invent prices")
    if "не вигадую" not in card["message"]:
        return _fail("review must say not inventing")
    if "BTCUSDT" in card["message"] and card["symbol"] != "BTCUSDT":
        return _fail("must not default BTC")

    no_sym = build_review_card("просто розбір без монети")
    if no_sym["symbol"]:
        return _fail("empty review must not assume a symbol")
    if "дефолтний тикер не підставляю" not in no_sym["message"]:
        return _fail("empty review must refuse default ticker")

    db = str(Path(tempfile.mkdtemp()) / "t1.db")
    init_office_db(db)

    rev = handle_review_command("/review T1REVUSDT LONG entry=10 sl=9", db)
    if rev["opens_position"]:
        return _fail("handle review position flag")
    n_j = _fetchone(db, "SELECT COUNT(*) FROM trade_journal", ())[0]
    if n_j != 0:
        return _fail("review wrote journal")

    bad = handle_position_command("/position T1BADUSDT LONG status=OPEN", db)
    if bad["ok"] or bad["opens_position"]:
        return _fail("incomplete position must fail")
    n_j = _fetchone(db, "SELECT COUNT(*) FROM trade_journal", ())[0]
    if n_j != 0:
        return _fail("incomplete position wrote journal")

    okp = handle_position_command(
        "/position T1POSUSDT SHORT entry=50.5 sl=52 status=OPEN",
        db,
    )
    if not okp["ok"] or not okp["opens_position"]:
        return _fail("valid position")
    row = _fetchone(
        db,
        "SELECT symbol, direction, status, entry_price, stop_loss, pnl_pct FROM trade_journal WHERE trade_id = ?",
        (okp["trade_id"],),
    )
    if not row or row[0] != "T1POSUSDT" or row[1] != "SHORT" or row[2] != "OPEN":
        return _fail(f"journal row {row}")
    if float(row[3]) != 50.5 or float(row[4]) != 52:
        return _fail("entry/sl")
    if row[5] is not None:
        return _fail("must not invent pnl")

    # PnL у тексті OPEN не пишемо в журнал.
    ok2 = handle_position_command(
        "/position T1PNLUSDT LONG entry=1 sl=0.9 status=OPEN pnl=12.3",
        db,
    )
    if not ok2["ok"]:
        return _fail("open with stray pnl should still record position")
    pnl = _fetchone(db, "SELECT pnl_pct FROM trade_journal WHERE trade_id = ?", (ok2["trade_id"],))[0]
    if pnl is not None:
        return _fail("stray pnl on OPEN must be ignored")

    closed = handle_position_command(
        "/position T1CLSUSDT LONG entry=8 sl=7 status=CLOSED pnl=-1.5",
        db,
    )
    if not closed["ok"]:
        return _fail("closed position")
    crow = _fetchone(
        db,
        "SELECT status, pnl_pct FROM trade_journal WHERE trade_id = ?",
        (closed["trade_id"],),
    )
    if crow[0] != "CLOSED" or float(crow[1]) != -1.5:
        return _fail(f"closed row {crow}")

    print("OK: test_review_position")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
