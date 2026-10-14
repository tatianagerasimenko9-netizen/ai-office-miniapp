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

from office2.learning.models import model_of
check("моделі PA за видом тези", model_of("SWEEP_SEQ") == "REJECTION" and model_of("PULLBACK_BREAK") == "BREAKOUT_RETEST" and model_of("X") == "UNKNOWN" and model_of(None) == "UNKNOWN")
check("summary: розріз за моделями", "by_model" in P.summary(db)["stats"])

# --- міграція scope: рядок без scope до запуску й NO_DATA → BACKFILL_INVALID; сучасний → LIVE
P._READY["done"] = False
P._ensure(db)
sc = {r[0]: r[1] for r in _fetchall(db, "SELECT scenario_id, scope FROM office2_paper_position")}
check("міграція scope: BOGUS(NO_DATA, до запуску)=BACKFILL_INVALID, нові=LIVE", sc.get("BOGUS") == "BACKFILL_INVALID" and sc.get("S1") == "LIVE")
sm = P.summary(db)
check("summary: невалідні не входять у LIVE, лічаться окремо", all(x["scope"] == "LIVE" for x in sm["items"]) and sm["backfill"]["invalid_no_data"] >= 1)

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

lr = P.learning_report(db)
check("learning-звіт paper: лише LIVE, розрізи", lr and lr["scope"] == "LIVE" and "by_model" in lr["overall"] and "LONG" in lr["by_direction"])

# --- 5. авто-розбір (структура реального знімка LINK LONG 11.10, скорочено)
from office2 import postmortem as PM
snap_link = {"thesis": {"kind": "SWEEP_SEQ", "reason": "повна послідовність", "level": {"kind": "NEW_YORK_L", "p": 12.95, "strength": 1},
                        "sequence": [{"ok": True, "step": "подія", "value": "ПОВТОРНИЙ ТЕСТ прийнятого рівня 12.936 (не свіжий sweep)"}, {"ok": True, "step": "зсув структури (MSS/BOS)", "value": "закриття вище 13.093"},
                                     {"ok": True, "step": "ретрейс у зону", "value": "low 13.003 торкнувся зони"}],
                        "invalidation": {"price": 12.936, "buffer": 0.014, "buffer_basis": "медіана 9 проколів", "why": "екстремум події"}, "quality": {"risk_atr15": 3.73}, "sizing": {"stop_pct": 0.76}},
             "session_tag": {"session": "ASIA", "weekend": True}, "alignment_summary": {"against": 2, "for": 1, "neutral": 2},
             "smc": {"agrees_ready": False, "state": "NONE", "structure": {"h4": {"trend": "DOWN"}, "h1": {"trend": "TRANSITION"}}}, "market_at_signal": {"market": {"btc_regd": -1, "btc_ret_4h": -0.03}}}
posx = {"direction": "LONG", "plan_entry": 13.021, "fill_price": 13.02, "sl": 12.922, "tp1": 13.14, "sl_ts": T0 + 600, "close_ts": T0 + 600, "cost_usd": 1.99, "pnl_a": -11.99, "mfe_r": 0.3, "mae_r": 1.0}
bars15 = [(T0, 13.02, 13.03, 12.91, 12.95), (T0 + 900, 12.95, 13.2, 12.94, 13.15)]
pm = PM.analyze(snap_link, posx, bars15, T0 + 900 * 4)
fl = set(pm["flags"])
check("розбір: прапори WEEKEND, HTF_CONFLICT_H4, BTC_DAILY_REGIME_CONFLICT, SMC_DISAGREES, RETEST_NOT_FRESH", {"WEEKEND", "HTF_CONFLICT_H4", "BTC_DAILY_REGIME_CONFLICT", "SMC_SHADOW_DISAGREES", "EVENT_IS_RETEST_NOT_FRESH_SWEEP"} <= fl, str(fl))
check("розбір: після SL ціна дійшла до TP1", pm["events"]["after_sl"]["reached_tp1_after_sl"] is True and "TP1_REACHED_AFTER_SL" in fl)
check("розбір: M15-свічка SL закрилась вище SL → прокол (wick)", pm["events"]["sl_candle"]["closed_beyond_sl"] is False and "SL_WICK_ONLY_M15_CLOSED_INSIDE" in fl)
pm2 = PM.analyze({"thesis": {}}, dict(posx, sl_ts=None), None, T0)
check("розбір без даних: NO_DATA, а не вигадані причини", pm2["events"]["level"] == "NO_DATA" and pm2["events"]["after_sl"] == "NO_DATA" and not pm2["flags"] and "level" in pm2["missing"])
check("частка витрат у збитку", abs(pm["events"]["cost"]["share_of_loss_pct"] - 16.6) < 0.2, str(pm["events"]["cost"]))

# --- 6. класи помилок + альтернативи
snap_link["evidence"] = [{"module": "M5/M1 тригер", "status": "USED", "supports": 0, "finding": "M5: закриття вище максимуму 3 попередніх барів — ні"},
                         {"module": "OB / FVG / OTE (premium-discount)", "status": "USED", "supports": -1, "finding": "зона в premium діапазону H4 (75%): ПРОТИ LONG"},
                         {"module": "Wyckoff (spring/upthrust, тест)", "status": "USED", "supports": 0, "finding": "фаза не визначена"},
                         {"module": "DOM / order book", "status": "NOT_CONNECTED", "supports": 0, "finding": "немає надійного джерела"}]
pm = PM.analyze(snap_link, posx, bars15, T0 + 900 * 4)
codes = {c["code"] for c in pm["error_classes"]}
check("класи: EARLY_ENTRY, WEAK_LEVEL, BTC_CONFLICT, HTF_CONFLICT, SESSION_RISK, BAD_PREMIUM_DISCOUNT, SL_HUNT_CANDIDATE", {"EARLY_ENTRY", "WEAK_LEVEL", "BTC_CONFLICT", "HTF_CONFLICT", "SESSION_RISK", "BAD_PREMIUM_DISCOUNT", "SL_HUNT_CANDIDATE"} <= codes, str(codes))
check("кожен клас має доказ і статус «кандидат»", all(c["proof"] and "не доведена" in c["status"] for c in pm["error_classes"]))
check("Wyckoff без фази = UNKNOWN, не вигадано", pm["events"]["wyckoff"].startswith("UNKNOWN"))
check("модулі без підключення перелічені окремо", "DOM / order book" in pm["events"]["evidence"]["not_connected"])
clean = PM.analyze({"thesis": {"kind": "SWEEP_SEQ", "sequence": [{"ok": True, "step": "подія", "value": "SWEEP 1"}, {"ok": True, "step": "зсув структури", "value": "x"}, {"ok": True, "step": "ретрейс у зону", "value": "y"}],
                              "level": {"kind": "X", "p": 1, "strength": 2}, "quality": {"risk_atr15": 2}, "sizing": {"stop_pct": 2.0}}, "session_tag": {"session": "LONDON", "weekend": False}, "evidence": []},
                   {"direction": "LONG", "plan_entry": 10, "sl": 9, "fill_price": 10, "cost_usd": 1, "pnl_a": -11, "sl_ts": None, "generated_ts": 1, "delivered_ts": 30}, None, T0)
check("коректна угода без ознак → VALID_LOSS", [c["code"] for c in clean["error_classes"]] == ["VALID_LOSS"], str(clean["error_classes"]))
# альтернативи: рішення на барі T0+900*k, свічки до/після
import numpy as np
nb = 60
tb = [T0 - 900 * 40 + 900 * i for i in range(nb)]
bb = [(t_, 100.0, 100.2, 99.8, 100.0) for t_ in tb]
bb[44] = (tb[44], 100.0, 100.6, 99.9, 100.5)        # BOS-бар після рішення (i=42)
bb[46] = (tb[46], 100.5, 102.6, 100.4, 102.4)       # досягнуто TP1
snapx = {"decided_ts": tb[42] + 900, "thesis": {"entry": 100.0, "sl": 99.0, "targets": [{"p": 102.0}]}}
alt = PM.alternatives(snapx, {"direction": "LONG", "symbol": "X"}, bb)
check("альтернативи V0..V8 на одній угоді + NO_TRADE + попередження про вибірку", alt["status"] == "OK" and "V8_bos_confirm" in alt["variants"] and alt["no_trade"]["r_net"] == 0.0 and "вибірці" in alt["note"], str(alt)[:300])
alt2 = PM.alternatives({"thesis": {}}, {"direction": "LONG", "symbol": "X"}, bb)
check("альтернативи без даних → NO_DATA", alt2["status"] == "NO_DATA")

# --- 6b. інтеграція: tick сам запускає авто-розбір закритих угод (S1 закрита за TP1 у секції 3)
row = _fetchall(db, "SELECT postmortem_json FROM office2_paper_position WHERE scenario_id = 'S1'")[0][0]
check("tick сам записує postmortem_json для закритої угоди", bool(row) and json.loads(row).get("version") == PM.VERSION, str(row)[:120])

# --- 7. контрольний потік: would-be READY, відсічений лімітом, не потрапляє в LIVE
_execute(db, """CREATE TABLE IF NOT EXISTS office2_live_scenario (scenario_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, kind TEXT, state TEXT, created_ts DOUBLE PRECISION,
    updated_ts DOUBLE PRECISION, expires_ts DOUBLE PRECISION, reason TEXT, thesis_json TEXT, version TEXT)""")
_execute(db, "INSERT INTO office2_live_scenario VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("O2|ctl|1", "DDDUSDT", "LONG", "SWEEP_SEQ", "NO_TRADE", T0, T0, None,
         "ємність сценаріїв: денний ліміт: 3 стопи за добу UTC", json.dumps({"entry": 100, "sl": 99, "targets": [{"p": 102}, {"p": 104}]}), "t"))
# сценарій ДО запуску контуру (PAPER_SINCE), але в межах 15 год від now: контрольний потік його бере
DATA["DDDUSDT"] = [B(T0 + 60, 100.1, 100.4, 100.0, 100.3), B(T0 + 120, 100.3, 102.3, 100.2, 102.0)]
NOW7 = T0 + 400 if False else P.PAPER_SINCE_TS + 3600
_execute(db, "INSERT INTO office2_live_scenario VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("O2|ctl|2", "EEEUSDT", "SHORT", "SWEEP_SEQ", "NO_TRADE", P.PAPER_SINCE_TS - 600, P.PAPER_SINCE_TS - 600, None,
         "ємність сценаріїв: денний ліміт: 3 стопи за добу UTC", json.dumps({"entry": 100, "sl": 101, "targets": [{"p": 98}]}), "t"))
DATA["EEEUSDT"] = [B(P.PAPER_SINCE_TS - 600 + 60, 99.9, 100.0, 97.9, 98.0)]
n7 = P.control_tick(db, mk_fetch(), NOW7, log=log.append)
check("контрольний потік бере сценарій до запуску (без PAPER_SINCE)", n7 >= 1 and any(r[0] == "CTL|O2|ctl|2" for r in _fetchall(db, "SELECT scenario_id FROM office2_paper_position")))
DATA["DDDUSDT"] = [B(T0 + 60, 100.1, 100.4, 100.0, 100.3), B(T0 + 120, 100.3, 102.3, 100.2, 102.0)]
live_before = P.summary(db)["stats"]["total"]
P.tick(db, mk_fetch(), T0 + 400, log=log.append)
P.tick(db, mk_fetch(), T0 + 400, log=log.append)           # повтор: без дублів
sm = P.summary(db)
ct = sm["control"]["stats"]
check("контроль: 2 позиції (до і після запуску), обидві розв'язані за TP1 (A), без дубля; в однієї B/C ще ведуть залишок", ct["total"] == 2 and ct["closed"] == 2 and ct["tp"] == 2 and ct["b_c_still_open"] == 1, str(ct))
check("контроль не змішується з LIVE", sm["stats"]["total"] == live_before and all(x["scope"] == "LIVE" for x in sm["items"]))
check("контроль згруповано за причиною ліміту", any("стопи" in k for k in sm["control"]["by_gate"]), str(sm["control"]["by_gate"]))
check("learning-звіт paper не містить CONTROL", P.learning_report(db)["overall"]["total"] == live_before)

# --- 8. статус ліміту для Mini App
NOWG = T0 + 3600
for i, (lvl, off) in enumerate((("ENTRY", 0), ("TP1", 100), ("SL", 200), ("SL", 300), ("SL", 400))):
    from office_bridge import log_event as _le
    _le(db, "SCENARIO_MILESTONE", {"level": lvl, "sent_ts": T0 + off}, "O2|g1")
_le(db, "SCENARIO_MILESTONE", {"level": "SL", "sent_ts": T0 + 500}, "O2|g2")
_le(db, "SCENARIO_MILESTONE", {"level": "SL", "sent_ts": T0 + 600}, "O2|g3")
g = P.gate_status(db, NOWG)
check("ліміт: 5 стопів за добу, НЕ locked (з 14.10.2026 лише попередження), підвищений ризик з 3-го (T0+400)", len(g["stops"]) == 5 and not g["locked"] and g["elevated_risk"] and abs(g["elevated_since_ts"] - (T0 + 400)) < 1, str(g)[:300])
check("ліміт: стоп після TP1 позначено, кінець блоку — наступна доба 00:00 UTC", any(x["after_tp1"] for x in g["stops"]) and g["lock_ends_ts"] % 86400 == 0)
check("ліміт: shadow_today та лічильники відсічених", "shadow_today" in g and "candidates_blocked_today" in g)

# --- 9. shadow-позначки (не блокують, ефект рахується окремо)
from datetime import datetime, timezone
from office2.learning import learned_flags as LF
SAT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc).timestamp()
WED = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc).timestamp()
thf = {"dir": "LONG", "sizing": {"stop_pct": 0.5}}
fs, fw = LF.flags_for(thf, SAT), LF.flags_for(thf, WED)
check("позначки: субота + малий стоп → WEEKEND і COST_HEAVY", "WEEKEND" in fs and "COST_HEAVY" in fs, str(fs))
check("позначки: проти тренду → COUNTER_TREND", "COUNTER_TREND" in LF.flags_for({"dir": "LONG", "integral": {"counter_trend": True}}, WED) and "COUNTER_TREND" not in fw, "")
check("позначки: середа не WEEKEND", "WEEKEND" not in fw, str(fw))
rows_f = [{"scope": "LIVE", "pnl_a": -10.0, "_flags": ["WEEKEND"]}, {"scope": "LIVE", "pnl_a": 8.0, "_flags": ["WEEKEND"]}, {"scope": "LIVE", "pnl_a": 8.0, "_flags": []}]
ev = LF.evaluate(rows_f)["rules"]["WEEKEND"]["by_scope"]["LIVE"]
check("ефект позначки: SL уникнуто 1, TP втрачено 1, чистий ефект +2$, n<30 → INSUFFICIENT",
      ev["flagged"] == 2 and ev["sl_avoided"] == 1 and ev["tp_lost"] == 1 and ev["effect_usd"] == 2.0 and ev["verdict"].startswith("INSUFFICIENT"), str(ev))
_execute(db, "UPDATE office2_paper_position SET learned_flags = NULL WHERE scenario_id = 'CTL|O2|ctl|2'")      # як позиція, створена до появи колонки
nfl = P.flags_pass(db, log=log.append)
check("flags_pass доносить позначки для старих позицій", nfl >= 1 and _fetchall(db, "SELECT COUNT(*) FROM office2_paper_position WHERE learned_flags IS NULL AND scope != 'BACKFILL_INVALID'")[0][0] == 0)
sm2 = P.summary(db)
check("summary містить learned_flags і позначки в позиціях; результат/гейти не змінено", "WEEKEND" in sm2["learned_flags"]["rules"] and all("flags" in x for x in sm2["items"]) and sm2["stats"]["total"] == live_before)

# --- гонка в БД: tick до появи першої 1m-свічки → позиція чекає; потім відкривається; а старий MISSED(NO_DATA) виправляється з аудитом
D4 = T0 + 2000 + 30
_execute(db, "INSERT INTO office2_live_signal(scenario_id,symbol,direction,created_ts,valid_until_ts,status,snapshot_json,version,delivered_ts,msg_id,last_error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
         ("S4", "DDDUSDT", "LONG", T0 + 2000, T0 + 9999, "DELIVERED", snap(100, 99, [102]), "v", D4, 4, None))
P._READY["done"] = False
P.tick(db, mk_fetch(), D4 + 45, log=log.append)
check("S4: без першої 1m-свічки позиція не фіксується як MISSED (повтор)", "S4" not in {x["scenario_id"] for x in P.summary(db)["items"]})
P.tick(db, mk_fetch({"DDDUSDT": [B(T0 + 2040, 100.0, 100.3, 99.95, 100.2)]}), D4 + 130, log=log.append)
s4 = [x for x in P.summary(db)["items"] if x["scenario_id"] == "S4"]
check("S4: наступний прохід відкриває позицію за open першої свічки", s4 and s4[0]["status"] == "OPEN" and s4[0]["fill_price"] == 100.0)
_execute(db, "INSERT INTO office2_live_signal(scenario_id,symbol,direction,created_ts,valid_until_ts,status,snapshot_json,version,delivered_ts,msg_id,last_error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
         ("S5", "EEEUSDT", "LONG", T0 + 3000, T0 + 9999, "DELIVERED", snap(100, 99, [102]), "v", T0 + 3030, 5, None))
_execute(db, "INSERT INTO office2_paper_position(scenario_id,symbol,direction,status,generated_ts,delivered_ts,miss_reason,scope) VALUES (?,?,?,?,?,?,?,?)",
         ("S5", "EEEUSDT", "LONG", "MISSED", T0 + 3000, T0 + 3030, "NO_DATA: немає 1m-свічок після доставки (не вигадуємо вхід)", "LIVE"))
nfix = P.repair_no_bars(db, mk_fetch({"EEEUSDT": [B(T0 + 3060, 100.0, 100.3, 99.95, 100.2)]}), T0 + 3300, log=log.append)
s5 = [x for x in P.summary(db)["items"] if x["scenario_id"] == "S5"]
check("S5: MISSED(NO_DATA) виправлено за наявними свічками", nfix == 1 and s5 and s5[0]["status"] == "OPEN", str((nfix, s5[:1])))
check("repair без свічок нічого не змінює", P.repair_no_bars(db, mk_fetch(), T0 + 3300, log=log.append) == 0)

# гонка: перша 1m-свічка після доставки ще не існує → позиція не фіксується як MISSED, а чекає
miss = {"status": "MISSED", "miss_reason": "NO_DATA: немає 1m-свічок після доставки (не вигадуємо вхід)", "delivered_ts": 1000.0}
check("NO_DATA одразу після доставки відкладається (не остаточний MISSED)", P._no_bars_yet(miss, 1000.0 + 90))
check("після вікна очікування NO_DATA фіксується як є", not P._no_bars_yet(miss, 1000.0 + P.NO_BARS_GRACE_SEC + 1))
check("інші причини MISSED не відкладаються", not P._no_bars_yet(dict(miss, miss_reason="MISSED: ціна вже за SL"), 1000.0 + 90))

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)
