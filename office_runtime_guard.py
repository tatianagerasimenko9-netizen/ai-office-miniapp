"""Стійкість worker на Render (512 МБ): видимість пам'яті, повернення її ОС і запас потоків для asyncio.to_thread.

Причини, виявлені у production 06.10: (1) пам'ять працювала на 460–530 МБ із 512 → OOM-рестарти (втрата циклів, повільний старт);
(2) загальний пул потоків asyncio (за замовчуванням ~5) забивався хвилинними REST-проходами старих планів → доставка/lifecycle Office2 стояли в черзі.
Нічого тут не торкається торгової логіки.
"""
from __future__ import annotations

import gc
import os
import threading
import time
from typing import Callable, Optional


def rss_mb() -> Optional[float]:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def trim_memory() -> bool:
    """Повертає ОС вільні сторінки glibc (після великих тимчасових виділень у потоках). На не-glibc — нічого."""
    try:
        import ctypes

        return bool(ctypes.CDLL("libc.so.6").malloc_trim(0))
    except Exception:  # noqa: BLE001
        return False


def start_memory_guard(log: Callable[[str], None] = print, period_sec: float = 60.0, warn_mb: float = 430.0) -> threading.Thread:
    """Раз на хвилину: gc + malloc_trim + рядок [mem] у лог (RSS до/після). Понад warn_mb — додатково gc.collect(2) і попередження."""

    def run() -> None:
        last_line = 0.0
        while True:
            time.sleep(period_sec)
            try:
                before = rss_mb()
                gc.collect()
                trim_memory()
                after = rss_mb()
                now = time.time()
                if (after is not None and after >= warn_mb) or now - last_line >= 300:
                    last_line = now
                    log(f"[mem] rss {before:.0f}→{after:.0f} МБ (ліміт 512){' ⚠ близько до ліміту' if after is not None and after >= warn_mb else ''}, потоків {threading.active_count()}")
            except Exception as exc:  # noqa: BLE001
                log(f"[mem][WARN] {type(exc).__name__}: {exc}")

    t = threading.Thread(target=run, name="mem-guard", daemon=True)
    t.start()
    return t


def default_executor_workers() -> int:
    try:
        return max(8, min(64, int(os.getenv("OFFICE_THREADPOOL_WORKERS", "24"))))
    except ValueError:
        return 24


def start_loop_lag_watchdog(loop, log: Callable[[str], None] = print, threshold_sec: float = 3.0, period_sec: float = 1.0) -> threading.Thread:
    """Сторожовий потік: якщо цикл подій asyncio не відповідає понад threshold_sec — пише в лог стек потоку циклу (хто саме блокує).
    Причина затримок Office2 після рестарту: синхронні мережеві виклики всередині async-задач старого Лева. Викликати З потоку циклу."""
    import sys
    import traceback

    loop_tid = threading.get_ident()

    def run() -> None:
        last_report = 0.0
        while True:
            ev = threading.Event()
            t0 = time.time()
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:
                return
            while not ev.wait(0.25):
                lag = time.time() - t0
                if lag >= threshold_sec and time.time() - last_report >= 30:
                    last_report = time.time()
                    fr = sys._current_frames().get(loop_tid)
                    stack = " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(traceback.extract_stack(fr)[-6:])) if fr else "?"
                    log(f"[loop-lag] цикл подій заблоковано {lag:.1f} с; стек: {stack}")
            time.sleep(period_sec)

    t = threading.Thread(target=run, name="loop-lag", daemon=True)
    t.start()
    return t
