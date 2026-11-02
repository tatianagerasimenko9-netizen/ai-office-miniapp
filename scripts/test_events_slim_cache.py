"""Гарячі цикли супроводу читають події інкрементально й без важких полів (пам'ять Worker біля ліміту 512 МБ): результат ≡ повне читання (без gate/trace/chart)."""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "s.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="")
import office_bridge as OB  # noqa: E402
import office_signal_track as T  # noqa: E402

OB.init_office_db(db)
ok = True


def check(n, c, i=""):
    global ok
    print(("OK   " if c else "FAIL ") + n, "" if c else i)
    ok &= bool(c)


def put(etype, sid, payload, ts=None):
    ts = ts or datetime.now(timezone.utc).isoformat()
    OB._execute(db, "INSERT INTO office_events(ts_utc, event_type, signal_id, payload_json) VALUES (?,?,?,?)", (ts, etype, sid, json.dumps(payload)))


def key(evs):
    return [(e["id"], e["signal_id"], e["p"].get("scenario_id")) for e in evs]


T.reset_events_cache()
h = time.time() - 14 * 86400
big = {"scenario_id": "O2|a|1", "symbol": "X", "gate": {"trace": ["x" * 1000] * 50}, "chart": {"candles": [[1] * 6] * 96}, "confirmed_ts": 1.0}
put(T.EV_PLAN, "O2|a|1", big)
put(T.EV_PLAN, "O2|b|1", dict(big, scenario_id="O2|b|1"))
a = T._events_slim(db, T.EV_PLAN, h)
full = T._events(db, T.EV_PLAN, h)
check("перший прохід ≡ повне читання за ключами", key(a) == key(full) and len(a) == 2)
check("важкі поля не тримаємо", all("gate" not in e["p"] and "chart" not in e["p"] and e["p"].get("symbol") == "X" for e in a))
put(T.EV_PLAN, "O2|c|1", dict(big, scenario_id="O2|c|1"))
b = T._events_slim(db, T.EV_PLAN, h)
check("нова подія підхоплена, старі без дублів", key(b) == key(T._events(db, T.EV_PLAN, h)) and len(b) == 3, key(b))
c = T._events_slim(db, T.EV_PLAN, h)
check("повторний прохід стабільний", key(c) == key(b))
# горизонт: стара подія відсікається
old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
put(T.EV_MILESTONE, "O2|old|1", {"scenario_id": "O2|old|1", "level": "SL"}, ts=old_ts)
put(T.EV_MILESTONE, "O2|new|1", {"scenario_id": "O2|new|1", "level": "TP1"})
m = T._events_slim(db, T.EV_MILESTONE, h)
check("поза горизонтом не повертається", [e["signal_id"] for e in m] == ["O2|new|1"], key(m))
# відставлений коміт: подія з id нижче вже прочитаного (перекриття)
mx = OB._fetchone(db, "SELECT MAX(id) FROM office_events")[0]
T._SLIM_CACHE[(db, T.EV_PLAN)]["last_id"] = mx + 100      # «прочитали далі, ніж є» (в межах перекриття)
put(T.EV_PLAN, "O2|late|1", dict(big, scenario_id="O2|late|1"))
d = T._events_slim(db, T.EV_PLAN, h)
check("перекриття підхоплює подію нижче last_id (Postgres: пізніший коміт)", any(e["signal_id"] == "O2|late|1" for e in d), key(d))
print("ALL OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
