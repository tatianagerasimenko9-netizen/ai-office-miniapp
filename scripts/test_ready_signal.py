#!/usr/bin/env python3
"""Готовий сигнал у Telegram: колір і слово за напрямком, лише цифри; межа входу; мовчазне відстеження результату; ведення позначеної угоди."""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"
import office_user_messages as M  # noqa: E402
import office_signal_track as T  # noqa: E402
import office_trade_updates as U  # noqa: E402
from office_alert_gate import max_entry_price, net_rr  # noqa: E402

# --- формат: LONG і SHORT
lg = M.ready_signal(symbol="AKEUSDT", direction="LONG", entry=0.030259, sl=0.029568, tp1=0.031621, tp2={"price": 0.032086, "why": "x"}, tp3=None,
                    max_entry=0.03035, size_usdt=438, risk_usd=10, valid_until="02:40")
assert lg.splitlines()[0] == "🟢 LONG · AKE · ПЛАН ГОТОВИЙ ✅", lg
assert "Вхід: 0,030259 $ (не вище 0,03035" in lg and "Стоп: 0,029568 $" in lg and "TP1: 0,031621 $" in lg and "TP2: 0,032086 $" in lg, lg
assert "TP3" not in lg and "Позиція 438 USDT · ризик 10 $" in lg and "⏳ Діє до 02:40 (Київ)" in lg, lg
sh = M.ready_signal(symbol="SNXXUSDT", direction="SHORT", entry=0.5, sl=0.52, tp1=0.46, tp3={"price": 0.4, "why": "x"}, max_entry=0.4896)
assert sh.splitlines()[0] == "🔴 SHORT · SNXX · ПЛАН ГОТОВИЙ ✅" and "(не нижче" in sh and "TP3: 0,4" in sh and "TP2" not in sh, sh
for txt in (lg, sh):
    for bad in ("ЗАРАЗ", "ПІДСТАВА", "СКАСОВУЄМО", "Це аналіз", "умови виконано", "ордер"):
        assert bad not in txt, (bad, txt)

# --- межа входу: RR після комісій рівно 1,5
for d, sl, tp in (("LONG", 0.029568, 0.031621), ("SHORT", 1.05, 0.95)):
    m = max_entry_price(d, sl, tp)
    assert abs(net_rr(m, sl, tp)["rr_net"] - 1.5) < 1e-9, (d, m)

# --- стан сценарію: READY має напрям у назві й кольорі; ціна за межею → не готовий
import office_scenario_state as S  # noqa: E402
from office_lev_watch import check_plan  # noqa: E402

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
FRESH = {"price": 0.0303, "as_of": NOW.isoformat(), "fresh": True, "source": "binance_futures"}


def row(direction, e, sl, tp1, lo, hi):
    return {"signal_id": "SCN|X|1", "symbol": "AKEUSDT", "direction": direction, "entry_low": lo, "entry_high": hi, "sl": sl, "tp1": tp1, "status": "CONFIRMED",
            "ts_created": NOW.isoformat(), "ts_updated": NOW.isoformat(), "analysis_note": f"ЛЕВ cancel={sl} confirm_sent=1 confirmed_px={e} tf=H1"}


TH = {"invalidation": "закриття за 0.0295", "confirmation": "M15"}
v = S.build(row("LONG", 0.030259, 0.029568, 0.031621, 0.0298, 0.0309), thesis=TH, price=FRESH, plan_check=check_plan, now=NOW)
assert v["state"] == "READY" and v["icon"] == "🟢" and v["state_ua"].startswith("LONG"), v
assert v["plan"]["max_entry"] and v["levels"]["max_entry"] > 0.0303
# ціна вже за межею входу (для LONG вище max) → не готовий
v2 = S.build(row("LONG", 0.030259, 0.029568, 0.031621, 0.0298, 0.0309), thesis=TH, price={**FRESH, "price": 0.0308}, plan_check=check_plan, now=NOW)
assert v2["state"] == "NOT_READY" and any("межею входу" in m for m in v2["missing"]), v2
vs = S.build({**row("SHORT", 0.5, 0.52, 0.46, 0.498, 0.505), "symbol": "SNXXUSDT"}, thesis=TH, price={**FRESH, "price": 0.5}, plan_check=check_plan, now=NOW)
assert vs["state"] == "READY" and vs["icon"] == "🔴" and vs["state_ua"].startswith("SHORT"), vs
txt = M.render_human(v)
assert txt.splitlines()[0] == "🟢 LONG · AKE · ПЛАН ГОТОВИЙ ✅" and "ЗАРАЗ" not in txt, txt

# --- мовчазне відстеження: свічки після підтвердження
T0 = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc).timestamp()


def candles(spec):
    return [{"ts": datetime.fromtimestamp(T0 + 900 * i, tz=timezone.utc).isoformat(), "open": o, "high": h, "low": l, "close": c} for i, (o, h, l, c) in enumerate(spec)]


plan = {"direction": "LONG", "entry": 100.0, "sl": 98.0, "tp1": 103.0, "tp2": 105.0, "tp3": 108.0, "confirmed_ts": T0, "valid_until_ts": T0 + 4 * 3600}
NOWT = T0 + 20 * 3600
up = candles([(100, 100.5, 99.8, 100.2), (100.2, 103.5, 100, 103), (103, 105.5, 102.5, 105), (105, 108.5, 104.5, 108)])
r = T.simulate(plan, up, NOWT)
assert r["status"] == "TP3" and r["reached"] == ["TP1", "TP2", "TP3"] and r["mfe_pct"] >= 8.4 and r["mae_pct"] >= 0.2, r
dn = candles([(100, 100.5, 99.8, 100.2), (100.2, 100.4, 97.5, 98)])
assert T.simulate(plan, dn, NOWT)["status"] == "STOP"
both = candles([(100, 100.5, 99.8, 100.2), (100.2, 103.5, 97.0, 100)])   # і ціль, і стоп в одній свічці → стоп (консервативно)
assert T.simulate(plan, both, NOWT)["status"] == "STOP"
tp1_then_stop = candles([(100, 100.5, 99.8, 100.2), (100.2, 103.2, 100, 103), (103, 103.5, 97.5, 98)])
assert T.simulate(plan, tp1_then_stop, NOWT)["status"] == "TP1"
away = candles([(105, 106, 104.5, 105.5)] * 20)    # ціна ніколи не торкнулась входу за час дії
assert T.simulate(plan, away, NOWT)["status"] == "NOT_FILLED"
assert T.simulate(plan, up, T0 + 1000)["status"] == "PENDING", "свічки ще не закриті"
short = {"direction": "SHORT", "entry": 100.0, "sl": 102.0, "tp1": 97.0, "confirmed_ts": T0, "valid_until_ts": T0 + 4 * 3600}
assert T.simulate(short, candles([(100, 100.4, 99.6, 99.8), (99.8, 100, 96.5, 97)]), NOWT)["status"] == "TP1"

# запис події, підсумок і звіт (SQLite)
from office_bridge import init_office_db  # noqa: E402

db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
try:
    init_office_db(db)
    T.record_plan(db, scenario_id="SCN|A", symbol="AKEUSDT", direction="LONG", tf="H1", entry=100, sl=98, tp1=103, tp2=105, tp3=108, max_entry=100.6,
                  confirmed_ts=T0, valid_until_ts=T0 + 4 * 3600, confirm_msg_id=777)
    T.record_plan(db, scenario_id="SCN|B", symbol="AKEUSDT", direction="LONG", tf="H1", entry=100, sl=99.5, tp1=101, confirmed_ts=T0,
                  valid_until_ts=T0 + 4 * 3600, rejected=True, reason="RR")
    res = T.tick(db, fetch=lambda s, tf, n: up, now_ts=NOWT)
    assert {r["scenario_id"]: r["outcome"] for r in res} == {"SCN|A": "TP3", "SCN|B": "TP1"}, res   # відхилений теж рахується гіпотетично
    assert T.tick(db, fetch=lambda s, tf, n: up, now_ts=NOWT) == [], "результат пишеться один раз"
    rep = T.report(db)
    assert rep["signals"]["plans"] == 1 and rep["rejected"]["plans"] == 1 and "n=1" in rep["signals"]["note"] and "fill_rate_pct" not in rep["signals"]
    assert T.confirm_msg_for(db, "SCN|A") == 777 and T.confirm_msg_for(db, "SCN|B") is None
finally:
    os.unlink(db)

# --- ведення позначеної угоди: дія в рядку, один раз
pos = {"symbol": "AKEUSDT", "direction": "LONG", "entry": 0.030259, "sl": 0.029568, "tp1": 0.031621, "tp2": 0.032086}
ev = {e["code"]: e["text"] for e in U.texts(pos, 0.0317)}
assert ev == {"TP1": "🎯 AKE · TP1 · закрий 40%, стоп у беззбиток 0,030259 $"}, ev
ev2 = {e["code"]: e["text"] for e in U.texts(pos, 0.0322)}
assert "TP2" in ev2 and "стоп на TP1 0,031621 $" in ev2["TP2"] and "TP1" in ev2
st = U.texts(pos, 0.0295)
assert st == [{"code": "STOP_PRICE", "text": "🔴 AKE · ціна досягла стопа"}] and "закрит" not in st[0]["text"]
assert U.texts(pos, 0.0303) == []
spos = {"symbol": "SNXXUSDT", "direction": "SHORT", "entry": 0.5, "sl": 0.52, "tp1": 0.46}
assert [e["code"] for e in U.texts(spos, 0.455)] == ["TP1"] and U.texts(spos, 0.521)[0]["code"] == "STOP_PRICE"
print("OK ready signal: direction colour+word, numbers only, max entry, silent tracking, managed-trade updates")
