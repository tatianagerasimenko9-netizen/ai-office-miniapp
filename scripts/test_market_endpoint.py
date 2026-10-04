#!/usr/bin/env python3
"""/api/v2/market: pending → готово; рядки «📊 РИНОК ЗАРАЗ» з чесних лічильників; активні плани; без мережі."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_market_view as mv  # noqa: E402
import office_mini_v2 as M  # noqa: E402
import office_market_bias as mb  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
mv._CACHE.update(at=0.0, v=None)
mv._BUILDING["on"] = True            # фонове збирання вимкнено: перевіряємо стан «ще збирається»
r = M.market_payload()
assert r["ok"] and r["pending"] is True and r["lines"] == [], r
mv._BUILDING["on"] = False

def flat(pct, n=40):
    return [{"close": 100.0 * (1 + pct / 100.0 * max(0, i - (n - 17)) / 16.0) if i >= n - 17 else 100.0, "open": 100.0, "high": 100.0, "low": 100.0, "ts": "x"} for i in range(n)]

m = mb.assess(btc_1h=flat(1.0), eth_1h=flat(1.2), basket_1h={f"C{i}": flat(0.9) for i in range(10)}, btc_week_dist_pct=0.8, bph=4)
mv._CACHE.update(at=time.time(), v={"market": m, "btc_time": {}, "btc15": flat(1.0), "built_at": time.time()})
r2 = M.market_payload()
assert r2["ok"] and not r2["pending"] and r2["bias"] == "LONG", r2
assert r2["lines"][0] == "📊 РИНОК ЗАРАЗ" and r2["lines"][1] == "Перевага: LONG" and r2["lines"][-1] == "Висновок: ринок зараз більше підтримує LONG.", r2["lines"]
assert any(x.startswith("BTC +1,0% за 4 год") for x in r2["lines"]), r2["lines"]
assert "DXY" in " ".join(r2["not_connected"]), r2["not_connected"]
print("OK /api/v2/market: pending → готово, перевага з лічильників, не підключене названо")
