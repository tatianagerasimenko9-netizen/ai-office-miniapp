"""Sequential READY number (№0001, №0002, …): atomic, in the DB, idempotent per scenario, restart-safe.

Not the Telegram message_id. The number is assigned right before a READY is delivered; asking again for the same
scenario returns the same number (so a retry after a failed send never burns a new one), and concurrent assigners
cannot share a number (UNIQUE(seq) + retry). Works on SQLite and PostgreSQL via office_bridge.
"""
from __future__ import annotations

import time
from typing import Optional

DDL = "CREATE TABLE IF NOT EXISTS office_ready_seq (scenario_id TEXT PRIMARY KEY, seq INTEGER NOT NULL UNIQUE, assigned_ts DOUBLE PRECISION NOT NULL)"
_READY_DBS: set = set()


def _ensure(db: str) -> None:
    if db in _READY_DBS:
        return
    from office_bridge import _execute

    _execute(db, DDL)
    _READY_DBS.add(db)


def number_of(db: str, scenario_id: str) -> Optional[int]:
    """Existing number or None (never creates)."""
    from office_bridge import _fetchall

    _ensure(db)
    rows = _fetchall(db, "SELECT seq FROM office_ready_seq WHERE scenario_id = ?", (str(scenario_id),))
    return int(rows[0][0]) if rows else None


def assign(db: str, scenario_id: str, now: Optional[float] = None, attempts: int = 25) -> int:
    from office_bridge import _execute

    sid = str(scenario_id or "")
    if not sid:
        raise ValueError("scenario_id required")
    _ensure(db)
    for _ in range(attempts):
        got = number_of(db, sid)
        if got is not None:
            return got
        # MAX+1 in one statement; a concurrent twin loses on UNIQUE(seq)/PK and we simply retry.
        _execute(db, "INSERT INTO office_ready_seq (scenario_id, seq, assigned_ts) SELECT ?, COALESCE(MAX(seq), 0) + 1, ? FROM office_ready_seq WHERE 1 = 1 ON CONFLICT DO NOTHING",
                 (sid, float(time.time() if now is None else now)))
    got = number_of(db, sid)
    if got is None:
        raise RuntimeError("could not assign READY number")
    return got


def label(seq: Optional[int]) -> str:
    return f"№{int(seq)}" if seq else ""
