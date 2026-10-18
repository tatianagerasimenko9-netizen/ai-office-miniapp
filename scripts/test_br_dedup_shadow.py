import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.dedup_shadow import duplicate_idea

C = {"symbol":"ETHUSDT","direction":"SHORT","confirm_ts":5000,
     "level":2400,"atr":10}
P = {"sig_id":"old","symbol":"ETHUSDT","direction":"SHORT",
     "confirm_ts":4800,"level":2403}


def test_same_idea():
    assert duplicate_idea(C,[P])["duplicate"]


def test_different_direction_or_symbol():
    assert not duplicate_idea(C,[dict(P,direction="LONG")])["duplicate"]
    assert not duplicate_idea(C,[dict(P,symbol="BTCUSDT")])["duplicate"]


def test_no_future_or_old_event():
    assert not duplicate_idea(C,[dict(P,confirm_ts=5001)])["duplicate"]
    assert not duplicate_idea(C,[dict(P,confirm_ts=100)])["duplicate"]


def test_missing_atr_is_not_pass():
    x=duplicate_idea(dict(C,atr=0),[P])
    assert not x["valid"] and x["mode"]=="SHADOW_ONLY"


if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("OK")
