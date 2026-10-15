"""Власні таблиці B&R · TEST (окремо від office2_*): сигнали, історія подій, окрема нумерація «B&R-№»."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

DDL = (
    """CREATE TABLE IF NOT EXISTS br_test_signal (
        sig_id TEXT PRIMARY KEY, seq BIGINT, symbol TEXT NOT NULL, direction TEXT NOT NULL, level DOUBLE PRECISION NOT NULL,
        break_ts DOUBLE PRECISION NOT NULL, retest_ts DOUBLE PRECISION NOT NULL, confirm_ts DOUBLE PRECISION NOT NULL,
        entry DOUBLE PRECISION NOT NULL, sl DOUBLE PRECISION NOT NULL, targets_json TEXT NOT NULL, hyp_json TEXT NOT NULL,
        created_ts DOUBLE PRECISION NOT NULL, status TEXT NOT NULL, msg_id BIGINT, sent_ts DOUBLE PRECISION, last_error TEXT)""",
    """CREATE TABLE IF NOT EXISTS br_test_event (
        sig_id TEXT NOT NULL, level TEXT NOT NULL, touched_ts DOUBLE PRECISION NOT NULL, price DOUBLE PRECISION,
        ts DOUBLE PRECISION NOT NULL, msg_id BIGINT, sent_ts DOUBLE PRECISION, PRIMARY KEY (sig_id, level))""",
)


def init(db: str) -> None:
    from office_bridge import _execute

    for ddl in DDL:
        _execute(db, ddl)


def sig_id(symbol: str, direction: str, level: float, break_ts: float) -> str:
    return f"BR|{symbol}|{direction}|{round(float(level), 8)}|{int(break_ts)}"


def record_signal(db: str, symbol: str, s: Dict[str, Any], hyp: Dict[str, Any], now: Optional[float] = None) -> Optional[str]:
    """Ідемпотентно: той самий (символ, напрям, рівень, час пробою) другий раз не пишеться. Повертає sig_id нового сигналу або None."""
    from office_bridge import _execute, _fetchone

    init(db)
    sid = sig_id(symbol, s["direction"], s["level"], s["break_ts"])
    if _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id = ?", (sid,)):
        return None
    nxt = _fetchone(db, "SELECT COALESCE(MAX(seq), 0) + 1 FROM br_test_signal")
    seq = int(nxt[0]) if nxt else 1
    _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (sid, seq, symbol, s["direction"], s["level"], s["break_ts"], s["retest_ts"], s["confirm_ts"], s["entry"], s["sl"], json.dumps(s["targets"]), json.dumps(hyp, default=str), now or time.time(), "NEW"))
    return sid


def record_event(db: str, sid: str, level: str, touched_ts: float, price: Optional[float], msg_id: Optional[int] = None) -> bool:
    from office_bridge import _execute, _fetchone

    init(db)
    if _fetchone(db, "SELECT 1 FROM br_test_event WHERE sig_id = ? AND level = ?", (sid, level)):
        return False
    _execute(db, "INSERT INTO br_test_event(sig_id, level, touched_ts, price, ts, msg_id, sent_ts) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (sid, level, touched_ts, price, time.time(), msg_id, time.time() if msg_id else None))
    return True


def rows(db: str, where: str = "", args: tuple = ()) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    init(db)
    cols = "sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, created_ts, status, msg_id"
    return [dict(zip(cols.replace(" ", "").split(","), r)) for r in _fetchall(db, f"SELECT {cols} FROM br_test_signal {where} ORDER BY created_ts", args)]



def init_manual_actions(db: str) -> None:
    """Owner-reported actions only. Never place an exchange order."""
    from office_bridge import _execute
    _execute(db, """CREATE TABLE IF NOT EXISTS br_manual_action (
        sig_id TEXT NOT NULL, action TEXT NOT NULL, noted_ts DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (sig_id, action))""")


def record_manual_action(db: str, sid: str, action: str) -> bool:
    """Explicit user acknowledgement; price touching a level does not imply a fill."""
    from office_bridge import _execute, _fetchone
    allowed = {"OPENED", "TP1_30", "SL_BE", "TP2_40", "TP3_REST", "CLOSED"}
    if action not in allowed:
        raise ValueError("unsupported B&R manual action")
    init(db)
    init_manual_actions(db)
    if not _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id = ?", (sid,)):
        return False
    _execute(db, "INSERT INTO br_manual_action(sig_id, action, noted_ts) VALUES (?,?,?) ON CONFLICT DO NOTHING",
             (sid, action, time.time()))
    return True


def manual_actions(db: str, sid: str) -> List[str]:
    from office_bridge import _fetchall
    init_manual_actions(db)
    return [str(x[0]) for x in _fetchall(db, "SELECT action FROM br_manual_action WHERE sig_id = ? ORDER BY noted_ts", (sid,))]


def events(db: str, sid: str) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    init(db)
    return [{"level": a, "touched_ts": b, "price": c, "msg_id": d} for a, b, c, d in _fetchall(db, "SELECT level, touched_ts, price, msg_id FROM br_test_event WHERE sig_id = ? ORDER BY touched_ts", (sid,))]
