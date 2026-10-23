"""Bounded B&R Futures universe scheduler.

Disabled unless BR_LIVE_DYNAMIC_UNIVERSE=1. No spot fallback, no parallel
historical REST fanout and no calls while Binance has a hard backoff.
"""
from __future__ import annotations
import os
import time
from office_br.universe import eligible_symbols, rotate

class Scheduler:
    def __init__(self, refresh_s: int = 21600):
        self.refresh_s = refresh_s
        self.last_refresh = 0.
        self.universe: tuple[str, ...] = ()
        self.cursor = 0

    def batch(self, fetch_exchange, *, now: float | None = None,
              hard_backoff: float = 0.) -> tuple[str, ...]:
        now = time.time() if now is None else now
        if hard_backoff > 0:
            return ()
        if not self.universe or now - self.last_refresh >= self.refresh_s:
            try:
                fresh = eligible_symbols(fetch_exchange())
            except Exception:
                return ()  # Never substitute the hardcoded 12 when discovery fails.
            self.universe = fresh
            self.last_refresh = now
        budget = max(1, min(int(os.getenv("BR_LIVE_DYNAMIC_BATCH", "4")), 12))
        batch, self.cursor = rotate(self.universe, self.cursor, budget)
        return batch
