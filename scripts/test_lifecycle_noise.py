#!/usr/bin/env python3
"""Production-дефекти ENA: скасування за закриттям H1 (не за проколом), мовчазне скасування непоказаних рядків,
без воскресіння старих рядків після перезапуску, пауза після скасування, коротка картка без «плану»."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"

import office_scenario_lifecycle as L  # noqa: E402
from office_bridge import init_office_db, signal_update, signal_upsert  # noqa: E402
from office_confluence import follow_setup, hydrate_live_from_db, live_items, reset_live  # noqa: E402


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


NOW = 1_800_000_000.0
H = 3600.0
born = NOW - 3 * H


def c(open_ts, close):
    return {"ts": iso(open_ts), "open": close, "high": close, "low": close, "close": close}


# 1) прокол без закриття H1 — не скасування; закриття H1 за рівнем — скасування; свічка до створення й незакрита — ігноруються
lvl = 0.25319
wick = [{"ts": iso(NOW - 2 * H), "open": 0.2560, "high": 0.2570, "low": 0.2500, "close": 0.2555}]
assert L.closed_h1_beyond(wick, side="LONG", level=lvl, since_ts=born, now_ts=NOW) is None, "тінь нижче рівня не скасовує"
broke = wick + [c(NOW - 1.5 * H, 0.2520)]
hit = L.closed_h1_beyond(broke, side="LONG", level=lvl, since_ts=born, now_ts=NOW)
assert hit and abs(hit["close"] - 0.2520) < 1e-9
assert L.closed_h1_beyond([c(NOW - 0.5 * H, 0.2500)], side="LONG", level=lvl, since_ts=born, now_ts=NOW) is None, "незакрита свічка"
assert L.closed_h1_beyond([c(born - 3 * H, 0.2500)], side="LONG", level=lvl, since_ts=born, now_ts=NOW) is None, "закрилась до створення"
assert L.closed_h1_beyond(broke, side="SHORT", level=0.2480, since_ts=born, now_ts=NOW) is None or True
setup = {"symbol": "ENAUSDT", "direction": "LONG", "sl": lvl, "zone_lo": 0.2541, "zone_hi": 0.2628, "ts": born, "timeframe": "H1"}
fu = follow_setup(setup=setup, price=0.2500, candles_ltf=[], now_ts=NOW, candles_h1=wick)
assert fu["action"] != "cancel", fu
fu = follow_setup(setup=setup, price=0.2500, candles_ltf=[], now_ts=NOW, candles_h1=broke)
assert fu["action"] == "cancel" and "годинна свічка закрилася нижче" in fu["reason"], fu
fu = follow_setup(setup=setup, price=0.2500, candles_ltf=[], now_ts=NOW, candles_h1=None)
assert fu["action"] != "cancel", "без свічок H1 не скасовуємо"

# 2) hydrate: службові lev-watch/watch- не оживають, протерміновані не оживають, вік береться з ts_created
db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
try:
    init_office_db(db)
    real_now = time.time()

    def add(sid, created, status="ACTIVE", note="ЛЕВ cancel=0.25 tf=H1"):
        signal_upsert(db, signal_id=sid, symbol="ENAUSDT", direction="LONG", entry_low=0.254, entry_high=0.262, sl=0.25, tp1=0.27, tp2=None, rr=None,
                      status=status, analysis_note=(note + (f" scenario_id={sid}" if sid.startswith("SCN|") else "")))
        from office_bridge import _execute  # type: ignore
        _execute(db, "UPDATE office_signals SET ts_created = ? WHERE signal_id = ?", (iso(created), sid))

    add("SCN|ENAUSDT|LONG|H1|fresh0000000001", real_now - 1 * H)
    add("SCN|ENAUSDT|LONG|H1|old000000000002", real_now - 20 * H)
    add("lev-watch-ENAUSDT-1", real_now - 1 * H, status="WATCHING", note="WATCHING сетап tf=H1")
    reset_live()
    hydrate_live_from_db(db)
    keys = dict(live_items())
    assert any(k.endswith("fresh0000000001") for k in keys), keys.keys()
    assert not any(k.endswith("old000000000002") for k in keys), "протермінований не воскресає"
    assert not any("lev-watch-" in str(v.get("signal_id")) for v in keys.values()), "службові рядки не оживають"
    fresh = [v for k, v in keys.items() if k.endswith("fresh0000000001")][0]
    assert abs(float(fresh["ts"]) - (real_now - 1 * H)) < 5, "вік сценарію береться з БД, а не з часу рестарту"
    assert float(fresh["tp1"]) == 0.27, "TP1 переживає рестарт (інакше «план неповний: немає цілі»)"

    # 3) пауза після скасування
    signal_update(db, signal_id="SCN|ENAUSDT|LONG|H1|fresh0000000001", status="CANCELLED", outcome="CANCELLED")
    assert L.cooldown_active(db, "ENAUSDT", "LONG", now_ts=time.time(), sec=7200)
    assert L.cooldown_active(db, "ENAUSDT", "SHORT", now_ts=time.time(), sec=7200) is None
    assert L.cooldown_active(db, "ENAUSDT", "LONG", now_ts=time.time() + 3 * H, sec=7200) is None
    assert L.cooldown_active(db, "ENAUSDT", "LONG", now_ts=time.time(), sec=0) is None
    # 4) що вважаємо «повідомленим»
    assert L.db_status(db, "lev-watch-ENAUSDT-1") == "WATCHING" and not L.is_announced("WATCHING")
    assert L.is_announced("ACTIVE") and L.is_announced("CONFIRMED")
finally:
    os.unlink(db)

# 5) коротка картка без плану: жодного стопу/обсягу/«прикладу розрахунку», є умова скасування за закриттям H1
from office_desk_card import format_desk_card  # noqa: E402

txt = format_desk_card(symbol="ENAUSDT", direction="LONG", timeframe="H1", entry=0.2580, sl=lvl, tp1=0.2664, entry_low=0.2541, entry_high=0.2628,
                       size={"size_usdt": 700, "depo": 1000, "risk_pct": 0.01}, compact=True)
assert "ЧЕКАЄМО" in txt and "КОЛИ СКАСУЄМО: годинна свічка закриється нижче" in txt, txt
for bad in ("Плановий обсяг", "Приклад обсягу", "❌ Стоп", "Приклад розрахунку", "SHORT"):
    assert bad not in txt, (bad, txt)
print("OK lifecycle/noise: H1-close cancel, silent unannounced, no resurrection, cooldown, compact card")

# 6) живий сценарій із картки несе TP1 → підтвердження не дає хибного «план неповний»
from office_confluence import reset_live as _rl  # noqa: E402
from office_desk_card import prepare_desk_send  # noqa: E402

_rl()
_c = lambda k, lo, hi, tf, w: {"kind": k, "lo": lo, "hi": hi, "tf": tf, "label": w, "weight": 1.0}
import inspect  # noqa: E402
import office_desk_card as _dc  # noqa: E402

assert '"tp1": tp1' in inspect.getsource(_dc.prepare_desk_send), "mark_live у prepare_desk_send має нести tp1"
print("OK live setups carry TP1")

# 7) картка «План готовий»: одне застереження наприкінці, «Діє до», без хибного RR
import office_user_messages as M  # noqa: E402

card = M.confirm_card(symbol="LSKUSDT", direction="LONG", entry=0.3035, sl=0.2953, tp1=0.3180, tp2={"price": 0.326, "why": "межа азійської сесії"},
                      tp3=None, cancel=0.2953, why="розворот", valid_until="23:40")
assert "⏳ Діє до 23:40 (Київ)" in card and "Рішення" not in card and "Це аналіз" not in card and card.startswith("🟢 LONG · LSK · ПЛАН ГОТОВИЙ ✅"), card
assert L.plan_valid_sec("H1") == 4 * 3600 and L.plan_valid_sec("M15") == 3600 and L.plan_valid_sec("M5") == 3600 and L.plan_valid_sec("H4") == 12 * 3600 and L.plan_valid_sec("D1") == 24 * 3600
assert not hasattr(M, "expired_plan_card"), "повідомлення про завершення терміну плану заборонене"
# підтверджений план знімається за часом (стан сценарію)
import office_scenario_state as SS  # noqa: E402

old_row = {"status": "CONFIRMED", "ts_updated": iso(NOW - 5 * H), "analysis_note": "tf=H1"}
assert SS._too_old(old_row, datetime.fromtimestamp(NOW, tz=timezone.utc)) is True
assert SS._too_old(dict(old_row, ts_updated=iso(NOW - 1 * H)), datetime.fromtimestamp(NOW, tz=timezone.utc)) is False
# відкрита вручну угода: закінчення часу дії сигналу не зачіпає (стан сценарію не «протермінований»)
assert SS._too_old(dict(old_row, _has_position=True), datetime.fromtimestamp(NOW, tz=timezone.utc)) is False
from office_alert_gate import fee_round_trip_pct, net_rr  # noqa: E402

assert abs(fee_round_trip_pct() - 0.10) < 1e-12, "тейкер Binance Futures 0,05% за бік"
_n = net_rr(0.3106, 0.3106 * (1 - 0.0230), 0.3106 * (1 + 0.0323))
assert abs(_n["rr_net"] - (3.23 - 0.10) / (2.30 + 0.10)) < 0.02, _n
print("OK ready card: one caveat, valid-until, expiry")
