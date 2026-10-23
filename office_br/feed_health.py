"""B&R feed health transition policy. Never infer signals from missing bars."""
from __future__ import annotations

class FeedHealth:
    def __init__(self, outage_cycles: int = 3):
        if outage_cycles < 1:
            raise ValueError("outage_cycles must be positive")
        self.outage_cycles = outage_cycles
        self.zero_streak = 0
        self.partial_streak = 0
        self.alerted = False
        self.partial_alerted = False

    def observe(self, ok: int, total: int) -> str | None:
        """Returns OUTAGE once, RECOVERED once, otherwise None.

        Does not notify about legitimate zero-signal cycles with healthy data.
        """
        if total <= 0 or ok < 0 or ok > total:
            return None
        if ok == 0:
            self.partial_streak = 0
            self.zero_streak += 1
            if self.zero_streak >= self.outage_cycles and not self.alerted:
                self.alerted = True
                return "OUTAGE"
            return None
        self.zero_streak = 0
        if ok < total:
            self.partial_streak += 1
            if self.partial_streak >= self.outage_cycles and not self.alerted and not self.partial_alerted:
                self.partial_alerted = True
                return "DEGRADED"
            return None
        self.partial_streak = 0
        if self.partial_alerted:
            self.partial_alerted = False
            self.alerted = False
            return "RECOVERED"
        if self.alerted and ok == total:
            self.alerted = False
            return "RECOVERED"
        return None
