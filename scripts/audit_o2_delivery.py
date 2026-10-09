#!/usr/bin/env python3
"""Read-only аудит Office2 READY outbox і фактичної Telegram latency.

Не запускає delivery, не змінює статуси та не надсилає повідомлень. Працює з
тим самим SQLite/PostgreSQL target, що й Office, і друкує лише агрегати та id.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from office2 import stats as ST

EXPECTED_NEW_TIMING = {
    "decision_to_sent_ms",
    "queue_ms",
    "send_ms",
}


def _rows(db: str, sql: str, params: tuple = ()) -> List[tuple]:
    from office_bridge import _fetchall

    return _fetchall(db, sql, params)


def _payload(raw: Any) -> Dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _timing_audit(db: str, since_iso: str) -> Dict[str, Any]:
    rows = _rows(
        db,
        "SELECT signal_id, payload_json FROM office_events "
        "WHERE event_type='OFFICE2_READY_SENT' AND ts_utc >= ? ORDER BY id ASC",
        (since_iso,),
    )
    issues = []
    new_n = old_n = invalid_json = 0
    for sid, raw in rows:
        payload = _payload(raw)
        if not payload:
            invalid_json += 1
            issues.append({"scenario_id": sid, "code": "INVALID_PAYLOAD"})
            continue
        timing = payload.get("timing") or {}
        is_new = any(timing.get(key) is not None for key in ("bar_to_sent_ms", "send_ms", "queue_ms"))
        if is_new:
            new_n += 1
            missing = sorted(key for key in EXPECTED_NEW_TIMING if not isinstance(timing.get(key), (int, float)))
            if missing:
                issues.append({"scenario_id": sid, "code": "MISSING_TIMING", "fields": missing})
        else:
            old_n += 1
        pairs = (
            ("decision_to_sent_ms", "emit_to_sent_s"),
            ("queue_ms", "pickup_s"),
            ("send_ms", "send_s"),
        )
        for ms_key, sec_key in pairs:
            if isinstance(timing.get(ms_key), (int, float)) and isinstance(timing.get(sec_key), (int, float)):
                delta = abs(float(timing[ms_key]) - float(timing[sec_key]) * 1000.0)
                if delta > 1500.0:
                    issues.append({"scenario_id": sid, "code": "TIMING_MISMATCH", "fields": [ms_key, sec_key], "delta_ms": round(delta, 1)})
    return {
        "events": len(rows),
        "new_format": new_n,
        "old_format": old_n,
        "invalid_payload": invalid_json,
        "issues": issues,
        "post_hardening_evidence": "AVAILABLE" if new_n else "NO_NEW_FORMAT_EVIDENCE",
    }


def collect(db: str, *, now: Optional[float] = None, days: float = 14.0, stale_pending_sec: float = 600.0) -> Dict[str, Any]:
    """Збирає факти без INSERT/UPDATE/DELETE."""
    ts = float(time.time() if now is None else now)
    cutoff = ts - float(days) * 86400.0
    rows = _rows(
        db,
        "SELECT scenario_id, symbol, direction, created_ts, valid_until_ts, status, "
        "delivered_ts, last_error FROM office2_live_signal WHERE created_ts >= ? "
        "ORDER BY created_ts ASC",
        (cutoff,),
    )
    statuses: Dict[str, int] = {}
    pending = []
    for sid, symbol, direction, created, valid_until, status, delivered, error in rows:
        state = str(status or "UNKNOWN").upper()
        statuses[state] = statuses.get(state, 0) + 1
        if state == "PENDING":
            age = max(0.0, ts - float(created))
            pending.append(
                {
                    "scenario_id": sid,
                    "symbol": symbol,
                    "direction": direction,
                    "age_s": round(age, 1),
                    "expired": ts > float(valid_until),
                    "stale": age > float(stale_pending_sec),
                    "last_error": error,
                }
            )

    delivered_ids = {str(r[0]) for r in rows if str(r[5] or "").upper() == "DELIVERED"}
    since_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    sent_ids = {
        str(sid)
        for (sid,) in _rows(
            db,
            "SELECT DISTINCT signal_id FROM office_events "
            "WHERE event_type='OFFICE2_READY_SENT' AND ts_utc >= ?",
            (since_iso,),
        )
        if sid
    }
    missing_sent_event = sorted(delivered_ids - sent_ids)
    latency = ST.latency(db, days=days, now=ts)
    return {
        "ok": True,
        "readonly": True,
        "as_of_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        "window_days": float(days),
        "signals": len(rows),
        "statuses": statuses,
        "pending": {
            "count": len(pending),
            "stale_count": sum(1 for item in pending if item["stale"]),
            "expired_count": sum(1 for item in pending if item["expired"]),
            "items": pending,
        },
        "delivered_without_ready_sent_event": missing_sent_event,
        "latency": latency,
        "timing_contract": _timing_audit(db, since_iso),
        "limitations": [
            "READY_SENT підтверджує виклик Telegram API, але не прочитання повідомлення користувачкою",
            "старий timing format не доводить швидкість після PR #162–#163",
        ],
    }


def _db(arg: str) -> str:
    return arg or os.getenv("DATABASE_URL", "").strip() or os.getenv("OFFICE_DB_PATH", "").strip() or "office_bridge.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="", help="PostgreSQL URL або SQLite path; інакше env/default")
    parser.add_argument("--days", type=float, default=14.0)
    parser.add_argument("--stale-pending-sec", type=float, default=600.0)
    parser.add_argument("--now", type=float, default=None, help="Фіксований epoch для відтворюваної перевірки")
    args = parser.parse_args()
    print(json.dumps(collect(_db(args.db), now=args.now, days=args.days, stale_pending_sec=args.stale_pending_sec), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
