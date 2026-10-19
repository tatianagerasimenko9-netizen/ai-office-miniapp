"""Read-only Binance USD-M Futures historical M1 candles, paginated by time.

Public market-data endpoint only. No API keys, orders or DB writes.
Network use is explicit through fetch_url injection or CLI caller.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen
from typing import Any, Callable

BASE = "https://fapi.binance.com/fapi/v1/klines"
MAX_LIMIT = 1000
MAX_CANDLES = 2880  # at most 48h for one B&R signal


def fetch_m1(symbol: str, eligible_ts: float, end_ts: float,
             *, fetch_url: Callable[[str], Any] | None = None) -> list[dict[str, float]]:
    if not symbol.endswith("USDT") or not symbol.replace("USDT", "").isalnum():
        raise ValueError("invalid USD-M symbol")
    if end_ts <= eligible_ts or end_ts-eligible_ts > MAX_CANDLES*60:
        raise ValueError("invalid replay window (max 48h)")
    if eligible_ts % 60 or end_ts % 60:
        raise ValueError("timestamps must align to M1 opens")
    def request(url: str) -> Any:
        if fetch_url is not None:
            return fetch_url(url)
        with urlopen(url, timeout=15) as response:
            return json.load(response)
    output = []
    next_ms = int(eligible_ts * 1000)
    end_ms = int(end_ts * 1000)
    while next_ms < end_ms:
        limit = min(MAX_LIMIT, (end_ms-next_ms)//60000)
        url = BASE+"?"+urlencode({"symbol":symbol,"interval":"1m",
                                  "startTime":next_ms,"endTime":end_ms-1,
                                  "limit":limit})
        payload = request(url)
        if not isinstance(payload, list) or not payload:
            break
        last_ms = next_ms-60000
        for row in payload:
            ts_ms = int(row[0])
            if ts_ms < next_ms or ts_ms >= end_ms:
                continue
            if ts_ms <= last_ms:
                raise ValueError("unordered or duplicate M1 response")
            output.append({"ts":ts_ms/1000,"open":float(row[1]),"high":float(row[2]),
                           "low":float(row[3]),"close":float(row[4])})
            last_ms = ts_ms
        if last_ms < next_ms:
            break
        next_ms = last_ms+60000
    return output
