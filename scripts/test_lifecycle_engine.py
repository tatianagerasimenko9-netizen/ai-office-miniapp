#!/usr/bin/env python3
"""Життєвий цикл у справжньому рушії (ізольована БД, синтетичні свічки, без мережі): ПРОДОВЖЕННЯ не створює новий READY; ПОВТОРНИЙ ВХІД несе посилання на попередній №
і йде відповіддю на його повідомлення; режим off повертає стару поведінку."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_office2_live as T  # noqa: E402
import office_bridge as OB  # noqa: E402
import office_ready_card as card  # noqa: E402
from office2 import delivery as DL  # noqa: E402
from office2 import lifecycle as LC  # noqa: E402

bad = 0


def check(name, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f" :: {info}"))
    bad += 0 if ok else 1


PARENT = {"scenario_id": "O2|aaaaaaaaaaaa|1790000000", "seq": 3, "msg_id": 10575, "created_ts": 1790000000.0, "valid_until_ts": 1790021600.0, "milestones": ["ENTRY", "TP1"], "entered": True,
          "terminal": [], "live": True, "plan": {"entry": 103.0, "sl": 102.0, "targets": [{"kind": "H4SW", "p": 105.0, "r": 2.0}], "zone": [102.8, 103.1], "thesis_id": "O2|aaaaaaaaaaaa", "invalidation": 102.0, "event": {}}}
bars, _ = T.S.build()


def run(mode, relation):
    os.environ["OFFICE2_LIFECYCLE"] = mode
    real = LC.relate
    LC.relate = lambda db, sym, d, th, now: {"relation": relation, "parent": dict(PARENT, terminal=["SL"] if relation == "REENTRY" else [], live=relation != "REENTRY") if relation != "NEW" else None, "same_idea": relation == "DUPLICATE",
                                             "difference": {"new_event": {"class": "FRESH_RAID", "kind": "LONDON_L"}, "new_invalidation": 101.5, "parent_invalidation": 102.0} if relation == "INDEPENDENT" else None}
    try:
        with tempfile.TemporaryDirectory() as td:
            db = T._db(td)
            T._drive(db, bars, [[103.6], [103.6, 103.8], [103.6, 103.8, 103.9]])
            sig = OB._fetchall(db, "SELECT scenario_id, status, snapshot_json FROM office2_live_signal")
            LC._ensure(db)
            ev = OB._fetchall(db, "SELECT event_id, relation, parent_seq, payload_json FROM office2_lifecycle_event")
            scen = OB._fetchall(db, "SELECT state, reason FROM office2_live_scenario")
            out = {"sig": sig, "ev": ev, "scen": scen}
            if sig:
                b = T.extend(bars, [103.6, 103.8, 103.9])
                sent = T._Sent()
                created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]
                n = asyncio.run(DL.deliver_pending(db, sent, lambda s, tf, lim: T._candles(b), card.render, "TRADE_UPDATE", now=created + 60, log=lambda m: None))
                out["sent"] = (n, sent.calls)
            return out
    finally:
        LC.relate = real
        os.environ.pop("OFFICE2_LIFECYCLE", None)


r = run("merge", "CONTINUATION")
check("ПРОДОВЖЕННЯ (merge): нового READY немає", r["sig"] == [], r["sig"])
check("ПРОДОВЖЕННЯ: сценарій збережено як NO_TRADE з поясненням «продовження сценарію №3»", any(s == "NO_TRADE" and "продовження сценарію №3" in (why or "") for s, why in r["scen"]), r["scen"])
pl0 = json.loads(r["ev"][0][3]) if r["ev"] else {}
check("ПРОДОВЖЕННЯ: створено рівно одну подію в гілці початкового №3; пропозиція цілей — «НЕ ЗАСТОСОВАНО», початковий план не змінюється",
      len(r["ev"]) == 1 and r["ev"][0][1] == "CONTINUATION" and r["ev"][0][2] == 3 and "ПРОПОЗИЦІЯ · НЕ ЗАСТОСОВАНО" in pl0["text"] and pl0["proposal"]["applied"] is False, r["ev"])

r = run("merge", "DUPLICATE")
check("ДУБЛІКАТ: нічого не надсилається (ні READY, ні події)", r["sig"] == [] and r["ev"] == [] and any("дублікат" in (why or "") for _s, why in r["scen"]), r)

r = run("merge", "INDEPENDENT")
snap = json.loads(r["sig"][0][2]) if r["sig"] else {}
n, calls = r["sent"] if r["sig"] else (0, [])
check("НЕЗАЛЕЖНИЙ сетап: окремий READY, у картці явне пояснення відмінності від №3 (нова структура, своє скасування), відповідь на №3",
      len(r["sig"]) == 1 and snap["thesis"]["lifecycle"]["relation"] == "INDEPENDENT" and "◆ НОВИЙ НЕЗАЛЕЖНИЙ СЕТАП · відмінність від №3" in calls[0][1] and "власне скасування 101,5" in calls[0][1] and calls[0][2].get("reply_to_message_id") == 10575, calls[0][1][:300] if calls else r)

r = run("annotate", "CONTINUATION")
check("режим annotate: READY лишається як раніше (рішення не змінено), позначка життєвого циклу в знімку", len(r["sig"]) == 1 and json.loads(r["sig"][0][2])["thesis"].get("lifecycle", {}).get("relation") == "CONTINUATION")

r = run("off", "CONTINUATION")
check("режим off: стара поведінка (READY є, подій немає, позначки немає)", len(r["sig"]) == 1 and "lifecycle" not in json.loads(r["sig"][0][2])["thesis"])

r = run("merge", "REENTRY")
snap = json.loads(r["sig"][0][2]) if r["sig"] else {}
check("ПОВТОРНИЙ ВХІД: окремий READY зі зв'язком у знімку", len(r["sig"]) == 1 and snap["thesis"]["lifecycle"]["relation"] == "REENTRY" and snap["thesis"]["lifecycle"]["parent_seq"] == 3, snap.get("thesis", {}).get("lifecycle"))
n, calls = r["sent"]
check("ПОВТОРНИЙ ВХІД: Telegram-картка з рядком «↻ ПОВТОРНИЙ ВХІД · після №3» і відповіддю на повідомлення №3 (id 10575)", n == 1 and "↻ ПОВТОРНИЙ ВХІД · після №3 (SL)" in calls[0][1] and calls[0][2].get("reply_to_message_id") == 10575 and calls[0][1].startswith("AI Office · №1\n"), calls[0][1][:200])

r = run("merge", "NEW")
check("звичайний READY (немає попередніх): без зв'язків, як раніше", len(r["sig"]) == 1 and "lifecycle" not in json.loads(r["sig"][0][2])["thesis"] and r["sent"][1][0][2].get("reply_to_message_id") is None)
print("ALL OK" if not bad else f"FAILED {bad}")
sys.exit(1 if bad else 0)
