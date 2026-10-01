#!/usr/bin/env python3
"""Одноразова перевірка Mini App на живих даних: пише результат у БД (новини, джерела, шари графіка по ТФ), повторно не виконується."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db = os.path.join(tempfile.mkdtemp(), "u.db")
os.environ["OFFICE_DB_PATH"] = db
os.environ["OFFICE_MINI_FIXTURE"] = "1"
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

from office_bridge import _fetchall, init_office_db, signal_upsert  # noqa: E402
import office_ui_check as uc  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


init_office_db(db)
signal_upsert(db, signal_id="ui-btc-1", symbol="BTCUSDT", direction="LONG", entry_low=99.8, entry_high=100.2, sl=98.0, tp1=104.0, tp2=106.0, rr=None, status="ACTIVE",
              analysis_note="Чекаю відкат")
msgs = []
check("перевірка виконується вперше", uc.run_once(db, printer=msgs.append) is True)
ev = [json.loads(r[0]) for r in _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ?", ("LAUNCH_DIAG",))]
main = [e for e in ev if e.get("task") == "ui_check"]
charts = [e for e in ev if e.get("task") == "ui_check_chart"]
check("є запис про сценарій без помилки", len(main) == 1 and "error" not in main[0], str(main)[:300])
check("шари графіка записано по всіх 6 ТФ", sorted(e["tf"] for e in charts) == sorted(uc.TFS), str([e.get("tf") for e in charts]))
check("канал є на кожному ТФ", all(e.get("channel") for e in charts), str([(e["tf"], e.get("channel")) for e in charts]))
check("у payload графіка немає внутрішніх рівнів", all(set(e["keys"]) <= {"ok", "symbol", "tf", "data_status", "channel", "fvg", "strong_candle", "previous", "note"} for e in charts))
check("жодних англійських літер у новинах (поле порожнє)", main[0].get("news_latin_letters") == [] , str(main[0].get("news_latin_letters")))
check("повторний запуск нічого не робить", uc.run_once(db, printer=msgs.append) is False)

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
