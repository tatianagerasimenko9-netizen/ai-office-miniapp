#!/usr/bin/env python3
"""Живий цикл Market Brain у спостереженні: журнал станів, відновлення пам'яті, snapshots, переоцінка READY; жодного Telegram."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
db = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_brain_live as bl  # noqa: E402
import office_market_brain as mb  # noqa: E402
import office_signal_track as trk  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def bars(n, step, fn, start=T0):
    out = []
    for i in range(n):
        p = fn(i)
        out.append({"ts": (start + timedelta(minutes=i * step)).isoformat(), "open": p, "high": p + 0.05, "low": p - 0.05, "close": p})
    return out


now = (T0 + timedelta(hours=8)).timestamp()
calls = []


def candles(sym, tf, n):
    calls.append((sym, tf, n))
    step = {"5m": 5, "15m": 15, "1d": 1440}[tf]
    return bars(n, step, lambda i: 100.0 + (0.0 if sym == "BTCUSDT" else 0.01 * i), start=T0 + timedelta(hours=8) - timedelta(minutes=step * n)) if tf != "1d" else \
        bars(n, step, lambda i: 100.0, start=T0 - timedelta(days=n))


def http(url, params):
    if "openInterestHist" in url:
        return [{"timestamp": (now - 300 * (14 - i)) * 1000, "sumOpenInterest": 100 + i * 0.4} for i in range(14)]
    if "globalLongShortAccountRatio" in url:
        return [{"timestamp": (now - 900) * 1000, "longShortRatio": 1.8}]
    return {"lastFundingRate": "0.00012"}


f = bl.gather(now, candles=candles, http=http)
assert f["ok"] and abs(f["funding_pct"] - 0.012) < 1e-9 and f["ls_ratio"] == 1.8, f
assert f["oi_30m"] is not None, "OI за 30 хв з 5-хвилинних точок"
assert not any("-" in x[0] and False for x in calls)

# цикл: два кроки з однаковими сильними доказами → перехід у журнал; Telegram немає (функція лише повертає текст)
strong = dict(f, oi_30m=4.2, funding_pct=0.012, ls_ratio=1.8, price_30m=0.0, breadth={"up": 4, "down": 16, "n": 20})
mem = bl.load_memory(db)
assert mem["state"] == "NEUTRAL"
plans = [{"symbol": "AAAUSDT", "direction": "LONG", "entered": False, "rel_btc_pp": 0.0}]
r1 = bl.tick(db, mem, now, 0.0, features=strong, plans=plans)
assert r1["tr"] is None and r1["snap_at"] == now
r2 = bl.tick(db, r1["mem"], now + 60, r1["snap_at"], features=strong, plans=plans)
assert r2["tr"] and r2["tr"]["to"] == {"state": "ACCUM", "side": "SHORT"} and "🟡 Накопичується SHORT" in r2["text"], r2["tr"]
assert r2["snap_at"] == now, "snapshot не частіше за SNAP_SEC"
assert len(trk._events(db, "MARKET_BRAIN_TRANSITION")) == 1 and len(trk._events(db, "MARKET_BRAIN_SNAP")) == 1
# відновлення після перезапуску
mem2 = bl.load_memory(db)
assert mem2["state"] == "ACCUM" and mem2["side"] == "SHORT", mem2
# переоцінка: ACCUM ще не «активний контекст» → ніхто не «проти»
assert r2["reassess"]["result"]["against"] == []
print("OK brain live: ознаки з реальних джерел (імітація), журнал переходів, відновлення пам'яті, snapshots, без Telegram")
