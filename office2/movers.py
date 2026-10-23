"""Read-only Binance USDT-M 24h movers discovery (research/shadow only).

Never produces READY, orders or Telegram messages. The 24h ranking is a
discovery input, NOT a trade direction or an entry trigger.
"""
from __future__ import annotations

import math

BASE = "https://fapi.binance.com"
MIN_QUOTE_VOLUME = 10_000_000.0


def _number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def rank_movers(exchange_info, tickers, *, limit=8, min_quote_volume=MIN_QUOTE_VOLUME):
    """Rank eligible USDT-M perpetuals; return two independently sorted lists.

    ExchangeInfo is authoritative for market eligibility. Do not infer a
    futures listing from a Binance spot/crypto app screenshot.
    """
    eligible = {
        s["symbol"] for s in exchange_info.get("symbols", [])
        if s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING"
        and s.get("quoteAsset") == "USDT"
        and s.get("marginAsset") == "USDT"
        and s.get("symbol", "").endswith("USDT")
    }
    found = []
    for row in tickers:
        symbol = row.get("symbol")
        if symbol not in eligible:
            continue
        change = _number(row.get("priceChangePercent"))
        turnover = _number(row.get("quoteVolume"))
        price = _number(row.get("lastPrice"))
        if change is None or turnover is None or price is None or price <= 0 or turnover < min_quote_volume:
            continue
        found.append({"symbol": symbol, "change_24h_pct": change,
                      "quote_volume_24h": turnover, "last_price": price,
                      "source": "binance_usdtm_futures_24hr",
                      "decision": "WATCH_ONLY", "entry_ready": False})
    gainers = sorted((x for x in found if x["change_24h_pct"] > 0),
                     key=lambda x: (-x["change_24h_pct"], -x["quote_volume_24h"], x["symbol"]))[:limit]
    losers = sorted((x for x in found if x["change_24h_pct"] < 0),
                    key=lambda x: (x["change_24h_pct"], -x["quote_volume_24h"], x["symbol"]))[:limit]
    return {"gainers": gainers, "losers": losers,
            "meaning": "discovery_only_no_trade_signal"}


def _get(path, timeout=8):
    """Share Binance 418/429 backoff, probe lock and weight accounting with the Worker.

    Do not use a separate urllib opener here: it bypasses the global IP-ban
    guard and can keep sending 24hr/exchangeInfo/bookTicker requests while
    the rest of Office is correctly paused. The shared client owns timeout.
    """
    from office_market_data import _http_get_json

    return _http_get_json(BASE + path, {}, scope="movers")


def fetch_movers(*, limit=8, min_quote_volume=MIN_QUOTE_VOLUME, timeout=8):
    """Explicit opt-in read-only call; caller controls cadence/cache and errors."""
    info = _get("/fapi/v1/exchangeInfo", timeout=timeout)
    ticks = _get("/fapi/v1/ticker/24hr", timeout=timeout)
    return rank_movers(info, ticks, limit=limit, min_quote_volume=min_quote_volume)
