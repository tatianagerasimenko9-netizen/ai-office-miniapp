"""Фонове накопичення досвіду: читає історію з БД → нормалізує → аналізує → пише звіт у office2_learning_report. Лише читає торгові таблиці. Kill-switch: OFFICE2_LEARNING=0."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, List

from office2.learning import report as R
from office2.learning import trades as T

DDL = ("""CREATE TABLE IF NOT EXISTS office2_learning_report (
    ts_epoch BIGINT NOT NULL, scope TEXT NOT NULL, n_trades INTEGER NOT NULL, report_json TEXT NOT NULL, version TEXT NOT NULL,
    PRIMARY KEY (ts_epoch, scope))""",)
VERSION = "learning-1"
EVERY_SEC = 6 * 3600


def enabled() -> bool:
    return os.getenv("OFFICE2_LEARNING", "1").strip().lower() not in ("0", "false", "no", "off")


def _last_by_scenario(rows) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for (pj,) in rows:
        try:
            j = json.loads(pj or "{}")
        except ValueError:
            continue
        if j.get("scenario_id"):
            out[j["scenario_id"]] = j
    return out


def load_old_lev(db: str) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    plans = _last_by_scenario(_fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = 'SIGNAL_PLAN' ORDER BY id ASC"))
    res = _last_by_scenario(_fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = 'SIGNAL_RESULT' ORDER BY id ASC"))
    out = []
    for sid, r in res.items():
        t = T.from_old_lev(plans[sid], r) if sid in plans else None
        if t:
            out.append(t)
    return out


def load_office2(db: str) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, created_ts, delivered_ts, snapshot_json FROM office2_live_signal WHERE status = 'DELIVERED' ORDER BY created_ts ASC")
    ms: Dict[str, List[List[Any]]] = {}
    for sid, pj in _fetchall(db, "SELECT signal_id, payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id LIKE 'O2|%' ORDER BY id ASC"):
        try:
            p = json.loads(pj or "{}")
        except ValueError:
            continue
        if p.get("level") and p.get("sent_ts") is not None:
            ms.setdefault(sid, []).append([p["level"], p["sent_ts"]])
    out = []
    for sid, sym, d, ct, dl, sj in rows:
        sn = json.loads(sj or "{}")
        th = sn.get("thesis") or {}
        q = th.get("quality") or {}
        tg = th.get("targets") or []
        al = sn.get("alignment_summary") or {}
        lv = th.get("level") or {}
        r = lambda i: (tg[i].get("r") if len(tg) > i and isinstance(tg[i], dict) else None)   # noqa: E731
        out.append(T.from_office2({"sid": sid, "symbol": sym, "direction": d, "created_ts": ct, "delivered_ts": dl, "kind": th.get("kind"),
                                   "r1": q.get("first_target_r") if q.get("first_target_r") is not None else r(0), "r2": r(1), "r3": r(2),
                                   "stop_pct": (th.get("sizing") or {}).get("stop_pct"), "risk_atr15": q.get("risk_atr15"),
                                   "align_against": al.get("against"), "align_for": al.get("for"), "level_kind": lv.get("kind"), "level_strength": lv.get("strength"),
                                   "milestones": ms.get(sid, [])}))
    return out


def run_once(db: str, now: float = None, log: Callable[[str], None] = print) -> Dict[str, int]:
    from office_bridge import _execute

    now = time.time() if now is None else now
    for d in DDL:
        _execute(db, d)
    scopes = {"office2": load_office2(db)}
    old = load_old_lev(db)
    scopes["old_lev_delivered"] = [t for t in old if t["delivered_to_user"]]
    scopes["old_lev_shadow"] = [t for t in old if not t["delivered_to_user"]]
    done = {}
    for name, trades in scopes.items():
        if not trades:
            continue
        rep = R.build(trades)
        _execute(db, "INSERT INTO office2_learning_report (ts_epoch, scope, n_trades, report_json, version) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                 (int(now), name, len(trades), json.dumps(rep, ensure_ascii=False), VERSION))
        done[name] = len(trades)
    log(f"[o2learn] звіт збережено: {done}")
    return done
