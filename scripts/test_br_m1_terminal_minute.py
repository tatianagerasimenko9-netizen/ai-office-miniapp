"""Independent M1 replay must reconcile terminal candle time, not just label."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.ledger_m1_compare import compare

def test_same_sl_different_minute_is_not_match():
    t = 1800000000.0
    signal = {"sig_id":"a", "confirm_ts":t-900, "direction":"LONG",
              "entry":100.0, "sl":99.0, "targets":[{"p":101.0},{"p":102.0},{"p":103.0}]}
    candles = [{"ts":t,"open":100,"high":100.5,"low":99.5,"close":100},
               {"ts":t+60,"open":100,"high":100.2,"low":98.5,"close":99}]
    correct = [{"sig_id":"a","level":"SL","touched_ts":t+60}]
    wrong = [{"sig_id":"a","level":"SL","touched_ts":t}]
    assert compare(signal,correct,candles,expected_end_ts=t+120)["verdict"] == "MATCH"
    assert compare(signal,wrong,candles,expected_end_ts=t+120)["verdict"] == "MISMATCH_TIME"

if __name__ == "__main__":
    test_same_sl_different_minute_is_not_match()
    print("ok test_same_sl_different_minute_is_not_match")
