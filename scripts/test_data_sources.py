#!/usr/bin/env python3
"""Mini App: статуси джерел даних ОКРЕМО (стакан / ліквідації / новини), а не одним рядком «Лев не бачить: стакан і спред, карта ліквідацій»."""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
os.environ.pop("OFFICE_MINI_FIXTURE", None)
os.environ["OFFICE_CALENDAR_BLOCK"] = "1"

import office_calendar as cal  # noqa: E402
import office_data_sources as ds_  # noqa: E402
from office_bridge import init_office_db, log_event  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


db = os.path.join(tempfile.mkdtemp(), "t.db")
init_office_db(db)
now = time.time()
cal.set_events_for_tests(cal.parse([{"title": "CPI m/m", "country": "USD", "date": datetime.fromtimestamp(now + 7200, tz=timezone.utc).isoformat(), "impact": "High"}]))

# --- стакан: авто-режим, серія стабільних годин
os.environ["OFFICE_DEPTH_ENABLED"] = "auto"
H = int(now // 3600)
for k in range(1, 9):
    log_event(db, "DATA_STABILITY", {"hour": H - k, "futures": 1000, "total": 1000, "share": 1.0, "rate_limited": 0})
d = ds_.depth_source("BTCUSDT", db)
check("стакан OFF при 8 з 24 год, з поясненням і лічильником", d["state"] == "off" and "8 з 24" in d["text"] and "вмикається сам" in d["text"], d["text"])
for k in range(9, 26):
    log_event(db, "DATA_STABILITY", {"hour": H - k, "futures": 1000, "total": 1000, "share": 1.0, "rate_limited": 0})
d = ds_.depth_source("BTCUSDT", db)
check("стакан ON, коли 24 год стабільності виконано", d["state"] == "on" and "автоматично" in d["text"], d["text"])
check("стакан для монети поза списком → OFF з поясненням", ds_.depth_source("ENAUSDT", db)["state"] == "off")
os.environ["OFFICE_DEPTH_ENABLED"] = "0"
check("стакан вимкнено в налаштуваннях → так і пише", "в налаштуваннях" in ds_.depth_source("BTCUSDT", db)["text"])
os.environ["OFFICE_DEPTH_ENABLED"] = "auto"

# --- ліквідації
snap = {"at": now - 120, "stream": {"connected": True, "started_at": now - 5 * 3600},
        "symbols": {"BTCUSDT": {"count": 12, "long_liq_usd": 3_200_000.0, "short_liq_usd": 400_000.0, "step": 100,
                                "buckets": [{"kind": "long_liq", "price": 83500.0, "price_to": 83600.0, "usd": 1_900_000.0},
                                            {"kind": "short_liq", "price": 86000.0, "price_to": 86100.0, "usd": 300_000.0}]},
                    "ETHUSDT": {"count": 0, "long_liq_usd": 0.0, "short_liq_usd": 0.0, "buckets": []}}}
log_event(db, "LIQ_MAP", snap)
l = ds_.liq_source("BTCUSDT", "LONG", 83450, 83900, db, now=now)
check("ліквідації ON, з підсумками, періодом і висновком для LONG", l["state"] == "on" and "3,2 млн $" in l["text"] and "400 тис $" in l["text"] and "за останні 5 год" in l["text"]
      and "Купівля ризикованіша" in l["text"] and "Біля зони входу вже були ліквідації лонгів" in l["text"] and "нічого не блокує" in l["text"], l["text"])
s_ = ds_.liq_source("BTCUSDT", "SHORT", 86000, 86200, db, now=now)
check("для SHORT висновок інший: переважали лонги → збігається з напрямком продажу", "збігається з напрямком продажу" in s_["text"], s_["text"])
check("порожній потік: «помітних ліквідацій немає»", "помітних ліквідацій цієї монети немає" in ds_.liq_source("ETHUSDT", "LONG", 1, 2, db, now=now)["text"])
st = ds_.liq_source("BTCUSDT", "LONG", 1, 2, db, now=now + 4000)
check("застарілий зліпок → OFF із причиною", st["state"] == "off" and "застарі" in st["text"], st["text"])
db2 = os.path.join(tempfile.mkdtemp(), "e.db")
init_office_db(db2)
check("потік ще нічого не записав → OFF із причиною", ds_.liq_source("BTCUSDT", "LONG", 1, 2, db2, now=now)["state"] == "off")

# --- новини
check("новини ON, коли календар підключено", ds_.news_source()["state"] == "on")

# --- окремі статуси (головне): стакан OFF не тягне за собою ліквідації
os.environ["OFFICE_DEPTH_ENABLED"] = "auto"
db3 = os.path.join(tempfile.mkdtemp(), "m.db")
init_office_db(db3)
for k in range(1, 9):
    log_event(db3, "DATA_STABILITY", {"hour": H - k, "futures": 1000, "total": 1000, "share": 1.0, "rate_limited": 0})
log_event(db3, "LIQ_MAP", {**snap, "at": time.time() - 60})
src = ds_.sources_for("BTCUSDT", "LONG", 83450, 83900, db3)
by = {x["key"]: x for x in src}
check("три окремі джерела зі своїм станом", set(by) == {"depth", "liquidations", "news"}, str([x["key"] for x in src]))
check("стакан OFF, а ліквідації ON — одночасно", by["depth"]["state"] == "off" and by["liquidations"]["state"] == "on")
blob = json.dumps(src, ensure_ascii=False)
check("немає старого змішаного «стакан і спред, карта ліквідацій»", "карта ліквідацій" not in blob.lower() and "стакан і спред, " not in blob.lower())

# --- інтеграція в картку сценарію та інтерфейс
import office_mini_v2 as m  # noqa: E402

html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "office_web", "mini_v2.html"), encoding="utf-8").read()
check("інтерфейс показує джерела окремими рядками", "hm.context.sources" in html and "Джерела даних" in html)
check("інтерфейс не виводить англійську назву новини (лише headline/text українською)", "newsHtml" in html and "hm.news.next.title" not in html and "hm.news.block.title" not in html)
nc = m.chart_context_payload  # імпорт працює
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
