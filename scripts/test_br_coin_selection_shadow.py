"""Fail-closed tests for research coin-selection screen."""
from office_br.coin_selection_shadow import screen

def test_rejects_missing_data():
    assert screen({"symbol":"AGTUSDT"})["decision"]=="REJECT"

def test_watch_before_breakout():
    s={"symbol":"QUSDT","quote_volume_usdt_24h":10_000_000,
       "spread_bps":5,"closed_m15_candles":240,"atr_pct":2.0,
       "extension_atr":1.0,"fresh_closed_m15":True,
       "closed_breakout":False,"confirmed_retest":False}
    assert screen(s)["decision"]=="WATCH_LEVEL"
    s["closed_breakout"]=True
    assert screen(s)["decision"]=="WATCH_RETEST"
    s["confirmed_retest"]=True
    assert screen(s)["decision"]=="CANDIDATE_CONFIRMED"
    s["fresh_closed_m15"]=False
    assert screen(s)["decision"]=="REJECT"

if __name__=="__main__":
    test_rejects_missing_data()
    test_watch_before_breakout()
    print("OK")
