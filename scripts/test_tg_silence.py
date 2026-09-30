#!/usr/bin/env python3
"""Telegram — лише (а) готовий сигнал, (б) ведення позначеної угоди. Протермінований план — ніколи. 13 старих планів після рестарту → 0 повідомлень."""
import inspect
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
from office_telegram_policy import outbound_allowed  # noqa: E402
import office_scenario_lifecycle as L  # noqa: E402

A = outbound_allowed
# дозволено
assert A(event_type="TRADE_UPDATE", kind="CONFIRM", intent="CONFIRM")
assert A(event_type="TRADE_UPDATE", kind="TP1", intent="POSITION_MANAGE", confirmed_position=True, position_open=True)
# заборонено: скасування, завершення терміну, WATCHING-картка, аналітика, новини, службове, супровід без позначеної угоди
for kw in (dict(event_type="TRADE_UPDATE", kind="CANCEL_BEFORE_ENTRY", intent="ANALYTICAL"),
           dict(event_type="TRADE_UPDATE", kind="EXPIRED", intent="ANALYTICAL"),
           dict(event_type="SIGNAL_ENTRY", kind="SIGNAL", intent="SIGNAL"),
           dict(event_type="NEWS_CRITICAL", kind="NEWS", intent="ANALYTICAL"),
           dict(event_type="EVENING_DEBRIEF", kind="", intent=""),
           dict(event_type="TRADE_UPDATE", kind="CONFIRM", intent="ANALYTICAL"),
           dict(event_type="TRADE_UPDATE", kind="TP1", intent="POSITION_MANAGE"),
           dict(event_type="TRADE_UPDATE", kind="TP1", intent="POSITION_MANAGE", confirmed_position=True, position_open=False)):
    assert not A(**kw), kw
os.environ["OFFICE_TG_STRICT"] = "0"
assert A(event_type="NEWS_CRITICAL", kind="NEWS", intent="ANALYTICAL"), "відкат працює"
del os.environ["OFFICE_TG_STRICT"]

# 13 протермінованих підтверджених планів після рестарту: усі знімаються в БД, жодного повідомлення (функція чиста, у relay після неї лише signal_update)
now = time.time()
old = [{"ts_updated": now - 30 * 3600, "tf": "H1", "sl": 0.25, "direction": "LONG"} for _ in range(13)]
acts = [L.confirmed_plan_action(ts_updated=r["ts_updated"], tf=r["tf"], sl=r["sl"], direction=r["direction"], candles_h1=[], has_position=False, now_ts=now) for r in old]
assert all(a and a["status"] == "EXPIRED" for a in acts) and len(acts) == 13
# угода позначена відкритою — термін плану її не зачіпає
assert L.confirmed_plan_action(ts_updated=now - 30 * 3600, tf="H1", sl=0.25, direction="LONG", candles_h1=[], has_position=True, now_ts=now) is None
# гілка CONFIRMED у relay не містить відправки
import re  # noqa: E402

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "office_relay_wizard.py"), encoding="utf-8").read()
blk = src[src.index("План надіслано, угоду власниця не позначала"):src.index("from office_lifecycle import watching_ttl_enabled")]
assert "send_proactive" not in blk and "send_office" not in blk, "у гілці терміну/скасування плану не має бути відправки"
assert "_tg_allowed(" in src[src.index("async def send_proactive("):src.index("async def send_proactive(") + 2500], "єдиний шлюз у send_proactive"
print("OK telegram silence: only ready signal + managed trade; expired/cancelled plans never; 13 old plans → 0 messages")
