"""DYNAMIC universe: ліквідні USDT-M perpetual-лідери руху поверх стабільного CORE (за замовчуванням вимкнено; OFFICE2_DYNAMIC_UNIVERSE=watch|1 — лише WATCH_ONLY без READY/Telegram; =live — явний перехід в основний цикл).

Рейтинг 24h — лише ВХІД ДЛЯ СПОСТЕРЕЖЕННЯ. Він не дає напрямку й не створює READY: монета проходить той самий рушій (структура, рівні, підтвердження, ризик), що й CORE.
Журнал причин додавання/виключення — таблиця office2_dynamic_log. Навантаження: один exchangeInfo (кеш), один 24hr, один bookTicker за оновлення; ліміт кандидатів.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from office2 import movers as MV

REFRESH_SEC = 900
MAX_DYNAMIC = 6
MIN_QUOTE_VOLUME = 20_000_000.0
MAX_SPREAD_BPS = 12.0
MIN_HOLD_CYCLES = 4          # монета не вилітає раніше, ніж через N оновлень (антидзиготання)
MIN_ABS_CHANGE = 5.0         # % за 24h, нижче — не «лідер руху»
INFO_TTL = 6 * 3600

DDL = ("""CREATE TABLE IF NOT EXISTS office2_dynamic_log (
    ts_epoch BIGINT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, metrics_json TEXT NOT NULL,
    PRIMARY KEY (ts_epoch, symbol, action))""",)

_STATE: Dict[str, Any] = {"active": {}, "at": 0.0, "info": None, "info_at": 0.0, "last": None, "backoff_until": 0.0}


def enabled() -> bool:
    from office2 import dynamic_watch as DW

    return DW.mode() != "off"


def _num(v) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def spreads(book: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for r in book or []:
        b, a = _num(r.get("bidPrice")), _num(r.get("askPrice"))
        if b and a and b > 0 and a >= b:
            out[r.get("symbol")] = (a - b) / ((a + b) / 2) * 1e4
    return out


def score(row: Dict[str, Any]) -> float:
    """Пріоритет кандидата: модуль руху × √оборот (ліквідність підсилює, але не домінує). Не торговий сигнал."""
    return abs(row["change_24h_pct"]) * math.sqrt(row["quote_volume_24h"] / 1e6)


def select(info: Dict[str, Any], tickers: List[Dict[str, Any]], book: List[Dict[str, Any]], core: List[str], previous: Dict[str, Dict[str, Any]],
           *, limit: int = MAX_DYNAMIC) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Чиста функція: повертає (новий active {symbol: meta}, журнал змін). Утримання: попередні лишаються ≥ MIN_HOLD_CYCLES, якщо досі придатні."""
    ranked = MV.rank_movers(info, tickers, limit=500, min_quote_volume=MIN_QUOTE_VOLUME)
    cand = {x["symbol"]: x for x in ranked["gainers"] + ranked["losers"]}
    sp = spreads(book)
    core_set = set(core)
    ok: Dict[str, Dict[str, Any]] = {}
    why_not: Dict[str, str] = {}
    for sym, x in cand.items():
        if sym in core_set:
            continue
        if abs(x["change_24h_pct"]) < MIN_ABS_CHANGE:
            why_not[sym] = "рух < %.0f%%" % MIN_ABS_CHANGE
        elif sym not in sp:
            why_not[sym] = "немає bid/ask"
        elif sp[sym] > MAX_SPREAD_BPS:
            why_not[sym] = "спред %.1f bps > %.0f" % (sp[sym], MAX_SPREAD_BPS)
        else:
            ok[sym] = {**x, "spread_bps": round(sp[sym], 2), "score": round(score(x), 2)}
    keep: Dict[str, Dict[str, Any]] = {}
    for sym, meta in previous.items():
        age = meta.get("cycles", 0) + 1
        if sym in ok:
            keep[sym] = {**ok[sym], "since": meta.get("since"), "cycles": age}
        elif age < MIN_HOLD_CYCLES and sym in cand and sym not in core_set:
            keep[sym] = {**meta, "cycles": age, "held": True}
    new = sorted((s for s in ok if s not in keep), key=lambda s: -ok[s]["score"])
    active = dict(sorted(keep.items(), key=lambda kv: -kv[1].get("score", 0))[:limit])
    for s in new:
        if len(active) >= limit:
            break
        active[s] = {**ok[s], "since": None, "cycles": 0}
    log: List[Dict[str, Any]] = []
    for s, m in active.items():
        if s not in previous:
            log.append({"symbol": s, "action": "ADD", "reason": "лідер руху %+.1f%%, оборот $%.0fM, спред %.1f bps" % (m["change_24h_pct"], m["quote_volume_24h"] / 1e6, m["spread_bps"]), "metrics": m})
    for s, m in previous.items():
        if s not in active:
            r = why_not.get(s) or ("ліміт %d, нижчий пріоритет" % limit if s in ok else "більше не лідер/придатний (exchangeInfo/ліквідність/рух)")
            log.append({"symbol": s, "action": "REMOVE", "reason": r, "metrics": m})
    return active, log


def _fetch_all(timeout: int = 8):
    now = time.time()
    if not _STATE["info"] or now - _STATE["info_at"] > INFO_TTL:
        _STATE["info"] = MV._get("/fapi/v1/exchangeInfo", timeout=timeout)
        _STATE["info_at"] = now
    return _STATE["info"], MV._get("/fapi/v1/ticker/24hr", timeout=timeout), MV._get("/fapi/v1/ticker/bookTicker", timeout=timeout)


def refresh(db: Optional[str], core: List[str], now: Optional[float] = None, fetch=None, log=print) -> List[str]:
    """Оновлює DYNAMIC не частіше за REFRESH_SEC. Помилка/429 → лишаємо попередній набір (сталість), backoff 5 хв."""
    now = time.time() if now is None else now
    if now - _STATE["at"] < REFRESH_SEC or now < _STATE["backoff_until"]:
        return list(_STATE["active"])
    try:
        info, tick, book = (fetch or _fetch_all)()
        active, chg = select(info, tick, book, core, _STATE["active"])
        for s, m in active.items():
            m["since"] = m.get("since") or int(now)
        _STATE.update(active=active, at=now, last={"at": int(now), "changes": len(chg), "active": list(active)})
        if db and chg:
            try:
                from office_bridge import _execute
                for d in DDL:
                    _execute(db, d)
                for c in chg:
                    _execute(db, "INSERT INTO office2_dynamic_log (ts_epoch, symbol, action, reason, metrics_json) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                             (int(now), c["symbol"], c["action"], c["reason"], __import__("json").dumps(c["metrics"], ensure_ascii=False)))
            except Exception as exc:  # noqa: BLE001
                log(f"[o2dyn] журнал не записано: {type(exc).__name__}: {str(exc)[:100]}")
        for c in chg:
            log(f"[o2dyn] {c['action']} {c['symbol']}: {c['reason']}")
    except Exception as exc:  # noqa: BLE001
        _STATE["backoff_until"] = now + 300
        log(f"[o2dyn] оновлення не вдалось ({type(exc).__name__}: {str(exc)[:100]}); лишаю попередній набір")
    return list(_STATE["active"])


def snapshot() -> Dict[str, Any]:
    return {"enabled": enabled(), "active": dict(_STATE["active"]), "updated_at": _STATE["at"] or None, "last": _STATE["last"], "meaning": "спостереження, не торговий сигнал"}
