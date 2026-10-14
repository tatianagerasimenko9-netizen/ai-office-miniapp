#!/usr/bin/env python3
"""Пауза Binance: Retry-After не обрізається до 300 с, повтор — одним пробним запитом (решта чекає), серія 429 подвоює очікування, успіх знімає режим проби."""
import io, os, sys, threading, time
from urllib.error import HTTPError
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_market_data as M

bad = 0
def check(n, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + n + ("" if ok else f" :: {info}")); bad += 0 if ok else 1

calls = []
mode = {"v": "429", "gate": None, "ra": "900"}
class Resp:
    headers = {}
    def read(self): return b"[]"
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake(req, timeout=0):
    calls.append(req.full_url)
    if mode["gate"] is not None:
        mode["gate"].wait(3)
    if mode["v"] == "429":
        raise HTTPError(req.full_url, 429, "Too Many", {"Retry-After": mode["ra"]}, io.BytesIO(b'{"code":-1003,"msg":"IP(1.2.3.4) banned until 1"}'))
    return Resp()
M.urlopen = fake
M._pace_fapi = lambda *a, **k: None
URL = "https://fapi.binance.com/fapi/v1/klines"
try:
    M._http_get_json(URL, {"symbol": "BTCUSDT"}); check("429 → RateLimited", False)
except M.RateLimited as e:
    check("429 → RateLimited, Retry-After 900 с не обрізано до 300", abs(M._BACKOFF_UNTIL - time.time() - 900) < 5, M._BACKOFF_UNTIL - time.time())
n = len(calls)
try: M._http_get_json(URL, {})
except M.RateLimited: pass
check("під час паузи запит до Binance не йде", len(calls) == n)
# закінчення паузи: режим проби — лише один запит одночасно
M._BACKOFF_UNTIL = 0.0
mode["v"] = "ok"; mode["gate"] = threading.Event()
res = {}
def first(): res["a"] = M._http_get_json(URL, {})
th = threading.Thread(target=first); th.start(); time.sleep(0.3)
n = len(calls)
try: M._http_get_json(URL, {}); second = "passed"
except M.RateLimited: second = "wait"
check("поки пробний запит летить, другий потік чекає (не б'є в Binance)", second == "wait" and len(calls) == n, (second, len(calls) - n))
mode["gate"].set(); th.join(2)
check("успіх проби знімає режим проби", M._NEED_PROBE is False and res.get("a") == [])
M._http_get_json(URL, {}); check("далі запити проходять без обмежень", True)
# серія: друге 429 швидко після першого → очікування ≥ 120 с
mode["v"] = "429"; mode["gate"] = None; mode["ra"] = "5"
M._BACKOFF_UNTIL = 0.0; M._NEED_PROBE = False; M._BAN_STREAK = 0; M._LAST_BAN_END = 0.0
for _ in range(2):
    try: M._http_get_json(URL, {})
    except M.RateLimited: pass
    M._BACKOFF_UNTIL = 0.0
try: M._http_get_json(URL, {})
except M.RateLimited: pass
check("серія 429: очікування зростає (≥120 с на третьому)", M._BACKOFF_UNTIL - time.time() >= 119, M._BACKOFF_UNTIL - time.time())
check("source_health віддає egress_ip і серію", "egress_ip" in M.source_health() and "ban_streak" in M.source_health())
sys.exit(1 if bad else 0)
