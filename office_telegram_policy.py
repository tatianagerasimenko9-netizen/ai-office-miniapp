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
_TRADE_TG_PENDING: Set[str] = set()


def trade_update_streams() -> Tuple[str, ...]:
    """Куди йде TRADE_UPDATE. Завжди рівно одна гілка."""
    return (TRADE_UPDATE_STREAM,)


def reset_trade_telegram_dedup() -> None:
    _TRADE_TG_LAST.clear()
    _TRADE_TG_PENDING.clear()


def _trade_fp_key(
    *,
    kind: str,
    symbol: str,
    sl: Any,
    text: str,
    stream: str,
    canonical_id: str = "",
    event: str = "",
) -> str:
    from office_telegram_filter import format_px

    k = str(kind or "").strip().upper()
    sym = str(symbol or "").strip().upper()
    st = str(stream or TRADE_UPDATE_STREAM).strip().lower() or TRADE_UPDATE_STREAM
    cid = str(canonical_id or "").strip()
    ev = str(event or kind or "").strip().upper()
    if cid and ev:
        return f"SCENARIO|{cid}|{ev}|{st}"
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
    canonical_id: str = "",
    event: str = "",
) -> Dict[str, Any]:
    """Другий той самий SL / той самий текст — тільки лог. Форсує одну гілку general."""
    st = TRADE_UPDATE_STREAM
    key = _trade_fp_key(
        kind=kind,
        symbol=symbol,
        sl=sl,
        text=text,
        stream=st,
        canonical_id=canonical_id,
        event=event,
    )
    try:
        now = float(now_ts or time_mod.time())
    except (TypeError, ValueError):
        now = time_mod.time()
    last = _TRADE_TG_LAST.get(key)
    stable_scenario_event = bool(str(canonical_id or "").strip() and str(event or kind or "").strip())
    if key in _TRADE_TG_PENDING or (last is not None and (stable_scenario_event or now - last < TRADE_TG_DEDUP_SEC)):
        return {"send": False, "reason": "duplicate telegram", "key": key, "stream": st}
    # Reserve before async I/O; only a confirmed Telegram message commits dedup.
    _TRADE_TG_PENDING.add(key)
    _ = stream  # ігноруємо другий stream — гілка одна
    return {"send": True, "reason": "ok", "key": key, "stream": st}


def finish_trade_telegram(*, key: str, delivered: bool, now_ts: float = 0.0) -> None:
    """Release reservation on failure; record dedup only after confirmed delivery."""
    k = str(key or "").strip()
    if not k:
        return
    _TRADE_TG_PENDING.discard(k)
    if delivered:
        _TRADE_TG_LAST[k] = float(now_ts or time_mod.time())


def mini_app_button(
    *, symbol: str = "", scenario_id: str = "", base_url: str = "",
) -> Optional[Dict[str, Any]]:
    """Кнопка «📊 Сценарій» → картка канонічного сценарію в Mini App.

    З scenario_id — пряме посилання на картку (/v2?scenario=…). Без нього —
    старий фільтр за монетою (крім BTC, як і раніше). Лише посилання, не дія.
    """
    from urllib.parse import quote

    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return None
    sid = str(scenario_id or "").strip()
    sym = str(symbol or "").strip().upper()
    if sid:
        url = f"{base}/v2?scenario={quote(sid, safe='')}"
        return {"inline_keyboard": [[{"text": "📊 Сценарій", "url": url}]]}
    if sym and sym != "BTCUSDT":
        url = f"{base}/?symbol={quote(sym, safe='')}&filterSymbol={quote(sym, safe='')}"
        return {"inline_keyboard": [[{"text": "📊 Графік", "url": url}]]}
    return None


def strict_enabled() -> bool:
    """Єдине правило Telegram: лише готовий сигнал і ведення позначеної угоди. Відкат: OFFICE_TG_STRICT=0."""
    import os

    return os.getenv("OFFICE_TG_STRICT", "1").strip().lower() not in ("0", "false", "no", "off")


def outbound_allowed(*, event_type: str = "", kind: str = "", intent: str = "", confirmed_position: bool = False,
                     position_open: bool = False) -> bool:
    """Єдине місце, що вирішує, чи може ПРОАКТИВНЕ повідомлення піти в Telegram (`send_proactive`).
    Дозволено лише: (а) готовий сигнал (CONFIRM), (б) ведення угоди, яку власниця позначила відкритою (POSITION_MANAGE + відкрита позиція).
    Усе інше — WATCHING, неповні плани, скасування/завершення терміну внутрішніх сценаріїв, службові стани — лише БД/Mini App."""
    if not strict_enabled():
        return True
    it = str(intent or "").strip().upper()
    kd = str(kind or "").strip().upper()
    if it == "CONFIRM" and kd == "CONFIRM":
        return True
    if it == "SCENARIO_EVENT" and kd == "SCENARIO_EVENT":
        return True   # рух ринку до TP/SL показаного плану — не залежить від кнопки «Я відкрила угоду»
    if it == "POSITION_MANAGE" and bool(confirmed_position) and bool(position_open):
        return True
    return False
