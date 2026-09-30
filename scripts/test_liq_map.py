#!/usr/bin/env python3
"""Карта ліквідацій: розбір forceOrder, фактичні групи за ціною, оцінка з OI і плеча (модель), застарілі дані, потік із перемиканням адреси."""
import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_liq_map as L  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


NOW = time.time()


def fo(sym, side, price, qty, ts=None, wrap=True):
    ev = {"e": "forceOrder", "E": int((ts or NOW) * 1000), "o": {"s": sym, "S": side, "ap": str(price), "p": str(price), "q": str(qty), "z": str(qty), "T": int((ts or NOW) * 1000)}}
    return json.dumps({"stream": "!forceOrder@arr", "data": ev} if wrap else ev)


# --- розбір ---
a = L.parse_event(fo("BTCUSDT", "SELL", 60000, 0.5))
check("SELL = ліквідація ЛОНГА, обсяг = ціна × кількість", a and a["kind"] == "long_liq" and abs(a["notional"] - 30000) < 1e-6, str(a))
b = L.parse_event(fo("ETHUSDT", "BUY", 3000, 10, wrap=False))
check("BUY = ліквідація ШОРТА; повідомлення без обгортки теж читається", b and b["kind"] == "short_liq" and b["symbol"] == "ETHUSDT", str(b))
check("сміття, не-ліквідація, нульова кількість → None", L.parse_event("{") is None and L.parse_event(json.dumps({"e": "kline"})) is None and L.parse_event(fo("BTCUSDT", "SELL", 60000, 0)) is None)

# --- фактичні групи ---
L.reset_for_tests()
for i in range(5):
    L.ingest(L.parse_event(fo("BTCUSDT", "SELL", 59000 + i * 10, 1.0, ts=NOW - 600)))      # лонги ліквідовано близько 59 000
L.ingest(L.parse_event(fo("BTCUSDT", "BUY", 61500, 2.0, ts=NOW - 300)))
L.ingest(L.parse_event(fo("BTCUSDT", "SELL", 40000, 9.0, ts=NOW - 30 * 3600)))            # старіше 24 год — не рахується
L.ingest(L.parse_event(fo("ETHUSDT", "SELL", 3000, 100.0, ts=NOW - 100)))
snap = L.real_snapshot("BTCUSDT", NOW)
check("фактичні: 6 подій за 24 год (старішу відкинуто)", snap["count"] == 6, str(snap))
check("фактичні: лонг і шорт-ліквідації окремо в USD", abs(snap["long_liq_usd"] - sum(59000 + i * 10 for i in range(5))) < 1e-3 and abs(snap["short_liq_usd"] - 123000) < 1e-3, str(snap))
check("фактичні: найбільша група — ліквідації лонгів біля 59 000", snap["buckets"][0]["kind"] in ("long_liq", "short_liq") and snap["buckets"][0]["usd"] >= 123000 - 1, str(snap["buckets"][:2]))
check("підпис: «не прогноз»", "не прогноз" in snap["label"])
empty = L.real_snapshot("XYZUSDT", NOW)
check("символ без ліквідацій: нуль, а не вигадка", empty["count"] == 0 and empty["buckets"] == [])
allsnap = L.snapshot_all(now=NOW)
check("зліпок для БД: BTC і ETH присутні", "BTCUSDT" in allsnap["symbols"] and "ETHUSDT" in allsnap["symbols"])

# --- оцінка з OI і плеча ---
T0 = datetime.fromtimestamp((NOW // 3600) * 3600 - 60 * 3600, tz=timezone.utc)


def bars(n, low_fn=None):
    out = []
    for i in range(n):
        lo = low_fn(i) if low_fn else 99.8
        out.append({"ts": (T0 + timedelta(hours=i)).isoformat(), "open": 100.0, "high": 100.2, "low": lo, "close": 100.0})
    return out


def oi(n, step=1e6, last_age_h=0):
    return [{"oi": 1e8 + i * step, "timestamp": (T0 + timedelta(hours=i)).timestamp()} for i in range(n)]


def ls(n, ratio=1.0):
    return [{"ratio": ratio, "timestamp": (T0 + timedelta(hours=i)).timestamp()} for i in range(n)]


N = 58
est = L.estimate(bars(N), oi(N), ls(N), now=(T0 + timedelta(hours=N - 1)).timestamp() + 600)
check("оцінка ок: є кластери нижче (лонги) і вище (шорти) ціни", est["ok"] and est["below"] and est["above"], str(est)[:300])
check("підпис оцінки: модель, не дані біржі", "модель" in est["label"] and "не дані біржі" in est["label"])
check("лонг-кластери нижче ціни, шорт-кластери вище", all(r["price"] < 100 for r in est["below"]) and all(r["price_to"] > 100 for r in est["above"]))
lv10 = [r for r in est["below"] if 90.0 <= r["price"] < 91.0]
lv25 = [r for r in est["below"] if 96.0 <= r["price"] < 97.0]
check("плече 10× → рівень ≈ 90,5, 25× → ≈ 96,5 (ціна × (1 − 1/плече + 0,5%))", bool(lv10) and bool(lv25), str(est["below"]))

# ціна впала до 96 на 40-й годині: лонги з ліквідацією вище 96 і відкриті до того — ліквідовані, не рахуємо
low = lambda i: 96.0 if i == 40 else 99.8  # noqa: E731
est2 = L.estimate(bars(N, low), oi(N), ls(N), now=(T0 + timedelta(hours=N - 1)).timestamp() + 600)
def usd_at(e, lo, hi): return sum(r["usd"] for r in e["below"] if lo <= r["price"] < hi)  # noqa: E731
check("після провалу до 96: рівні лонгів 96,5 (25×), 98,5 (50×), 99,5 (100×) скоротились (частину ліквідовано)", usd_at(est2, 96.0, 97.0) < usd_at(est, 96.0, 97.0) and usd_at(est2, 98.0, 99.0) < usd_at(est, 98.0, 99.0) and usd_at(est2, 99.0, 100.0) < usd_at(est, 99.0, 100.0), f"{usd_at(est2,96,97)} vs {usd_at(est,96,97)}")
check("рівень 90,5 (10×) лишився (ціна 96 під нього не зайшла)", usd_at(est2, 90.0, 91.0) >= usd_at(est, 90.0, 91.0) * 0.95)
est3 = L.estimate(bars(N), oi(N), ls(N, ratio=3.0), now=(T0 + timedelta(hours=N - 1)).timestamp() + 600)
check("більше акаунтів у лонгу → більше обсягу лонг-ліквідацій, ніж шорт", sum(r["usd"] for r in est3["below"]) > sum(r["usd"] for r in est3["above"]))
old = L.estimate(bars(N), oi(N), ls(N), now=(T0 + timedelta(hours=N - 1)).timestamp() + 10 * 3600)
check("OI-історія застаріла → оцінки нема (чесно)", old["ok"] is False and "застаріла" in old["note"])
few = L.estimate(bars(5), oi(2), [], now=NOW)
check("замало даних → оцінки нема", few["ok"] is False)
flatoi = L.estimate(bars(N), [{"oi": 1e8, "timestamp": (T0 + timedelta(hours=i)).timestamp()} for i in range(N)], ls(N), now=(T0 + timedelta(hours=N - 1)).timestamp() + 600)
check("OI не росте → нових позицій нема → кластерів нема", flatoi["ok"] and not flatoi["below"] and not flatoi["above"])

# --- потік: перша адреса мовчить → перемикання на другу, де є ліквідації ---
from aiohttp import web  # noqa: E402

PORTS = {}


async def silent(request):
    ws = web.WebSocketResponse(heartbeat=5)
    await ws.prepare(request)
    await asyncio.sleep(30)
    return ws


async def live(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    for i in range(20):
        await ws.send_str(fo("SOLUSDT", "SELL", 150 + i * 0.1, 10, ts=time.time()))
        await asyncio.sleep(0.05)
    await asyncio.sleep(5)
    return ws


def serve(handler, key):
    started = threading.Event()

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = web.Application()
        app.router.add_get("/stream", handler)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        loop.run_until_complete(site.start())
        PORTS[key] = site._server.sockets[0].getsockname()[1]
        started.set()
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    started.wait(10)


serve(silent, "a")
serve(live, "b")
L.reset_for_tests()
L.STREAM_BASES = (f"ws://127.0.0.1:{PORTS['a']}/stream", f"ws://127.0.0.1:{PORTS['b']}/stream")
L.SILENCE_ROTATE_SEC = 2.0
L._CHECK_SEC = 0.4
os.environ["OFFICE_LIQ_MAP"] = "1"
check("start() запускає потік", L.start() is True)
end = time.time() + 15
while time.time() < end and L.stream_state()["events"] < 5:
    time.sleep(0.2)
st = L.stream_state()
check("мовчазна адреса → перемикання на наступну, події пішли", st["rotations"] >= 1 and st["events"] >= 5, str(st))
check("фактичні ліквідації SOL з потоку потрапили в книгу", L.real_snapshot("SOLUSDT")["count"] >= 5)
os.environ["OFFICE_LIQ_MAP"] = "0"
check("OFFICE_LIQ_MAP=0 вимикає", L.enabled() is False)

# --- зліпок у БД і читання для web ---
import tempfile  # noqa: E402

db = os.path.join(tempfile.mkdtemp(), "t.db")
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
L.reset_for_tests()
L._LAST_PERSIST = 0.0
L.ingest(L.parse_event(fo("BTCUSDT", "SELL", 59000, 2.0, ts=time.time() - 60)))
check("persist пише зліпок", L.persist(db) is True)
check("persist не частіше за інтервал", L.persist(db) is False)
got = L.latest_persisted(db, "BTCUSDT")
check("web читає зліпок: фактичні ліквідації BTC", got["ok"] and got["real"]["count"] == 1 and got["real"]["long_liq_usd"] == 118000.0, str(got)[:200])
nosym = L.latest_persisted(db, "ABCUSDT")
check("символ без ліквідацій у зліпку: нуль, а не вигадка", nosym["ok"] and nosym["real"]["count"] == 0)
stale = L.latest_persisted(db, "BTCUSDT", now=time.time() + 4000)
check("застарілий зліпок → недоступно (чесно)", stale["ok"] is False and "застарів" in stale["note"])
empty_db = os.path.join(tempfile.mkdtemp(), "e.db")
init_office_db(empty_db)
check("зліпка ще нема → чесна примітка", L.latest_persisted(empty_db, "BTCUSDT")["ok"] is False)

os.environ["OFFICE_MINI_FIXTURE"] = "1"
import office_mini_v2 as m2  # noqa: E402

fx = m2.liqmap_payload("BTCUSDT")
check("fixture: API карти ліквідацій не вигадує дані", fx["ok"] is False)
check("некоректний символ відхилено", m2.liqmap_payload("../x")["ok"] is False)
os.environ.pop("OFFICE_MINI_FIXTURE")

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
