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

# Curated priority is a *subset*, not a fixed market universe.
PRIORITY = ("BTCUSDT", "ETHUSDT", "XAUUSDT", "CLUSDT", "BZUSDT", "NATGASUSDT")

def rotate(universe: tuple[str, ...], cursor: int, size: int,
           priority: tuple[str, ...] = PRIORITY) -> tuple[tuple[str, ...], int]:
    """Fair rotation, with energy/metals in every batch if listed.

    Bounded calls per cycle rather than loading every symbol in parallel.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    items = tuple(dict.fromkeys(universe))
    if not items:
        return (), 0
    # Reserve at least half the budget for discovery/rotation even for tiny batches.
    pin_budget = min(len(priority), max(1, size // 2)) if size > 1 else 0
    available_priority = tuple(p for p in priority if p in items)
    pinned = tuple(available_priority[(cursor + i) % len(available_priority)] for i in range(pin_budget)) if available_priority else ()
    remaining = tuple(x for x in items if x not in pinned)
    slots = size - len(pinned)
    if not remaining or slots <= 0:
        return pinned, 0
    start = cursor % len(remaining)
    chosen = tuple(remaining[(start + k) % len(remaining)] for k in range(min(slots, len(remaining))))
    return pinned + chosen, (start + len(chosen)) % len(remaining)
