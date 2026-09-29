#!/usr/bin/env python3
"""Маршрут до Telegram: TP1/SL лише для verified OPEN /position.

Текст не дає права на дію. Не Live. Не змінює ATR 80/90, Edge 85, MIN_RR 1.5.
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
os.environ["OFFICE_TG_POSITION_SUPPORT"] = "1"  # логіка шлюзу; прапорець за замовчуванням вимкнено — див. окремий тест

from office_alert_gate import (  # noqa: E402
    apply_setup_event,
    gate_outbound_telegram,
    get_explicit_open_position,
    has_explicit_position,
    may_emit_telegram,
    origin_key,
    reset_alert_gate,
    text_grants_entry,
    text_instructs_position_change,
)
from office_bridge import (  # noqa: E402
    POSITION_CONFIRM_REASON,
    init_office_db,
    is_confirmed_position_row,
    journal_close_trade,
    journal_open_trade,
    signal_upsert,
)
from office_lifecycle import format_tp1_hit  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85 or float(MIN_RR) != 1.5:
        return _fail("gates frozen")

    tp1 = format_tp1_hit(
        symbol="MANTAUSDT",
        direction="SHORT",
        entry=0.07111,
        tp1=0.068619,
        tp2=0.066,
    )
    if "закрий 50" not in tp1.lower() or not text_instructs_position_change(tp1):
        return _fail(f"tp1 card {tp1}")
    sl_txt = "Тетяно, MANTAUSDT: SL перебитий\nЩо робити зараз: повний вихід з позиції зараз\nSL після дії: позиція закрита"
    if not text_instructs_position_change(sl_txt):
        return _fail("sl text")

    # Без /position — fail-closed, навіть з тими самими словами.
    g0 = gate_outbound_telegram(intent="POSITION_MANAGE", text=tp1)
    if g0.get("send"):
        return _fail(f"tp1 without position {g0}")
    g1 = gate_outbound_telegram(
        intent="",
        text=tp1,
        in_position=True,
        position_id="pos-x",
        position_open=True,
    )
    if g1.get("send"):
        return _fail(f"empty intent must fail-closed {g1}")
    g2 = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=tp1,
        in_position=True,
        position_id="",
        position_open=True,
    )
    if g2.get("send"):
        return _fail(f"missing id {g2}")
    g3 = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=tp1,
        in_position=True,
        position_id="pos-x",
        position_open=False,
    )
    if g3.get("send"):
        return _fail(f"closed pos {g3}")
    print("OK ті самі фрази без verified /position блокуються")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_office_db(db)
    signal_upsert(
        db,
        signal_id="manta-short-m15",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_low=0.070471,
        entry_high=0.071447,
        sl=0.072504,
        tp1=0.068619,
        tp2=None,
        rr=2.0,
        status="CONFIRMED",
        analysis_note="origin=desk tf=M15",
    )
    if has_explicit_position(db, "MANTAUSDT", "SHORT"):
        return _fail("CONFIRMED ≠ /position")
    g_conf = gate_outbound_telegram(intent="CONFIRM", text=tp1)
    if g_conf.get("send"):
        return _fail("confirm+tp1 order language")
    ok_conf = gate_outbound_telegram(
        intent="CONFIRM",
        text="MANTAUSDT SHORT підтверджено на 0.07111. Не позиція.",
    )
    if not ok_conf.get("send"):
        return _fail(ok_conf)
    zkey = origin_key(
        symbol="MANTAUSDT", direction="SHORT", zone_lo=0.070471, zone_hi=0.071447, origin="t0"
    )
    reset_alert_gate()
    apply_setup_event(zkey, "ZONE_IN", in_zone=True)
    zg = may_emit_telegram(key=zkey, intent="ZONE_IN", in_zone=True)
    if zg.get("send"):
        return _fail(zg)
    g_zone = gate_outbound_telegram(intent="ZONE_IN", text=tp1)
    if g_zone.get("send"):
        return _fail("zone+tp1")
    add = may_emit_telegram(intent="ADD_ON", in_position=False)
    if add.get("send"):
        return _fail(add)
    print("OK ZONE_REACHED/CONFIRMED без позиції не створюють entry/добір")

    # Neither a pos- ID nor a legacy setup label proves an owner /position.
    for reason, setup, tid in (
        ("", "T1_MY_POSITION", "pos-forged"),
        ("desk enter after agent chain", "T1_MY_POSITION", "pos-desk"),
        ("", "", "pos-only"),
        ("explicit /position by owner (unverified)", "T1_MY_POSITION", "pos-ambiguous"),
    ):
        if is_confirmed_position_row(reason, setup, tid):
            return _fail(("unverified position accepted", reason, setup, tid))
    journal_open_trade(
        db,
        trade_id="pos-forged",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_price=0.07111,
        stop_loss=0.072504,
        setup_name="T1_MY_POSITION",
        entry_reason="desk enter after agent chain",
    )
    if get_explicit_open_position(db, "MANTAUSDT", "SHORT").get("ok"):
        return _fail("forged pos- ID/setup granted verified position")
    print("OK pos- ID and T1_MY_POSITION alone cannot authorize /position")

    journal_open_trade(
        db,
        trade_id="pos-manta-1",
        symbol="MANTAUSDT",
        direction="SHORT",
        entry_price=0.07111,
        stop_loss=0.072504,
        take_profit=0.068619,
        setup_name="T1_MY_POSITION",
        entry_reason=POSITION_CONFIRM_REASON,
    )
    rec = get_explicit_open_position(db, "MANTAUSDT", "SHORT")
    if not rec.get("ok") or rec.get("trade_id") != "pos-manta-1":
        return _fail(rec)
    g_tp1 = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=tp1,
        in_position=True,
        position_id=rec["trade_id"],
        position_open=True,
        event_type="TRADE_UPDATE",
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    if not g_tp1.get("send"):
        return _fail(f"tp1 with /position {g_tp1}")
    g_sl = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=sl_txt,
        in_position=True,
        position_id=rec["trade_id"],
        position_open=True,
        event_type="TRADE_CLOSED",
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    if not g_sl.get("send"):
        return _fail(f"sl with /position {g_sl}")
    trail = "Закрий ще частину\nSL в беззбиток 0.07111, далі підтягую стоп за рухом"
    g_tr = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=trail,
        in_position=True,
        position_id=rec["trade_id"],
        position_open=True,
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    if not g_tr.get("send"):
        return _fail(f"trail {g_tr}")
    tp2_txt = "✅ TP2 · MANTAUSDT SHORT\nЗакрий ще частину\nSL на 0.068619"
    g_tp2 = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=tp2_txt,
        in_position=True,
        position_id=rec["trade_id"],
        position_open=True,
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    if not g_tp2.get("send"):
        return _fail(f"tp2 {g_tp2}")
    g_tp2_no = gate_outbound_telegram(intent="", text=tp2_txt)
    if g_tp2_no.get("send"):
        return _fail("tp2 empty intent")
    g_tr_no = gate_outbound_telegram(intent="POSITION_MANAGE", text=trail)
    if g_tr_no.get("send"):
        return _fail("trail without position")
    print("OK TP1 «закрий 50» / SL-вихід / trail лише для OPEN /position")

    if text_grants_entry(tp1):
        return _fail("tp1 must not be classified as entry grant")
    fake = "можна входити в MANTA /position"
    g_fake = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=fake,
        in_position=True,
        position_id="pos-manta-1",
        position_open=True,
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    if g_fake.get("send"):
        return _fail("substring /position must not grant entry")
    print("OK згадка /position у тексті не дає права")

    journal_close_trade(
        db,
        trade_id="pos-manta-1",
        outcome="LOSS",
        exit_price=0.0725,
        pnl_pct=0.0,
        exit_reason="SL",
    )
    rec2 = get_explicit_open_position(db, "MANTAUSDT", "SHORT")
    if rec2.get("ok"):
        return _fail("closed still open")
    g_closed = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=tp1,
        in_position=True,
        position_id="pos-manta-1",
        position_open=True,
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    if g_closed.get("send"):
        return _fail("closed position instructions")
    g_unknown = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=tp1,
        in_position=True,
        position_id="pos-unknown",
        position_open=True,
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    rec_u = get_explicit_open_position(db, "MANTAUSDT", "SHORT")
    g_unk2 = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=tp1,
        in_position=bool(rec_u.get("ok")),
        position_id=str(rec_u.get("trade_id") or ""),
        position_open=bool(rec_u.get("open")),
        db_path=db,
        symbol="MANTAUSDT",
        direction="SHORT",
    )
    if g_unk2.get("send"):
        return _fail("unknown/closed via lookup")
    print("OK закрита/невідома позиція не отримує інструкцій")
    os.environ.pop("OFFICE_TG_POSITION_SUPPORT", None)
    g_off = gate_outbound_telegram(
        intent="POSITION_MANAGE", text=tp1, in_position=True, position_id=rec["trade_id"], position_open=True,
        event_type="TRADE_UPDATE", db_path=db, symbol="MANTAUSDT", direction="SHORT",
    )
    if g_off.get("send"):
        return _fail(f"position support must be off by default {g_off}")
    print("OK супровід позицій у Telegram вимкнено за замовчуванням (OFFICE_TG_POSITION_SUPPORT)")
    print("OK: test_telegram_position_gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
