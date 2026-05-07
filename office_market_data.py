from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Union
from urllib.parse import urlencode
from urllib.request import urlopen


JSONLike = Union[Dict[str, Any], List[Any]]


def _http_get_json(url: str, params: Dict[str, Any]) -> JSONLike:
    qs = urlencode(params)
    full_url = f"{url}?{qs}" if qs else url
    with urlopen(full_url, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def fetch_btc_candles(tf: str, limit: int = 3) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetch BTCUSDT futures candles from Binance.
    Returns list of candles or {} on failure.
    """
    try:
        data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/klines",
            {"symbol": "BTCUSDT", "interval": tf, "limit": int(limit)},
        )
        out: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            return {}
        for row in data:
            if not isinstance(row, list) or len(row) < 6:
                continue
            ts_ms = int(row[0])
            ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()
            out.append(
                {
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "ts": ts,
                }
            )
        return out
    except Exception:
        return {}


def fetch_open_interest(symbol: str) -> Dict[str, Any]:
    """
    Fetch current OI and recent 1h OI history.
    Returns {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}

        now_data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/openInterest",
            {"symbol": sym},
        )
        hist_data = _http_get_json(
            "https://fapi.binance.com/futures/data/openInterestHist",
            {"symbol": sym, "period": "1h", "limit": 4},
        )

        oi_now = float((now_data or {}).get("openInterest") or 0.0) if isinstance(now_data, dict) else 0.0
        hist: List[Dict[str, Any]] = []
        if isinstance(hist_data, list):
            for item in hist_data:
                if not isinstance(item, dict):
                    continue
                oi_val = float(item.get("sumOpenInterestValue") or item.get("sumOpenInterest") or 0.0)
                ts_ms = int(item.get("timestamp") or 0)
                ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat() if ts_ms > 0 else ""
                hist.append({"oi": oi_val, "timestamp": ts})

        return {
            "oi": oi_now,
            "symbol": sym,
            "history": hist,
        }
    except Exception:
        return {}


def fetch_liquidations_proxy(symbol: str) -> Dict[str, Any]:
    """
    Proxy liquidation zones from 24h high/low and current price.
    Returns {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            {"symbol": sym},
        )
        if not isinstance(data, dict):
            return {}
        high_24h = float(data.get("highPrice") or 0.0)
        low_24h = float(data.get("lowPrice") or 0.0)
        current_price = float(data.get("lastPrice") or 0.0)
        return {
            "liq_zone_above": high_24h * 1.002,
            "liq_zone_below": low_24h * 0.998,
            "current_price": current_price,
        }
    except Exception:
        return {}
