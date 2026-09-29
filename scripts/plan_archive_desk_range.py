#!/usr/bin/env python3
"""Dry-run архіву chase-карток desk-range. SELECT only. Не UPDATE. Не /position.

Застосувати UPDATE можна лише після окремого дозволу Тетяни.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Знімок public /api/summary 2026-09-27 (finger c78e00696e638425). Не секрет.
SNAPSHOT_OPEN_OSIG = [
    "osig-desk-range-BTCUSDT-1790505544",
    "osig-desk-range-BTCUSDT-1790504592",
    "osig-desk-range-BTCUSDT-1790498364",
    "osig-desk-range-BTCUSDT-1790497637",
    "osig-desk-range-SOXLUSDT-1790495192",
    "osig-desk-range-BCHUSDT-1790493276",
]

JOURNAL_SELECT = """
SELECT trade_id, symbol, direction, status, entry_price, stop_loss, take_profit,
       setup_name, entry_reason, ts_open_utc
FROM trade_journal
WHERE status = 'OPEN'
  AND (
    trade_id LIKE 'osig-desk-range-%'
    OR trade_id LIKE 'desk-range-%'
  )
ORDER BY ts_open_utc DESC
"""

SIGNALS_SELECT = """
SELECT signal_id, symbol, direction, status, entry_low, entry_high, sl, tp1, analysis_note
FROM office_signals
WHERE signal_id LIKE 'desk-range-%'
   OR signal_id LIKE 'osig-desk-range-%'
ORDER BY ts_created DESC
"""

# Застосування (НЕ виконувати цим скриптом):
PROPOSED_JOURNAL_UPDATE = """
UPDATE trade_journal
SET status = 'CANCELLED',
    outcome = 'ARCHIVED_LEGACY_RANGE',
    exit_reason = 'dry-run archive desk-range chase; not /position'
WHERE status = 'OPEN'
  AND (
    trade_id LIKE 'osig-desk-range-%'
    OR trade_id LIKE 'desk-range-%'
  )
"""
PROPOSED_SIGNALS_UPDATE = """
UPDATE office_signals
SET status = 'CANCELLED',
    outcome = 'ARCHIVED_LEGACY_RANGE'
WHERE signal_id LIKE 'desk-range-%'
   OR signal_id LIKE 'osig-desk-range-%'
"""


def plan_dict(*, journal_rows: List[Tuple[Any, ...]] | None = None, signal_rows: List[Tuple[Any, ...]] | None = None) -> Dict[str, Any]:
    jn = len(journal_rows or [])
    sn = len(signal_rows or [])
    ids = [str(r[0]) for r in (journal_rows or [])]
    return {
        "ok": True,
        "apply": False,
        "criterion": "OPEN osig-desk-range-* / desk-range-* ; не чіпати pos- і не osig-feed/osig-radar",
        "snapshot_open_count": len(SNAPSHOT_OPEN_OSIG),
        "snapshot_ids": list(SNAPSHOT_OPEN_OSIG),
        "select_journal_n": jn,
        "select_signal_n": sn,
        "select_journal_ids": ids,
        "stats_impact": (
            "У /stats n=10 зараз: БОКОВИК n=6 збігається зі snapshot. "
            "Архів OPEN desk-range зменшить групу БОКОВИК; WR/PnL і далі THIN до n>=20. "
            "Закриті /position і osig-feed-pump / osig-radar не входять у критерій."
        ),
        "rollback": (
            "Зберегти SELECT * перед UPDATE. Відкат: UPDATE status='OPEN', outcome=NULL "
            "WHERE outcome='ARCHIVED_LEGACY_RANGE'."
        ),
        "proposed_journal_update": PROPOSED_JOURNAL_UPDATE.strip(),
        "proposed_signals_update": PROPOSED_SIGNALS_UPDATE.strip(),
        "blocked": "немає дозволу на запис production DB",
    }


def _select(db: str) -> Tuple[List[tuple], List[tuple]]:
    from office_bridge import _fetchall

    journal = _fetchall(db, JOURNAL_SELECT, ()) or []
    signals = _fetchall(db, SIGNALS_SELECT, ()) or []
    return list(journal), list(signals)


def main() -> int:
    if "--apply" in sys.argv:
        print("REFUSE: цей скрипт тільки dry-run. Production UPDATE заборонений без окремого ТЗ.")
        return 2
    target = ""
    if "--select" in sys.argv:
        url = os.getenv("DATABASE_URL", "").strip()
        path = os.getenv("OFFICE_DB_PATH", "").strip()
        target = url or path
        if not target:
            print("NO DB: DATABASE_URL / OFFICE_DB_PATH порожні — лише snapshot plan")
    if target:
        try:
            j, s = _select(target)
        except Exception as exc:
            print(f"SELECT failed: {type(exc).__name__}: {exc}")
            j, s = [], []
        plan = plan_dict(journal_rows=j, signal_rows=s)
    else:
        plan = plan_dict()
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
