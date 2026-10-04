#!/usr/bin/env python3
"""ALGO (живий випадок): Telegram READY + Mini App «План не готовий» через резервний ринок.
Правило: доставлений READY лишається READY із ТИМИ САМИМИ рівнями, що в Telegram (вхід, стоп, TP1/2/3); якщо зараз ціни не з ф'ючерсів Binance —
«Зараз» = ⚠️ ПЛАН ПРИЗУПИНЕНО з причиною й часом, новий вхід не підтверджуємо, рівні не змінюються."""
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_market_data as MD  # noqa: E402
import office_mini_v2 as M  # noqa: E402
import office_ready_core as RC  # noqa: E402

ISO = datetime.now(timezone.utc).isoformat()
SID = "SCN|ALGOUSDT|SHORT|H1|7c3ebff7233ba2e2"
E, SL, T1, T2, T3, ME = 0.13038, 0.133195855, 0.12469, 0.12231, 0.10278, 0.12935166466466308
row = {"signal_id": SID, "symbol": "ALGOUSDT", "direction": "SHORT", "entry_low": 0.12924512, "entry_high": 0.13231, "sl": SL, "tp1": T1, "tp2": T2,
       "status": "CONFIRMED", "ts_created": ISO, "ts_updated": ISO,
       "analysis_note": f"ЛЕВ cancel={SL} origin=desk tf=H1 scenario_id={SID} confirm_sent=1 confirmed_px={E}"}
plan = {"scenario_id": SID, "symbol": "ALGOUSDT", "direction": "SHORT", "tf": "H1", "entry": E, "sl": SL, "tp1": T1, "tp2": T2, "tp3": T3, "max_entry": ME,
        "confirmed_ts": time.time() - 540, "valid_until_ts": time.time() + 86400 - 540, "rejected": False, "confirm_msg_id": 9791,
        "gate": RC.gate_snapshot(direction="SHORT", entry=E, sl=SL, tp1=T1, tp2=T2, tp3=T3, max_entry=ME, min_tp1_pct=3.0,
                                 confirm=RC.confirm_basis({"confirms": ["level_hold"], "detail": "закріплення за рівнем + закриття в зоні 0.1292–0.1323", "price": E}))}

M._fixture_on = lambda: True
M._live_price = lambda sym: {"price": 0.1306, "fresh": True, "as_of": ISO}

# 1) ф'ючерси є: READY, рівні = Telegram
MD._FALLBACK_AT.clear()
v = M._human_view(row, None, [], plan)
assert v["state"] == "READY", v["state"]
lv = {x["k"]: x["raw"] for x in v["ready"]["levels"]}
assert lv == {"sl": SL, "tp1": T1, "tp2": T2, "tp3": T3}, lv
assert v["ready"]["entry"].replace(",", ".").replace(" $", "") == "0.13038", v["ready"]["entry"]
assert not v["now"].get("paused")

# 2) зараз тільки спот: те саме READY, рівні ті самі, але «Зараз» призупинено
MD._FALLBACK_AT["ALGOUSDT"] = (time.time(), "binance_spot_vision", time.time() - 600)
v2 = M._human_view(row, None, [], plan)
assert v2["state"] == "READY" and v2["state_ua"] != "План не готовий", (v2["state"], v2.get("state_ua"))
assert {x["k"]: x["raw"] for x in v2["ready"]["levels"]} == lv, "рівні змінились після переходу на резервний ринок"
p = v2["now"]["paused"]
assert p["title"] == "⚠️ ПЛАН ПРИЗУПИНЕНО" and "Ф'ючерси Binance недоступні з " in p["reason"] and "спот" in p["reason"], p
assert "Новий вхід не підтверджуємо" in p["action"] and "не змінилися" in p["action"], p
assert v2["now"]["eligible"] is None
# історія не суперечить: стан не «не готовий»
assert "не готовий" not in str(v2.get("headline", "")).lower(), v2.get("headline")

# 3) обидва екрани дають однакові числа (Telegram-картка з того ж знімка)
import office_user_messages as UM  # noqa: E402

card = UM.ready_signal(symbol="ALGOUSDT", direction="SHORT", entry=E, sl=SL, tp1=T1, tp2=T2, tp3=T3, valid_until=RC.kyiv_stamp(plan["valid_until_ts"]),
                       setup=v["ready"]["setup"]["name"] or "", why=v["ready"]["setup"]["why"])
for lvl in (E, SL, T1, T2, T3):
    assert str(lvl).rstrip("0").replace(".", ",")[:7] in card.replace(" ", ""), (lvl, card)
print("OK ALGO: READY не стає «не готовий» через резервний ринок; рівні Telegram = Mini App; «Зараз» → ПЛАН ПРИЗУПИНЕНО з причиною")
