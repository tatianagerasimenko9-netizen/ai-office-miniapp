"""Стійкість worker на Render (512 МБ): видимість пам'яті, повернення її ОС і запас потоків для asyncio.to_thread.

Причини, виявлені у production 06.10: (1) пам'ять працювала на 460–530 МБ із 512 → OOM-рестарти (втрата циклів, повільний старт);
(2) загальний пул потоків asyncio (за замовчуванням ~5) забивався хвилинними REST-проходами старих планів → доставка/lifecycle Office2 стояли в черзі.
Нічого тут не торкається торгової логіки.
"""
from __future__ import annotations

import contextlib
import gc
import os
import threading
import time
from typing import Any, Callable, Dict, Iterator, Optional


def rss_mb() -> Optional[float]:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def rss_hwm_mb() -> Optional[float]:
    """Пік RSS процесу від старту (VmHWM) — те, що бачить OOM-killer."""
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


# --- Вимірювання: які структури та етапи тримають пам'ять (RSS процесний, тому етапи, що йдуть паралельно, перекриваються) ---
_PROBES: Dict[str, Callable[[], Any]] = {}
_STAGES: Dict[str, Dict[str, float]] = {}
_STAGE_LOCK = threading.Lock()


def register_probe(name: str, fn: Callable[[], Any]) -> None:
    """Реєструє дешеву функцію, що повертає розмір структури (кількість записів / оцінка МБ). Викликається раз на 5 хв."""
    _PROBES[name] = fn


def probe_report() -> str:
    out = []
    for name, fn in sorted(_PROBES.items()):
        try:
            out.append(f"{name}={fn()}")
        except Exception as exc:  # noqa: BLE001
            out.append(f"{name}=ERR:{type(exc).__name__}")
    return "; ".join(out)


@contextlib.contextmanager
def stage(name: str) -> Iterator[None]:
    """Позначає етап циклу: RSS на вході/виході, найбільший приріст і найвищий RSS на виході. Нічого не змінює в логіці."""
    before = rss_mb() or 0.0
    t0 = time.time()
    try:
        yield
    finally:
        after = rss_mb() or 0.0
        with _STAGE_LOCK:
            st = _STAGES.setdefault(name, {"n": 0.0, "max_delta": 0.0, "max_rss": 0.0, "last_rss": 0.0, "max_s": 0.0})
            st["n"] += 1
            st["max_delta"] = max(st["max_delta"], after - before)
            st["max_rss"] = max(st["max_rss"], after)
            st["last_rss"] = after
            st["max_s"] = max(st["max_s"], time.time() - t0)


def stage_report(reset: bool = True) -> str:
    with _STAGE_LOCK:
        items = sorted(_STAGES.items(), key=lambda kv: -kv[1]["max_delta"])
        txt = "; ".join(f"{k}: n={int(v['n'])} Δmax={v['max_delta']:+.0f} rssmax={v['max_rss']:.0f} t≤{v['max_s']:.0f}с" for k, v in items)
        if reset:
            _STAGES.clear()
    return txt


def register_default_probes() -> None:
    """Розміри відомих module-level структур, які можуть рости (кількість записів). Імпорти ліниві: відсутній модуль просто пропускається."""
    def _len(mod: str, attr: str) -> Callable[[], Any]:
        def f() -> Any:
            import sys

            m = sys.modules.get(mod)          # лише вже завантажений модуль: проба ніколи не імпортує нічого нового
            return len(getattr(m, attr)) if m is not None else "не завантажено"
        return f

    for name, mod, attr in (("bridge.sig_cache", "office_bridge", "_SIG_CACHE"), ("bridge.pg_pool", "office_bridge", "_PG_POOL"),
                            ("track.bar_memo", "office_signal_track", "_BAR_MEMO"), ("track.ms_done", "office_signal_track", "_MS_DONE"),
                            ("journal.last_raw", "office_thesis_journal", "_LAST_RAW"), ("liq.events_symbols", "office_liq_map", "_EVENTS"),
                            ("ticker.symbols", "office_ws_ticker", "_TICK"), ("relay.chat_history", "office_relay_wizard", "_chat_history"),
                            ("market.depth_cache", "office_market_data", "_DEPTH_CACHE"), ("market.callers", "office_market_data", "_CALLERS")):
        register_probe(name, _len(mod, attr))
    register_probe("gc_objects", lambda: len(gc.get_objects()))
    register_probe("threads", lambda: threading.active_count())


def trim_memory() -> bool:
    """Повертає ОС вільні сторінки glibc (після великих тимчасових виділень у потоках). На не-glibc — нічого."""
    try:
        import ctypes

        return bool(ctypes.CDLL("libc.so.6").malloc_trim(0))
    except Exception:  # noqa: BLE001
        return False


def start_memory_guard(log: Callable[[str], None] = print, period_sec: float = 60.0, warn_mb: float = 430.0) -> threading.Thread:
    """Раз на хвилину: gc + malloc_trim + рядок [mem] у лог (RSS до/після). Понад warn_mb — додатково gc.collect(2) і попередження."""

    try:
        register_default_probes()
    except Exception:  # noqa: BLE001
        pass

    def run() -> None:
        last_line = 0.0
        last_detail = 0.0
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
                if now - last_detail >= 300:
                    last_detail = now
                    hwm = rss_hwm_mb()
                    log(f"[mem][detail] пік {hwm:.0f} МБ" if hwm is not None else "[mem][detail] пік н/д")
                    log(f"[mem][components] {probe_report()}")
                    log(f"[mem][stages] {stage_report(reset=True)}")
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
