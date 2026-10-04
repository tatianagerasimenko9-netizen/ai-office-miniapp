"""Ринок на момент сигналу з реальних свічок: перевага ринку, монета проти BTC, Weekly/Monthly структура, час до закриття.

Тонка обгортка над чистими office_market_bias / office_time_structure. Свічки — office_market_data.fetch_candles (ф'ючерси Binance, кеш);
кошик великих монет і BTC/ETH кешуємо на 5 хв, щоб не навантажувати ліміти. Будь-який збій → порожній результат
(рядки «Ринок» просто не з'являються — нічого не вигадуємо). Лише інформація, на сигнали не впливає.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

import office_market_bias as mb
import office_time_structure as tstruct

TTL_SEC = 300.0
_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"at": 0.0, "v": None}


def _c(sym: str, tf: str, n: int) -> List[Dict[str, Any]]:
    from office_market_data import fetch_candles

    r = fetch_candles(sym, tf, n)
    return r if isinstance(r, list) else []


def _fresh(rows: List[Dict[str, Any]], now: float, tf_sec: int) -> bool:
    try:
        from datetime import datetime

        t = datetime.fromisoformat(str(rows[-1]["ts"]).replace("Z", "+00:00")).timestamp()
        return now - t <= tf_sec * 3
    except Exception:  # noqa: BLE001
        return False


def build_market(now: Optional[float] = None, *, force: bool = False) -> Dict[str, Any]:
    """Спільна частина для всіх сигналів: BTC/ETH/кошик (15m), BTC на тижневих/місячних відкриттях (1d, 1h)."""
    now = time.time() if now is None else now
    with _LOCK:
        if not force and _CACHE["v"] is not None and now - _CACHE["at"] < TTL_SEC:
            return _CACHE["v"]
    out: Dict[str, Any] = {}
    try:
        btc15, eth15 = _c("BTCUSDT", "15m", 40), _c("ETHUSDT", "15m", 40)
        if len(btc15) >= 17 and len(eth15) >= 17 and _fresh(btc15, now, 900):
            basket = {s: _c(s + "USDT", "15m", 20) for s in mb.BASKET if s != "ETH"}
            basket["ETH"] = eth15
            btc1d, btc1h = _c("BTCUSDT", "1d", 120), _c("BTCUSDT", "1h", 170)
            px = float(btc15[-1]["close"])
            ts_btc = tstruct.snapshot(now, px, btc1d, hourly=btc1h)
            m = mb.assess(btc_1h=btc15, eth_1h=eth15, basket_1h=basket, btc_week_dist_pct=ts_btc["week"]["dist_open_pct"], bph=4)
            out = {"market": m, "btc_time": ts_btc, "btc15": btc15, "built_at": now}
    except Exception:  # noqa: BLE001
        out = {}
    with _LOCK:
        _CACHE.update(at=now, v=out)
    return out


def for_signal(symbol: str, direction: str, now: Optional[float] = None) -> Dict[str, Any]:
    """{lines, calendar, snapshot}: рядки для READY-картки + повний знімок для журналу (SIGNAL_PLAN.gate.context). Порожньо, якщо даних немає."""
    now = time.time() if now is None else now
    try:
        base = build_market(now)
        if not base:
            return {}
        coin = str(symbol).upper().replace("USDT", "")
        c15 = _c(coin + "USDT", "15m", 40)
        al = None
        if len(c15) >= 17 and _fresh(c15, now, 900):
            al = mb.alignment(base["market"], direction=direction, coin=coin, coin_1h=c15, btc_1h=base["btc15"], corr_btc=mb.corr(c15, base["btc15"]), bph=4)
        lines = mb.card_lines(base["market"], al) if al else []
        wl = tstruct.week_line(base["btc_time"], "BTC")
        cal = [wl] if wl else []
        coin_ts = None
        try:
            coin_ts = tstruct.snapshot(now, c15[-1]["close"], _c(coin + "USDT", "1d", 120)) if c15 else None
        except Exception:  # noqa: BLE001
            coin_ts = None
        m = base["market"]
        snap = {"built_at": base["built_at"], "bias": m["bias"], "long": m["long"], "short": m["short"], "checked": m["checked"],
                "facts": [f["text"] for f in m["facts"]], "btc_1h": m["btc_1h"], "btc_4h": m["btc_4h"], "eth_4h": m["eth_4h"],
                "alignment": al, "lines": lines, "calendar": cal, "time": {k: base["btc_time"][k] for k in ("weekday", "week", "month", "quarter", "sessions", "closing")},
                "coin_time": ({k: coin_ts[k] for k in ("week", "month", "quarter")} if coin_ts else None)}
        return {"lines": lines, "calendar": cal, "snapshot": snap}
    except Exception:  # noqa: BLE001
        return {}


_BUILDING = {"on": False}


def cached() -> Optional[Dict[str, Any]]:
    """Останній зібраний стан ринку без мережі (або None)."""
    with _LOCK:
        return _CACHE["v"] or None


def refresh_async(max_age: float = TTL_SEC) -> None:
    """Оновити стан ринку у фоні, якщо він застарів: запит Mini App не чекає на десятки запитів до біржі."""
    now = time.time()
    with _LOCK:
        if _BUILDING["on"] or (_CACHE["v"] is not None and now - _CACHE["at"] < max_age):
            return
        _BUILDING["on"] = True

    def run() -> None:
        try:
            build_market(time.time(), force=True)
        finally:
            with _LOCK:
                _BUILDING["on"] = False

    threading.Thread(target=run, name="market-view", daemon=True).start()
