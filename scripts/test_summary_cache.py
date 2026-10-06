#!/usr/bin/env python3
"""/api/summary = health-check Render (5 с): HTTP не чекає на повільну БД, якщо є кеш; без кешу рахує синхронно; фонове оновлення single-flight."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_mini_app as M  # noqa: E402


def test_cache_fast_and_single_flight():
    calls = []
    delay = {"s": 0.0}

    def fake_get_data(**kw):
        calls.append(time.time())
        time.sleep(delay["s"])
        return {"now_utc": "x", "n": len(calls), "desk_state": {}, "db_identity": {}}

    orig = M.get_data
    M.get_data = fake_get_data
    M._SUMMARY_CACHE.clear()
    try:
        key = ("", "", "", "", "summary")
        b1 = M.summary_body(key)                     # холодний: синхронно
        assert b1 and len(calls) == 1
        M._SUMMARY_CACHE[key]["ts"] -= 10            # застаріло, але в межах MAX_STALE
        delay["s"] = 2.0                             # БД «зависла»
        t0 = time.time()
        bodies = [M.summary_body(key) for _ in range(5)]
        assert time.time() - t0 < 0.5, "HTTP не повинен чекати на БД"
        assert all(b == b1 for b in bodies)
        time.sleep(2.4)
        assert len(calls) == 2, calls                # одне фонове оновлення, не п'ять
        assert M.summary_body(key) != b1             # кеш оновився
        M._SUMMARY_CACHE[key]["ts"] -= 1000          # дуже старе → синхронно
        delay["s"] = 0.0
        assert M.summary_body(key)
        k2 = ("x", "", "", "", "office_state")
        assert b'"desk_state"' in M.summary_body(k2) and b'"n"' not in M.summary_body(k2)
    finally:
        M.get_data = orig
        M._SUMMARY_CACHE.clear()


def main():
    test_cache_fast_and_single_flight()
    print("ok test_cache_fast_and_single_flight")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
