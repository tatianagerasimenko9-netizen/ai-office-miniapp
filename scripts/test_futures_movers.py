#!/usr/bin/env python3
"""Offline regression for futures movers discovery."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office2.movers import rank_movers


def symbol(name, **changes):
    item = dict(symbol=name, contractType="PERPETUAL", status="TRADING",
                quoteAsset="USDT", marginAsset="USDT")
    item.update(changes)
    return item


def ticker(name, pct, vol="15000000", price="1"):
    return dict(symbol=name, priceChangePercent=str(pct), quoteVolume=str(vol), lastPrice=str(price))


def test_filters_and_ranking():
    info = {"symbols": [
        symbol("LUMIAUSDT"), symbol("PYTHUSDT"), symbol("CFXUSDT"),
        symbol("SPOTUSDT", contractType="CURRENT_QUARTER"),
        symbol("HALTEDUSDT", status="BREAK"),
        symbol("LOWVOLUSDT"), symbol("BADUSDT"),
        symbol("ETHUSDC", quoteAsset="USDC", marginAsset="USDC"),
    ]}
    ticks = [
        ticker("LUMIAUSDT", 37.27), ticker("PYTHUSDT", -7.59),
        ticker("CFXUSDT", 19.74), ticker("SPOTUSDT", 90),
        ticker("HALTEDUSDT", -99), ticker("LOWVOLUSDT", 50, vol="1000"),
        ticker("BADUSDT", "NaN"), ticker("ETHUSDC", 45),
        ticker("UNLISTEDUSDT", 200)
    ]
    result = rank_movers(info, ticks)
    assert [x["symbol"] for x in result["gainers"]] == ["LUMIAUSDT", "CFXUSDT"], result
    assert [x["symbol"] for x in result["losers"]] == ["PYTHUSDT"], result
    assert all(not x["entry_ready"] and x["decision"] == "WATCH_ONLY"
               for side in ("gainers", "losers") for x in result[side])
    assert result["meaning"] == "discovery_only_no_trade_signal"
    assert len(rank_movers(info, ticks, limit=1)["gainers"]) == 1


if __name__ == "__main__":
    test_filters_and_ranking()
    print("PASS: futures movers eligibility, liquidity, rank and shadow-only")
