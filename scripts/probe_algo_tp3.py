"""Звідки взявся TP3 0.10278 у ALGO: той самий office_targets.levels/structural_targets на тижневих/денних свічках (Binance spot як проксі ф'ючерсів; лише читання)."""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def get(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=30).read().decode())


def kl(sym, tf, n):
    rows = get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval={tf}&limit={n}")
    return [{"ts": datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc).isoformat(), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])} for r in rows]


import office_targets as T  # noqa: E402

w, d, m15 = kl("ALGOUSDT", "1w", 6), kl("ALGOUSDT", "1d", 25), kl("ALGOUSDT", "15m", 96)
print("ТИЖНЕВІ СВІЧКИ (остання = поточна):")
for r in w:
    print("  ", r["ts"][:10], "low", r["low"], "high", r["high"], "close", r["close"])
print("ДЕННІ (останні 8):")
for r in d[-8:]:
    print("  ", r["ts"][:10], "low", r["low"], "high", r["high"])
lv = T.levels(m15=m15[:-0 or None], daily=d, weekly=w[-4:])
print("levels():", json.dumps(lv))
E, T1 = 0.13038, 0.12469
print("entry", E, "atr_d1", lv["atr_d1"], "3*ATR(D1) =", None if not lv["atr_d1"] else 3 * lv["atr_d1"], "відстань до TP3 0.10278 =", E - 0.10278)
tg = T.structural_targets(direction="SHORT", entry=E, tp1=T1, lv=lv)
print("structural_targets:", json.dumps(tg, ensure_ascii=False))
print("збіг TP3 0.10278 з PDL:", lv["pdl"], "| з мінімумом минулого тижня:", lv["w_low"])
