import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.ltf_confirmation import evaluate

ASOF = 86400
SIGNAL = {"direction": "LONG", "level": 100}

def candles(symbol, tf, limit, closed_only):
    assert closed_only
    step = 300 if tf == "5m" else 60
    return [{"ts": ASOF - step*(i+1), "open": 101, "high": 104,
             "low": 100, "close": 103} for i in reversed(range(5))]

def test_confirmed():
    assert evaluate("ETHUSDT", SIGNAL, ASOF, candles)["status"] == "CONFIRMED"

def test_future_candles_have_no_effect():
    def future(*args, **kwargs):
        return candles(*args, **kwargs) + [{"ts": ASOF + 60, "open": 1,
                                           "high": 999, "low": 1, "close": 999}]
    assert evaluate("ETHUSDT", SIGNAL, ASOF, candles) == evaluate("ETHUSDT", SIGNAL, ASOF, future)

def test_missing_m1_unknown():
    def missing(symbol, tf, limit, closed_only):
        return [] if tf == "1m" else candles(symbol, tf, limit, closed_only)
    assert evaluate("ETHUSDT", SIGNAL, ASOF, missing)["status"] == "UNKNOWN"

def test_opposing_m1_not_confirmed():
    def opposing(symbol, tf, limit, closed_only):
        rows = candles(symbol, tf, limit, closed_only)
        if tf == "1m":
            rows[-1] = dict(rows[-1], open=103, close=101)
        return rows
    assert evaluate("ETHUSDT", SIGNAL, ASOF, opposing)["status"] == "NOT_CONFIRMED"

def test_short_confirmation():
    def short(symbol, tf, limit, closed_only):
        return [dict(r, open=99, high=100, low=96, close=97)
                for r in candles(symbol, tf, limit, closed_only)]
    assert evaluate("ETHUSDT", {"direction": "SHORT", "level": 100}, ASOF, short)["status"] == "CONFIRMED"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")
