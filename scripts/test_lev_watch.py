#!/usr/bin/env python3
"""Лев відстежує умову: чекаємо → в зоні → підтверджено / скасовано / час минув / дані застаріли.
Синтетичні свічки, без мережі й Telegram. Перевіряє: перехід станів, одне повідомлення на зміну, тиша без змін,
переживання рестарту (стан у БД), відмову плану за правилом мінімального TP1, вимкнене сповіщення, мову без жаргону."""
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
db = str(Path(tempfile.mkdtemp()) / "w.db")
os.environ["OFFICE_DB_PATH"] = db
os.environ["DATABASE_URL"] = ""
import office_lev_watch as W  # noqa: E402
import office_user_messages as M  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
SYM = "BTCUSDT"


def bars(start, closes, step, lows=None, highs=None):
    out = []
    for i, c in enumerate(closes):
        ts = start + timedelta(seconds=step * i)
        out.append({"ts": ts.isoformat(), "open": c, "close": c, "low": (lows or closes)[i], "high": (highs or closes)[i]})
    return out


def feed(now, m15_closes, h1_closes, lows=None, highs=None):
    """свічки, що закінчуються 'зараз': останній M15 відкритий на now-15хв."""
    m15 = bars(now - timedelta(seconds=900 * len(m15_closes)) + timedelta(seconds=900) - timedelta(seconds=900) + timedelta(seconds=0), m15_closes, 900, lows, highs)
    # вирівнюємо: остання свічка відкрита рівно за 15 хв до now
    shift = now - timedelta(seconds=900) - datetime.fromisoformat(m15[-1]["ts"])
    m15 = [{**c, "ts": (datetime.fromisoformat(c["ts"]) + shift).isoformat()} for c in m15]
    h1 = bars(now - timedelta(seconds=3600 * len(h1_closes)), h1_closes, 3600)
    return lambda sym, iv, n=100: {"15m": m15, "1h": h1}[iv]


def fake_cycle(send=False, plan=None, zone=(83066.0, 83901.0)):
    plan = plan or {"entry": 83500.0, "sl": 82900.0, "tp1": 85000.0, "tp2": 86000.0}
    return lambda d, s: {"action": "SEND" if send else "WAIT", "send": send, "direction": "LONG", **plan,
                         "draft": {"zone_lo": zone[0], "zone_hi": zone[1], "invalidation": 82965.0}}


# --- реєстрація: без рівня скасування/зони обіцяти нічого; повторна — без дубля
assert W.register(db, symbol=SYM, direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=None, now=T0) is None
w = W.register(db, symbol=SYM, direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=82965, now=T0)
assert w and w["state"] == "WAIT"
assert W.register(db, symbol=SYM, direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=82965, now=T0 + timedelta(minutes=5))["watch_id"] == w["watch_id"]
assert len(W.active_watches(db)) == 1

# --- ціна вище зони, нічого не змінилось → мовчимо (жодних «чекаємо» щоразу)
now = T0 + timedelta(minutes=30)
f = feed(now, [84200] * 8, [84100] * 3)
for k in range(4):
    assert W.tick(db, now=now + timedelta(minutes=5 * k), fetch=f, cycle_fn=fake_cycle(), send_enabled=True) == []

# --- ціна торкнулась зони, підтвердження немає → одне повідомлення «в зоні», далі тиша
now = T0 + timedelta(hours=1)
f = feed(now, [84000, 83900, 83700, 83500, 83400, 83450, 83500, 83600], [84000, 83600], lows=[83950, 83850, 83650, 83450, 83300, 83400, 83450, 83550], highs=[84050, 84000, 83800, 83600, 83500, 83500, 83550, 83650])
out = W.tick(db, now=now, fetch=f, cycle_fn=fake_cycle(), send_enabled=True)
assert [o["event"] for o in out] == ["IN_ZONE"], out
assert "🟡" in out[0]["text"] and "підтвердження ще немає" in out[0]["text"]
assert W.tick(db, now=now + timedelta(minutes=5), fetch=f, cycle_fn=fake_cycle(), send_enabled=True) == [], "no duplicate IN_ZONE"

# --- рестарт: стан береться з БД, та сама подія не повторюється
W._STALE_TICKS.clear()
assert W.tick(db, now=now + timedelta(minutes=10), fetch=f, cycle_fn=fake_cycle(), send_enabled=True) == []
assert W.active_watches(db)[0]["state"] == "IN_ZONE" and W.active_watches(db)[0]["touched_zone"] is True

# --- підтвердження: Лев дав повний план, що проходить правило мінімального TP1 → зелене повідомлення з планом
out = W.tick(db, now=now + timedelta(minutes=15), fetch=f, cycle_fn=fake_cycle(send=True), send_enabled=True)
assert [o["event"] for o in out] == ["CONFIRMED"], out
t = out[0]["text"]
assert "🟢" in t and "ПЛАН УГОДИ" in t and "83 500" in t and "82 900" in t and "85 000" in t and "86 000" in t, t
assert W.tick(db, now=now + timedelta(minutes=20), fetch=f, cycle_fn=fake_cycle(send=True), send_enabled=True) == [], "no duplicate CONFIRMED"

# --- після підтвердження закриття години нижче інвалідації → «план скасовано», один раз, умова закривається
now2 = T0 + timedelta(hours=3)
f2 = feed(now2, [83000] * 8, [83500, 82800, 82700])
out = W.tick(db, now=now2, fetch=f2, cycle_fn=fake_cycle(), send_enabled=True)
assert [o["event"] for o in out] == ["CANCELLED"] and "🔴" in out[0]["text"] and "82 965" in out[0]["text"], out
assert W.active_watches(db) == [] and W.tick(db, now=now2, fetch=f2, cycle_fn=fake_cycle(), send_enabled=True) == []

# --- новий сценарій: план не проходить правило мінімального TP1 → «умови є, але входу немає» (не зелене)
db2 = str(Path(tempfile.mkdtemp()) / "w2.db")
init_office_db(db2)
W.register(db2, symbol="SOLUSDT", direction="LONG", zone_lo=100, zone_hi=101, invalidation=98, now=T0)
now = T0 + timedelta(minutes=45)
fs = feed(now, [101.5, 101.2, 100.8, 100.6, 100.7, 100.9], [101, 100.9], lows=[101, 100.9, 100.5, 100.4, 100.5, 100.7], highs=[101.6, 101.3, 101, 100.8, 100.9, 101])
out = W.tick(db2, now=now, fetch=fs, cycle_fn=lambda d, s: {"action": "SEND", "send": True, "direction": "LONG", "entry": 100.5, "sl": 99.5, "tp1": 101.5,
                                                              "draft": {"zone_lo": 100, "zone_hi": 101, "invalidation": 98}}, send_enabled=True)
ev = [o["event"] for o in out]
assert ev == ["REJECTED"] or ev == ["IN_ZONE"] and False, out  # REJECTED має пріоритет над «в зоні»
assert "🟢" not in out[0]["text"] and "ВХОДУ НЕМАЄ" in out[0]["text"], out[0]["text"]

# --- час минув → «час очікування закінчився» (і що ціна заходила в зону)
db3 = str(Path(tempfile.mkdtemp()) / "w3.db")
init_office_db(db3)
W.register(db3, symbol=SYM, direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=82965, now=T0)
late = T0 + timedelta(hours=13)
out = W.tick(db3, now=late, fetch=feed(late, [84200] * 8, [84100] * 3), cycle_fn=fake_cycle(), send_enabled=True)
assert [o["event"] for o in out] == ["EXPIRED"] and "⚪" in out[0]["text"], out

# --- дані застаріли: не одразу (3 проходи), одне повідомлення, без спаму
db4 = str(Path(tempfile.mkdtemp()) / "w4.db")
init_office_db(db4)
W._STALE_TICKS.clear()
W.register(db4, symbol=SYM, direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=82965, now=T0)
n = T0 + timedelta(hours=2)
stale_feed = feed(n - timedelta(hours=2), [84200] * 8, [84100] * 3)
got = [W.tick(db4, now=n + timedelta(minutes=5 * k), fetch=stale_feed, cycle_fn=fake_cycle(), send_enabled=True) for k in range(6)]
flat = [o["event"] for g in got for o in g]
assert flat == ["STALE"] and "⚠️" in got[2][0]["text"], got

# --- сповіщення вимкнене: події записуються (видно в Mini App), у Telegram нічого не йде
db5 = str(Path(tempfile.mkdtemp()) / "w5.db")
init_office_db(db5)
W.register(db5, symbol=SYM, direction="LONG", zone_lo=83066, zone_hi=83901, invalidation=82965, now=T0)
out = W.tick(db5, now=late, fetch=feed(late, [84200] * 8, [84100] * 3), cycle_fn=fake_cycle(), send_enabled=False)
assert out == [] and W.recent_notes(db5)[0]["event"] == "EXPIRED" and W.recent_notes(db5)[0]["sent"] is False

# --- мова: жодного внутрішнього жаргону в жодному шаблоні
base = dict(symbol="BTCUSDT", direction="LONG", price=83971, zone_lo=83066, zone_hi=83901, invalidation=82965, wait_tf="M15",
            scenario_tf="H1", tracking=True, expires_at="2026-09-30T02:00:00+00:00", plan={"entry": 83500, "sl": 82965, "tp1": 84800, "tp2": 85600})
BAD = re.compile(r"WATCHING|LONG|SHORT|Risk Officer|shadow|SFP|reclaim|TTL|CONFIRMED|INVALIDATED|SCN\||кандидат|scenario_id|regime|confluence|ATR", re.I)
for st in ("WAIT", "IN_ZONE", "CONFIRMED", "CANCELLED", "EXPIRED", "STALE", "REJECTED", "NO_TRADE"):
    txt = M.render({**base, "state": st, "reason": "Ціна вже пройшла близько 188% звичайного денного руху — входити пізно."})
    assert not BAD.search(txt), (st, BAD.search(txt).group(0), txt)
    assert "не ордер" in txt or st == "STALE"
    if st != "CONFIRMED":
        assert "ПЛАН УГОДИ: вхід" not in txt and "🟢" not in txt, (st, txt)
# без сповіщення повідомлення чесно не обіцяє «напишу сам»
assert "сам напише" not in M.render({**base, "state": "WAIT", "tracking": False}) and "/lev BTC" in M.render({**base, "state": "WAIT", "tracking": False})
# ціна вже нижча за зону для SHORT / всередині зони — різні речення
assert "вже в зоні" in M.render({**base, "state": "WAIT", "price": 83500})
print("OK Lev watch: transitions, one message per change, restart-safe, TP1 rejection, stale/expiry, plain language")
