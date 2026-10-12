#!/usr/bin/env python3
"""Кеш старших ТФ Feed не має ховати щойно ЗАКРИТИЙ бар: після закриття D1/H4/W1/M бару наступний запит мусить повернути його (а не старий кеш до кінця TTL).
Також: незакритий (формується) бар ніколи не потрапляє в масив; ТФ 15m не кешується."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office2.live as L  # noqa: E402

W = {"15m": 900, "4h": 14400, "1d": 86400, "1w": 604800}
bad = []


def check(n, c):
    if not c:
        bad.append(n)
        print("FAIL", n)


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def month_starts(t0, t1):
    out, y, m = [], 2026, 1
    while True:
        s = utc(y, m, 1)
        if s > t1:
            break
        if s >= t0:
            out.append(s)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


class Exchange:
    """Мінімальна модель klines: повертає всі бари з open ≤ clock (включно з тим, що формується) — як Binance."""
    def __init__(self):
        self.clock = 0.0
        self.calls = 0

    def get(self, url, params):
        self.calls += 1
        tf = params["interval"]
        lim = int(params.get("limit", 500))
        if tf == "1M":
            starts = month_starts(utc(2025, 1, 1), self.clock)
            ends = [utc(s_.year, s_.month + 1, 1) if (s_ := datetime.fromtimestamp(s, timezone.utc)).month < 12 else utc(s_.year + 1, 1, 1) for s in starts]
        else:
            w = W[tf]
            first = int(utc(2025, 1, 6)) if tf == "1w" else int(utc(2025, 1, 6) // w) * w     # Binance: тижневі бари відкриваються в понеділок 00:00 UTC (2025-01-06)
            n = int((self.clock - first) // w) + 1
            starts = [first + i * w for i in range(n)]
            ends = [s + w for s in starts]
        rows = [[s * 1000, "1", "2", "0.5", "1.5", "10", int(e * 1000 - 1), "0", "0", "5"] for s, e in zip(starts, ends)]
        return rows[-lim:]


ex = Exchange()
feed = L.Feed(getter=ex.get, pause=0)
SYM = "XUSDT"

# D1: об 23:45 останній закритий — вчорашній; об 00:00 нового дня має з'явитись щойно закритий
ex.clock = utc(2026, 10, 11, 23, 45)
d1_a = feed.klines(SYM, "1d", ex.clock)
last_a = float(d1_a["t"][-1])
check("D1 23:45: останній закритий бар — 10.10", last_a == utc(2026, 10, 10))
ex.clock = utc(2026, 10, 12, 0, 0)
d1_b = feed.klines(SYM, "1d", ex.clock)
check("D1 00:00: щойно закритий бар 11.10 присутній (кеш не застарілий)", float(d1_b["t"][-1]) == utc(2026, 10, 11))
# незакритий бар не потрапляє
check("D1: бар, що формується (12.10), відсутній", float(d1_b["t"][-1]) < utc(2026, 10, 12))

# повторний виклик у межах того ж інтервалу — з кешу (без нового запиту)
calls = ex.calls
ex.clock = utc(2026, 10, 12, 0, 15)
feed.klines(SYM, "1d", ex.clock)
check("D1 00:15: кеш діє (бару більше не закрилось)", ex.calls == calls)

# H4: 23:15 → 00:00
ex.clock = utc(2026, 10, 11, 23, 15)
h4_a = feed.klines(SYM, "4h", ex.clock)
check("H4 23:15: останній закритий 16:00–20:00", float(h4_a["t"][-1]) == utc(2026, 10, 11, 16))
ex.clock = utc(2026, 10, 12, 0, 0)
h4_b = feed.klines(SYM, "4h", ex.clock)
check("H4 00:00: бар 20:00–24:00 присутній", float(h4_b["t"][-1]) == utc(2026, 10, 11, 20))

# W1: неділя 23:45 → понеділок 00:00 (2026-10-12 — понеділок)
ex.clock = utc(2026, 10, 11, 23, 45)
w1_a = feed.klines(SYM, "1w", ex.clock)
ex.clock = utc(2026, 10, 12, 0, 0)
w1_b = feed.klines(SYM, "1w", ex.clock)
check("W1: після закриття тижня з'являється новий бар", float(w1_b["t"][-1]) > float(w1_a["t"][-1]))

# Місяць: 30.09 23:45 → 01.10 00:00
ex.clock = utc(2026, 9, 30, 23, 45)
m_a = feed.klines(SYM, "1M", ex.clock)
ex.clock = utc(2026, 10, 1, 0, 0)
m_b = feed.klines(SYM, "1M", ex.clock)
check("1M: після закриття місяця з'являється новий бар", float(m_b["t"][-1]) > float(m_a["t"][-1]))

# next_bar_close_after: логіка меж
check("next_close D1", L.next_bar_close_after("1d", {"t": __import__("numpy").array([utc(2026, 10, 11)])}) == utc(2026, 10, 13))
check("невідомий ТФ → лише TTL", L.next_bar_close_after("3d", {"t": __import__("numpy").array([1.0])}) == float("inf"))
print("OK" if not bad else f"FAIL {bad}")
sys.exit(1 if bad else 0)
