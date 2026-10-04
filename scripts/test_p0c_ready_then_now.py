#!/usr/bin/env python3
"""P0c: READY (історичний знімок) ≠ можливість входу ЗАРАЗ; перевірка RR у Mini App = правило гейта; відхилені плани не дублюються. OP/TAKE/JUP — фікстури + довільні символи."""
import os
import random
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
db = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1", OFFICE_CALENDAR_BLOCK="1")
import office_alert_gate as G  # noqa: E402
import office_calendar as cal  # noqa: E402
import office_execution_check as EX  # noqa: E402
import office_ready_core as RC  # noqa: E402
import office_scenario_state as SS  # noqa: E402
import office_signal_track as T  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

init_office_db(db)
cal.set_events_for_tests(cal.parse([]), at=time.time())
NOW = time.time()
ISO = datetime.now(timezone.utc).isoformat()


def row_of(sid, sym, side, lo, hi, sl, tp1, tp2, entry):
    return {"signal_id": sid, "symbol": sym, "direction": side, "entry_low": lo, "entry_high": hi, "sl": sl, "tp1": tp1, "tp2": tp2, "status": "CONFIRMED",
            "ts_created": ISO, "ts_updated": ISO, "analysis_note": f"ЛЕВ cancel={sl} origin=desk tf=H1 scenario_id={sid} confirm_sent=1 confirmed_px={entry}"}


def plan_of(sid, sym, side, entry, sl, t1, t2, t3, me, ts=None):
    ts = ts or NOW - 600
    return {"scenario_id": sid, "symbol": sym, "direction": side, "entry": entry, "sl": sl, "tp1": t1, "tp2": t2, "tp3": t3, "max_entry": me, "confirmed_ts": ts,
            "valid_until_ts": ts + 86400, "rejected": False, "confirm_msg_id": 1,
            "gate": RC.gate_snapshot(direction=side, entry=entry, sl=sl, tp1=t1, tp2=t2, tp3=t3, max_entry=me,
                                     confirm=RC.confirm_basis({"confirms": ["pin_bar"], "detail": "x", "price": entry, "need_retest": False}))}


fresh = lambda p: {"price": p, "fresh": True, "as_of": ISO}  # noqa: E731
pc = lambda *a, **k: None  # noqa: E731

# --- JUP: READY при RR до TP1 1,27 і зваженому 1,70 (правило гейта); у Mini App «зараз» ціна 0.329
jup = plan_of("SCN|JUP|SHORT|H1|1", "JUPUSDT", "SHORT", 0.3295, 0.33749305, 0.3186, 0.3126, 0.2742, G.max_entry_price("SHORT", 0.33749305, 0.3186, 0.3126))
assert G.rr_gate(0.3295, 0.33749305, 0.3186, 0.3126)["ok"], "JUP на момент READY проходить правило гейта"
v = SS.build(row_of("SCN|JUP|SHORT|H1|1", "JUPUSDT", "SHORT", 0.3290, 0.3360, 0.33749305, 0.3186, 0.3126, 0.3295), thesis={"confirmation": []}, price=fresh(0.329), plan_check=pc, plan=jup)
assert v["state"] == "READY" and v["ready"]["rr_net"] and "підтверджено" in v["headline"], v
assert v["ready"]["confirm_ua"] and "пін-бар" in v["ready"]["confirm_ua"]
# TP1-only без комісій давало «1:1,22 → не розглядати»; за правилом гейта від ціни 0.329:
chk = EX.execution_checks(symbol="JUPUSDT", direction="SHORT", zone_lo=0.3290, zone_hi=0.3360, sl=0.33749305, tp1=0.3186, price=0.329, price_fresh=True,
                          has_open_position=False, min_rr=1.5, min_tp1_pct=3.0, tp2=0.3126)
rrc = [c for c in chk["checks"] if c["key"] == "rr"][0]
assert rrc["state"] == ("OK" if G.rr_gate(0.329, 0.33749305, 0.3186, 0.3126)["ok"] else "FAIL") and "після комісій" in rrc["detail"], rrc

# --- TAKE: READY за net RR 1,517; ціна пішла вниз → «зараз» не розглядати, але READY лишається READY
take = plan_of("SCN|TAKE|SHORT|H1|1", "TAKEUSDT", "SHORT", 0.06544, 0.06709127941262483, 0.06277, 0.0595, 0.05301, 0.065)
v2 = SS.build(row_of("SCN|TAKE|SHORT|H1|1", "TAKEUSDT", "SHORT", 0.0650, 0.0670, 0.06709127941262483, 0.06277, 0.0595, 0.06544), thesis=None, price=fresh(0.06532), plan_check=pc, plan=take)
assert v2["state"] == "READY" and v2["now"]["eligible"] in (True, False)
v2b = SS.build(row_of("SCN|TAKE|SHORT|H1|1", "TAKEUSDT", "SHORT", 0.0650, 0.0670, 0.06709127941262483, 0.06277, 0.0595, 0.06544), thesis=None, price=fresh(0.0640), plan_check=pc, plan=take)
assert v2b["state"] == "READY" and v2b["now"]["eligible"] is False and v2b["now"]["reasons"], v2b["now"]   # далеко за межею входу
assert "не розглядати" in v2b["headline"]

# --- довільні символи: дрейф ціни ніколи не перетворює історичний READY на NOT_READY; «зараз» окремо
rnd = random.Random(11)
for k in range(30):
    sym = "".join(rnd.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(rnd.randint(2, 6))) + "USDT"
    p0 = rnd.choice([0.0123, 1.7, 48.0, 3100.0])
    short = rnd.random() < 0.5
    sg = -1 if short else 1
    e, sl, t1, t2 = p0, p0 * (1 - sg * 0.025), p0 * (1 + sg * 0.05), p0 * (1 + sg * 0.09)
    side = "SHORT" if short else "LONG"
    me = G.max_entry_price(side, sl, t1, t2)
    pl = plan_of(f"SCN|{sym}|{side}|H1|{k}", sym, side, e, sl, t1, t2, None, me)
    rw = row_of(pl["scenario_id"], sym, side, p0 * 0.99, p0 * 1.01, sl, t1, t2, e)
    for drift in (-0.04, -0.01, 0.0, 0.01, 0.04):
        vv = SS.build(rw, thesis={"confirmation": []}, price=fresh(p0 * (1 + drift)), plan_check=pc, plan=pl)
        assert vv["state"] == "READY", (sym, drift, vv["state"], vv["missing"])
        assert vv["now"]["eligible"] in (True, False)
    # вхід за планом (ціна = вхід) — гейт той самий → eligible True
    v0 = SS.build(rw, thesis=None, price=fresh(e), plan_check=pc, plan=pl)
    assert v0["now"]["eligible"] is True, (sym, v0["now"])
# прострочений за знімком — EXPIRED
old = plan_of("SCN|OLD|LONG|H1|1", "OLDUSDT", "LONG", 1.0, 0.97, 1.05, 1.09, None, 1.02, ts=NOW - 2 * 86400)
vo = SS.build(row_of("SCN|OLD|LONG|H1|1", "OLDUSDT", "LONG", 0.99, 1.01, 0.97, 1.05, 1.09, 1.0), thesis=None, price=fresh(1.0), plan_check=pc, plan=old)
assert vo["state"] == "EXPIRED", vo["state"]
# без свіжої ціни — «не перевірено», не вигадуємо
vn = SS.build(row_of("SCN|OLD|LONG|H1|1", "OLDUSDT", "LONG", 0.99, 1.01, 0.97, 1.05, 1.09, 1.0), thesis=None, price={"price": None, "fresh": False}, plan_check=pc, plan=jup)
assert vn["state"] == "NO_DATA"

# відхилені плани: не дублюємо ту саму причину
T.record_plan(db, scenario_id="SCN|R|LONG|H1|1", symbol="RUSDT", direction="LONG", tf="H1", entry=1, sl=0.9, tp1=1.1, confirmed_ts=NOW, valid_until_ts=NOW + 1, rejected=True, reason="Причина А")
assert T.rejected_recently(db, "SCN|R|LONG|H1|1", "Причина А") and not T.rejected_recently(db, "SCN|R|LONG|H1|1", "Інша причина")
assert not T.rejected_recently(db, "SCN|R|LONG|H1|1", "Причина А", within_sec=0.0, now=NOW + 5)
print("test_p0c_ready_then_now: OK")

# --- регресія машини станів: повторна перевірка вже READY-сценарію не робить його CANCELLED (реальна машина станів)
from office_alert_gate import apply_setup_event, get_setup_state  # noqa: E402

k = "SCN|SM|SHORT|H1|1"
apply_setup_event(k, "CONFIRMED", ltf_ok=True)
assert get_setup_state(k)["state"] == "CONFIRMED"
dup_same = {"scenario_id": k}
apply_setup_event(k, RC.dup_setup_event(dup_same, k), ltf_ok=True)
assert get_setup_state(k)["state"] == "CONFIRMED", get_setup_state(k)           # той самий сценарій: лишається READY
k2 = "SCN|SM|SHORT|H1|2"
apply_setup_event(k2, "ZONE_REACHED")
apply_setup_event(k2, RC.dup_setup_event({"scenario_id": k}, k2), ltf_ok=True)
assert get_setup_state(k2)["state"] == "CANCELLED", get_setup_state(k2)          # інший scenario_id тієї ж ідеї: скасовується
assert RC.dup_setup_event(None, k) == "CANCELLED"
print("test_p0c state-machine regression: OK")
