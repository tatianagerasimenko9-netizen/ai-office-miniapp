"""Binance USDⓈ-M Futures universe extraction (read-only).

Caller fetches /fapi/v1/exchangeInfo with caching and request budgets.
Fail closed on malformed responses; never silently substitute spot symbols.
"""
from __future__ import annotations

def eligible_symbols(exchange_info: dict) -> tuple[str, ...]:
    if not isinstance(exchange_info, dict) or not isinstance(exchange_info.get("symbols"), list):
        raise ValueError("invalid futures exchangeInfo")
    result = set()
    for item in exchange_info["symbols"]:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if (isinstance(symbol, str) and item.get("status") == "TRADING"
                and item.get("contractType") == "PERPETUAL"
                and item.get("quoteAsset") == "USDT"
                and item.get("marginAsset") == "USDT"):
            result.add(symbol)
    if not result:
        raise ValueError("empty futures universe; do not fall back to 12-symbol list")
    return tuple(sorted(result))
