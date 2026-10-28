"""Offline safety checks for live B&R observational stream (no network, no Telegram)."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from office_br import live


def test_off_by_default():
    with patch.dict(os.environ, {"BR_LIVE_TG": "0"}):
        assert not live.enabled()
    with patch.dict(os.environ, {"BR_LIVE_TG": "1"}):
        assert live.enabled()


def test_only_futures_closed_candles_requested():
    seen = []
    def fake(symbol, tf, limit, *, closed_only):
        seen.append((symbol, tf, limit, closed_only))
        return {}
    assert live.scan_symbol("no-db", "BTCUSDT", fake) == 0
    assert seen == [("BTCUSDT", "15m", 240, True)]


def test_time_and_ohlc():
    rows = [{"ts": "2026-10-15T09:00:00+00:00", "open": 1, "high": 3, "low": 0.5, "close": 2}]
    t, o, h, l, c = live._bars(rows)
    assert t == [1792054800.0]
    assert o == [1.0] and h == [3.0] and l == [0.5] and c == [2.0]


def test_isolated_number_and_experimental_disclosure():
    from office_br.card import build_card
    row = {"symbol": "BTCUSDT", "direction": "LONG", "seq": 1,
           "entry": 100, "sl": 99, "level": 100, "targets": [{"p": 101, "src": "structure"}]}
    text = build_card(row)
    assert "B&R LIVE" in text
    assert "replay V1/V2 збитковий" in text
    assert "B&R-1" in text
    assert "AI Office · №" not in text
    from office_br.card import reminder_text
    assert "фіксацію 30%" in reminder_text(row, "TP1")
    assert "беззбиток" in reminder_text(row, "TP1")
    assert "ще 40%" in reminder_text(row, "TP2")
    assert "залишку" in reminder_text(row, "TP3")
    assert "Торкання ≠ виконання ордера" in reminder_text(row, "ENTRY")


def test_monitor_marks_only_successful_scan_and_reports_coverage():
    from inspect import getsource
    source = getsource(live.monitor)
    assert source.index("found = await asyncio.to_thread(") < source.index("seen[sym] = ts")
    assert "scan health ok=" in source
    assert "scan_missing += 1" in source and "scan_stale += 1" in source
    assert "scan_errors += 1" in source


def test_br_ui_is_manual_and_has_both_charts():
    page = (Path(__file__).resolve().parents[1] / "office_web" / "br_live.html").read_text(encoding="utf-8")
    assert "chart_a" in page and "chart_b" in page
    assert "/api/v2/candles" in page and "Binance Futures" in page
    assert "Я відкрила угоду" in page and "Я перенесла SL у BE" in page
    assert "/api/br/manual" in page and "X-Telegram-Init-Data" in page
    assert "Н/Д" in page
    assert "exchange_order" not in page


def test_track_does_not_replay_entry_before_ready_delivery():
    """Paper tracking must not count an entry touched before READY reached Telegram."""
    import json
    import types

    def epoch(ts):
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()

    ready_sent = epoch("2026-10-28T15:46:51Z")
    row = {
        "sig_id": "BR|BTCUSDT|LONG|100|test", "seq": 1, "symbol": "BTCUSDT",
        "direction": "LONG", "confirm_ts": epoch("2026-10-28T15:30:00Z"),
        "created_ts": epoch("2026-10-28T15:46:47Z"), "sent_ts": ready_sent,
        "status": "SENT", "msg_id": 123, "entry": 100.0, "sl": 98.0,
        "targets_json": json.dumps([{"p": 110.0, "src": "structure"}]),
    }
    bars = [
        {"ts": "2026-10-28T15:45:00Z", "open": 100, "high": 101, "low": 99, "close": 100},
        {"ts": "2026-10-28T15:46:00Z", "open": 100, "high": 101, "low": 99, "close": 100},
        {"ts": "2026-10-28T15:47:00Z", "open": 99.7, "high": 99.8, "low": 99.5, "close": 99.7},
    ]
    captured = {"fallback": None, "events": [], "sent": []}
    bridge = types.ModuleType("office_bridge")
    bridge._execute = lambda *args, **kwargs: None
    with patch.dict(sys.modules, {"office_bridge": bridge}):
        with patch.object(live.store, "rows", lambda *args, **kwargs: [row]):
            with patch.object(live.store, "events", lambda *args, **kwargs: []):
                with patch.object(live.store, "record_event",
                                  lambda *args, **kwargs: captured["events"].append(args)):
                    with patch.object(live, "_cursor",
                                      lambda db, sid, fallback: captured.update(fallback=fallback) or fallback - 120):
                        with patch.object(live, "_save_cursor", lambda *args, **kwargs: None):
                            async def send(*args, **kwargs):
                                captured["sent"].append((args, kwargs))
                                return 456

                            result = asyncio.run(live.track(
                                "offline-test-db",
                                lambda *args, **kwargs: bars,
                                send,
                            ))

    assert captured["fallback"] == ready_sent
    assert result == 0
    assert captured["sent"] == []
    assert captured["events"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
