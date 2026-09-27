#!/usr/bin/env python3
"""PR51: єдина картка, ATR-стоп, TP1 majors/alts, переворот, near-stop /position."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["OFFICE_DEPO_USDT"] = "1000"

from office_bridge import (  # noqa: E402
    POSITION_CONFIRM_REASON,
    _fetchone,
    init_office_db,
    journal_open_office_signal,
    journal_open_trade,
    office_signal_trade_id,
    signal_upsert,
)
from office_desk_card import (  # noqa: E402
    card_has_banned,
    desk_entry_gate,
    format_desk_card,
    latest_open_desk_signal,
    may_send_near_stop,
    min_tp1_pct,
    prepare_desk_send,
    reset_near_stop_once,
)
from office_level_parse import parse_signal_levels_from_text  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_telegram_filter import MIN_ALERT_MOVE_PCT, alert_decision  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85 or MIN_RR < 1.5:
        return _fail("atr/edge/rr frozen")
    if MIN_ALERT_MOVE_PCT != 3.0:
        return _fail("alts 3% const")
    if min_tp1_pct("SNXXUSDT") != 3.0 or min_tp1_pct("BTCUSDT") != 1.2:
        return _fail("tp1 majors/alts")
    if min_tp1_pct("XAUUSDT") != 1.2 or min_tp1_pct("ETHUSDT") != 1.2:
        return _fail("xau/eth")

    # Live XAU 0.06% stop / 0.08% TP1 — не йде (TP1 < 1.2%; стоп < ATR).
    xau = desk_entry_gate(
        symbol="XAUUSDT",
        direction="SHORT",
        entry=3900.0,
        sl=3902.34,  # ~0.06%
        tp1=3896.88,  # ~0.08%
        atr_h1=39.0,  # 1%
        score=12,
        min_score=10,
    )
    if xau.get("send"):
        return _fail(f"XAU 0.06% must not send {xau}")

    # Альті <3% не йде; BTC 1.3% проходить TP1-фільтр (якщо стоп/розмір ок).
    alt = alert_decision(
        status="CONFIRMED",
        entry=17.46,
        sl=17.30,
        tp1=17.70,
        rr_net=2.0,
        symbol="SNXXUSDT",
    )
    if alt.get("send"):
        return _fail("alt 1.4% must fail 3%")
    btc_tp = alert_decision(
        status="CONFIRMED",
        entry=84069.0,
        sl=83000.0,
        tp1=85100.0,
        rr_net=2.0,
        symbol="BTCUSDT",
    )
    if not btc_tp.get("send"):
        return _fail(f"btc 1.2%+ should send {btc_tp}")

    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db.close()
    init_office_db(db.name)

    # BTC LONG 18:42
    signal_upsert(
        db.name,
        signal_id="pump-btc-1842",
        symbol="BTCUSDT",
        direction="LONG",
        entry_low=84069.0,
        entry_high=84069.0,
        sl=83756.0,
        tp1=84500.0,
        tp2=85000.0,
        rr=2.0,
        status="ACTIVE",
        analysis_note="PUMP cancel=84000",
    )
    journal_open_office_signal(
        db.name,
        signal_id="pump-btc-1842",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=84069.0,
        stop_loss=83756.0,
        take_profit=84500.0,
        timeframe="M15",
        setup_note="PUMP",
    )
    prev = latest_open_desk_signal(db.name, "BTCUSDT")
    if not prev or str(prev.get("direction")).upper() != "LONG":
        return _fail(f"prev long {prev}")

    # 18:50 SHORT без скасування — конфлікт модулів
    conflict = prepare_desk_send(
        db_path=db.name,
        symbol="BTCUSDT",
        direction="SHORT",
        timeframe="H1",
        entry=84042.0,
        sl=84210.0,
        tp1=82500.0,
        atr_h1=900.0,
        score=10,
        min_score=10,
        setup_type="РАДАР",
        m15_close=84050.0,
        prev=prev,
        require_confluence=False,
    )
    if conflict.get("send") or conflict.get("reason") != "конфлікт модулів":
        return _fail(f"conflict {conflict}")

    # Сильніший протилежний сетап (бал ≥ поріг+1) — переворот без закриття M15.
    strong = desk_entry_gate(
        symbol="BTCUSDT",
        direction="SHORT",
        entry=84042.0,
        sl=84942.0,
        tp1=82000.0,
        atr_h1=900.0,
        score=11,
        min_score=10,
        m15_close=84050.0,
        prev=prev,
    )
    if not strong.get("send") or not strong.get("reversal"):
        return _fail(f"rev_min_score {strong}")

    prev_from_db = latest_open_desk_signal(db.name, "BTCUSDT")
    stored_cancel = (prev_from_db or {}).get("cancel_level")
    if stored_cancel is None or abs(float(stored_cancel) - 84000.0) > 1e-6:
        return _fail(f"cancel_level from note {prev_from_db}")

    prev_c = dict(prev_from_db or prev)
    rev = prepare_desk_send(
        db_path=db.name,
        symbol="BTCUSDT",
        direction="SHORT",
        timeframe="H1",
        entry=84042.0,
        sl=84942.0,
        tp1=82000.0,
        atr_h1=900.0,
        score=10,
        min_score=10,
        setup_type="РАДАР",
        m15_close=83950.0,
        prev=prev_c,
        require_confluence=False,
    )
    if not rev.get("send") or not rev.get("reversal"):
        return _fail(f"reversal {rev}")
    txt = str(rev.get("text") or "")
    if "🔄 LONG від 84 069 скасовано" not in txt:
        return _fail(f"reversal card {txt}")
    if "M15 закрилась нижче 84 000" not in txt:
        return _fail(f"reversal reason {txt}")
    banned = card_has_banned(txt)
    if banned:
        return _fail(f"banned {banned} in {txt}")
    if "🎯 Вхід" not in txt or "❌ Стоп" not in txt:
        return _fail("ukrainian labels")
    tid = office_signal_trade_id("pump-btc-1842")
    closed = _fetchone(
        db.name,
        "SELECT status, exit_reason FROM trade_journal WHERE trade_id = ?",
        (tid,),
    )
    if not closed or str(closed[0]) != "CLOSED" or str(closed[1]) != "переворот":
        return _fail(f"journal reversal {closed}")

    # Картка DUMP як у ТЗ (Rich Bears)
    dump = format_desk_card(
        symbol="SNXXUSDT",
        direction="SHORT",
        timeframe="M15",
        entry=17.46,
        sl=17.62,
        tp1=17.22,
        tp2=16.98,
        tp3=16.67,
        setup_type="DUMP",
        grade="A",
        zone_line="сильна свічка M15 + OB H1",
        confirm_wait="Чекаю на M5: подвійна вершина або SFP у зоні",
        size={"size_usdt": 1099, "depo": 1000, "risk_pct": 0.01},
    )
    snxx_need = (
        "🔴 SHORT · SNXXUSDT · M15",
        "Шорт на відкаті · сила A",
        "🎯 Вхід · 17.46",
        "❌ Стоп · 17.62  (−0.9%)",
        "✅ TP1 · 17.22  (+1.4%)",
        "✅ TP2 · 16.98  (+2.7%)",
        "✅ TP3 · 16.67  (+4.5%)",
        "Зона: сильна свічка M15 + OB H1",
        "Чекаю на M5:",
        "Позиція 1 099 USDT · ризик 10$",
    )
    for bit in snxx_need:
        if bit not in dump:
            return _fail(f"SNXX missing {bit!r} in {dump}")
    if "RR 1:" in dump or "Балі" in dump or "Бали" in dump:
        return _fail(f"SNXX extra {dump}")
    parsed = parse_signal_levels_from_text(dump)
    if abs(float(parsed.get("entry_low") or 0) - 17.46) > 1e-6:
        return _fail(f"parse вхід {parsed}")
    if abs(float(parsed.get("sl") or 0) - 17.62) > 1e-6:
        return _fail(f"parse стоп {parsed}")
    if parsed.get("direction") != "SHORT":
        return _fail(f"parse dir {parsed}")

    ake = format_desk_card(
        symbol="AKEUSDT",
        direction="LONG",
        timeframe="M15",
        entry=0.03289,
        sl=0.03215,
        tp1=0.03475,
        tp2=0.03529,
        tp3=0.03780,
        add_px=0.03250,
        setup_type="Відкат у сильну свічку",
        grade="B",
        size={"size_usdt": 454, "depo": 1000, "risk_pct": 0.01},
    )
    if "🟢 LONG · AKEUSDT · M15" not in ake or "Відкат у сильну свічку" not in ake:
        return _fail(ake)
    if "🎯 Вхід · " not in ake or "сила B" not in ake:
        return _fail(ake)

    # Live: BTC стоп 0.20% → розмір > 3× депо (TP нижче entry, інакше геометрія ріже раніше)
    btc_slim = desk_entry_gate(
        symbol="BTCUSDT",
        direction="SHORT",
        entry=84042.0,
        sl=84210.0,  # 0.20%
        tp1=83000.0,
        atr_h1=168.0,
        score=10,
        min_score=10,
    )
    if btc_slim.get("send"):
        return _fail(f"BTC 0.20% must not send {btc_slim}")
    if "3×" not in str(btc_slim.get("reason") or "") and "депо" not in str(btc_slim.get("reason") or ""):
        return _fail(f"BTC 0.20% reason {btc_slim}")

    # Live: SNXX TP1 1.36% < 3% альти
    snxx_gate = desk_entry_gate(
        symbol="SNXXUSDT",
        direction="SHORT",
        entry=17.46,
        sl=17.62,
        tp1=17.22,
        atr_h1=0.20,
        score=12,
        min_score=10,
    )
    if snxx_gate.get("send"):
        return _fail(f"SNXX 1.36% must not send {snxx_gate}")

    # Near-stop: 5 разів — 1 раз і лише /position
    reset_near_stop_once()
    office_ok = may_send_near_stop(trade_id="osig-btc", confirmed_position=False)
    if office_ok:
        return _fail("office signal near-stop")
    sent = 0
    for _ in range(5):
        if may_send_near_stop(trade_id="pos-btc-1", confirmed_position=True):
            sent += 1
    if sent != 1:
        return _fail(f"near-stop count {sent}")

    journal_open_trade(
        db.name,
        trade_id="pos-eth-1",
        symbol="ETHUSDT",
        direction="LONG",
        entry_price=4000.0,
        stop_loss=3960.0,
        take_profit=4120.0,
        setup_name="T1_MY_POSITION",
        entry_reason=POSITION_CONFIRM_REASON,
    )
    reset_near_stop_once()
    if not may_send_near_stop(trade_id="pos-eth-1", confirmed_position=True):
        return _fail("position first near-stop")
    if may_send_near_stop(trade_id="pos-eth-1", confirmed_position=True):
        return _fail("position second near-stop")

    print("OK: test_pr51_desk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
