#!/usr/bin/env python3
"""MANTAUSDT: WATCHING → CONFIRMED 0.07111 → повторний ZONE_REACHED 0.07081.

Жодного другого entry-алерту, жодного legacy «можна входити».
OHLCV Live / signal_id з prod — DATA_UNAVAILABLE (немає production DB).
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["OFFICE_DEPO_USDT"] = "1000"

from office_alert_gate import (  # noqa: E402
    apply_setup_event,
    chase_blocks_entry,
    format_zone_wait_message,
    has_explicit_position,
    may_emit_telegram,
    origin_key,
    plan_metrics,
    reset_alert_gate,
    scale_in_review,
    text_grants_entry,
    validate_trade_geometry,
)
from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_bridge import (  # noqa: E402
    POSITION_CONFIRM_REASON,
    init_office_db,
    journal_open_trade,
    signal_get_active,
    signal_upsert,
)
from office_confluence import detect_ltf_confirms, follow_setup, format_confirm_card  # noqa: E402
from office_desk_card import desk_entry_gate, format_desk_card, prepare_desk_send  # noqa: E402
from office_lifecycle import next_lifecycle_state  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_mini_v1 import _card_from_signal, live_unique_cards  # noqa: E402
from office_position_size import plan_position_size  # noqa: E402
from office_price_format import format_level_span, format_px, has_float_tail  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_zone_alert import (  # noqa: E402
    ATR_DAY_USED_ENTRY_BLOCK_PCT,
    format_zone_signal_entry,
    plan_watching_zone_hit,
    zone_reached_to_telegram,
)

ART = Path("/opt/cursor/artifacts")

ZONE_LO = 0.070471
ZONE_HI = 0.071447
SL = 0.072504
TP1 = 0.068619
PX_CONFIRM = 0.07111
PX_LATER = 0.07081


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl, vol=10.0):
    return {"open": o, "high": h, "low": l, "close": cl, "volume": vol}


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("ATR frozen")
    if SIGNAL_THRESHOLD != 85 or MIN_RR < 1.5:
        return _fail("edge/rr frozen")

    reset_alert_gate()
    junk = 0.07144666000000001
    if format_px(junk) == str(junk) or "00000001" in format_px(ZONE_HI * 1.0):
        if "00000001" in format_px(junk):
            return _fail(f"float junk {format_px(junk)}")
    if "0000001" in format_zone_wait_message(
        symbol="MANTAUSDT",
        current_price=PX_LATER,
        entry_low=ZONE_LO,
        entry_high=junk,
        sl=SL,
        tp1=TP1,
    ):
        return _fail("wait msg float junk")
    print("OK tick/format_px без 0.07144666000000001")

    # Три рушії — різні origin, не один код.
    k_desk = origin_key(
        symbol="MANTAUSDT", direction="SHORT", zone_lo=ZONE_LO, zone_hi=ZONE_HI, origin="desk"
    )
    k_t0 = origin_key(
        symbol="MANTAUSDT", direction="SHORT", zone_lo=ZONE_LO, zone_hi=ZONE_HI, origin="t0"
    )
    if k_desk == k_t0:
        return _fail("desk і t0 мають різні origin")
    print("OK різні origin desk vs t0 vs follow")

    # (1) WATCHING картка Лева — зона, чекаю M5.
    apply_setup_event(k_desk, "FOUND")
    apply_setup_event(k_desk, "ZONE_IN", in_zone=True)
    z1 = may_emit_telegram(key=k_desk, intent="ZONE_IN", in_zone=True)
    if z1.get("send"):
        return _fail(f"zone telegram {z1}")
    ready = plan_watching_zone_hit(
        current_price=0.07081,
        entry_low=ZONE_LO,
        entry_high=ZONE_HI,
        day_used_pct=40.0,
        sl=SL,
        tp1=TP1,
        symbol="MANTAUSDT",
    )
    if zone_reached_to_telegram(ready) or ready.promote_active:
        return _fail("T0 zone telegram")
    if "можна входити" in ready.message.lower():
        return _fail(ready.message)
    print("OK msg1-path: WATCHING/зона без дозволу на вхід")

    # (2) M5 confirm 0.07111 у зоні; DT+TT з тих самих свінгів → лише triple.
    ltf = [
        _c(0.0706, 0.07120, 0.07050, 0.07090),
        _c(0.0709, 0.07130, 0.07070, 0.07110),
        _c(0.0711, 0.07135, 0.07080, 0.07100),
        _c(0.0710, 0.07150, 0.07075, PX_CONFIRM),  # SFP: тінь вище зони, close в зоні
    ]
    hits = detect_ltf_confirms(
        direction="SHORT", candles_ltf=ltf, zone_lo=ZONE_LO, zone_hi=ZONE_HI
    )
    if "sfp" not in hits:
        return _fail(f"need sfp {hits}")
    if "double_top" in hits and "triple_top" in hits:
        return _fail(f"DT+TT dup {hits}")
    # Три майже рівні хаї — лише потрійна, не double+triple.
    zig = [
        _c(0.0706, 0.07140, 0.0705, 0.0708),
        _c(0.0708, 0.07110, 0.0706, 0.0707),
        _c(0.0707, 0.07141, 0.0705, 0.0708),
        _c(0.0708, 0.07105, 0.0706, 0.0707),
        _c(0.0707, 0.07142, 0.0705, 0.0709),
        _c(0.0709, 0.07155, 0.0707, PX_CONFIRM),
    ]
    zhit = detect_ltf_confirms(direction="SHORT", candles_ltf=zig, zone_lo=ZONE_LO, zone_hi=ZONE_HI)
    if "triple_top" in zhit and "double_top" in zhit:
        return _fail(f"same-swing DT+TT {zhit}")
    fu = follow_setup(
        setup={
            "direction": "SHORT",
            "sl": SL,
            "zone_lo": ZONE_LO,
            "zone_hi": ZONE_HI,
            "ts": 1.0,
            "timeframe": "M15",
        },
        price=PX_CONFIRM,
        candles_ltf=ltf,
        now_ts=2.0,
    )
    if fu.get("action") != "confirm":
        return _fail(f"confirm {fu}")
    if abs(float(fu.get("price")) - PX_CONFIRM) > 1e-9:
        return _fail(f"entry {fu.get('price')}")
    if "нижче" in str(fu.get("detail") or ""):
        return _fail(f"не можна писати close below lo при close={PX_CONFIRM}: {fu}")
    c2 = may_emit_telegram(key=k_desk, intent="CONFIRM", ltf_confirmed=True)
    if not c2.get("send"):
        return _fail(f"first confirm {c2}")
    apply_setup_event(k_desk, "CONFIRMED", ltf_ok=True)
    from office_alert_gate import mark_confirm_sent

    mark_confirm_sent(k_desk)
    txt2 = format_confirm_card(
        symbol="MANTAUSDT",
        direction="SHORT",
        price=fu.get("price"),
        detail=str(fu.get("detail") or ""),
    )
    if text_grants_entry(txt2):
        return _fail(f"confirm grants entry {txt2}")
    print("OK msg2-path: одне LTF-підтвердження 0.07111, без close-below-ло")

    # Close below zone без ретесту — 0.07111 невалідний як поточний entry.
    broke = list(ltf) + [_c(0.0704, 0.0705, 0.0702, 0.0703)]
    fu_b = follow_setup(
        setup={
            "direction": "SHORT",
            "sl": SL,
            "zone_lo": ZONE_LO,
            "zone_hi": ZONE_HI,
            "ts": 1.0,
            "timeframe": "M15",
        },
        price=0.0703,
        candles_ltf=broke,
        now_ts=3.0,
    )
    if fu_b.get("action") != "hold" or not fu_b.get("need_retest"):
        return _fail(f"need retest {fu_b}")
    if fu_b.get("price") == PX_CONFIRM:
        return _fail("stale 0.07111 after break")
    print("OK після close < zone_lo — ретест, не старий 0.07111")

    # (3) Повторний ZONE_REACHED 0.07081 після CONFIRMED — тиша.
    z3 = may_emit_telegram(key=k_desk, intent="ZONE_IN", in_zone=True, state="CONFIRMED")
    h3 = may_emit_telegram(key=k_t0, intent="HIT_ENTRY_PRICE", in_zone=True, state="CONFIRMED")
    e3 = may_emit_telegram(
        key=k_desk, intent="ENTRY_PERMISSION", ltf_confirmed=True, state="CONFIRMED"
    )
    if z3.get("send") or h3.get("send") or e3.get("send"):
        return _fail(f"second entry {z3} {h3} {e3}")
    legacy = (
        f"Тетяно, MANTAUSDT досяг зони входу {ZONE_LO}-{ZONE_HI}. "
        f"Зараз {PX_LATER}. Можна входити. SL: {SL} TP1: {TP1}"
    )
    if not text_grants_entry(legacy):
        return _fail("detector")
    card = format_zone_signal_entry(
        symbol="MANTAUSDT",
        current_price=PX_LATER,
        entry_low=ZONE_LO,
        entry_high=ZONE_HI,
        sl=SL,
        tp1=TP1,
    )
    if text_grants_entry(card) or str(junk) in card:
        return _fail(card)
    lc = next_lifecycle_state(
        current="CONFIRMED",
        price=PX_LATER,
        entry_low=ZONE_LO,
        entry_high=ZONE_HI,
        confirmed=False,
    )
    if lc["state"] != "CONFIRMED":
        return _fail(f"lifecycle {lc}")
    print("OK msg3-path: повторна зона 0.07081 не дає «можна входити»")

    met = plan_metrics(entry=PX_CONFIRM, sl=SL, tp1=TP1)
    if met.get("rr_net") is None or met["rr_net"] < 0:
        return _fail(f"rr_net {met}")
    if met.get("sl_pct") is None or met.get("tp1_pct") is None:
        return _fail(met)
    print(f"OK metrics from actual entry sl%={met['sl_pct']:.2f} tp1%={met['tp1_pct']:.2f} rr_net={met['rr_net']:.2f}")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["OFFICE_DB_PATH"] = db
    init_office_db(db)
    signal_upsert(
        db,
        signal_id="desk-lev-MANTAUSDT-1",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_low=ZONE_LO,
        entry_high=ZONE_HI,
        sl=SL,
        tp1=TP1,
        tp2=None,
        rr=None,
        status="CONFIRMED",
        analysis_note="ckey=MANTAUSDT|SHORT",
    )
    rows = signal_get_active(db)
    cards = live_unique_cards(rows)
    if not cards:
        return _fail(f"mini cards {rows}")
    card_m = cards[0]
    if card_m.get("status") != "підтверджено":
        return _fail(f"mini status {card_m}")
    if card_m.get("in_position"):
        return _fail("CONFIRMED ≠ позиція")
    mapped = _card_from_signal({"status": "CONFIRMED", "symbol": "MANTAUSDT", "direction": "SHORT"})
    if mapped.get("in_position"):
        return _fail("in_position")
    print("OK Mini App: CONFIRMED, не в позиції")

    if has_explicit_position(db, "MANTAUSDT", "SHORT"):
        return _fail("/position falsely true on CONFIRMED signal")
    add0 = may_emit_telegram(intent="ADD_ON", in_position=False)
    if add0.get("send") or "добір заборонено" not in str(add0.get("reason") or ""):
        return _fail(f"add without position {add0}")
    add1 = may_emit_telegram(intent="ADD_ON", in_position=True)
    if add1.get("send"):
        return _fail(f"add auto with position {add1}")
    plan0 = scale_in_review(in_position=False)
    if plan0.get("order") or plan0.get("ok"):
        return _fail(f"scale without pos {plan0}")
    journal_open_trade(
        db,
        trade_id="pos-manta-1",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_price=PX_CONFIRM,
        stop_loss=SL,
        take_profit=TP1,
        setup_name="T1_MY_POSITION",
        entry_reason=POSITION_CONFIRM_REASON,
    )
    if not has_explicit_position(db, "MANTAUSDT", "SHORT"):
        return _fail("/position not seen")
    plan1 = scale_in_review(in_position=True, geometry_ok=True, setup_valid=True)
    if plan1.get("order") or not plan1.get("plan_only"):
        return _fail(f"scale with pos must be plan only {plan1}")
    print("OK добір: без /position заборонено; з /position лише план, без ордера")

    junk_span = format_level_span(0.07047058, 0.07144666000000001, "MANTAUSDT")
    sl_txt = format_px(0.07250414754616397, "MANTAUSDT")
    if junk_span != "0.070471–0.071447":
        return _fail(f"manta zone display {junk_span}")
    if sl_txt != "0.072504":
        return _fail(f"manta sl display {sl_txt}")
    fake_add = (
        f"Тетяно, MANTAUSDT: ціна повернулась в entry-зону {junk_span}. "
        "Що робити зараз: можливий добір позиції малим обсягом у зоні. "
        f"SL після дії: {sl_txt}"
    )
    if not text_grants_entry(fake_add) or has_float_tail(fake_add):
        return _fail(f"add phrase/float {fake_add}")
    print(f"OK виправлений текст зони: {junk_span} SL {sl_txt}")

    btc_lo, btc_hi = 83343.89, 84411.2
    btc_sl, btc_t1, btc_t2 = 84623.82, 85023.51, 85263.33
    geo_btc = validate_trade_geometry(
        direction="LONG",
        sl=btc_sl,
        tp1=btc_t1,
        entry_low=btc_lo,
        entry_high=btc_hi,
        tp2=btc_t2,
    )
    if geo_btc.get("ok") or geo_btc.get("size_allowed"):
        return _fail(f"BTC LONG SL above zone must fail {geo_btc}")
    card_btc = format_desk_card(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="H1",
        entry=btc_lo,
        sl=btc_sl,
        tp1=btc_t1,
        tp2=btc_t2,
        entry_low=btc_lo,
        entry_high=btc_hi,
        now_line="Зараз: ціна вже вище зони — не ганяю",
    )
    if card_btc:
        return _fail(f"BTC invalid card leaked {card_btc}")
    gate_btc = desk_entry_gate(
        symbol="BTCUSDT",
        direction="LONG",
        entry=(btc_lo + btc_hi) / 2,
        sl=btc_sl,
        tp1=btc_t1,
        atr_h1=800.0,
        entry_low=btc_lo,
        entry_high=btc_hi,
        tp2=btc_t2,
    )
    if gate_btc.get("send") or gate_btc.get("size"):
        return _fail(f"BTC gate size {gate_btc}")
    sz_bad = plan_position_size(entry=83877.0, sl=btc_sl, direction="LONG", depo=1000)
    if sz_bad.get("ok") or sz_bad.get("size_usdt"):
        return _fail(f"abs() hid wrong-side SL {sz_bad}")
    if not chase_blocks_entry(direction="LONG", price=84800.0, zone_lo=btc_lo, zone_hi=btc_hi):
        return _fail("chase LONG")
    prep_btc = prepare_desk_send(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="H1",
        entry=btc_lo,
        sl=btc_sl,
        tp1=btc_t1,
        tp2=btc_t2,
        atr_h1=800.0,
        price=84800.0,
        require_confluence=False,
        add_px=btc_hi,
    )
    if prep_btc.get("send"):
        return _fail(f"prepare sent invalid BTC {prep_btc}")
    print("OK BTC LONG SL вище зони: картка/розмір/send заборонені")

    geo_short = validate_trade_geometry(
        direction="SHORT",
        sl=83000.0,
        tp1=82000.0,
        entry_low=btc_lo,
        entry_high=btc_hi,
        tp2=81000.0,
    )
    if geo_short.get("ok"):
        return _fail(f"SHORT SL below zone {geo_short}")
    geo_edge = validate_trade_geometry(
        direction="LONG",
        sl=btc_lo,
        tp1=btc_t1,
        entry_low=btc_lo,
        entry_high=btc_hi,
    )
    if geo_edge.get("ok"):
        return _fail("LONG SL == zone_lo must fail")
    geo_tp = validate_trade_geometry(
        direction="LONG",
        sl=82000.0,
        tp1=84000.0,
        entry_low=btc_lo,
        entry_high=btc_hi,
    )
    if geo_tp.get("ok"):
        return _fail(f"LONG TP inside zone {geo_tp}")
    geo_ok = validate_trade_geometry(
        direction="LONG",
        sl=82000.0,
        tp1=87000.0,
        entry_low=btc_lo,
        entry_high=btc_hi,
        tp2=88000.0,
    )
    if not geo_ok.get("ok"):
        return _fail(f"valid LONG {geo_ok}")
    print("OK SHORT-дзеркало, межа зони, невірний TP")

    routes = [
        format_zone_wait_message(
            symbol="MANTAUSDT",
            current_price=0.07144666000000001,
            entry_low=0.07047058,
            entry_high=0.07144666000000001,
            sl=0.07250414754616397,
            tp1=TP1,
        ),
        junk_span,
        format_px(83343.89, "BTCUSDT"),
        format_desk_card(
            symbol="SNXXUSDT",
            direction="SHORT",
            timeframe="M15",
            entry=17.46,
            sl=17.62,
            tp1=17.22,
            tp2=16.98,
        ),
    ]
    for blob in routes:
        if has_float_tail(blob) or "00000001" in str(blob):
            return _fail(f"float tail {blob}")
    print("OK ціни без float-хвостів на маршрутах")

    fd2, db2 = tempfile.mkstemp(suffix=".db")
    os.close(fd2)
    init_office_db(db2)
    signal_upsert(
        db2,
        signal_id="manta-long-h1",
        symbol="MANTAUSDT",
        direction="LONG",
        entry_low=0.068,
        entry_high=0.069,
        sl=0.066,
        tp1=0.072,
        tp2=None,
        rr=None,
        status="ACTIVE",
        analysis_note="origin=desk tf=H1",
    )
    signal_upsert(
        db2,
        signal_id="manta-short-m15",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_low=ZONE_LO,
        entry_high=ZONE_HI,
        sl=SL,
        tp1=TP1,
        tp2=None,
        rr=None,
        status="ACTIVE",
        analysis_note="origin=desk tf=M15",
    )
    from office_scenario_memory import apply_confirmed_status, gate_entry_vs_memory

    upd = apply_confirmed_status(
        db2,
        symbol="MANTAUSDT",
        direction="SHORT",
        timeframe="M15",
        origin="desk",
        zone_lo=ZONE_LO,
        zone_hi=ZONE_HI,
        price=PX_CONFIRM,
    )
    if upd != ["manta-short-m15"]:
        return _fail(f"scoped confirm {upd}")
    rows2 = {r["signal_id"]: r for r in signal_get_active(db2)}
    if rows2["manta-short-m15"]["status"] != "CONFIRMED":
        return _fail("short not confirmed")
    if rows2["manta-long-h1"]["status"] != "ACTIVE":
        return _fail("long H1 must stay ACTIVE")
    memg = gate_entry_vs_memory(
        list(rows2.values()),
        symbol="MANTAUSDT",
        direction="SHORT",
        timeframe="M15",
    )
    if not memg.get("allow_entry") or not memg.get("coexist"):
        return _fail(f"SHORT M15 має співіснувати з LONG H1 {memg}")
    mem_same = gate_entry_vs_memory(
        list(rows2.values()),
        symbol="MANTAUSDT",
        direction="LONG",
        timeframe="M15",
    )
    if mem_same.get("allow_entry"):
        return _fail(f"same-horizon opposite must block {mem_same}")
    print("OK MANTA LONG H1 + SHORT M15: CONFIRMED лише SHORT M15, різні горизонти співіснують")

    ART.mkdir(parents=True, exist_ok=True)
    (ART / "manta_alert_audit.md").write_text(
        "\n".join(
            [
                "# MANTAUSDT + BTC geometry audit",
                "",
                "## MANTA ADD_ON",
                "Джерело: T0 monitor HIT_ENTRY + ціна знову в зоні (`office_relay_wizard.py`).",
                "Не /position. Текст був «можливий добір…» з сирими float.",
                "Після gate: Telegram ADD_ON завжди deny; без /position — заборона; з /position — лише план.",
                "",
                "## BTC LONG H1",
                "Entry 83343.89–84411.2, SL 84623.82 вище зони. widen_sl_to_atr_h1 тримав |entry-SL|≥ATR.",
                "plan_position_size(abs) малював 1124 USDT. Gate тепер fail-closed, картки немає.",
                "",
                "## Live",
                "DATA_UNAVAILABLE — немає production DB / стрічки Telegram у цьому середовищі.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print("OK: test_manta_alert_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
