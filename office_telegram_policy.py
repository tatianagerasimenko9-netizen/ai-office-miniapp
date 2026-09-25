"""Стрічка Telegram: тільки важливі тригери. Логіка PR39 лишається в БД.

OFFICE_RULES_UA.md §2/§8: без спаму. WATCHING і «наближається» — мовчки в БД.
Не змінює ATR 80/90, Edge 85, фільтр 3%.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set

TELEGRAM_COOLDOWN_SEC = 60.0
KIND_SIGNAL = "signal"
KIND_WATCHING = "watching"
KIND_SWEEP_NEAR = "sweep_near"
KIND_TP = "tp"
KIND_SL = "sl"
KIND_NEWS = "news"
KIND_DEBRIEF = "debrief"
PRIORITY_SKIP_COOLDOWN = frozenset({KIND_TP, KIND_SL, KIND_NEWS, KIND_DEBRIEF})
MODE_RANK = {"scalp": 0, "intraday": 1, "swing": 2}


def watching_to_telegram() -> bool:
    return False


def sweep_near_to_telegram() -> bool:
    return False


def preferred_scan_mode(modes: Iterable[str]) -> str:
    """H1/intraday старший за M5/scalp — одне повідомлення на символ."""
    best = "intraday"
    best_r = -1
    for m in modes:
        key = str(m or "").strip().lower() or "intraday"
        r = int(MODE_RANK.get(key, 1))
        if r > best_r:
            best, best_r = key, r
    return best


def allow_proactive_telegram(
    *,
    kind: str,
    symbol: str = "",
    sent_symbols: Optional[Set[str]] = None,
    last_feed_ts: float = 0.0,
    now_ts: float = 0.0,
    cooldown_sec: float = TELEGRAM_COOLDOWN_SEC,
) -> Dict[str, Any]:
    """Чи можна слати в Telegram. Аналіз/БД не чіпає."""
    k = str(kind or "").strip().lower()
    sym = str(symbol or "").strip().upper()
    sent = sent_symbols if sent_symbols is not None else set()
    if k in (KIND_WATCHING, KIND_SWEEP_NEAR, "waiting_sweep", "near_sweep"):
        return {"send": False, "reason": "WATCHING/NEAR тільки в БД", "kind": k}
    if k in PRIORITY_SKIP_COOLDOWN:
        return {"send": True, "reason": "пріоритет TP/SL/новина/debrief", "kind": k, "skip_cooldown": True}
    if k != KIND_SIGNAL:
        return {"send": False, "reason": f"невідомий kind {k}", "kind": k}
    if not sym:
        return {"send": False, "reason": "немає символу", "kind": k}
    if sym in sent:
        return {"send": False, "reason": "символ уже в цьому циклі", "kind": k}
    try:
        last = float(last_feed_ts or 0.0)
        now = float(now_ts or 0.0)
        cool = float(cooldown_sec)
    except (TypeError, ValueError):
        last, now, cool = 0.0, 0.0, TELEGRAM_COOLDOWN_SEC
    if last > 0 and now > 0 and (now - last) < cool:
        return {"send": False, "reason": f"cooldown {cool:.0f}s", "kind": k}
    return {"send": True, "reason": "сигнал після свіпу/BOS", "kind": k}


def mark_cycle_sent(sent_symbols: Set[str], symbol: str) -> None:
    s = str(symbol or "").strip().upper()
    if s:
        sent_symbols.add(s)
