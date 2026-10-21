"""Незалежний трекер звірки (scripts/recon_vs_exchange.py): правила входу/SL/TP/EXPIRED на контрольних хвилинах."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recon_vs_exchange as R

T = [0, 60, 120, 180, 240]


def p(d, entry, sl, tp1, tp2, tp3=None, conf=0, valid=1000):
    return ("x", "S", d, entry, sl, tp1, tp2, tp3, conf, valid, 1)


def test_long_entry_tp1_tp2():
    assert R.track(p("LONG", 10.5, 9.5, 11.5, 12.5), T, [10, 11, 12, 13, 14], [9, 10, 11, 12, 13]) == {"ENTRY": 60.0, "TP1": 120.0, "TP2": 180.0}


def test_sl_before_entry_is_not_a_stop():
    out = R.track(p("LONG", 10.5, 9.5, 11.5, 12.5), T, [10, 10, 11, 11, 11], [9, 9, 9, 9, 9])   # хвилина 0: діапазон 9–10 не містить 10.5; low ≤ SL але входу ще немає
    assert "SL" not in out or "ENTRY" in out


def test_same_minute_entry_and_sl_is_sl():
    out = R.track(p("LONG", 10.5, 9.5, 11.5, 12.5), [0], [11], [9])
    assert out == {"ENTRY": 0.0, "SL": 0.0}


def test_short_mirror_and_stop_ends_scenario():
    out = R.track(p("SHORT", 10.5, 11.5, 9.5, 8.5), T, [11, 11, 12, 12, 12], [10, 10, 10, 10, 10])
    assert out.get("ENTRY") == 0.0 and out.get("SL") == 120.0 and "TP1" not in out


def test_candle_before_ready_ignored_and_expiry():
    out = R.track(p("LONG", 10.5, 9.5, 11.5, 12.5, conf=100, valid=200), T, [10, 11, 12, 13, 14], [20, 20, 20, 20, 20])
    assert out == {"EXPIRED": 200}


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
    print("OK")
