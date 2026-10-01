#!/usr/bin/env python3
"""Цілі Лева зі структури: поріг RR 1,5 після комісій НЕ знижено, формула «1,5R» прибрана, READY технічно досяжний."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"
import office_alert_gate as G  # noqa: E402
import office_calendar as CAL  # noqa: E402
import office_lev_targets as LT  # noqa: E402
from office_lev_watch import check_plan, plan_from_cycle  # noqa: E402

CAL.entry_block = lambda *a, **k: None   # hermetic: без мережі/календаря

E, SL = 100.0, 98.0   # ризик 2%

# 1) Колишня формула: TP1 рівно 1,5R до комісій → гейт після комісій її відхиляє (це і була суперечність)
legacy_tp = E + 1.5 * (E - SL)
assert not G.rr_gate(E, SL, legacy_tp, None)["ok"], "1,5R брутто після комісій < 1,5 — суперечність, яку усунуто"

# 2) Немає реальних рівнів → відхилено, ціль не вигадується
r = LT.pick_targets(direction="LONG", entry=E, sl=SL, levels=[])
assert not r["ok"] and r["tp1"] is None and "не вигадую" in r["reason"], r

# 3) Лише рівень, що дає RR нижче порога → відхилено (ціль не «підтягуємо»)
r = LT.pick_targets(direction="LONG", entry=E, sl=SL, levels=[(102.5, "свінг H1")])   # 1,25R брутто
assert not r["ok"] and r["tp1"] is None and "відхилено" in r["reason"], r

# 4) Реальний рівень із достатнім RR → TP1 без TP2, RR після комісій ≥ 1,5
r = LT.pick_targets(direction="LONG", entry=E, sl=SL, levels=[(103.5, "свінг H4")])
assert r["ok"] and r["tp1"] == 103.5 and r["tp2"] is None and r["rr"] >= 1.5 and r["rr_net"] >= 1.5, r
assert G.rr_gate(E, SL, r["tp1"], r["tp2"])["ok"]

# 5) Є реальний TP2 → зважене правило: 40% TP1 + 60% TP2 ≥ 1,5 і RR до TP1 ≥ 1,0
r = LT.pick_targets(direction="LONG", entry=E, sl=SL, levels=[(102.4, "свінг H1"), (106.0, "рівень попереднього дня")])
assert r["ok"] and r["tp1"] == 102.4 and r["tp2"] == 106.0, r
assert r["rr_weighted"] >= 1.5 and r["rr_net"] >= 1.0 and r["rr"] == r["rr_weighted"], r
assert G.rr_gate(E, SL, r["tp1"], r["tp2"])["ok"]

# 6) Найближчий рівень не дає RR, наступний дає → беремо перший, що проходить; TP1 не підтягується між рівнями
r = LT.pick_targets(direction="LONG", entry=E, sl=SL, levels=[(101.5, "свінг H1"), (104.0, "зона рівня")])
assert r["ok"] and r["tp1"] == 104.0 and r.get("skipped_nearer") == 1, r

# 7) SHORT — дзеркально
r = LT.pick_targets(direction="SHORT", entry=E, sl=102.0, levels=[(96.5, "свінг H4")])
assert r["ok"] and r["tp1"] == 96.5 and r["rr_net"] >= 1.5, r
r = LT.pick_targets(direction="SHORT", entry=E, sl=102.0, levels=[(99.0, "x"), (103.0, "y")])   # 103 — не по ходу SHORT
assert not r["ok"], r

# 8) Чинний мінімум простору до TP1 (мажори 1,2%) не знижено
r = LT.pick_targets(direction="LONG", entry=E, sl=99.7, levels=[(100.6, "свінг H1")], min_tp1_pct=1.2)
assert not r["ok"], r   # 0,6% < 1,2% — навіть якщо RR достатній

# 9) Рівні ближче за 0,15% зливаються; ціль не далі за 3×ATR(D1)
r = LT.pick_targets(direction="LONG", entry=E, sl=SL, levels=[(103.5, "свінг"), (150.0, "далекий")], atr_d1=2.0)
assert r["ok"] and r["tp1"] == 103.5 and r["tp2"] is None, r   # 150 далі за 3×2=6 від входу — не ціль

# 10) Збір рівнів зі свічок не падає на порожніх/коротких даних
lv, atr = LT.collect_levels(direction="LONG", candles_h1=[], candles_h4=None)
assert lv == [] and atr is None

# 11) Відкатний ПОВНИЙ шлях: lev_cycle (синтетичний сценарій) → SEND → check_plan(той самий гейт, що й READY) → None
import test_lev_analyst_first as A  # noqa: E402
from office_lev_verdict import lev_cycle  # noqa: E402

px = 84870.0
m15, h1 = A._bars_flat(30, px), A._bars_flat(30, px)
cyc = lev_cycle(symbol="BTCUSDT", price=px, timeframe="H1", candles_m15=m15, candles_h1=h1, atr_h1=900.0, day_used_pct=35.0,
                candidates_long=A._btc_long_cands(), candidates_short=A._btc_short_cands_weak(),
                market_context={"data_status": "DATA_UNAVAILABLE"}, stances=A._neutral_stances("LONG"),
                target_levels=[(84700.0, "свінг H1"), (86200.0, "рівень попереднього дня")])
assert cyc["send"] and cyc["action"] == "SEND" and cyc["tp1"] and cyc["tp2"], cyc
plan = plan_from_cycle(cyc)
g = G.rr_gate(plan["entry"], plan["sl"], plan["tp1"], plan["tp2"])
assert g["ok"] and g["rr_weighted"] >= 1.5 and g["rr_net"] >= 1.0, g
d = cyc["draft"]
assert check_plan("BTCUSDT", "LONG", plan, d["zone_lo"], d["zone_hi"]) is None, check_plan("BTCUSDT", "LONG", plan, d["zone_lo"], d["zone_hi"])
assert abs(d["rr"] - g["rr_weighted"]) < 1e-9

# 12) READY: стан сценарію з цими цілями — READY (RR ≥ 1,5 після комісій, вхід у межі)
import office_scenario_state as S  # noqa: E402

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
row = {"signal_id": "SCN|BTC|1", "symbol": "BTCUSDT", "direction": "LONG", "entry_low": d["zone_lo"], "entry_high": d["zone_hi"], "sl": plan["sl"], "tp1": plan["tp1"],
       "tp2": plan["tp2"], "status": "CONFIRMED", "ts_created": NOW.isoformat(), "ts_updated": NOW.isoformat(),
       "analysis_note": f"ЛЕВ cancel={plan['sl']} confirm_sent=1 confirmed_px={plan['entry']} tf=H1"}
v = S.build(row, thesis={"invalidation": "закриття нижче стопа", "confirmation": "M15"},
            price={"price": plan["entry"], "as_of": NOW.isoformat(), "fresh": True, "source": "binance_futures"}, plan_check=check_plan, now=NOW)
assert v["state"] == "READY", v

# 13) Контрприклад: старий «1,5R брутто» план цей самий гейт відхиляє
old_plan = {"entry": plan["entry"], "sl": plan["sl"], "tp1": plan["entry"] + 1.5 * (plan["entry"] - plan["sl"]), "tp2": None}
assert check_plan("BTCUSDT", "LONG", old_plan, d["zone_lo"], d["zone_hi"]) is not None

# 14) lev_cycle без реальної цілі → SKIP з чіткою причиною, не SEND
cyc2 = lev_cycle(symbol="BTCUSDT", price=px, timeframe="H1", candles_m15=m15, candles_h1=h1, atr_h1=900.0, day_used_pct=35.0,
                 candidates_long=A._btc_long_cands(), candidates_short=A._btc_short_cands_weak(),
                 market_context={"data_status": "DATA_UNAVAILABLE"}, stances=A._neutral_stances("LONG"), target_levels=[(84000.0, "x")])
assert not cyc2["send"] and cyc2["action"] == "SKIP" and cyc2["tp1"] is None and ("ціль" in cyc2["reason"] or "відхилено" in cyc2["reason"]), cyc2

print("OK Lev targets: структурні цілі, поріг 1,5 після комісій не знижено, READY досяжний, 1,5R-формули немає")
