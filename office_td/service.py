"""Фоновий потік TD-V1 для сервісу Mini App (web): рахує кандидатів H1 і M15-підтвердження та ПИШЕ сигнали в спільну БД.
Доставку в Telegram і супровід (ENTRY/TP/SL) робить існуючий контур B&R у Worker (office_br.live) — без важких обчислень у Worker (512 МБ).
Вимкнути: TD_LIVE=0."""
from __future__ import annotations

import os
import threading
import time


def _run(db: str, period_s: float = 45.0) -> None:
    from office_market_data import fetch_candles_futures
    from office_br import store
    from office_td import live
    time.sleep(30)
    try:
        store.init(db); live.init(db); live.model()
        print(f"[td] сервіс запущено: модель {len(live.model().trees)} дерев, поріг {live.model().threshold:.3f}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[td] ІНІЦІАЛІЗАЦІЯ НЕ ВДАЛАСЬ, TD-V1 не працює: {type(exc).__name__}: {exc}", flush=True)
        return
    while True:
        try:
            res = live.cycle(db, fetch_candles_futures)
            if res.get("candidates") or res.get("signals"):
                print(f"[td] cycle {res}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[td] cycle: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(period_s)


def start(db: str) -> bool:
    from office_td import live
    if not live.enabled():
        print("[td] вимкнено (TD_LIVE=0)", flush=True); return False
    if not live.MODEL_PATH.exists():
        print(f"[td] немає {live.MODEL_PATH.name}: TD-V1 не запускається", flush=True); return False
    threading.Thread(target=_run, args=(db,), daemon=True, name="td-v1").start()
    return True
