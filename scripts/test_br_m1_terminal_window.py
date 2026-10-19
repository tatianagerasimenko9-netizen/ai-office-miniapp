"""Regression: terminal M1 replay must not request candles beyond terminal touch."""
import json
from office_br.m1_batch_replay import run


def test_terminal_window_ends_after_terminal_minute():
    eligible = 1800000000.0  # minute-aligned
    assert eligible % 60 == 0
    calls = []
    def fetch(symbol, start, end):
        calls.append((symbol, start, end))
        return [{"ts": float(t), "open": 100., "high": 101., "low": 99., "close": 100.}
                for t in range(int(start), int(end), 60)]
    signal = {"sig_id": "s1", "symbol": "BTCUSDT", "direction": "LONG",
              "confirm_ts": eligible - 900, "entry": 100., "sl": 99.,
              "targets_json": json.dumps([{"p": 101.}, {"p": 102.}, {"p": 103.}]),
              "status": "SL"}
    events = [{"sig_id": "s1", "level": "SL", "touched_ts": eligible + 120}]
    result = run([signal], events, fetch=fetch)
    assert calls == [("BTCUSDT", eligible, eligible + 180)]
    assert result["summary"]["total"] == 1
    assert result["results"][0]["verdict"] != "M1_DATA_INCOMPLETE"


def test_unresolved_still_requires_full_horizon():
    eligible = 1800000000.0
    calls = []
    def fetch(symbol, start, end):
        calls.append((start, end))
        return []
    signal = {"sig_id": "s2", "symbol": "BTCUSDT", "direction": "LONG",
              "confirm_ts": eligible - 900, "entry": 100., "sl": 99.,
              "targets_json": "[]", "status": "TIMEOUT"}
    result = run([signal], [], fetch=fetch)
    assert calls == [(eligible, eligible + 48 * 3600)]
    assert result["results"][0]["verdict"] == "M1_DATA_INCOMPLETE"
