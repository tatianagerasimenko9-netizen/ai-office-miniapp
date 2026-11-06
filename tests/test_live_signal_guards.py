from office2.live_signal_guards import (
    allow_lifecycle_event,
    public_outcome_label,
    verified_futures_candle,
)


def test_futures_source_and_closed_bar():
    bar = dict(source="binance_futures_ws", market="um_futures", ts=900, open=10, high=11, low=9, close=10.5)
    assert verified_futures_candle(bar, decision_ts=960, interval_sec=60)
    assert not verified_futures_candle({**bar, "source": "binance_spot_vision"}, decision_ts=960, interval_sec=60)
    assert not verified_futures_candle(bar, decision_ts=950, interval_sec=60)
    assert not verified_futures_candle(bar, decision_ts=1100, interval_sec=60)
    assert not verified_futures_candle({**bar, "high": 9}, decision_ts=960, interval_sec=60)


def test_no_profit_without_entry():
    card = {"state": "INVALIDATED", "entry_confirmed": False}
    assert not allow_lifecycle_event(card, "TP1")
    assert not allow_lifecycle_event(card, "CONFIRMED_ENTRY")
    assert "не нараховано" in public_outcome_label(card, "TP2")


def test_confirmed_paper_still_not_real_profit():
    card = {"state": "ENTERED", "entry_confirmed": True, "execution_mode": "PAPER"}
    assert allow_lifecycle_event(card, "TP1")
    assert "симуляція" in public_outcome_label(card, "TP1")
