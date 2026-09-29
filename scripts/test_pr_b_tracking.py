#!/usr/bin/env python3
"""PR-B: одне джерело правди для діалогу /lev, Mini App і відстеження; доставка з результатом і повтором; передача
трекеру карток без дублів; умови з діалогу мають власну сторінку. Офлайн (SQLite), без мережі й Telegram."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "b.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
os.environ.pop("OFFICE_MINI_FIXTURE", None)
import office_lev_dialog as D  # noqa: E402
import office_lev_watch as W  # noqa: E402
import office_mini_v2 as MV  # noqa: E402
from office_bridge import init_office_db, log_event, signal_upsert  # noqa: E402

init_office_db(db)
NOW = datetime.now(timezone.utc)
FRESH = {"price": 0.3106, "fresh": True, "as_of": NOW.isoformat(), "data_status": "DATA_OK"}
MV._live_price = lambda sym: FRESH
MV._human_targets = None
import office_market_data as MD  # noqa: E402
MD.fetch_candles = lambda *a, **k: {}          # рівні для цілей недоступні → «немає обґрунтованої», без мережі

SID = "SCN|LSKUSDT|LONG|H1|54994d1a679acdab"
created = (NOW - timedelta(hours=1)).isoformat()
signal_upsert(db, signal_id=SID, symbol="LSKUSDT", direction="LONG", entry_low=0.30028, entry_high=0.30525, sl=0.29531, tp1=0.31393, tp2=None, rr=None,
              status="ACTIVE", analysis_note=f"ЛЕВ cancel=0.2953189 ckey=LSKUSDT|LONG|0.30028|0.30525 origin=desk tf=H1 scenario_id={SID}")
log_event(db, "THESIS_VERSION", {"thesis_id": SID, "symbol": "LSKUSDT", "direction": "LONG", "state": "WATCHING", "invalidation": "закриття за 0.295319",
                                  "confirmation": "Чекаю на M15: подвійне дно або SFP у зоні"}, SID)
signal_upsert(db, signal_id="lev-watch-LSKUSDT-1", symbol="LSKUSDT", direction="LONG", entry_low=0.30028, entry_high=0.30525, sl=0.29531, tp1=0.31393,
              tp2=None, rr=None, status="WATCHING", analysis_note="WAIT дубль")

# 1. Діалог і сторінка сценарію — той самий стан (Telegram ≡ Mini App)
page = MV.scenario_detail(SID)["human"]
ans = D.answer(db, "лев, аналіз LSK", now=NOW.timestamp())
assert ans["source"] == "scenario" and ans["state"] == page["state"] == "WAIT", (ans["state"], page["state"])
head = ans["text"].split("\n")[0]
assert head == f"{page['icon']} LSK · {page['state_ua'].upper()}", head
assert page["headline"] in ans["text"] and page["wait"] in ans["text"] and page["cancel"] in ans["text"]
inv = D.answer(db, "а інвалідація?", symbol="LSKUSDT", now=NOW.timestamp())
assert "СКАСУЄ ПЛАН" in inv["text"] and "0,29531" in inv["text"] and "LINK" not in inv["text"], inv["text"]
# без свіжої ціни обидва кажуть «Даних немає» (ніде не «готовий»)
MV._live_price = lambda sym: {"price": None, "fresh": False, "as_of": None}
assert MV.scenario_detail(SID)["human"]["state"] == "NO_DATA" and D.answer(db, "аналіз LSK")["state"] == "NO_DATA"
MV._live_price = lambda sym: FRESH

# 2. Один сценарій — один рядок у списку: службовий lev-watch, що дублює картку, прихований
cards = MV.dedupe_cards([{"scenario_id": SID, "symbol": "LSKUSDT", "direction": "LONG", "status_raw": "ACTIVE", "zone_lo": 0.30028, "zone_hi": 0.30525},
                         {"scenario_id": "lev-watch-LSKUSDT-1", "symbol": "LSKUSDT", "direction": "LONG", "status_raw": "WATCHING", "zone_lo": 0.30028, "zone_hi": 0.30525},
                         {"scenario_id": "watch-near-LSKUSDT-scalp", "symbol": "LSKUSDT", "direction": "LONG", "status_raw": "WATCHING", "zone_lo": 0.3115, "zone_hi": 0.3115},
                         {"scenario_id": "lev-watch-ETHUSDT-1", "symbol": "ETHUSDT", "direction": "LONG", "status_raw": "WATCHING", "zone_lo": 1, "zone_hi": 2}])
assert [c["scenario_id"] for c in cards] == [SID, "lev-watch-ETHUSDT-1"], cards

# 3. Умова з діалогу: реєструється лише без відправленої картки; сторінка W-… показує той самий людський стан
assert W.register(db, symbol="LSKUSDT", direction="LONG", zone_lo=0.30028, zone_hi=0.30525, invalidation=0.29531) is None, "картку веде основний трекер"
w = W.register(db, symbol="BTCUSDT", direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=82965, now=NOW)
pg = MV.scenario_detail(w["watch_id"])
assert pg["ok"] and pg["human"]["state"] in ("WAIT", "NO_DATA", "IN_ZONE") and pg["scenario"]["symbol"] == "BTCUSDT", pg.get("human")

# 4. Доставка з результатом: pending → failed → повтор (≤3) → sent; після успіху тиша
late = NOW + timedelta(hours=13)
cs = [{"ts": (late - timedelta(minutes=15 * (8 - i))).isoformat(), "open": 84200, "close": 84200, "low": 84200, "high": 84200} for i in range(8)]
fetch = lambda sym, iv, n=100: cs  # noqa: E731
cyc = lambda d, s: {}  # noqa: E731
out = W.tick(db, now=late, fetch=fetch, cycle_fn=cyc, send_enabled=True)
assert [o["event"] for o in out] == ["EXPIRED"] and W.recent_notes(db)[0]["status"] == "pending"
W.mark_result(db, w["watch_id"], "EXPIRED", False, None, "Telegram 500")
assert W.recent_notes(db)[0]["status"] == "failed" and W.recent_notes(db)[0]["attempts"] == 1 and "500" in W.recent_notes(db)[0]["why"]
r1 = W.tick(db, now=late, fetch=fetch, cycle_fn=cyc, send_enabled=True)
assert len(r1) == 1 and r1[0].get("retry") and r1[0]["event"] == "EXPIRED"
W.mark_result(db, w["watch_id"], "EXPIRED", False, None, "Telegram 500")
W.mark_result(db, w["watch_id"], "EXPIRED", False, None, "Telegram 500")
assert W.tick(db, now=late, fetch=fetch, cycle_fn=cyc, send_enabled=True) == [], "після 3 спроб не спамимо; помилка лишається видимою"
assert W.recent_notes(db)[0]["status"] == "failed" and W.recent_notes(db)[0]["attempts"] == 3
db2 = str(Path(tempfile.mkdtemp()) / "b2.db")
init_office_db(db2)
w2 = W.register(db2, symbol="BTCUSDT", direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=82965, now=NOW)
o2 = W.tick(db2, now=late, fetch=fetch, cycle_fn=cyc, send_enabled=True)
W.mark_result(db2, w2["watch_id"], "EXPIRED", True, 4242)
n = W.recent_notes(db2)[0]
assert n["status"] == "sent" and n["sent"] is True and n["message_id"] == 4242
assert W.tick(db2, now=late, fetch=fetch, cycle_fn=cyc, send_enabled=True) == []

# 5. Передача карткам: умова була зареєстрована, потім Лев відправив картку для тієї ж зони → тиха передача, без повідомлень
db3 = str(Path(tempfile.mkdtemp()) / "b3.db")
init_office_db(db3)
w3 = W.register(db3, symbol="SOLUSDT", direction="LONG", zone_lo=100, zone_hi=101, invalidation=98, now=NOW)
signal_upsert(db3, signal_id="SCN|SOLUSDT|LONG|H1|x", symbol="SOLUSDT", direction="LONG", entry_low=100, entry_high=101.2, sl=98, tp1=104, tp2=None, rr=None,
              status="ACTIVE", analysis_note="cancel=98 tf=H1")
assert W.tick(db3, now=NOW + timedelta(minutes=5), fetch=fetch, cycle_fn=cyc, send_enabled=True) == [] and W.active_watches(db3) == []
print("OK PR-B: dialog ≡ Mini App state, one row per scenario, delivery result+retry, handoff to card tracker")
