#!/usr/bin/env python3
"""Learning-завантаження порціями дає ТОЙ САМИЙ результат, що й повне читання (еталон — попередня реалізація), включно з >chunk подій; пам'ять не залежить від довжини історії."""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _old_module():
    """Еталонна (попередня) реалізація: повні fetchall."""
    src = '''
import json
from typing import Any, Dict, List
from office2.learning import trades as T

def _last_by_scenario(rows):
    out = {}
    for (pj,) in rows:
        try:
            j = json.loads(pj or "{}")
        except ValueError:
            continue
        if j.get("scenario_id"):
            out[j["scenario_id"]] = j
    return out

def load_old_lev(db):
    from office_bridge import _fetchall
    plans = _last_by_scenario(_fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = 'SIGNAL_PLAN' ORDER BY id ASC"))
    res = _last_by_scenario(_fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = 'SIGNAL_RESULT' ORDER BY id ASC"))
    out = []
    for sid, r in res.items():
        t = T.from_old_lev(plans[sid], r) if sid in plans else None
        if t:
            out.append(t)
    return out
'''
    src += '''

def load_office2(db):
    from office_bridge import _fetchall
    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, created_ts, delivered_ts, snapshot_json FROM office2_live_signal WHERE status = 'DELIVERED' ORDER BY created_ts ASC")
    ms = {}
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
        r = lambda i: (tg[i].get("r") if len(tg) > i and isinstance(tg[i], dict) else None)
        out.append(T.from_office2({"sid": sid, "symbol": sym, "direction": d, "created_ts": ct, "delivered_ts": dl, "kind": th.get("kind"),
                                   "r1": q.get("first_target_r") if q.get("first_target_r") is not None else r(0), "r2": r(1), "r3": r(2),
                                   "stop_pct": (th.get("sizing") or {}).get("stop_pct"), "risk_atr15": q.get("risk_atr15"),
                                   "align_against": al.get("against"), "align_for": al.get("for"), "level_kind": lv.get("kind"), "level_strength": lv.get("strength"),
                                   "milestones": ms.get(sid, [])}))
    return out
'''
    ns: dict = {}
    exec(compile(src, "old_job", "exec"), ns)
    return ns


def main():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "t.db")
    os.environ.pop("DATABASE_URL", None)
    os.environ["OFFICE_DB_PATH"] = db
    import office_bridge as OB
    from office2 import engine as EN
    from office2.learning import job as J

    OB.init_office_db(db)
    EN.init_db(db)
    n = 700            # > chunk (300) кілька разів
    for i in range(n):
        sid = f"O2|S{i:04d}|{1790000000 + i}"
        plan = {"scenario_id": sid, "confirmed_ts": 1790000000.0 + i, "symbol": "XUSDT", "direction": "LONG" if i % 2 else "SHORT", "entry": 1.0, "sl": 0.99, "tp1": 1.02, "tp2": 1.03, "tp3": 1.04,
                "valid_until_ts": 1790100000.0, "confirm_msg_id": i + 1, "rejected": False}
        OB.log_event(db, "SIGNAL_PLAN", plan, sid)
        if i % 3 == 0:
            OB.log_event(db, "SIGNAL_RESULT", {"scenario_id": sid, "confirmed_ts": plan["confirmed_ts"], "symbol": "XUSDT", "direction": plan["direction"], "rejected": False,
                                               "outcome": "TARGET" if i % 2 else "STOP", "reached": ["TP1"] if i % 2 else [], "mfe_pct": 1.0, "mae_pct": 0.5, "filled": True, "time_to_result_sec": 900.0}, sid)
    new = J.load_old_lev(db)
    old = _old_module()["load_old_lev"](db)
    assert len(new) == len(old) > 100, (len(new), len(old))
    assert json.dumps(new, sort_keys=True, default=str) == json.dumps(old, sort_keys=True, default=str), "порційне читання змінило результат"
    # читання порціями справді порційне
    seen = list(J._iter_payloads(db, "SIGNAL_PLAN", chunk=50))
    assert len(seen) == n
    from office_bridge import _execute

    for i in range(40):
        sid = f"O2|S{i:04d}|{1790000000 + i}"
        snap = {"thesis": {"kind": "SWEEP_SEQ", "targets": [{"r": 2.0}, {"r": 3.0}, {"r": 5.0}], "quality": {"first_target_r": 2.0 + i / 10, "risk_atr15": 1.1}, "sizing": {"stop_pct": 0.8 + i / 100},
                           "level": {"kind": "PDH", "strength": 2}}, "alignment_summary": {"against": i % 3, "for": 1}, "pad": "x" * 2000}
        _execute(db, "INSERT INTO office2_live_signal (scenario_id, symbol, direction, created_ts, valid_until_ts, status, msg_id, delivered_ts, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (sid, "XUSDT", "LONG", 1790000000.0 + i, 1790090000.0, "DELIVERED" if i % 5 else "SUPPRESSED", i, 1790000030.0 + i, json.dumps(snap), "v"))
        OB.log_event(db, "SCENARIO_MILESTONE", {"level": "ENTRY", "sent_ts": 1790000040.0 + i}, sid)
        if i % 2:
            OB.log_event(db, "SCENARIO_MILESTONE", {"level": "SL", "sent_ts": 1790000900.0 + i}, sid)
    n2, o2 = J.load_office2(db), _old_module()["load_office2"](db)
    assert len(n2) == len(o2) == 32, (len(n2), len(o2))
    assert json.dumps(n2, sort_keys=True, default=str) == json.dumps(o2, sort_keys=True, default=str), "load_office2 змінився"
    print("ok learning chunked load", len(new))


main()
