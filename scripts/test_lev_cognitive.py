#!/usr/bin/env python3
"""Права модулів, cancel-before-entry, SIGNAL без intent, XSS-маркери Mini.

Не Live. Fixture ≠ Live. Не змінює ATR 80/90, Edge 85, MIN_RR 1.5.
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
    gate_outbound_telegram,
    get_explicit_open_position,
    validate_trade_geometry,
)
from office_bridge import (  # noqa: E402
    POSITION_CONFIRM_REASON,
    init_office_db,
    journal_close_trade,
    journal_open_trade,
    signal_upsert,
)
from office_confluence import format_confirm_card  # noqa: E402
from office_desk_card import format_desk_card  # noqa: E402
from office_lev_authority import (  # noqa: E402
    cancel_before_entry_text,
    cancelled_before_entry_is_position_close,
    confirmed_is_open_position,
    had_confirmed_entry,
    indicator_creates_enter,
    module_may_create_signal,
    previous_to_new_link,
    reentry_label_allowed,
    recommend_close_text,
    scenario_sl_may_override_position_sl,
    status_after_cancel_new_setup,
)
from office_lev_verdict import collect_indicator_stances, finalize_lev  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_telegram_policy import reset_trade_telegram_dedup, should_send_trade_telegram  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85 or float(MIN_RR) != 1.5:
        return _fail("gates frozen")
    if indicator_creates_enter() or confirmed_is_open_position():
        return _fail("entity mix")
    if cancelled_before_entry_is_position_close() or scenario_sl_may_override_position_sl():
        return _fail("cancel/position mix")
    for mod in ("radar", "pump_dump", "ict_hunter", "regression_channel", "t0", "llm", "follow"):
        if module_may_create_signal(mod, lev_cycle_ok=False):
            return _fail(f"{mod} created SIGNAL")
        if module_may_create_signal(mod, lev_cycle_ok=True):
            return _fail(f"{mod} bypass lev")
    if not module_may_create_signal("lev_cycle", lev_cycle_ok=True):
        return _fail("lev cannot SIGNAL")
    if module_may_create_signal("desk", lev_cycle_ok=False):
        return _fail("desk without cycle")
    print("OK indicator/radar/T0/LLM/follow не створюють ENTER")

    st = collect_indicator_stances(
        lev_direction="SHORT",
        price=0.071,
        candles_m5=[],
        candles_m15=[],
        candles_h1=[],
        pine_alerts={"pump": "DUMP"},
    )
    fin = finalize_lev(
        {
            "send_card": False,
            "direction": "SHORT",
            "entry": 0.071,
            "sl": 0.073,
            "tp1": 0.068,
            "reason": "немає збігів",
            "confluence": {"n": 0, "send_card": False},
            "atr": {},
            "liquidity": {},
            "market_context": {"data_status": "DATA_UNAVAILABLE"},
        },
        st,
    )
    if fin.get("creates_enter_from_indicator") or fin.get("send"):
        return _fail(f"indicator-only enter {fin}")
    print("OK indicator-only не SEND")

    g_sig_empty = gate_outbound_telegram(
        intent="",
        text="🟢 LONG · BTCUSDT · H1\nПлановий обсяг 1522 USDT",
        event_type="SIGNAL_ENTRY",
    )
    if g_sig_empty.get("send"):
        return _fail(f"SIGNAL_ENTRY empty intent {g_sig_empty}")
    g_png = gate_outbound_telegram(
        intent="ANALYTICAL",
        text="картка з PNG",
        event_type="SIGNAL_ENTRY",
    )
    if g_png.get("send"):
        return _fail("analytical SIGNAL_ENTRY")
    g_ok = gate_outbound_telegram(
        intent="SIGNAL",
        text="🟢 SHORT · MANTAUSDT · M15\nЗараз: поза угодою, чекаю відкат",
        event_type="SIGNAL_ENTRY",
    )
    if not g_ok.get("send"):
        return _fail(g_ok)
    print("OK EVENT_SIGNAL_ENTRY без SIGNAL fail-closed")

    office = gate_outbound_telegram(
        intent="ANALYTICAL",
        text="Тетяно, BTCUSDT: повний вихід з позиції зараз\nпозиція закрита",
        event_type="TRADE_UPDATE",
    )
    if office.get("send"):
        return _fail("send_office analog leaked POSITION_MANAGE")
    print("OK ANALYTICAL/send_office не обходить gate")

    cancel = cancel_before_entry_text(
        symbol="BTCUSDT", direction="LONG", reason="ціна за стопом сценарію"
    )
    if "не закриття позиції" not in cancel:
        return _fail(cancel)
    g_c = gate_outbound_telegram(intent="ANALYTICAL", text=cancel, event_type="TRADE_UPDATE")
    if not g_c.get("send"):
        return _fail(g_c)
    if "повний вихід" in cancel or "позиція закрита" in cancel:
        return _fail("cancel used position language")
    if had_confirmed_entry("ACTIVE") or had_confirmed_entry("WATCHING"):
        return _fail("watching as entry")
    if reentry_label_allowed(previous_status="HIT_SL", previous_had_position=False):
        return _fail("reentry after cancel-before-entry")
    if status_after_cancel_new_setup() != "WATCHING":
        return _fail("new status")
    link = previous_to_new_link(
        prev_direction="LONG",
        prev_status="HIT_SL",
        reason="ціна за стопом до входу",
        new_tf="H1",
        wait_for="відкат у зону",
        had_entry=False,
    )
    if "Повторний" in link or "скасовано до входу" not in link:
        return _fail(link)
    card = format_desk_card(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="H1",
        entry=84556.4,
        sl=84000.76,
        tp1=85564.25,
        tp2=86128.7,
        entry_low=84556.4,
        entry_high=84556.4,
        reentry=True,
        had_confirmed_entry=False,
        previous_link=link,
        now_line="Зараз: поза угодою, чекаю відкат",
        confirm_wait="Чекаю відкат",
        size={"size_usdt": 1522, "depo": 1000, "risk_pct": 0.01},
    )
    if "Повторний вхід" in card:
        return _fail(card)
    if "Плановий обсяг" not in card:
        return _fail(card)
    if "Позиція 1522" in card:
        return _fail("real position wording")
    print("OK cancel-before-entry → новий WATCHING, не повторний вхід")

    geo_bad = validate_trade_geometry(
        direction="LONG",
        sl=84623.82,
        tp1=87000.0,
        entry_low=83343.89,
        entry_high=84411.2,
    )
    if geo_bad.get("ok"):
        return _fail("BTC SL above zone")
    geo_short = validate_trade_geometry(
        direction="SHORT",
        sl=85425.45,
        tp1=83351.57,
        entry_low=84310.26,
        entry_high=85095.0,
        entry=85095.0,
    )
    if not geo_short.get("ok"):
        return _fail(f"wide SHORT valid from worst edge {geo_short}")
    print("OK BTC geometry LONG fail / SHORT wide zone from hi")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_office_db(db)
    signal_upsert(
        db,
        signal_id="btc-long-h1-old",
        symbol="BTCUSDT",
        direction="LONG",
        entry_low=83343.89,
        entry_high=84411.2,
        sl=84000.0,
        tp1=85564.0,
        tp2=None,
        rr=2.0,
        status="ACTIVE",
        analysis_note="origin=desk tf=H1",
    )
    rec0 = get_explicit_open_position(db, "BTCUSDT", "LONG")
    if rec0.get("ok"):
        return _fail("scenario as position")
    exit_txt = recommend_close_text(symbol="BTCUSDT", price=84623.5003, sl=84623.5003)
    g_no = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=exit_txt,
        db_path=db,
        symbol="BTCUSDT",
        direction="LONG",
        in_position=True,
        position_id="lie",
        position_open=True,
    )
    if g_no.get("send"):
        return _fail("caller flags without OPEN")
    journal_open_trade(
        db,
        trade_id="pos-btc-1",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=84556.4,
        stop_loss=84100.0,
        take_profit=85564.25,
        setup_name="T1_MY_POSITION",
        entry_reason=POSITION_CONFIRM_REASON,
    )
    rec = get_explicit_open_position(db, "BTCUSDT", "LONG")
    if abs(float(rec.get("sl") or 0) - 84100.0) > 1e-6:
        return _fail(f"position SL {rec}")
    if abs(float(rec.get("sl") or 0) - 84623.5003) < 1:
        return _fail("scenario SL leaked into position")
    g_yes = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=exit_txt,
        db_path=db,
        symbol="BTCUSDT",
        direction="LONG",
    )
    if not g_yes.get("send"):
        return _fail(g_yes)
    journal_close_trade(db, trade_id="pos-btc-1", outcome="LOSS", exit_price=84100.0, pnl_pct=0.0)
    g_after = gate_outbound_telegram(
        intent="POSITION_MANAGE",
        text=exit_txt,
        in_position=True,
        position_id="pos-btc-1",
        position_open=True,
        db_path=db,
        symbol="BTCUSDT",
        direction="LONG",
    )
    if g_after.get("send"):
        return _fail("manage after close")
    print("OK /position SL ≠ scenario SL; closed → fail-closed")

    reset_trade_telegram_dedup()
    d1 = should_send_trade_telegram(text=cancel, kind="CANCEL_BEFORE_ENTRY", symbol="BTCUSDT", sl=84000)
    d2 = should_send_trade_telegram(text=cancel, kind="CANCEL_BEFORE_ENTRY", symbol="BTCUSDT", sl=84000)
    if not d1.get("send") or d2.get("send"):
        return _fail(f"dedup {d1} {d2}")
    print("OK повторний Telegram event — dedup")

    conf = format_confirm_card(symbol="MANTAUSDT", direction="SHORT", price=0.07111, detail="LTF у зоні")
    if "вхід підтверджено" in conf or "/position" not in conf:
        return _fail(conf)
    g_conf_order = gate_outbound_telegram(intent="CONFIRM", text=conf + "\nповний вихід з позиції")
    if g_conf_order.get("send"):
        return _fail("confirm+order")
    print("OK CONFIRM без entry-grant")

    html = (ROOT / "office_web" / "mini_v2.html").read_text(encoding="utf-8")
    if "function esc(" not in html:
        return _fail("no esc()")
    if "${s.symbol||''}" in html or "${s.analysis_note" in html:
        return _fail("unescaped symbol/note")
    if "esc(s.symbol" not in html:
        return _fail("symbol not escaped")
    print("OK Mini v2 XSS escape")

    from office_mini_app import _tv_webhook_secret_ok  # noqa: WPS433

    class _H:
        def __init__(self, host: str, secret: str = ""):
            self.client_address = (host, 1)
            self.headers = {"X-TradingView-Secret": secret}

    class _U:
        query = ""

    os.environ.pop("TRADINGVIEW_WEBHOOK_SECRET", None)
    if not _tv_webhook_secret_ok(_H("127.0.0.1"), _U()):
        return _fail("loopback without secret")
    if _tv_webhook_secret_ok(_H("8.8.8.8"), _U()):
        return _fail("remote webhook without secret")
    os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = "unit-secret"
    if _tv_webhook_secret_ok(_H("127.0.0.1"), _U()):
        return _fail("secret required even on loopback when set")
    if not _tv_webhook_secret_ok(_H("8.8.8.8", "unit-secret"), _U()):
        return _fail("valid secret rejected")
    os.environ.pop("TRADINGVIEW_WEBHOOK_SECRET", None)
    print("OK webhook auth")

    print("OK: test_lev_cognitive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
