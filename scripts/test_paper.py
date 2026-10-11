"""Офлайн-тести paper-супроводу: правила входу після доставки, TP/SL порядок, моделі A/B/C, витрати, ідемпотентність, MISSED, відновлення."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)
from office2 import paper as P

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if not cond else ""))
    if not cond:
        FAILS.append(name)


def B(t, o, h, l, c):
    return (float(t), float(o), float(h), float(l), float(c))


T0 = 1_800_000_000.0   # після PAPER_SINCE_TS
# LONG: план 100, SL 99 (risk 1), TP1 102, TP2 104, TP3 106
D = T0 + 30      # доставка посеред хвилини
# --- 1. вхід
bars = [B(T0, 100, 100.2, 99.9, 100.1), B(T0 + 60, 100.1, 100.4, 100.0, 100.3)]
r = P.decide_fill("LONG", 100, 99, 102, D, bars)
check("fill = open першої свічки ПІСЛЯ доставки (не заднім числом)", r["ok"] and r["fill_ts"] == T0 + 60 and r["fill_price"] == 100.1)
r = P.decide_fill("LONG", 100, 99, 102, D, [B(T0 + 60, 100.8, 101, 100.7, 100.9)])
check("chase 0.8R > 0.5R → MISSED", not r["ok"] and "MISSED" in r["reason"])
r = P.decide_fill("LONG", 100, 99, 102, D, [B(T0 + 60, 98.9, 99.2, 98.5, 99)])
check("ціна вже за SL → MISSED", not r["ok"] and "SL" in r["reason"])
r = P.decide_fill("LONG", 100, 99, 102, D, [B(T0 + 60, 102.1, 102.5, 102, 102.3)])
check("ціна вже на TP1 → MISSED", not r["ok"] and "TP1" in r["reason"])
r = P.decide_fill("LONG", 100, 99, 102, D, [B(T0 - 600, 100, 100, 100, 100)])
check("немає даних після доставки → NO_DATA, а не вигаданий вхід", not r["ok"] and "NO_DATA" in r["reason"])
r = P.decide_fill("SHORT", 100, 101, 98, D, [B(T0 + 60, 99.9, 100, 99.8, 99.9)])
check("SHORT: сприятлива ціна теж fill", r["ok"] and r["fill_price"] == 99.9)

# --- 2. супровід, LONG fill 100, risk 1
fill_ts = T0 + 60
def run(extra, now=None):
    bs = [B(fill_ts, 100, 100.5, 99.8, 100.2)] + extra
    return P.walk("LONG", fill_ts, 100.0, 99.0, [102, 104, 106], bs, now or (bs[-1][0] + 60))

w = run([B(fill_ts + 60, 100.2, 102.2, 100.1, 102), B(fill_ts + 120, 102, 104.5, 101.9, 104), B(fill_ts + 180, 104, 106.5, 103.9, 106)])
c = w["closed"]
check("всі цілі: A=+2R", abs(c["A"]["r"] - 2.0) < 1e-9 and c["A"]["why"] == "TP1")
check("всі цілі: B=0.5*2+0.5*4=3R", abs(c["B"]["r"] - 3.0) < 1e-9)
check("всі цілі: C=0.3*2+0.4*4+0.3*6=4R", abs(c["C"]["r"] - 4.0) < 1e-9 and c["C"]["why"] == "TP3")
check("час TP1<TP2<TP3", w["tp_ts"]["TP1"] < w["tp_ts"]["TP2"] < w["tp_ts"]["TP3"])

w = run([B(fill_ts + 60, 100, 102.1, 100, 102), B(fill_ts + 120, 102, 102.2, 99.9, 100)])   # TP1, потім повернення до входу
c = w["closed"]
check("TP1 потім беззбиток: A=+2R, B=0.5*2+0=+1R (BE), C=0.3*2=+0.6R", abs(c["A"]["r"] - 2) < 1e-9 and abs(c["B"]["r"] - 1.0) < 1e-9 and abs(c["C"]["r"] - 0.6) < 1e-9 and c["B"]["why"] == "BE")

w = run([B(fill_ts + 60, 100, 102.5, 98.9, 100)])
check("свічка зі SL і TP1 → SL першим (-1R для всіх)", all(abs(w["closed"][m]["r"] + 1.0) < 1e-9 for m in "ABC") and w["sl_ts"])

w = run([B(fill_ts + 60, 100, 101, 99.5, 100.5)])
check("без подій → відкрито", not any(w["closed"][m]["done"] for m in "ABC") and w["mfe_r"] > 0.9 and w["mae_r"] > 0.4)

w = P.walk("LONG", fill_ts, 100.0, 99.0, [102, 104, 106], [B(fill_ts, 100, 100.5, 99.8, 100.2), B(fill_ts + 60, 100, 103, 100, 102.9)], fill_ts + 60 + 30)
check("незакрита свічка не рахується (чекаємо закриття)", not w["closed"]["A"]["done"])

# --- 3. БД, ідемпотентність, відновлення, витрати
db = os.path.join(tempfile.mkdtemp(), "p.db")
P._READY["done"] = False
from office_bridge import _execute, _fetchall

_execute(db, """CREATE TABLE IF NOT EXISTS office2_live_signal (scenario_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, created_ts DOUBLE PRECISION, valid_until_ts DOUBLE PRECISION,
    status TEXT, snapshot_json TEXT, version TEXT, delivered_ts DOUBLE PRECISION, msg_id BIGINT, last_error TEXT)""")


def snap(entry, sl, tps):
    return json.dumps({"thesis": {"entry": entry, "sl": sl, "targets": [{"p": x} for x in tps]}, "session_tag": {"session": "LONDON"}, "market_at_signal": {"btc": "UP"}})


# контрольований тест у тестовій БД (НЕ production): один доставлений, один suppressed, один недоступний вхід
rows = [("S1", "AAAUSDT", "LONG", T0, T0 + 9999, "DELIVERED", snap(100, 99, [102, 104, 106]), "v", D, 1, None),
        ("S2", "BBBUSDT", "LONG", T0, T0 + 9999, "SUPPRESSED", snap(100, 99, [102]), "v", None, None, "STALE: не доставлено за 400 с"),
        ("S3", "CCCUSDT", "LONG", T0, T0 + 9999, "DELIVERED", snap(100, 99, [102]), "v", D, 2, None)]
for r in rows:
    _execute(db, "INSERT INTO office2_live_signal(scenario_id,symbol,direction,created_ts,valid_until_ts,status,snapshot_json,version,delivered_ts,msg_id,last_error) VALUES (?,?,?,?,?,?,?,?,?,?,?)", r)

DATA = {"AAAUSDT": [B(T0 + 60, 100.1, 100.4, 100.0, 100.3)], "CCCUSDT": [B(T0 + 60, 101.0, 101.2, 100.9, 101.0)]}


def mk_fetch(extra=None):
    def f(sym, tf, n):
        bs = list(DATA.get(sym, [])) + list((extra or {}).get(sym, []))
        return [{"ts": int(b[0] * 1000), "open": b[1], "high": b[2], "low": b[3], "close": b[4]} for b in bs]
    return f


now = T0 + 300
log = []
res = P.tick(db, mk_fetch(), now, log=log.append)
print(log)
check("перший тік: 3 нових, 2 MISSED (suppressed + chase)", res["new"] == 3 and res["missed"] == 2, str(res))
pos = {x["scenario_id"]: x for x in P.summary(db)["items"]}
check("S1 відкрито за open після доставки", pos["S1"]["status"] == "OPEN" and pos["S1"]["fill_price"] == 100.1)
check("S2 MISSED з причиною доставки", pos["S2"]["status"] == "MISSED" and "НЕ ДОСТАВЛЕНО" in pos["S2"]["miss_reason"])
check("S3 MISSED (ціна 101 = 1R гірше)", pos["S3"]["status"] == "MISSED" and "вхід недоступний" in pos["S3"]["miss_reason"])
check("qty від ризику $10 з фактичного входу", abs(pos["S1"]["qty"] * (100.1 - 99.0) - 10.0) < 1e-6)
res = P.tick(db, mk_fetch(), now, log=log.append)
check("повторний тік не дублює", res["new"] == 0 and len(P.summary(db)["items"]) == 3)

# рестарт: скидаємо кеш DDL (новий процес) — стан у БД, TP1+TP2+TP3 приходять
P._READY["done"] = False
more = {"AAAUSDT": [B(T0 + 120, 100.3, 102.3, 100.2, 102), B(T0 + 180, 102, 104.4, 101.9, 104), B(T0 + 240, 104, 106.2, 103.9, 106)]}
res = P.tick(db, mk_fetch(more), T0 + 400, log=log.append)
s = P.summary(db)
p1 = [x for x in s["items"] if x["scenario_id"] == "S1"][0]
check("після рестарту позицію закрито за TP3", p1["status"] == "CLOSED" and res["closed"] == 1 and p1["tp1_ts"] and p1["tp3_ts"])
notional = 10.0 / 1.1 * 100.1
cost = notional * 0.0015
gross_a = 1.9 / 1.1  # (102-100.1)/1.1
check("витрати 0.15% ноціоналу відняті: A", abs(p1["pnl_a"] - round((gross_a - cost / 10.0) * 10.0, 2)) < 0.011 and abs(p1["cost_usd"] - cost) < 1e-6, str((p1["pnl_a"], cost)))
check("summary: комісії і сума PnL", s["stats"]["closed"] == 1 and s["stats"]["open"] == 0 and s["stats"]["missed"] == 2 and abs(s["stats"]["fees_usd"] - round(cost, 2)) < 0.011)
check("B і C відрізняються від A (часткові виходи)", p1["pnl_b"] != p1["pnl_a"] and p1["pnl_c"] != p1["pnl_b"])

# історичні сигнали (до запуску контуру) не створюють paper-рядків
_execute(db, "INSERT INTO office2_live_signal(scenario_id,symbol,direction,created_ts,valid_until_ts,status,snapshot_json,version,delivered_ts,msg_id,last_error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
         ("OLD", "OLDUSDT", "LONG", P.PAPER_SINCE_TS - 3600, P.PAPER_SINCE_TS + 9999, "DELIVERED", snap(100, 99, [102]), "v", P.PAPER_SINCE_TS - 3500, 9, None))
P.tick(db, mk_fetch(), T0 + 400, log=log.append)
_execute(db, "INSERT INTO office2_paper_position(scenario_id,symbol,direction,status,generated_ts,delivered_ts,miss_reason) VALUES (?,?,?,?,?,?,?)", ("BOGUS", "BOGUSUSDT", "LONG", "MISSED", P.PAPER_SINCE_TS - 100, P.PAPER_SINCE_TS - 90, "NO_DATA"))
check("історичний сигнал до запуску не обліковується", "OLD" not in {x["scenario_id"] for x in P.summary(db)["items"]})

# --- 4. збій Telegram → технічне попередження в БД (раз на сигнал)
from office2 import delivery as DL
from office_bridge import init_office_db as _init
try:
    _init(db)
except Exception:
    pass
DL._tg_alert(db, "S9", "ZZZUSDT", "LONG", "Telegram не підтвердив доставку")
DL._tg_alert(db, "S9", "ZZZUSDT", "LONG", "Telegram не підтвердив доставку")
n = _fetchall(db, "SELECT COUNT(*) FROM office_events WHERE event_type='OFFICE2_TELEGRAM_FAILURE' AND signal_id='S9'")[0][0]
check("збій Telegram записано в БД один раз", n == 1, str(n))

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
