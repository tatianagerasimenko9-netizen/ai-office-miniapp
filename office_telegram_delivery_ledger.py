"""Persistent, transactional Telegram delivery reservations (SQLite/PostgreSQL).

The relay uses this only with explicit opt-in after an owner-approved migration.
No request path creates or migrates the production table.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Optional

try:
    import psycopg
except ImportError:
    psycopg = None

from office_bridge import _is_pg, _sqlite_path_from_url

DDL = """CREATE TABLE IF NOT EXISTS office_telegram_delivery (
    dedup_key TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    token TEXT NOT NULL,
    expires_at DOUBLE PRECISION,
    delivered_at DOUBLE PRECISION
)"""


def _connect(db_path: str):
    if _is_pg(db_path):
        if psycopg is None:
            raise RuntimeError("psycopg required for Telegram delivery ledger")
        return psycopg.connect(db_path)
    return sqlite3.connect(_sqlite_path_from_url(db_path), timeout=15)


def _sql(db_path: str, query: str) -> str:
    return query.replace("?", "%s") if _is_pg(db_path) else query


def migrate_delivery_ledger(db_path: str) -> None:
    """Additive migration only; never deletes existing data."""
    with _connect(db_path) as conn:
        conn.execute(DDL)


def reserve_delivery(
    db_path: str, key: str, *, stable: bool = False,
    now: Optional[float] = None, lease_seconds: float = 120.0,
    dedup_seconds: float = 900.0,
) -> Optional[str]:
    """Atomically claim one event. None means pending or already delivered.

    stable=True means a canonical scenario event is never re-sent after delivery.
    An expired in-flight lease can be retried; a crash after Telegram accepts a
    message but before DB commit can still cause a duplicate (no Telegram 2PC).
    """
    if not key or lease_seconds <= 0 or dedup_seconds <= 0:
        raise ValueError("invalid delivery reservation")
    ts = float(time.time() if now is None else now)
    token = uuid.uuid4().hex
    with _connect(db_path) as conn:
        conn.execute(
            _sql(db_path, "INSERT INTO office_telegram_delivery "
                "(dedup_key,state,token,expires_at,delivered_at) "
                "VALUES (?,'PENDING',?,?,NULL) ON CONFLICT(dedup_key) DO NOTHING"),
            (key, token, ts + lease_seconds),
        )
        row = conn.execute(
            _sql(db_path, "SELECT state,token,expires_at FROM office_telegram_delivery "
                "WHERE dedup_key=?"), (key,),
        ).fetchone()
        if row and row[0] == "PENDING" and row[1] == token:
            return token
        if row and row[0] == "DELIVERED" and stable:
            return None
        # Conditional UPDATE serializes concurrent claimants across processes.
        cur = conn.execute(
            _sql(db_path, "UPDATE office_telegram_delivery "
                "SET state='PENDING',token=?,expires_at=?,delivered_at=NULL "
                "WHERE dedup_key=? AND expires_at<=?"),
            (token, ts + lease_seconds, key, ts),
        )
        return token if cur.rowcount == 1 else None


def finish_delivery(
    db_path: str, key: str, token: str, *, delivered: bool,
    stable: bool = False, now: Optional[float] = None,
    dedup_seconds: float = 900.0,
) -> bool:
    """Only the lease owner can mark delivery; failed sends release their claim."""
    if not key or not token:
        return False
    ts = float(time.time() if now is None else now)
    with _connect(db_path) as conn:
        if delivered:
            cur = conn.execute(
                _sql(db_path, "UPDATE office_telegram_delivery "
                    "SET state='DELIVERED',delivered_at=?,expires_at=? "
                    "WHERE dedup_key=? AND token=? AND state='PENDING'"),
                (ts, ts + (3153600000.0 if stable else dedup_seconds), key, token),
            )
        else:
            cur = conn.execute(
                _sql(db_path, "DELETE FROM office_telegram_delivery "
                    "WHERE dedup_key=? AND token=? AND state='PENDING'"),
                (key, token),
            )
        return cur.rowcount == 1
