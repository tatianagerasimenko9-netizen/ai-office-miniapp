#!/usr/bin/env python3
"""Посилання з Telegram на картку радара: справжній HTTP-сервер Mini App на тимчасовій БД; картка знаходиться за коротким, старим, одинарно й подвійно закодованим посиланням.
(Регресія помилки «Картку не знайдено» з production 11.10.)"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import office_bridge as OB  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import radar_text as RT  # noqa: E402
from office2 import radar_watch as RW  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "dl.db")
OB.init_office_db(db)
EN.init_db(db)
NOW = time.time()
HEX = "687671d4c162"
th = {"id": "d", "dir": "SHORT", "entry": 1.2338, "sl": 1.246, "risk_pct": 1.0, "targets": [{"p": 1.2, "kind": "PDL", "r": 3.0}], "entry_zone": [1.2338, 1.2399], "level": {"p": 1.2434, "kind": "D1H"}}
OB._execute(db, "INSERT INTO office2_live_scenario VALUES (?,?,?,?,?,?,?,?,?,?,?)", (f"O2|{HEX}", "DOTUSDT", "SHORT", "SWEEP_SEQ", "NO_TRADE", NOW - 60, NOW - 60, None, "ємність сценаріїв: денний ліміт: 3 стопи за добу UTC", json.dumps(th), "t"))
RW.sync(db, NOW)
s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
env = {**os.environ, "OFFICE_DB_PATH": db, "OFFICE_MINI_FIXTURE": "1", "OFFICE_EXINFO_SEED": "1", "OFFICE_MINI_PORT": str(port), "OFFICE_MINI_HOST": "127.0.0.1", "DATABASE_URL": ""}
proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "office_mini_app.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    base = f"http://127.0.0.1:{port}"
    card_id = f"B|O2|{HEX}"
    lid = RT.link_id(card_id)
    for name, tok in (("коротке (те, що йде в Telegram)", quote(lid, safe="")), ("старе W|O2|… закодоване", quote(card_id, safe="")), ("подвійно закодоване", quote(quote(card_id, safe=""), safe="")), ("лише хеш", HEX)):
        d = json.loads(urlopen(f"{base}/api/v2/live_radar?card={tok}", timeout=15).read())
        c = d.get("card")
        check(f"HTTP: картка знайдена за посиланням — {name}", bool(c) and c["card_id"] == card_id and c["h"]["status"], str(d)[:200])
    d = json.loads(urlopen(f"{base}/api/v2/live_radar?card=B-ffffffffffff", timeout=15).read())
    check("HTTP: неіснуюча картка → card=null (UI покаже зрозуміле повідомлення)", d.get("ok") and d.get("card") is None)
    html = urlopen(f"{base}/v2?tab=radar&card={quote(lid, safe='')}", timeout=15).read().decode()
    check("HTTP: сторінка /v2 з параметром card віддається й вміє відкрити картку", "openRadarCard" in html and "qs.get('card')" in html)
    lst = json.loads(urlopen(f"{base}/api/v2/live_radar", timeout=15).read())
    check("HTTP: список карток із готовими українськими текстами", lst["cards"] and lst["cards"][0]["h"]["title"].startswith("🎓") and lst["why_no_ready"]["message"], str(lst)[:200])
finally:
    proc.terminate()
print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
