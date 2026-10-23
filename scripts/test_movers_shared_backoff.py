#!/usr/bin/env python3
"""Offline regression: movers discovery cannot bypass the shared Binance IP ban."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import office_market_data as market
from office2 import movers


class Response:
    headers = {}

    def read(self):
        return b'[]'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def main():
    calls = []
    original_urlopen = market.urlopen
    original_pace = market._pace_fapi
    old_backoff = market._BACKOFF_UNTIL
    old_soft = market._SOFT_UNTIL
    old_probe = market._NEED_PROBE

    def fake_urlopen(request, timeout=0):
        calls.append(request.full_url)
        return Response()

    try:
        market.urlopen = fake_urlopen
        market._pace_fapi = lambda *args, **kwargs: None
        market._BACKOFF_UNTIL = time.time() + 3600
        market._SOFT_UNTIL = 0
        market._NEED_PROBE = False

        try:
            movers._get("/fapi/v1/ticker/24hr")
        except market.RateLimited as exc:
            assert exc.retry_after > 3500, exc.retry_after
        else:
            raise AssertionError("movers bypassed Binance 418/429 backoff")
        assert not calls, f"unexpected Binance requests during IP ban: {calls}"

        market._BACKOFF_UNTIL = 0
        assert movers._get("/fapi/v1/ticker/24hr") == []
        assert calls == ["https://fapi.binance.com/fapi/v1/ticker/24hr"], calls
        print("PASS: movers honors shared backoff and resumes through shared client")
    finally:
        market.urlopen = original_urlopen
        market._pace_fapi = original_pace
        market._BACKOFF_UNTIL = old_backoff
        market._SOFT_UNTIL = old_soft
        market._NEED_PROBE = old_probe


if __name__ == "__main__":
    main()
