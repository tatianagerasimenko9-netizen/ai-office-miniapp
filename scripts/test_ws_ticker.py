#!/usr/bin/env python3
"""WebSocket-тікер: розбір miniTicker, свіжість, ті самі поля, що давав REST; вимкнено за замовчуванням; споживачі падають назад на REST."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_market_data as M  # noqa: E402
import office_ws_ticker as W  # noqa: E402

os.environ.pop("OFFICE_WS_TICKER", None)
assert not W.enabled() and W.get("BTCUSDT") is None, "за замовчуванням вимкнено"

os.environ["OFFICE_WS_TICKER"] = "1"
W._ensure_thread = lambda: None      # без мережі
W.reset_for_tests()
n = W._parse({"stream": "!miniTicker@arr", "data": [{"e": "24hrMiniTicker", "s": "ALGOUSDT", "c": "0.1305", "o": "0.1200", "h": "0.1342", "l": "0.1190", "v": "1", "q": "5000000"},
                                                      {"e": "24hrMiniTicker", "s": "BAD", "c": "x"}]})
assert n == 1, n
g = W.get("algo")
assert g and abs(g["priceChangePercent"] - 8.75) < 1e-9 and g["highPrice"] == 0.1342 and g["lowPrice"] == 0.1190 and g["lastPrice"] == 0.1305 and g["quoteVolume"] == 5000000.0, g
assert W._parse([{"s": "ETHUSDT", "c": "2700", "o": "2650", "h": "2710", "l": "2600", "q": "1"}]) == 1 and W.get("ETHUSDT")["priceChangePercent"] > 1.8
# застарілі дані не віддаємо
W._TICK["ALGOUSDT"]["at"] = time.time() - 120
assert W.get("ALGOUSDT") is None and W.stats()["misses"] >= 1
# споживачі: з потоку — без REST; без потоку — REST
calls = []
M._http_get_json = lambda url, params, scope="": calls.append(url) or {"priceChangePercent": "1.5", "highPrice": "2", "lowPrice": "1", "lastPrice": "1.5"}
W._TICK["ALGOUSDT"] = {"c": 0.1305, "o": 0.12, "h": 0.1342, "l": 0.119, "q": 5e6, "at": time.time()}
assert abs(M._ticker_24h_change_pct("ALGOUSDT") - 8.75) < 1e-9 and calls == [], "зі свіжого потоку REST не викликається"
liq = M.fetch_liquidations_proxy("ALGOUSDT")
assert abs(liq["current_price"] - 0.1305) < 1e-12 and calls == [], liq
W._TICK.clear()
assert M._ticker_24h_change_pct("ALGOUSDT") == 1.5 and len(calls) == 1, "немає даних потоку → REST як раніше"
print("OK ws ticker: розбір, свіжість, поля як у REST, вимкнено за замовчуванням, fallback на REST")
