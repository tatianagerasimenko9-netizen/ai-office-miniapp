"""Макрокалендар: розбір, вікно блоку (30 хв до / 15 хв після), фільтр країни й важливості, «недоступно» без вигадок, інтеграція в check_plan."""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import office_calendar as cal  # noqa: E402

FAILS = []
os.environ["OFFICE_CALENDAR_BLOCK"] = "1"


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


T = datetime(2026, 3, 11, 12, 30, tzinfo=timezone.utc)       # CPI 12:30 UTC
raw = [
    {"title": "CPI m/m", "country": "USD", "date": "2026-03-11T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
    {"title": "German Factory Orders", "country": "EUR", "date": "2026-03-11T08:00:00+01:00", "impact": "High"},
    {"title": "Unemployment Claims", "country": "USD", "date": "2026-03-11T08:30:00-04:00", "impact": "Low"},
    {"title": "Broken", "country": "USD", "date": "не дата", "impact": "High"},
    "сміття",
]
ev = cal.parse(raw)
check("розбір: 3 валідні події, сміття й погана дата пропущені", len(ev) == 3, str(len(ev)))
check("час CPI переведено в UTC", abs(ev[-1]["ts"] - T.timestamp()) < 1 or any(abs(e["ts"] - T.timestamp()) < 1 for e in ev))

os.environ.pop("OFFICE_CALENDAR_COUNTRIES", None)
cal.set_events_for_tests(ev)
t0 = T.timestamp()
check("за 31 хв до виходу — не блокуємо", cal.entry_block(t0 - 31 * 60) is None)
msg = cal.entry_block(t0 - 29 * 60)
check("за 29 хв до виходу — блок із українською назвою й часом (без англійської)", bool(msg) and "Інфляція" in msg and "CPI" not in msg and ":" in msg, str(msg))
check("у момент виходу — блок", cal.entry_block(t0) is not None)
check("через 14 хв після — блок", cal.entry_block(t0 + 14 * 60) is not None)
check("через 16 хв після — блоку нема", cal.entry_block(t0 + 16 * 60) is None)

eur = datetime(2026, 3, 11, 7, 0, tzinfo=timezone.utc).timestamp()   # 08:00+01:00 → 07:00 UTC, EUR
check("EUR-подія за замовчуванням не блокує (лише USD)", cal.entry_block(eur) is None)
os.environ["OFFICE_CALENDAR_COUNTRIES"] = "USD,EUR"
check("з OFFICE_CALENDAR_COUNTRIES=USD,EUR — блокує", cal.entry_block(eur) is not None)
os.environ.pop("OFFICE_CALENDAR_COUNTRIES")
low = t0  # Low-подія о тому ж часі не має сама створювати блок: вилучаємо CPI й лишаємо Low
cal.set_events_for_tests([e for e in ev if e["title"] == "Unemployment Claims"])
check("низька важливість не блокує", cal.entry_block(low) is None)

cal.set_events_for_tests(ev)
os.environ["OFFICE_CALENDAR_BLOCK"] = "0"
check("OFFICE_CALENDAR_BLOCK=0 вимикає блок", cal.entry_block(t0) is None)
os.environ.pop("OFFICE_CALENDAR_BLOCK")
check("за замовчуванням блок вимкнено (без мережі в тестах)", cal.block_enabled() is False)
os.environ["OFFICE_CALENDAR_BLOCK"] = "1"

s = cal.summary(t0 - 3600)
check("summary: є найближча подія, блоку нема", s["status"] == "DATA_OK" and s["block"] is None and s["next"] and "Інфляція" in s["next"]["title"] and "CPI" not in s["next"]["title"], str(s))
s = cal.summary(t0 - 60)
check("summary: блок зараз, назва українською", s["block"] and "Інфляція" in s["block"]["title"])

# джерело недоступне й кешу нема → DATA_UNAVAILABLE, блок не вигадуємо
cal.set_events_for_tests(None)
cal._CACHE["fail_at"] = time.time()          # щойно був збій — джерело не смикаємо
s = cal.summary(t0)
check("немає даних → DATA_UNAVAILABLE і чесна примітка", s["status"] == "DATA_UNAVAILABLE" and "недоступний" in s["note"], str(s))
check("немає даних → вхід не блокуємо", cal.entry_block(t0) is None)

# застарілі (старші за тиждень) дані не видаються за актуальні
cal.set_events_for_tests(ev, at=time.time() - 8 * 86400)
cal._CACHE["fail_at"] = time.time()
check("дані старші за 7 діб → недоступно", cal.load(time.time())["status"] == "DATA_UNAVAILABLE")

# інтеграція: check_plan відхиляє план під час новини
import office_lev_watch as lw  # noqa: E402

cal.set_events_for_tests(ev)
plan = {"entry": 100.0, "sl": 98.0, "tp1": 104.0}
real_entry_block = cal.entry_block
cal.entry_block = lambda now=None: real_entry_block(t0 - 60)   # «зараз» = за хвилину до CPI
why = lw.check_plan("BTCUSDT", "LONG", plan, 99.5, 100.5)
check("check_plan: під час новини план відхилено з українською причиною", bool(why) and "Інфляція" in why and "CPI" not in why, str(why))
cal.entry_block = lambda now=None: real_entry_block(t0 - 3 * 3600)
check("check_plan: поза вікном новини не заважає", "CPI" not in str(lw.check_plan("BTCUSDT", "LONG", plan, 99.5, 100.5)))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
