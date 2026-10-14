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


def _iter_payloads(db: str, etype: str, signal_like: str = None, chunk: int = 300):
    """Порційне читання payload_json подій типу etype за зростанням id (по chunk рядків): пам'ять не росте разом з історією (раніше fetchall тримав усе одним списком)."""
    from office_bridge import _fetchall

    last = 0
    while True:
        if signal_like:
            rows = _fetchall(db, "SELECT id, signal_id, payload_json FROM office_events WHERE event_type = ? AND signal_id LIKE ? AND id > ? ORDER BY id ASC LIMIT ?", (etype, signal_like, last, chunk))
        else:
            rows = _fetchall(db, "SELECT id, signal_id, payload_json FROM office_events WHERE event_type = ? AND id > ? ORDER BY id ASC LIMIT ?", (etype, last, chunk))
        if not rows:
            return
        for rid, sid, pj in rows:
            last = max(last, int(rid))
            yield sid, pj
        if len(rows) < chunk:
            return


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


_PLAN_KEYS = ("scenario_id", "symbol", "direction", "tf", "entry", "sl", "tp1", "confirmed_ts")
_RES_KEYS = ("scenario_id", "outcome", "filled", "rejected", "time_to_result_sec", "mfe_pct", "mae_pct")


def _last_by_scenario_lean(rows, keys) -> Dict[str, Dict[str, Any]]:
    """Те саме, що _last_by_scenario, але в пам'яті лишаються лише потрібні поля (SIGNAL_PLAN/RESULT старого Лева ≈ 34 тис. подій: повні розібрані payload давали +130 МБ RSS на 512-МБ worker)."""
    out: Dict[str, Dict[str, Any]] = {}
    for (pj,) in rows:
        try:
            j = json.loads(pj or "{}")
        except ValueError:
            continue
        if j.get("scenario_id"):
            out[j["scenario_id"]] = {k: j.get(k) for k in keys if k in j}
    return out


def load_old_lev(db: str) -> List[Dict[str, Any]]:
    plans = _last_by_scenario_lean(((pj,) for _sid, pj in _iter_payloads(db, "SIGNAL_PLAN")), _PLAN_KEYS)
    res = _last_by_scenario_lean(((pj,) for _sid, pj in _iter_payloads(db, "SIGNAL_RESULT")), _RES_KEYS)
    out = []
    for sid, r in res.items():
        t = T.from_old_lev(plans[sid], r) if sid in plans else None
        if t:
            out.append(t)
    return out


def load_office2(db: str) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    sids = [r[0] for r in _fetchall(db, "SELECT scenario_id FROM office2_live_signal WHERE status = 'DELIVERED' ORDER BY created_ts ASC")]
    ms: Dict[str, List[List[Any]]] = {}
    for sid, pj in _iter_payloads(db, "SCENARIO_MILESTONE", signal_like="O2|%"):
        try:
            p = json.loads(pj or "{}")
        except ValueError:
            continue
        if p.get("level") and p.get("sent_ts") is not None:
            ms.setdefault(sid, []).append([p["level"], p["sent_ts"]])
    out = []
    for one in sids:       # знімок (snapshot_json) читаємо по одному сигналу: він містить свічки графіка й важить сотні КБ
        got = _fetchall(db, "SELECT scenario_id, symbol, direction, created_ts, delivered_ts, snapshot_json FROM office2_live_signal WHERE scenario_id = ? AND status = 'DELIVERED'", (one,))
        if not got:
            continue
        sid, sym, d, ct, dl, sj = got[0]
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
        del sn, th, got
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
    try:
        from office2 import paper as PP

        prep = PP.learning_report(db)
        if prep:
            _execute(db, "INSERT INTO office2_learning_report (ts_epoch, scope, n_trades, report_json, version) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                     (int(now), "office2_paper_live", prep["overall"]["closed"], json.dumps(prep, ensure_ascii=False, default=str), VERSION))
            done["office2_paper_live"] = prep["overall"]["closed"]
    except Exception as exc:  # noqa: BLE001
        log(f"[o2learn] paper-звіт не записано: {type(exc).__name__}: {str(exc)[:100]}")
    try:   # розбір аналітика × paper-результати (оцінка якості, прапори, картки): описова статистика, правил не змінює
        from office2 import analyst as AN

        wk = AN.weekly_review(db, now, 7.0)
        if wk["signals"]:
            _execute(db, "INSERT INTO office2_learning_report (ts_epoch, scope, n_trades, report_json, version) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                     (int(now), "analyst_weekly", wk["closed"], json.dumps(wk, ensure_ascii=False, default=str), VERSION))
            done["analyst_weekly"] = wk["closed"]
    except Exception as exc:  # noqa: BLE001
        log(f"[o2learn] звіт аналітика не записано: {type(exc).__name__}: {str(exc)[:100]}")
    log(f"[o2learn] звіт збережено: {done}")
    return done
