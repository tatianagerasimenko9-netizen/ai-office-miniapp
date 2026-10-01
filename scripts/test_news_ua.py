#!/usr/bin/env python3
"""Новини для користувача — лише українською: переклад назви, пояснення, час Київ, вікно паузи; англійської назви в тексті/JSON немає."""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OFFICE_CALENDAR_BLOCK"] = "1"

import office_calendar as cal  # noqa: E402
import office_news_ua as nu  # noqa: E402

FAILS = []
LAT = re.compile(r"[A-Za-z]")


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# 1. приклад власниці
ts = datetime(2026, 10, 2, 12, 30, tzinfo=timezone.utc).timestamp()      # 15:30 Київ (літній час, UTC+3)
now = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc).timestamp()      # 11:00 Київ — той самий день
ev = {"ts": ts, "title": "Average Hourly Earnings m/m", "country": "USD", "impact": "High"}
d = nu.describe(ev, ticker="BTCUSDT", now=now)
check("назва: «Зміна середньої погодинної зарплати у США»", d["title_ua"] == "Зміна середньої погодинної зарплати у США", d["title_ua"])
check("заголовок = назва — 15:30 (Київ)", d["headline"] == "Зміна середньої погодинної зарплати у США — 15:30", d["headline"])
check("вікно паузи 15:00–15:45 (Київ)", d["window"] == "15:00–15:45", d["window"])
check("текст містить формулювання власниці", "Важлива статистика, під час виходу якої BTC може різко рухатися." in d["text"]
      and "Нові входи з 15:00 до 15:45 не відкриваємо." in d["text"], d["text"])
check("є рядок про цей сценарій (вхід почекає)", "вхід почекає до 15:45" in d["text"])
check("у тексті немає англійських літер, крім тикера BTC", not LAT.search(d["headline"]) and not LAT.search(d["text"].replace("BTC", "")), d["text"])

# 2. поширені події: переклад і жодної латиниці в назві
titles = ["Non-Farm Employment Change", "Unemployment Rate", "CPI m/m", "CPI y/y", "Core CPI m/m", "PPI m/m", "Core PCE Price Index m/m",
          "Federal Funds Rate", "FOMC Statement", "FOMC Press Conference", "FOMC Meeting Minutes", "Fed Chair Powell Speaks",
          "FOMC Member Waller Speaks", "Advance GDP q/q", "Prelim GDP q/q", "Retail Sales m/m", "ISM Manufacturing PMI", "ISM Services PMI",
          "JOLTS Job Openings", "ADP Non-Farm Employment Change", "Unemployment Claims", "Prelim UoM Consumer Sentiment", "Durable Goods Orders m/m",
          "Existing Home Sales", "Crude Oil Inventories", "10-y Bond Auction", "Trade Balance", "Philly Fed Manufacturing Index"]
bad = [t for t in titles if LAT.search(nu.title_ua(t, "USD"))]
check("жодна поширена назва не містить латиниці після перекладу", not bad, str(bad))
generic = [t for t in titles if nu.title_ua(t, "USD") == "Важлива економічна новина США"]
check("усі поширені події мають конкретний переклад (не загальну фразу)", not generic, str(generic))

# 3. невідома назва НЕ показується як є
u = nu.describe({"ts": ts, "title": "Some Brand New Weird Index q/q", "country": "USD"}, ticker="ETH", now=now)
check("невідома назва → загальна українська фраза, оригінал не показано", u["title_ua"] == "Важлива економічна новина США" and "Weird" not in json.dumps(u, ensure_ascii=False), str(u))
check("тикер сценарію в тексті (ETH)", "ETH" in u["text"])

# 4. інший день → день тижня й дата
nd = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc).timestamp()
check("інший день: «пʼятниця, 02.10 о 15:30»", nu.when_ua(ts, nd) == "пʼятниця, 02.10 о 15:30", nu.when_ua(ts, nd))

# 5. під час паузи
in_win = ts - 10 * 60
b = nu.describe(ev, ticker="BTC", now=in_win)
check("під час паузи: blocked і «Зараз діє пауза»", b["blocked"] and "Зараз діє пауза" in b["text"], b["text"])

# 6. news_view: календар → лише українське, без англійської назви в JSON
cal.set_events_for_tests(cal.parse([{"title": "Average Hourly Earnings m/m", "country": "USD", "date": "2026-10-02T12:30:00+00:00", "impact": "High"}]), at=now)
v = nu.news_view(ticker="BTCUSDT", now=now)
blob = json.dumps(v, ensure_ascii=False)
check("news_view: DATA_OK, є пункт", v["status"] == "DATA_OK" and v["item"] and v["item"]["headline"].endswith("— 15:30"), blob)
check("news_view: у JSON немає англійської назви події", "Average" not in blob and "Earnings" not in blob and "m/m" not in blob and "USD" not in blob, blob)
vb = nu.news_view(ticker="BTC", now=in_win)
check("news_view: під час паузи blocked=True", vb["blocked"] is True)
vq = nu.news_view(ticker="BTC", now=ts + 3600)
check("після події — важливих новин немає, українською", vq["item"] is None and "новин" in vq["note"] and not LAT.search(vq["note"]), str(vq))
cal.set_events_for_tests(None)
cal._CACHE["fail_at"] = now      # «щойно був збій» відносно тестового часу — джерело не смикаємо, мережі в тесті немає
vu = nu.news_view(ticker="BTC", now=now)
check("календар недоступний → чесна українська примітка", vu["status"] == "DATA_UNAVAILABLE" and not LAT.search(vu["note"]), str(vu))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
