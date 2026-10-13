#!/usr/bin/env python3
"""Радар sync читає thesis_json порціями: результат не залежить від розміру порції (SYNC_CHUNK=1, 10, 1000 дають ті самі картки), порядок і межі порцій не гублять сценарії."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_bridge as OB  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import radar_watch as RW  # noqa: E402

NOW = 1_800_000_000.0


def thesis(i):
    entry = 100.0 + i
    pv = {"ok": True, "entry": entry, "sl": entry - 1.2, "risk_pct": 1.2 / entry * 100, "targets": [{"p": entry + 1.4 * k, "kind": "PDH", "r": 1.17 * k} for k in (1, 2, 3)], "reject": None}
    return {"id": f"x{i}", "dir": "LONG", "state": "WAIT", "entry_zone": [entry, entry + 0.4], "zone": [entry, entry + 0.4], "level": {"p": entry - 0.5, "kind": "PDL"},
            "need": {"px": entry, "text": "бичаче закриття M15"}, "preview": pv}


def build(n):
    db = os.path.join(tempfile.mkdtemp(), "r.db")
    OB.init_office_db(db)
    EN.init_db(db)
    for i in range(n):
        OB._execute(db, "INSERT INTO office2_live_scenario VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f"O2|s{i:03d}", f"S{i:03d}USDT", "LONG", "SWEEP_SEQ", "WAIT", NOW + i, NOW + i, None, "WAIT 3/3 · ARMED (зона досягнута): ціна в зоні", json.dumps(thesis(i)), "t"))
    return db


def cards(db):
    return sorted(OB._fetchall(db, "SELECT card_id, symbol, entry, sl, tp1, stage FROM office2_radar_card"))


def main():
    n = 37                      # не кратне порціям
    res = {}
    for chunk in (1, 10, 1000):
        RW.SYNC_CHUNK = chunk
        db = build(n)
        out = RW.sync(db, NOW + 100)
        assert out["new"] == n, (chunk, out)
        res[chunk] = cards(db)
    assert res[1] == res[10] == res[1000] and len(res[10]) == n
    print("ok radar sync chunks", n)


main()
