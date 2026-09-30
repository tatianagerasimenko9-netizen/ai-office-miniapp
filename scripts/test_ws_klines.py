"""WebSocket-свічки: підписка, seed історії, живі оновлення, новий бар, обрив із відновленням, відхилений символ, вимкнено за замовчуванням.
Замість Binance — локальний aiohttp-сервер, що поводиться як combined kline streams. Мережі не потрібно."""
import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from aiohttp import web, WSMsgType  # noqa: E402

import office_market_data as omd  # noqa: E402
import office_ws_klines as ws  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---------- фальшивий Binance ----------
SRV = {"conns": [], "close_now": False, "rev": 0}
T0_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000) // 900000 * 900000


async def handler(request):
    resp = web.WebSocketResponse()
    await resp.prepare(request)
    subs = set(x for x in (request.query.get("streams") or "").split("/") if x)
    conn = {"ws": resp, "subs": subs}
    SRV["conns"].append(conn)

    async def pump():
        i = 0
        while not resp.closed:
            i += 1
            for s in list(subs):
                sym, _, kl = s.partition("@kline_")
                await resp.send_str(json.dumps({"stream": s, "data": {"e": "kline", "s": sym.upper(), "k": {
                    "t": T0_MS + SRV["rev"] * 900000, "s": sym.upper(), "i": kl, "o": "100", "h": "110", "l": "90",
                    "c": str(200 + i), "v": "5", "x": False}}}))
            await asyncio.sleep(0.05)

    task = asyncio.ensure_future(pump())
    try:
        async for m in resp:
            if m.type == WSMsgType.TEXT:
                d = json.loads(m.data)
                if d.get("method") == "SUBSCRIBE":
                    bad = [p for p in d["params"] if p.startswith("badusdt@")]
                    if bad:
                        await resp.send_str(json.dumps({"error": {"code": 2, "msg": "Invalid request"}, "id": d["id"]}))
                        continue
                    subs.update(d["params"])
                    await resp.send_str(json.dumps({"result": None, "id": d["id"]}))
            if SRV["close_now"]:
                break
    finally:
        task.cancel()
    return resp


def start_server():
    started = threading.Event()
    info = {}

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = web.Application()
        app.router.add_get("/stream", handler)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        loop.run_until_complete(site.start())
        info["port"] = site._server.sockets[0].getsockname()[1]
        info["loop"] = loop
        started.set()
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    started.wait(10)
    return info


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def rest_rows(limit, close=150.0):
    return [[T0_MS + (i - limit + 1) * 900000, "100", "110", "90", str(close), "5"] for i in range(limit)]


REST_CALLS = []


def fake_get(url, params, scope=""):
    if "fapi.binance.com/fapi/v1/klines" in url:
        REST_CALLS.append(dict(params))
        return rest_rows(int(params["limit"]))
    raise RuntimeError("unexpected url " + url)


omd._http_get_json = fake_get
omd._pace_fapi = lambda: None

# 0) за замовчуванням вимкнено
os.environ.pop("OFFICE_WS_KLINES", None)
check("вимкнено за замовчуванням", ws.register("ETHUSDT", "15m", 10) is False and ws.stats()["enabled"] is False)
omd.reset_market_cache()
r = omd.fetch_candles("ETHUSDT", "15m", 5)
check("вимкнено: працює REST", isinstance(r, list) and len(r) == 5 and len(REST_CALLS) == 1)

# 1) увімкнено
info = start_server()
os.environ["OFFICE_WS_KLINES"] = "1"
os.environ["OFFICE_WS_BASE"] = f"ws://127.0.0.1:{info['port']}/stream"
ws.reset_for_tests()
omd.reset_market_cache()
REST_CALLS.clear()

r1 = omd.fetch_candles("ETHUSDT", "15m", 20)
check("перший виклик: REST (підписка ще не підтверджена)", isinstance(r1, list) and len(r1) == 20 and len(REST_CALLS) == 1)
check("сервер отримав підключення", wait_for(lambda: ws.stats()["connected"]))
ok = wait_for(lambda: (omd.fetch_candles("ETHUSDT", "15m", 20) and ws.stats()["seeds"] >= 1), 10)
check("історія засіяна (seed) з кешу першого REST-запиту, без другого", ok and ws.stats()["seeds"] == 1 and len(REST_CALLS) == 1, str(ws.stats()) + str(len(REST_CALLS)))
n_rest = len(REST_CALLS)
check("після seed підписка підтверджена", ws.stats()["acked"] >= 2)
rows = None
for _ in range(60):
    rows = omd.fetch_candles("ETHUSDT", "15m", 20)
    if rows and rows[-1]["close"] > 200:
        break
    time.sleep(0.05)
check("свічки віддаються з WebSocket (остання свічка жива)", bool(rows) and rows[-1]["close"] > 200 and len(rows) == 20, str(rows[-1:] if rows else rows))
check("джерело — ф'ючерси Binance", all(x.get("src") == "binance_futures" for x in rows))
check("REST-запитів більше не було", len(REST_CALLS) == n_rest, f"{len(REST_CALLS)} vs {n_rest}")
before = len(REST_CALLS)
for _ in range(50):
    omd.fetch_candles("ETHUSDT", "15m", 20)
check("50 викликів → 0 REST-запитів", len(REST_CALLS) == before)
check("лічильник ws_hits росте", omd.source_health().get("ws_hits", 0) >= 50)

# 2) новий бар: історія росте, старі свічки не губляться
SRV["rev"] = 1
ok = wait_for(lambda: len(ws.get("ETHUSDT", "15m", 21) or []) == 21, 5)
check("новий бар додається до історії", ok)
last = (ws.get("ETHUSDT", "15m", 2) or [{}])[-1].get("ts")
check("ts нового бару правильний", last == datetime.fromtimestamp((T0_MS + 900000) / 1000, tz=timezone.utc).isoformat(), str(last))
SRV["rev"] = 0   # старий бар (запізніле оновлення) ігнорується
time.sleep(0.3)
check("запізніле оновлення старого бару ігнорується", len(ws.get("ETHUSDT", "15m", 21) or []) == 21)

# 3) seed відхиляється, якщо підписку підтверджено ПІСЛЯ початку REST-запиту (можлива діра)
ws.register("SOLUSDT", "15m", 10)
wait_for(lambda: ws.needs_seed("SOLUSDT", "15m"), 5)
rej = ws.seed("SOLUSDT", "15m", [{"ts": "x", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}], time.time() - 3600)
check("seed до підтвердження підписки не приймається", rej is False)

# 4) відхилений Binance символ → REST, без падіння
REST_CALLS.clear()
r = omd.fetch_candles("BADUSDT", "15m", 5)
check("відхилений символ: працює REST", isinstance(r, list) and len(r) == 5)
wait_for(lambda: ws.stats()["sub_errors"] >= 1, 5)
check("помилка підписки пораховано", ws.stats()["sub_errors"] >= 1)
REST_CALLS.clear()
omd.reset_market_cache()
r = omd.fetch_candles("BADUSDT", "15m", 5)
check("відхилений символ і далі через REST", isinstance(r, list) and len(REST_CALLS) == 1)

# 5) обрив з'єднання: буфери скидаються, працює REST, після відновлення — знову WS
SRV["close_now"] = True
for c in SRV["conns"]:
    asyncio.run_coroutine_threadsafe(c["ws"].close(), info["loop"])
ok = wait_for(lambda: ws.stats()["disconnects"] >= 1, 5)
check("обрив зафіксовано", ok)
SRV["close_now"] = False
REST_CALLS.clear()
omd.reset_market_cache()
r = omd.fetch_candles("ETHUSDT", "15m", 20)
check("під час обриву свічки все одно віддаються (REST)", isinstance(r, list) and len(r) == 20 and len(REST_CALLS) >= 1)
check("після обриву потік не віддає застарілі буфери", ws.get("SOLUSDT", "15m", 10) is None)
ok = wait_for(lambda: ws.stats()["connected"], 10)
check("з'єднання відновилось само", ok and ws.stats()["connects"] >= 2, str(ws.stats()))
def _again():
    omd.reset_market_cache()   # кеш REST не заважає повторному seed
    return omd.fetch_candles("ETHUSDT", "15m", 20) and ws.get("ETHUSDT", "15m", 20) is not None


ok = wait_for(_again, 10)
check("поганий символ не зіпсував сусідні потоки (перепідписка по одному)", ws.stats()["bad"] == 1, str(ws.stats()))
check("після відновлення історія засіяна знову і свічки йдуть з WS", ok, str(ws.stats()))

# 6) кількість потоків обмежена
os.environ["OFFICE_WS_MAX_STREAMS"] = "3"
check("ліміт потоків: понад ліміт — REST", ws.register("XRPUSDT", "5m", 5) is False)
os.environ.pop("OFFICE_WS_MAX_STREAMS")

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)
