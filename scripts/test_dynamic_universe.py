#!/usr/bin/env python3
"""Offline: DYNAMIC universe — відбір, спред, утримання, ліміт, відмова мережі, вимкнено за замовчуванням."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office2 import dynamic_universe as D


def sym(n):
    return dict(symbol=n, contractType="PERPETUAL", status="TRADING", quoteAsset="USDT", marginAsset="USDT")


def tk(n, pct, vol=50e6):
    return dict(symbol=n, priceChangePercent=str(pct), quoteVolume=str(vol), lastPrice="1")


def bk(n, bid=1.0, ask=1.0005):
    return dict(symbol=n, bidPrice=str(bid), askPrice=str(ask))


INFO = {"symbols": [sym(x) for x in ("AUSDT", "BUSDT", "CUSDT", "WIDEUSDT", "SMALLUSDT", "BTCUSDT", "NOBOOKUSDT")]}


def test_select_filters():
    tick = [tk("AUSDT", 40), tk("BUSDT", -12), tk("CUSDT", 2), tk("WIDEUSDT", 30), tk("SMALLUSDT", 30, vol=1e6), tk("BTCUSDT", 9), tk("NOBOOKUSDT", 25)]
    book = [bk("AUSDT"), bk("BUSDT"), bk("CUSDT"), bk("WIDEUSDT", 1, 1.01), bk("BTCUSDT")]
    act, log = D.select(INFO, tick, book, ["BTCUSDT"], {})
    assert set(act) == {"AUSDT", "BUSDT"}, act
    assert all(l["action"] == "ADD" and l["reason"] for l in log)


def test_limit_and_hold():
    names = [f"X{i}USDT" for i in range(10)]
    info = {"symbols": [sym(n) for n in names]}
    tick = [tk(n, 10 + i) for i, n in enumerate(names)]
    book = [bk(n) for n in names]
    act, _ = D.select(info, tick, book, [], {}, limit=3)
    assert len(act) == 3 and "X9USDT" in act
    # лідер впав — але утримується до MIN_HOLD_CYCLES
    tick2 = [tk(n, 0.5 if n == "X9USDT" else 10 + i) for i, n in enumerate(names)]
    prev = {k: {**v, "cycles": 0} for k, v in act.items()}
    act2, log2 = D.select(info, tick2, book, [], prev, limit=3)
    assert "X9USDT" in act2 and act2["X9USDT"].get("held")
    prev3 = {k: {**v, "cycles": D.MIN_HOLD_CYCLES} for k, v in act2.items()}
    act3, log3 = D.select(info, tick2, book, [], prev3, limit=3)
    assert "X9USDT" not in act3 and any(l["action"] == "REMOVE" and l["symbol"] == "X9USDT" for l in log3)


def test_refresh_failure_keeps_previous_and_backoff():
    D._STATE.update(active={"AUSDT": {"cycles": 0}}, at=0.0, backoff_until=0.0)
    msgs = []

    def boom():
        raise RuntimeError("429")
    r = D.refresh(None, ["BTCUSDT"], now=10_000.0, fetch=boom, log=msgs.append)
    assert r == ["AUSDT"] and D._STATE["backoff_until"] > 10_000
    assert D.refresh(None, [], now=10_100.0, fetch=boom, log=msgs.append) == ["AUSDT"]
    assert len(msgs) == 1


def test_refresh_cadence():
    D._STATE.update(active={}, at=0.0, backoff_until=0.0)
    calls = []

    def ok():
        calls.append(1)
        return INFO, [tk("AUSDT", 30)], [bk("AUSDT")]
    D.refresh(None, [], now=5_000.0, fetch=ok, log=lambda m: None)
    D.refresh(None, [], now=5_100.0, fetch=ok, log=lambda m: None)
    assert len(calls) == 1 and "AUSDT" in D._STATE["active"]


def test_disabled_by_default():
    os.environ.pop("OFFICE2_DYNAMIC_UNIVERSE", None)
    assert not D.enabled()


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
    print("OK dynamic universe")
