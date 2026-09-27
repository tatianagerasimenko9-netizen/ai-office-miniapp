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
    may_emit_telegram,
    origin_key,
    plan_metrics,
    reset_alert_gate,
    text_grants_entry,
    format_zone_wait_message,
)
from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_bridge import init_office_db, signal_get_active, signal_upsert  # noqa: E402
from office_confluence import detect_ltf_confirms, follow_setup, format_confirm_card  # noqa: E402
from office_lifecycle import next_lifecycle_state  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_mini_v1 import _card_from_signal, live_unique_cards  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_telegram_filter import format_px  # noqa: E402
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

    ART.mkdir(parents=True, exist_ok=True)
    (ART / "manta_alert_audit.md").write_text(
        "\n".join(
            [
                "# MANTAUSDT audit",
                "",
                "## Три повідомлення — три рушії (не один код)",
                "1. Desk/confluence картка Лева (`format_desk_card` / `_desk_send`): SHORT M15, зона, «чекаю підтвердження M5». Origin=desk. Telegram SIGNAL_ENTRY.",
                "2. Follow loop (`follow_setup` + `format_confirm_card`): «вхід підтверджено · 0.07111». Origin=desk follow. EVENT_TRADE_UPDATE. Раніше detail брехав «закриття нижче zone_lo», навіть коли close був у зоні.",
                "3. Legacy T0 HIT_ENTRY (`monitor` ACTIVE + ціна в зоні, `stream=general`): «досяг зони… Можна входити» з сирими float. Origin=t0. Не desk. Графік «чекаю», бо в тексті немає «сила A».",
                "",
                "## Live OHLCV / prod signal_id",
                "DATA_UNAVAILABLE — у цьому середовищі немає production DB і стрічки Telegram.",
                "",
                "## Gate",
                "ZONE_IN / HIT_ENTRY_PRICE ніколи не send. Після CONFIRMED повторна зона не ENTRY.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print("OK: test_manta_alert_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
