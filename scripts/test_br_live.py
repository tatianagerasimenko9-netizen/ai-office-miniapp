"""Offline safety checks for live B&R observational stream (no network, no Telegram)."""
import os
import sys
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
    assert "replay V1/V2 збитковий" not in text
    assert "B&R-1" in text
    assert "AI Office · №" not in text
    from office_br.card import reminder_text
    assert "TP1 досягнуто" in reminder_text(row, "TP1")
    assert "Mini App" not in reminder_text(row, "ENTRY")
    assert "TP2 досягнуто" in reminder_text(row, "TP2")
    assert "TP3 досягнуто" in reminder_text(row, "TP3")
    assert "Ціну входу торкнуто" in reminder_text(row, "ENTRY")


def test_monitor_marks_only_successful_scan_and_reports_coverage():
    from inspect import getsource
    source = getsource(live.monitor)
    assert source.index("found = await asyncio.to_thread(") < source.index("seen[sym] = ts")
    assert "scan health ok=" in source
    assert "scan_missing += 1" in source and "scan_stale += 1" in source
    assert "scan_errors += 1" in source


def test_br_ui_is_manual_and_has_both_charts():
    page = (Path(__file__).resolve().parents[1] / "office_web" / "br_live.html").read_text(encoding="utf-8")
    assert "chart_a" in page and "chart_b" not in page
    assert "/api/v2/candles" in page and "Binance Futures" in page
    assert "Я відкрила угоду" in page and "Я перенесла SL у BE" in page
    assert "/api/br/manual" in page and "X-Telegram-Init-Data" in page
    assert "Угоду відкрито вручну" in page
    assert "exchange_order" not in page


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
