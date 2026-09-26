"""Стрічка Telegram: лише 4 проактивні типи + вечірній підсумок угод.

OFFICE_RULES_UA.md §2/§8. WATCHING / ZONE_REACHED без входу / SKIP / привітання —
мовчки в БД і лог. Не змінює ATR 80/90, Edge 85, фільтр 3%.
"""
from __future__ import annotations

import hashlib
import time as time_mod
from typing import Any, Dict, Iterable, Optional, Set, Tuple

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

EVENT_SIGNAL_ENTRY = "SIGNAL_ENTRY"
EVENT_TRADE_UPDATE = "TRADE_UPDATE"
EVENT_TRADE_CLOSED = "TRADE_CLOSED"
EVENT_NEWS_CRITICAL = "NEWS_CRITICAL"
EVENT_EVENING_DEBRIEF = "EVENING_DEBRIEF"

PROACTIVE_ALLOWED = {
    EVENT_SIGNAL_ENTRY,
    EVENT_TRADE_UPDATE,
    EVENT_TRADE_CLOSED,
    EVENT_NEWS_CRITICAL,
    EVENT_EVENING_DEBRIEF,
}

KIND_TO_EVENT = {
    KIND_SIGNAL: EVENT_SIGNAL_ENTRY,
    KIND_TP: EVENT_TRADE_UPDATE,
    KIND_SL: EVENT_TRADE_UPDATE,
    KIND_NEWS: EVENT_NEWS_CRITICAL,
    KIND_DEBRIEF: EVENT_EVENING_DEBRIEF,
}

# ZONE_REACHED SIGNAL=NO раніше: Lev ask_agent + коментар Олесі (2 LLM).
LLM_CALLS_SAVED_PER_ZONE_SKIP = 2


def watching_to_telegram() -> bool:
    return False


def sweep_near_to_telegram() -> bool:
    return False


def may_send_proactive(event_type: str, *, reply_to_user: bool = False) -> bool:
    """Відповідь на запит Тетяни — завжди. Інакше лише PROACTIVE_ALLOWED."""
    if reply_to_user:
        return True
    ev = str(event_type or "").strip().upper()
    return ev in PROACTIVE_ALLOWED


def event_type_for_kind(kind: str) -> str:
    raw = str(kind or "").strip()
    up = raw.upper()
    if up in PROACTIVE_ALLOWED:
        return up
    return str(KIND_TO_EVENT.get(raw.lower(), "") or "")


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
    reply_to_user: bool = False,
) -> Dict[str, Any]:
    """Чи можна слати в Telegram. Аналіз/БД не чіпає."""
    k = str(kind or "").strip().lower()
    sym = str(symbol or "").strip().upper()
    sent = sent_symbols if sent_symbols is not None else set()
    if reply_to_user:
        return {"send": True, "reason": "відповідь на запит Тетяни", "kind": k, "event": "USER_REPLY"}
    if k in (KIND_WATCHING, KIND_SWEEP_NEAR, "waiting_sweep", "near_sweep", "zone_reached"):
        return {"send": False, "reason": "WATCHING/NEAR/ZONE_REACHED тільки в БД", "kind": k}
    event = event_type_for_kind(kind)
    if not may_send_proactive(event):
        return {"send": False, "reason": f"проактивно заборонено {kind}", "kind": k, "event": event}
    if event in (
        EVENT_TRADE_UPDATE,
        EVENT_TRADE_CLOSED,
        EVENT_NEWS_CRITICAL,
        EVENT_EVENING_DEBRIEF,
    ) or k in PRIORITY_SKIP_COOLDOWN:
        return {
            "send": True,
            "reason": "пріоритет TP/SL/новина/debrief",
            "kind": k,
            "event": event,
            "skip_cooldown": True,
        }
    if event != EVENT_SIGNAL_ENTRY:
        return {"send": False, "reason": f"невідомий kind {k}", "kind": k, "event": event}
    if not sym:
        return {"send": False, "reason": "немає символу", "kind": k, "event": event}
    if sym in sent:
        return {"send": False, "reason": "символ уже в цьому циклі", "kind": k, "event": event}
    try:
        last = float(last_feed_ts or 0.0)
        now = float(now_ts or 0.0)
        cool = float(cooldown_sec)
    except (TypeError, ValueError):
        last, now, cool = 0.0, 0.0, TELEGRAM_COOLDOWN_SEC
    if last > 0 and now > 0 and (now - last) < cool:
        return {"send": False, "reason": f"cooldown {cool:.0f}s", "kind": k, "event": event}
    return {"send": True, "reason": "сигнал після свіпу/BOS", "kind": k, "event": event}


def mark_cycle_sent(sent_symbols: Set[str], symbol: str) -> None:
    s = str(symbol or "").strip().upper()
    if s:
        sent_symbols.add(s)


# Одна гілка desk: «Загальний» (OFFICE_GENERAL_THREAD_ID). Не слати ще раз у корінь форуму «General».
TRADE_UPDATE_STREAM = "general"
TRADE_TG_DEDUP_SEC = 900.0
_TRADE_TG_LAST: Dict[str, float] = {}


def trade_update_streams() -> Tuple[str, ...]:
    """Куди йде TRADE_UPDATE. Завжди рівно одна гілка."""
    return (TRADE_UPDATE_STREAM,)


def reset_trade_telegram_dedup() -> None:
    _TRADE_TG_LAST.clear()


def _trade_fp_key(*, kind: str, symbol: str, sl: Any, text: str, stream: str) -> str:
    from office_telegram_filter import format_px

    k = str(kind or "").strip().upper()
    sym = str(symbol or "").strip().upper()
    st = str(stream or TRADE_UPDATE_STREAM).strip().lower() or TRADE_UPDATE_STREAM
    sls = format_px(sl)
    if k == "TRAIL" and sym and sls:
        return f"TRAIL|{sym}|{sls}|{st}"
    raw = " ".join(str(text or "").split())
    digest = hashlib.sha256(f"{st}|{k}|{sym}|{raw}".encode("utf-8")).hexdigest()[:20]
    return f"{k or 'MSG'}|{sym}|{digest}|{st}"


def should_send_trade_telegram(
    *,
    text: str,
    kind: str = "",
    symbol: str = "",
    sl: Any = None,
    stream: str = TRADE_UPDATE_STREAM,
    now_ts: float = 0.0,
) -> Dict[str, Any]:
    """Другий той самий SL / той самий текст — тільки лог. Форсує одну гілку general."""
    st = TRADE_UPDATE_STREAM
    key = _trade_fp_key(kind=kind, symbol=symbol, sl=sl, text=text, stream=st)
    try:
        now = float(now_ts or time_mod.time())
    except (TypeError, ValueError):
        now = time_mod.time()
    last = _TRADE_TG_LAST.get(key)
    if last is not None and now - last < TRADE_TG_DEDUP_SEC:
        return {"send": False, "reason": "duplicate telegram", "key": key, "stream": st}
    _TRADE_TG_LAST[key] = now
    _ = stream  # ігноруємо другий stream — гілка одна
    return {"send": True, "reason": "ok", "key": key, "stream": st}
