from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

try:
    import tzdata  # noqa: F401  # IANA zones для ZoneInfo (Windows / slim Linux)
except ImportError:
    pass

import aiohttp
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

from office_factor_pack import build_factor_pack_from_desk_inputs
from office_style_qa import polish_agent_message

from office_bridge import (
    OfficeSignal,
    agent_say,
    briefing_get_last,
    briefing_save,
    check_drawdown_alert,
    check_portfolio_correlation,
    clean_llm_note,
    clean_self_naming,
    detect_setup_type,
    fmt_agent_line,
    get_agent_card_text,
    get_meta_intelligence_report,
    init_office_db,
    journal_close_trade,
    journal_consecutive_loss_streak,
    journal_add_feedback,
    journal_learning_hints_from_tags,
    journal_open_trade,
    journal_open_office_signal,
    journal_recurring_mistakes,
    journal_total_closed,
    journal_update_excursions,
    office_signal_trade_id,
    log_event,
    office_db_identity,
    office_desk_user_question,
    office_evening_debrief,
    build_evening_journal_summary,
    office_handle_signal,
    office_morning_briefing,
    office_news_trigger,
    office_position_event,
    office_run_scenario,
    office_trade_closed,
    live_risk_snapshot,
    office_signals_tp2_streak,
    OLESYA_RULE,
    signal_get_active,
    signal_get_by_symbol,
    signal_get_latest_by_symbol,
    signal_should_skip_proactive_scan,
    signal_touch_updated,
    signal_update,
    signal_upsert,
    trade_journal_add,
    trade_journal_get_recent,
    trade_journal_search_similar,
    tv_signal_fetch_unprocessed,
    tv_signal_mark_processed,
    victor_recent_sl_streak,
    VICTOR_RULE,
    _extract_first_usdt_symbol,
    _now_kyiv_hm,
    _to_kyiv_time_from_utc,
    LEV_RULE,
    DESK_BASE_RULE,
    MARICHKA_RULE,
    ARTEM_RULE,
)
from office_llm_agent import ask_agent
from office_market_state import market_state_get, record_scan_facts, scanner_blocked_notice, scanner_signal_blocked
from office_review_position import (
    handle_position_command,
    handle_review_command,
    parse_t1_command,
    scanner_enter_opens_position,
    scanner_review_notice,
)
from office_zone_alert import (
    T0_PROBE_PREFIX,
    ZONE_REACHED_COOLDOWN_SEC,
    after_zone_reached_action,
    format_zone_signal_entry,
    plan_watching_zone_hit,
    zone_reached_to_telegram,
)
from office_alert_gate import (
    apply_setup_event,
    get_explicit_open_position,
    has_explicit_position,
    mark_confirm_sent,
    may_emit_telegram,
    origin_key,
    gate_outbound_telegram,
    text_grants_entry,
)
from office_level_parse import apply_zone_sanity, parse_signal_levels_from_text
from office_watching_dedup import (
    apply_skip_watching_gate,
    record_skip_if_valid,
    should_keep_watching_on_skip,
)
from office_radar import RADAR_SYMBOLS, evaluate_radar
from office_session_radar import evaluate_session_radar
from office_external_signal import (
    gather_external_market,
    ingest_external_signal,
    persist_external_original,
    review_external_signal,
)
from office_range_radar import (
    evaluate_range_radar,
)
from office_market_scout import (
    already_ran_without_entry,
    btc_context_only,
    promote_for_deep_scan,
    screen_futures_market,
    shortlist_with_reasons,
)
from office_level_scalp import evaluate_level_book
from office_skip_plan import persist_skip_case
from office_trader_plan import compose_trader_plan, format_trader_plan
from office_telegram_filter import (
    format_level_span,
    format_px,
    level_book_to_alert,
    level_book_to_sweep_approach,
    level_book_to_watching,
    newest_quote_asof,
    quote_is_stale,
    range_result_to_alert,
)
from office_trade_steer import (
    ManageBook,
    format_entry_trigger,
    format_signal_steer_card,
    next_manage_event,
    plan_stop_behind_manipulation,
    plan_sweep_reentry,
    parse_sc_zone_note,
    sc_setup_cancelled,
    signal_case_key,
    tp3_from_liquidity,
)
from office_rsi_heat import exhaustion_candle, rsi_from_candles
from office_lev_verdict import lev_cycle
import office_lev_dialog as _lev_dialog
import office_lev_watch as _lev_watch
import office_targets as _targets
import office_user_messages as _msgs
import office_scenario_lifecycle as _lc

_CONFIRM_REJECT_LOGGED: set = set()
from office_telegram_policy import (
    EVENT_EVENING_DEBRIEF,
    EVENT_NEWS_CRITICAL,
    EVENT_SIGNAL_ENTRY,
    EVENT_TRADE_CLOSED,
    EVENT_TRADE_UPDATE,
    KIND_SIGNAL,
    KIND_SWEEP_NEAR,
    KIND_WATCHING,
    TRADE_UPDATE_STREAM,
    allow_proactive_telegram,
    mark_cycle_sent,
    may_send_proactive,
    preferred_scan_mode,
    should_send_trade_telegram,
    finish_trade_telegram,
    trade_update_streams,
)
from office_telegram_delivery_ledger import (
    reserve_delivery, finish_delivery, renew_delivery, mark_delivery_uncertain,
    get_scenario_root, remember_scenario_root,
)
from office_lifecycle import db_status_for
from office_news_agent import DATA_EMPTY, DATA_UNAVAILABLE, format_nazar_update
from office_atr_policy import classify_atr_day_used
from office_btc_liquidations import (
    BTC_FORCE_ORDER_BOOK,
    format_radar_liq_summary,
    run_btc_force_order_loop,
)

ROOT_DIR = Path(__file__).resolve().parent
MASTER_PROMPT_PATH = ROOT_DIR / "OFFICE_MASTER_PROMPT_UA.md"
CHECKLIST_PATH = ROOT_DIR / "OFFICE_CHECKLIST_STATUS_UA.md"
RUNBOOK_PATH = ROOT_DIR / "RUNBOOK_UA.md"
MAX_HISTORY = 5
HISTORY_TTL_SEC = 30 * 60
_chat_history: List[Dict[str, str]] = []
_chat_history_ts: float = 0.0
_last_signal_time: Dict[str, float] = {}
_last_notified: Dict[str, float] = {}
_steer_books: Dict[str, ManageBook] = {}
_reentry_done: Set[str] = set()


def _ensure_steer_book(
    *,
    signal_id: str,
    symbol: str,
    direction: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: Optional[float] = None,
    status: str = "ACTIVE",
) -> ManageBook:
    book = _steer_books.get(signal_id)
    if book is None:
        st = "ACTIVE"
        su = str(status or "").upper()
        if su == "HIT_TP1":
            st = "TP1"
        elif su == "HIT_TP2":
            st = "TP2"
        book = ManageBook(
            symbol=str(symbol or "").upper(),
            direction=str(direction or "LONG").upper(),
            entry=float(entry),
            sl=float(sl),
            tp1=float(tp1),
            tp2=tp2,
            state=st,
            trail_sl=None,
        )
        if st in ("TP1", "TP2", "TRAIL"):
            side = str(book.direction).upper()
            ts = float(entry)
            try:
                slv = float(sl)
            except (TypeError, ValueError):
                slv = ts
            if st in ("TP2", "TRAIL"):
                if side == "LONG":
                    ts = max(ts, slv)
                else:
                    ts = min(ts, slv)
            book.trail_sl = ts
            book.extras["last_sent_sl"] = slv if slv != float(entry) else None
        _steer_books[signal_id] = book
    return book


def _journal_signal_excursions(db_path: str, signal_id: str, book: ManageBook, extra: Optional[Dict[str, Any]] = None) -> None:
    try:
        journal_update_excursions(
            db_path,
            trade_id=office_signal_trade_id(signal_id),
            mfe_pct=float(book.mfe),
            mae_pct=float(book.mae),
            extra=extra,
        )
    except Exception as exc:
        print(f"[steer] journal mfe/mae failed: {exc}")
_risk_committee_last_sent: float = 0.0
_lev_last_response: Dict[str, float] = {}

OFFICE_RULES_BRIEF_UA = (
    "Правила офісу (коротко):\n"
    "1) Пишемо простою українською, коротко.\n"
    "2) Спочатку безпека депозиту, потім прибуток.\n"
    "3) Рішення по сигналу = командна дискусія ролей, без хаосу.\n"
    "4) Лев фіналить напрямок, Марко дає план виконання.\n"
    "5) При серії збитків ризик має пріоритет, вхід блокується.\n"
    "6) Для повних ролей/деталей: команда /officeprompt."
)
# UBUSDT і BUSDT — різні контракти на Binance Futures (обидва тікери існують; BUUSDT немає).
_CHAT_USDT_PAIR_ALIASES: Dict[str, str] = {
    "BUSDT": "BUSDT",
}

# LEV_RULE / DESK_BASE_RULE — єдине джерело в office_bridge (+ GERCHIK_KERNEL).

# Один стартовий ping у OFFICE за процес (уникнення дубля при повторному вході в run()).
_RELAY_OFFICE_STARTUP_PING_SENT: bool = False


@dataclass
class DialogItem:
    idx: int
    chat_id: int
    title: str


@dataclass
class ActivePosition:
    signal_id: str
    symbol: str
    direction: str
    opened_ts: float
    entry_price: float = 0.0
    last_price: float = 0.0
    partial_sent: bool = False
    moved_sl: bool = False
    stage: int = 0
    initial_volatility_pct: float = 0.0
    initial_news_risk: str = "SAFE"


@dataclass
class NewsRisk:
    level: str
    headline: str
    minutes_to_event: int
    event_name: str = ""
    event_time_utc: str = ""
    currency: str = "USD"
    importance: str = "low"
    data_status: str = "DATA_OK"


def relay_config_path() -> Path:
    p = os.getenv("OFFICE_RELAY_CONFIG", "").strip()
    if p:
        return Path(p)
    return Path(__file__).with_name("office_relay_config.json")


def load_relay_config() -> Dict[str, Any]:
    path = relay_config_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return dict(raw)
    except Exception:
        return {}
    return {}


def save_relay_config(cfg: Dict[str, Any]) -> None:
    path = relay_config_path()
    # Keep file readable; this file may contain secrets — treat it like a password file.
    merged: Dict[str, object] = {}
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                merged.update(existing)  # type: ignore[arg-type]
    except Exception:
        merged = {}

    # Shallow-merge top-level keys; deep-merge agent_bot_tokens to avoid wiping other bots.
    for k, v in cfg.items():
        if k == "agent_bot_tokens" and isinstance(v, dict) and isinstance(merged.get("agent_bot_tokens"), dict):
            base_tokens = dict(merged.get("agent_bot_tokens") or {})
            base_tokens.update(v)
            merged[k] = base_tokens
        elif k == "agent_bot_usernames" and isinstance(v, dict) and isinstance(merged.get("agent_bot_usernames"), dict):
            base_u = dict(merged.get("agent_bot_usernames") or {})
            base_u.update(v)
            merged[k] = base_u
        else:
            merged[k] = v

    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_text_head(path: Path, max_chars: int = 3500) -> str:
    try:
        txt = path.read_text(encoding="utf-8")
        txt = txt.strip()
        if not txt:
            return ""
        return txt[:max_chars]
    except Exception:
        return ""


def _safe_json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


async def init_office_memory_stores() -> Dict[str, str]:
    """Create or reuse Office memory stores for Lev and Sofia."""
    import httpx

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    lev_store_id = os.getenv("LEV_MEMORY_STORE_ID", "").strip()
    sofia_store_id = os.getenv("SOFIA_MEMORY_STORE_ID", "").strip()
    result: Dict[str, str] = {
        "lev": lev_store_id,
        "memory": sofia_store_id,
    }

    if lev_store_id:
        print(f"[memory] Lev store: {lev_store_id}")
    if sofia_store_id:
        print(f"[memory] Sofia store: {sofia_store_id}")
    if not api_key:
        print("[memory] ANTHROPIC_API_KEY is missing; skip memory stores init")
        return result

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "managed-agents-2026-04-01",
                "content-type": "application/json",
            }
            required = [
                ("lev", "lev_trading_decisions", "LEV_MEMORY_STORE_ID"),
                ("memory", "sofia_trading_memory", "SOFIA_MEMORY_STORE_ID"),
            ]
            for key, store_name, env_name in required:
                if result.get(key):
                    continue
                resp = await client.post(
                    "https://api.anthropic.com/v1/memory_stores",
                    headers=headers,
                    json={"name": store_name},
                    timeout=15.0,
                )
                if not resp.is_success:
                    print(f"[memory] Store create failed for {key}: {resp.status_code} {resp.text[:500]}")
                    continue
                data = resp.json()
                new_id = str(data.get("id", "") or "").strip()
                if new_id:
                    result[key] = new_id
                    print(f"[memory] Created {key} store: {new_id}")
                    print(f"[memory] Add to Render env: {env_name}={new_id}")
                else:
                    print(f"[memory] Store create response has no id for {key}")
    except Exception as e:
        print(f"[memory] Stores init failed: {e}")
    return result


def load_agent_bot_tokens() -> Dict[str, str]:
    """
    Optional multi-bot mode via env vars:
    AGENT_BOT_TOKEN_LEV, AGENT_BOT_TOKEN_MAKS, AGENT_BOT_TOKEN_DARYNA,
    AGENT_BOT_TOKEN_MARKO, AGENT_BOT_TOKEN_OLESYA, AGENT_BOT_TOKEN_NEWS,
    AGENT_BOT_TOKEN_MEMORY (Софія), AGENT_BOT_TOKEN_PSYCH (Віктор),
    AGENT_BOT_TOKEN_DEV (Артем)
    """
    keys = ("lev", "maks", "news", "daryna", "marko", "olesya", "memory", "psych", "dev", "marichka")
    result: Dict[str, str] = {}
    for k in keys:
        v = os.getenv(f"AGENT_BOT_TOKEN_{k.upper()}", "").strip()
        if v:
            result[k] = v

    # Optional: load from office_relay_config.json without requiring env exports.
    try:
        cfg = load_relay_config()
        nested = cfg.get("agent_bot_tokens")
        if isinstance(nested, dict):
            for k in keys:
                if k in result:
                    continue
                v2 = str(nested.get(k, "") or "").strip()
                if v2:
                    result[k] = v2
    except Exception:
        pass

    return result


def load_agent_bot_usernames() -> Dict[str, str]:
    """
    Usernames інших ботів для Bot API (Phase 14, direct bot-to-bot).
    Env: AGENT_BOT_USERNAME_LEV, … або office_relay_config.json → agent_bot_usernames.
    Значення без @; у sendMessage передається як @username.
    """
    keys = ("lev", "maks", "news", "daryna", "marko", "olesya", "memory", "psych", "dev", "marichka")
    result: Dict[str, str] = {}
    for k in keys:
        raw = os.getenv(f"AGENT_BOT_USERNAME_{k.upper()}", "").strip().lstrip("@")
        if raw:
            result[k] = raw
    try:
        cfg = load_relay_config()
        nested = cfg.get("agent_bot_usernames")
        if isinstance(nested, dict):
            for kk in keys:
                if kk in result:
                    continue
                v2 = str(nested.get(kk, "") or "").strip().lstrip("@")
                if v2:
                    result[kk] = v2
    except Exception:
        pass
    return result


async def bot_to_bot_message(
    from_agent: str,
    to_agent: str,
    text: str,
    *,
    session: Optional[aiohttp.ClientSession] = None,
    agent_tokens: Optional[Dict[str, str]] = None,
    agent_usernames: Optional[Dict[str, str]] = None,
) -> None:
    """
    Відправляє повідомлення від одного агента іншому через Telegram Bot API (sendMessage).

    Потрібні токен відправника та username отримувача (див. load_agent_bot_usernames).
    У Telegram 2026+ для ланцюга bot→bot обидва боти мають увімкнути bot-to-bot у налаштуваннях.
    """
    fk = str(from_agent or "").strip().lower()
    tk = str(to_agent or "").strip().lower()
    toks = agent_tokens if agent_tokens is not None else load_agent_bot_tokens()
    users = agent_usernames if agent_usernames is not None else load_agent_bot_usernames()
    from_token = toks.get(fk)
    to_username = (users.get(tk) or "").strip().lstrip("@")
    if not from_token or not to_username or not (text or "").strip():
        return
    url = f"https://api.telegram.org/bot{from_token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": f"@{to_username}",
        "text": str(text)[:3900],
        "disable_web_page_preview": True,
    }
    try:

        async def _post(sess: aiohttp.ClientSession) -> None:
            async with sess.post(url, json=payload) as resp:
                body = await resp.json()
                if resp.status != 200 or not bool((body or {}).get("ok")):
                    print(f"[bot2bot] send failed {fk}->{tk}: http={resp.status} body={body!r}")

        if session is not None:
            await _post(session)
        else:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as sess:
                await _post(sess)
    except Exception as e:
        print(f"[bot2bot] error: {e}")


def detect_agent_key(message: str) -> Optional[str]:
    m = re.match(r"^@@([a-z_]+)@@", message)
    if m:
        return m.group(1).strip().lower()
    text = message[:120]
    if "Лев" in text:
        return "lev"
    if "Макс" in text:
        return "maks"
    if "Назар" in text:
        return "news"
    if "Дарина" in text:
        return "daryna"
    if "Марко" in text:
        return "marko"
    if "Олеся" in text:
        return "olesya"
    if "Софія" in text:
        return "memory"
    if "Віктор" in text:
        return "psych"
    if "Артем" in text:
        return "dev"
    return None


def split_long_message(text: str, limit: int = 2500) -> List[str]:
    """
    Split long text into chunks up to `limit` characters.
    Prefers paragraph boundaries (\\n\\n) to avoid mid-sentence cuts.
    """
    raw = str(text or "")
    if len(raw) <= limit:
        return [raw]
    parts: List[str] = []
    paragraphs = raw.split("\n\n")
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= limit:
            current += (("\n\n" if current else "") + para)
        else:
            if current:
                parts.append(current)
            if len(para) <= limit:
                current = para
                continue
            # Fallback for oversized paragraph.
            start = 0
            while start < len(para):
                chunk = para[start : start + limit]
                parts.append(chunk)
                start += limit
            current = ""
    if current:
        parts.append(current)
    return parts if parts else [raw]


def _trim_lines(text: str, max_lines: int = 6) -> str:
    lines = [l for l in str(text or "").split("\n") if l.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return "\n".join(lines).strip()


def _desk_card_min_tp1(symbol: str) -> float:
    from office_desk_card import min_tp1_pct

    return min_tp1_pct(symbol)


async def send_via_bot_api(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
    retries: int = 0,
    timeout_sec: Optional[float] = None,
) -> tuple[bool, str, Optional[int]]:
    """
    Send via Bot API without parse_mode.

    Reason: our desk messages often include characters that break Telegram Markdown parsing.
    Plain text is the most reliable mode for multi-bot delivery.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = int(reply_to_message_id)
    if message_thread_id:
        payload["message_thread_id"] = int(message_thread_id)
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    kw: Dict[str, Any] = {"timeout": aiohttp.ClientTimeout(total=float(timeout_sec))} if timeout_sec else {}
    last = "exception: unknown"
    for attempt in range(max(0, int(retries)) + 1):
        try:
            async with session.post(url, json=payload, **kw) as resp:
                body = await resp.json()
                if resp.status != 200:
                    return False, f"http {resp.status}: {body}", None
                if not bool(body.get("ok")):
                    desc = str((body or {}).get("description") or body)
                    return False, f"telegram: {desc}", None
                msg_id = None
                try:
                    msg_id = int(((body or {}).get("result") or {}).get("message_id"))
                except Exception:
                    msg_id = None
                return True, "ok", msg_id
        except Exception as exc:
            # Збій з'єднання/таймаут: для повідомлення з кнопкою повторюємо Bot API (Telethon-запасний шлях кнопки не має — це й губило «Сценарій»).
            last = f"exception: {type(exc).__name__}: {exc}"
            if attempt < max(0, int(retries)):
                await asyncio.sleep(1.5 * (attempt + 1))
    return False, last, None


async def send_via_bot_photo(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: int,
    photo_path: str,
    caption: str = "",
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> tuple[bool, str, Optional[int]]:
    """Одне повідомлення: фото + caption (ліміт Telegram 1024)."""
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    cap = str(caption or "")[:1024]
    data = aiohttp.FormData()
    data.add_field("chat_id", str(chat_id))
    if cap:
        data.add_field("caption", cap)
    if reply_to_message_id:
        data.add_field("reply_to_message_id", str(int(reply_to_message_id)))
    if message_thread_id:
        data.add_field("message_thread_id", str(int(message_thread_id)))
    if reply_markup:
        data.add_field("reply_markup", json.dumps(reply_markup, ensure_ascii=False))
    try:
        with open(photo_path, "rb") as fh:
            data.add_field("photo", fh, filename=os.path.basename(photo_path), content_type="image/png")
            async with session.post(url, data=data) as resp:
                body = await resp.json()
                if resp.status != 200 or not bool(body.get("ok")):
                    desc = str((body or {}).get("description") or body)
                    return False, f"telegram photo: {desc}", None
                msg_id = None
                try:
                    msg_id = int(((body or {}).get("result") or {}).get("message_id"))
                except Exception:
                    msg_id = None
                return True, "ok", msg_id
    except Exception as exc:
        return False, f"exception: {exc}", None


async def send_via_bot_streaming(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: int,
    text: str,
    thread_id: Optional[int] = None,
    reply_to: Optional[int] = None,
) -> Tuple[bool, str, Optional[int]]:
    """
    Streaming повідомлення через sendMessageDraft.
    Telegram показує текст в реальному часі поки агент "думає".
    """
    url = f"https://api.telegram.org/bot{token}/sendMessageDraft"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    if reply_to:
        payload["reply_to_message_id"] = int(reply_to)
    try:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
            if bool(data.get("ok")):
                msg_id = ((data.get("result") or {}) if isinstance(data, dict) else {}).get("message_id")
                try:
                    msg_id = int(msg_id) if msg_id is not None else None
                except Exception:
                    msg_id = None
                return True, "ok", msg_id
            return False, str(data), None
    except Exception as e:
        return False, str(e), None


async def check_bot_api_access(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: int,
) -> tuple[bool, str, Optional[int]]:
    try:
        me_url = f"https://api.telegram.org/bot{token}/getMe"
        async with session.get(me_url) as resp:
            body = await resp.json()
            if resp.status != 200 or not bool((body or {}).get("ok")):
                return False, f"getMe failed: {body}", None
            bot_id = int(((body or {}).get("result") or {}).get("id"))
        member_url = f"https://api.telegram.org/bot{token}/getChatMember"
        params = {"chat_id": chat_id, "user_id": bot_id}
        async with session.get(member_url, params=params) as resp2:
            body2 = await resp2.json()
            if resp2.status != 200 or not bool((body2 or {}).get("ok")):
                return False, f"getChatMember failed: {body2}", bot_id
            status = str((((body2 or {}).get("result") or {}).get("status") or "")).lower()
            if status in ("left", "kicked", ""):
                return False, f"chat member status: {status or 'unknown'}", bot_id
            return True, f"status={status}", bot_id
    except Exception as exc:
        return False, f"exception: {exc}", None


async def fetch_mark_price(session: aiohttp.ClientSession, symbol: str) -> float:
    """
    Binance Futures public mark price endpoint (no auth required).
    """
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    params = {"symbol": symbol.upper()}
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            raise RuntimeError(f"price status {resp.status}")
        data = await resp.json()
    return float(data.get("markPrice") or data.get("price") or 0.0)


async def fetch_binance_premium_index(session: aiohttp.ClientSession, symbol: str) -> Optional[Dict[str, float]]:
    """
    Mark / index / last funding (Binance USDT-M public).
    """
    from office_market_data import backoff_left, note_rate_limited

    if backoff_left() > 0:
        return None
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    params = {"symbol": symbol.upper()}
    async with session.get(url, params=params) as resp:
        if resp.status in (418, 429):
            note_rate_limited(resp.headers.get("Retry-After"))
        if resp.status != 200:
            return None
        data = await resp.json()
    funding_pct: Optional[float] = None
    fr = data.get("lastFundingRate")
    if fr is not None:
        try:
            funding_pct = float(fr) * 100.0
        except Exception:
            funding_pct = None
    try:
        mp = float(data.get("markPrice") or 0.0)
        ip = float(data.get("indexPrice") or 0.0)
    except Exception:
        return None
    return {
        "mark_price": mp if mp > 0 else None,
        "index_price": ip if ip > 0 else None,
        "funding_rate_pct": funding_pct,
    }


async def fetch_binance_futures_ticker(session: aiohttp.ClientSession, symbol: str) -> Dict[str, float]:
    """
    Public 24h ticker for USDT-M futures.
    """
    from office_market_data import backoff_left, note_rate_limited

    if backoff_left() > 0:
        raise RuntimeError(f"binance backoff {backoff_left():.0f}s")
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    params = {"symbol": symbol.upper()}
    async with session.get(url, params=params) as resp:
        if resp.status in (418, 429):
            note_rate_limited(resp.headers.get("Retry-After"))
        if resp.status != 200:
            raise RuntimeError(f"ticker status {resp.status}")
        data = await resp.json()
    last = float(data.get("lastPrice") or 0.0)
    high = float(data.get("highPrice") or 0.0)
    low = float(data.get("lowPrice") or 0.0)
    quote_vol = float(data.get("quoteVolume") or 0.0)
    pct = float(data.get("priceChangePercent") or 0.0)
    vol_pct = 0.0
    if high > 0 and low > 0:
        vol_pct = ((high - low) / ((high + low) / 2.0)) * 100.0
    return {
        "last": last,
        "pct": pct,
        "quote_volume_usdt": quote_vol,
        "volatility_pct": vol_pct,
    }


def _parse_desk_command(text: str) -> Optional[str]:
    s = (text or "").strip()
    low = s.lower()
    prefixes = ("!ask", "!desk", "!питання", "/ask", "/desk")
    for p in prefixes:
        if low.startswith(p):
            return s[len(p) :].strip()
    return None


def _strip_agent_tag(message: str) -> str:
    return re.sub(r"^@@[a-z_]+@@", "", message, count=1)


def _parse_scenario_command(text: str) -> Optional[str]:
    s = (text or "").strip()
    low = s.lower()
    for p in ("!scenario", "/scenario"):
        if low.startswith(p):
            return s[len(p) :].strip().lower()
    return None


def _parse_hh_mm(env_val: str, default_h: int, default_m: int) -> Tuple[int, int]:
    raw = (env_val or "").strip()
    if not raw:
        return default_h, default_m
    sep = ":" if ":" in raw else ("." if "." in raw else None)
    if sep is None:
        return default_h, default_m
    parts = raw.split(sep, 1)
    if len(parts) != 2:
        return default_h, default_m
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except Exception:
        return default_h, default_m


def _briefing_tzinfo():
    if ZoneInfo is None:
        return timezone.utc
    name = os.getenv("OFFICE_BRIEFING_TZ", "Europe/Kyiv").strip()
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        print(f"[relay][WARN] OFFICE_BRIEFING_TZ={name!r} недоступна, використовую UTC")
        return timezone.utc


def format_kyiv_time(dt: datetime) -> str:
    """Час для Telegram без двокрапки HH:MM (інакше клієнт лінкує як URL)."""
    return f"{dt.hour} год {dt.minute:02d} хв"


def get_session_status_kyiv(*, include_kill_zone: bool = True) -> str:
    """
    Повертає поточний статус сесій у зрозумілому форматі за Києвом
    (OFFICE_BRIEFING_TZ, зазвичай Europe/Kyiv).

    include_kill_zone=False — без рядка KILL ZONE (щоб не дублювати session_announcer).
    """
    tz = _briefing_tzinfo()
    now = datetime.now(tz)
    h = now.hour
    time_safe = format_kyiv_time(now)

    sessions: List[str] = []
    if 3 <= h < 11:
        sessions.append("🌏 Азія відкрита")
    if 11 <= h < 19:
        sessions.append("🇬🇧 Лондон відкритий")
    if h >= 16 or h < 1:
        sessions.append("🇺🇸 Нью-Йорк відкритий")

    if include_kill_zone:
        if 11 <= h < 14:
            sessions.append("⚡ KILL ZONE Лондон (з 11 год до 14 год за Києвом)")
        elif 16 <= h < 19:
            sessions.append("⚡ KILL ZONE Нью-Йорк (з 16 год до 19 год за Києвом)")

    if not sessions:
        sessions.append("😴 Між сесіями — тихо")

    return f"🕐 Зараз {time_safe} за Києвом\n" + "\n".join(sessions)


def _session_label_from_hour(h: int) -> str:
    if 0 <= h < 9:
        return "ASIA"
    if 9 <= h < 16:
        return "LONDON"
    return "NEW_YORK"


def build_signal_kickoff(symbol: str, direction: str) -> str:
    intros = [
        "Новий сигнал. Працюємо по плану.",
        "Є свіжий сигнал. Беремо в роботу.",
        "Зайшов новий кейс. Починаємо розбір.",
        "Новий сигнал на столі. Працюємо спокійно.",
    ]
    intro = random.choice(intros)
    side = "LONG" if str(direction).upper() == "LONG" else "SHORT"
    return (
        f"{intro}\n"
        f"Сигнал: {symbol.upper()} · {side}"
    )


async def build_desk_market_snapshot(session: aiohttp.ClientSession, symbol: str) -> Dict[str, Any]:
    sym = symbol.upper()
    btc = await fetch_binance_futures_ticker(session, "BTCUSDT")
    alt = await fetch_binance_futures_ticker(session, sym)

    premium: Optional[Dict[str, float]] = None
    try:
        premium = await fetch_binance_premium_index(session, sym)
    except Exception:
        premium = None

    # "Gold" proxy on Binance USDT-M (best-effort). If symbol missing, ignore in snapshot.
    gold: Dict[str, float] = {}
    for candidate in ("PAXGUSDT", "XAUUSDT"):
        try:
            gold = await fetch_binance_futures_ticker(session, candidate)
            gold["symbol"] = candidate
            break
        except Exception:
            continue

    # Simple desk hints (not trading advice): relative strength vs BTC + liquidity + chop proxy.
    score_hint = 12
    if alt["pct"] - btc["pct"] >= 1.0:
        score_hint = 13
    if alt["quote_volume_usdt"] < 20_000_000:
        score_hint -= 2

    regime = "TREND"
    if alt["volatility_pct"] >= 6.0:
        regime = "CHOP"

    score_hint = max(8, min(18, score_hint))

    gs: Optional[str] = None
    gc: Optional[float] = None
    if gold:
        gs = str(gold.get("symbol", ""))
        gc = float(gold.get("pct", 0.0))

    pack = build_factor_pack_from_desk_inputs(
        btc_ticker=btc,
        alt_ticker=alt,
        premium=premium,
        gold_symbol=gs,
        gold_change_pct=gc,
        score_hint=score_hint,
        regime=regime,
        session="LONDON",
    )

    out: Dict[str, Any] = {
        "btc_change_pct": btc["pct"],
        "sym_change_pct": alt["pct"],
        "quote_volume_usdt": alt["quote_volume_usdt"],
        "volatility_pct": alt["volatility_pct"],
        "rr_hint": 2.0,
        "score_hint": score_hint,
        "session": "LONDON",
        "regime": regime,
        "news_risk": "SAFE",
        "minutes_to_event": 999,
        "factor_pack_v2": pack.to_json_safe(),
    }
    if gold:
        out["gold_symbol"] = gs or ""
        out["gold_change_pct"] = gc or 0.0
    return out


def _parse_dt_any(value: str) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip()
    patterns = (
        lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
        lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"),
        lambda x: datetime.strptime(x, "%Y-%m-%d"),
    )
    for p in patterns:
        try:
            dt = p(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


async def fetch_news_risk(session: aiohttp.ClientSession, api_key: str) -> NewsRisk:
    """
    Live economic-calendar check via FinancialModelingPrep.
    Returns SAFE/RISK/HIGH RISK with nearest headline.
    """
    if not api_key:
        return NewsRisk(
            "SAFE",
            "news api unavailable",
            999,
            "",
            "",
            "USD",
            "low",
            DATA_UNAVAILABLE,
        )
    now = datetime.now(timezone.utc)
    from_s = now.strftime("%Y-%m-%d")
    to_s = from_s
    url = "https://financialmodelingprep.com/stable/economic-calendar"
    params = {"from": from_s, "to": to_s, "apikey": api_key}
    news_timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with session.get(url, params=params, timeout=news_timeout) as resp:
            if resp.status != 200:
                return NewsRisk(
                    "SAFE",
                    f"news status {resp.status}",
                    999,
                    "",
                    "",
                    "USD",
                    "low",
                    DATA_UNAVAILABLE,
                )
            data = await resp.json()
    except Exception:
        return NewsRisk("SAFE", "news timeout", 999, "", "", "USD", "low", DATA_UNAVAILABLE)
    nearest_min = 999
    nearest_title = "no high impact events"
    nearest_time_utc = ""
    nearest_currency = "USD"
    nearest_importance = "low"
    keys = ("fomc", "fed", "rate", "cpi", "nfp", "powell", "inflation", "ecb", "boj")
    for e in (data if isinstance(data, list) else []):
        title = str(e.get("event") or e.get("title") or "")
        if not title:
            continue
        impact = str(e.get("impact") or e.get("importance") or "").lower().strip()
        importance = "low"
        if "high" in impact:
            importance = "high"
        elif "medium" in impact or "med" in impact:
            importance = "medium"
        elif any(k in title.lower() for k in keys):
            importance = "high"
        dt = _parse_dt_any(str(e.get("date") or e.get("time") or ""))
        if dt is None:
            continue
        mins = int((dt - now).total_seconds() / 60)
        if 0 <= mins < nearest_min:
            nearest_min = mins
            nearest_title = title
            nearest_time_utc = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            nearest_currency = str(e.get("currency") or e.get("country") or "USD")
            nearest_importance = importance
    if nearest_min <= 60:
        return NewsRisk(
            "HIGH RISK",
            nearest_title,
            nearest_min,
            nearest_title,
            nearest_time_utc,
            nearest_currency,
            nearest_importance,
            "DATA_OK",
        )
    if nearest_min <= 180:
        return NewsRisk(
            "RISK",
            nearest_title,
            nearest_min,
            nearest_title,
            nearest_time_utc,
            nearest_currency,
            nearest_importance,
            "DATA_OK",
        )
    empty = nearest_min >= 999
    return NewsRisk(
        "SAFE",
        nearest_title if not empty else "",
        nearest_min,
        nearest_title if not empty else "",
        nearest_time_utc,
        nearest_currency,
        nearest_importance,
        DATA_EMPTY if empty else "DATA_OK",
    )


def looks_like_signal(text: str) -> bool:
    up = (text or "").upper()

    # Явні тригери з каналів / шаблонів.
    hard_keys = (
        "SMART MONEY SETUP",
        "ВХОДЬ",
        "ВХІД",
        "SIGNAL",
        "СИГНАЛ",
        "ENTRY",
        "SETUP",
    )
    if any(k in up for k in hard_keys):
        return True

    # Символ (напр. BTCUSDT) + напрямок у різних форматах.
    has_symbol = bool(re.search(r"\b[A-Z0-9]{2,15}USDT\b", up))
    side_tokens = (
        "LONG",
        "SHORT",
        "BUY",
        "SELL",
        "ЛОНГ",
        "ШОРТ",
        "КУПІВЛ",
        "ПРОДАЖ",
        "🟢",
        "🔴",
    )
    has_side = any(tok in up for tok in side_tokens)
    return has_symbol and has_side


def _extract_price_hint(text: str, labels: tuple[str, ...]) -> Optional[float]:
    def _pick_number(chunk: str) -> Optional[float]:
        for m in re.finditer(r"(\d+(?:[.,]\d+)?)", chunk):
            raw = m.group(1)
            start = int(m.start(1))
            end = int(m.end(1))
            tail = chunk[end : end + 2]
            # Skip percentages like 50% or 3.8%
            if "%" in tail:
                continue
            # Prefer decimal-like prices over plain integers (e.g. TP1, 1m).
            if "." not in raw and "," not in raw:
                continue
            try:
                return float(raw.replace(",", "."))
            except Exception:
                continue
        return None

    low = text.lower()
    for line in text.splitlines():
        ll = line.lower()
        for lb in labels:
            i = ll.find(lb)
            if i < 0:
                continue
            # Common signal formats often place the price BEFORE the label:
            # "0.01513 (вхід 50%)", "0.01547 (hard stop)".
            before = line[:i]
            after = line[i:]
            nums_before = list(re.finditer(r"(\d+(?:[.,]\d+)?)", before))
            for m in reversed(nums_before):
                raw = m.group(1)
                if "." not in raw and "," not in raw:
                    continue
                try:
                    return float(raw.replace(",", "."))
                except Exception:
                    continue
            val_after = _pick_number(after)
            if val_after is not None:
                return val_after
    # Fallback: previous behavior on whole text windows, but percent-safe.
    for lb in labels:
        i = low.find(lb)
        if i < 0:
            continue
        window = text[max(0, i - 40) : i + 120]
        val = _pick_number(window)
        if val is not None:
            return val
    return None


def build_stoploss_postmortem(
    *,
    move_pct: float,
    age_sec: float,
    volatility_pct: float,
    news_risk: str,
    had_partial: bool,
) -> tuple[List[str], str]:
    tags: List[str] = []
    notes: List[str] = []
    if volatility_pct >= 5.0:
        tags.append("high_volatility")
        notes.append("волатильність була підвищена")
    if str(news_risk).upper() in ("RISK", "HIGH", "HIGH RISK"):
        tags.append("news_risk")
        notes.append("поряд був новинний ризик")
    if age_sec < 180:
        tags.append("early_stopout")
        notes.append("стоп спрацював дуже рано після входу")
    if move_pct <= -1.8:
        tags.append("strong_adverse_move")
        notes.append("рух проти позиції був різкий")
    if not had_partial:
        tags.append("no_partial_before_loss")
        notes.append("не було часткової фіксації до стопа")

    if not notes:
        notes.append("базовий ринковий стоп без явного порушення")
    note = "STOP-розбір: " + "; ".join(notes) + ". Наступний крок: зменшити ризик і чекати чистіший сетап."
    return tags, note


def build_daily_journal_report(db_path: str) -> str:
    """Щоденний зріз журналу: Київ, /position окремо, без фейкових 0%."""
    return build_evening_journal_summary(db_path)


def build_weekly_journal_report(db_path: str) -> str:
    """
    Ролінг 7 днів закритих угод (MASTER п.29).
    """
    try:
        is_pg = str(db_path).lower().startswith("postgres://") or str(db_path).lower().startswith("postgresql://")
        if is_pg:
            if psycopg is None:
                raise RuntimeError("psycopg is required for PostgreSQL mode")
            with psycopg.connect(db_path) as conn:  # type: ignore[arg-type]
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT outcome, pnl_pct, r_multiple, mistake_tags_json, symbol
                        FROM trade_journal
                        WHERE status = 'CLOSED'
                          AND ts_close_utc IS NOT NULL
                          AND TRIM(ts_close_utc) <> ''
                          AND ts_close_utc::timestamptz >= (NOW() - INTERVAL '7 days')
                        """
                    )
                    rows = cur.fetchall()
        else:
            dbp = db_path
            if str(dbp).lower().startswith("sqlite:///"):
                dbp = str(dbp)[10:]
            with sqlite3.connect(dbp) as conn:
                rows = conn.execute(
                    """
                    SELECT outcome, pnl_pct, r_multiple, mistake_tags_json, symbol
                    FROM trade_journal
                    WHERE status = 'CLOSED'
                      AND ts_close_utc IS NOT NULL
                      AND TRIM(ts_close_utc) <> ''
                      AND datetime(ts_close_utc) >= datetime('now', '-7 days')
                    """
                ).fetchall()
    except Exception:
        rows = []

    wins = 0
    losses = 0
    be = 0
    pnl_sum = 0.0
    r_vals: List[float] = []
    tags_count: Dict[str, int] = {}
    sym_trade_count: Dict[str, int] = {}

    for outcome, pnl_pct, r_multiple, tags_json, symbol in rows:
        o = str(outcome or "").upper()
        if o == "WIN":
            wins += 1
        elif o == "LOSS":
            losses += 1
        elif o == "BE":
            be += 1
        try:
            pnl_sum += float(pnl_pct or 0.0)
        except Exception:
            pass
        try:
            if r_multiple is not None:
                r_vals.append(float(r_multiple))
        except Exception:
            pass
        try:
            tags = json.loads(str(tags_json or "[]"))
            if isinstance(tags, list):
                for t in tags:
                    k = str(t).strip().lower()
                    if k:
                        tags_count[k] = tags_count.get(k, 0) + 1
        except Exception:
            pass
        sym = str(symbol or "").upper().strip()
        if sym:
            sym_trade_count[sym] = sym_trade_count.get(sym, 0) + 1

    total = wins + losses + be
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
    avg_r = (sum(r_vals) / len(r_vals)) if r_vals else 0.0
    top_tags = sorted(tags_count.items(), key=lambda x: (-x[1], x[0]))[:4]
    tags_text = ", ".join(f"{k} x{v}" for k, v in top_tags) if top_tags else "нема"
    top_syms = sorted(sym_trade_count.items(), key=lambda x: (-x[1], x[0]))[:4]
    syms_text = ", ".join(f"{k} ({v})" for k, v in top_syms) if top_syms else "нема"

    return (
        "Тижневий зріз (останні 7 діб, закриті):\n"
        f"Угод: {total} | W {wins} · L {losses} · BE {be} | WR {wr:.1f}%\n"
        f"PnL сумарно: {pnl_sum:+.2f}% | Avg R: {avg_r:+.2f}\n"
        f"Топ помилок: {tags_text}\n"
        f"Найчастіші символи: {syms_text}"
    )


def _journal_today_loss_count(db_path: str) -> int:
    try:
        is_pg = str(db_path).lower().startswith("postgres://") or str(db_path).lower().startswith("postgresql://")
        if is_pg:
            if psycopg is None:
                return 0
            with psycopg.connect(db_path) as conn:  # type: ignore[arg-type]
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM trade_journal
                        WHERE status = 'CLOSED'
                          AND UPPER(TRIM(COALESCE(outcome, ''))) = 'LOSS'
                          AND LEFT(COALESCE(ts_close_utc, ''), 10) = TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD')
                        """
                    )
                    row = cur.fetchone()
                    return int(row[0]) if row and row[0] is not None else 0
        dbp = db_path
        if str(dbp).lower().startswith("sqlite:///"):
            dbp = str(dbp)[10:]
        with sqlite3.connect(dbp) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM trade_journal
                WHERE status = 'CLOSED'
                  AND UPPER(TRIM(COALESCE(outcome, ''))) = 'LOSS'
                  AND date(ts_close_utc) = date('now')
                """
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def parse_signal(text: str, msg_id: int) -> OfficeSignal:
    up = (text or "").upper()
    symbol = _extract_first_usdt_symbol(text)

    direction = "LONG"
    short_tokens = ("SHORT", "SELL", "ШОРТ", "ПРОДАЖ", "🔴")
    long_tokens = ("LONG", "BUY", "ЛОНГ", "КУПІВЛ", "🟢")
    if any(tok in up for tok in short_tokens):
        direction = "SHORT"
    elif any(tok in up for tok in long_tokens):
        direction = "LONG"
    score = 12
    rr = 2.0
    vol = 1.8
    news_risk = "SAFE"
    mins_to_event = 999
    up = text.upper()
    if "CPI" in up or "FOMC" in up or "NFP" in up:
        news_risk = "HIGH"
        mins_to_event = 30
    elif "NEWS" in up:
        news_risk = "RISK"
        mins_to_event = 90
    entry_price = _extract_price_hint(text, ("entry", "вхід", "вход", "buy", "sell"))
    stop_loss = _extract_price_hint(text, ("stop", "sl", "стоп"))
    take_profit = _extract_price_hint(text, ("take", "tp", "тейк"))
    return OfficeSignal(
        signal_id=f"relay-{msg_id}",
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        score=score,
        session="LONDON",
        regime="TREND",
        source_text=text[:1200],
        meta={
            "source": "wizard_relay",
            "rr": rr,
            "volatility_pct": vol,
            "news_risk": news_risk,
            "minutes_to_event": mins_to_event,
            "is_whitelist": True,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        },
    )


def extract_symbols(text: str) -> List[str]:
    """
    Extract likely trading symbols from user text.
    Supports explicit XXXUSDT and short aliases like BTC, ETH, SOL.
    """
    up = str(text or "").upper()
    found: List[str] = []
    seen: set[str] = set()

    for sym in re.findall(r"\b[A-Z]{2,10}USDT\b", up):
        if sym not in seen:
            seen.add(sym)
            found.append(sym)

    aliases = {
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "BNB": "BNBUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
        "ADA": "ADAUSDT",
        "LINK": "LINKUSDT",
        "AVAX": "AVAXUSDT",
        "DOT": "DOTUSDT",
        "SXT": "SXTUSDT",
    }
    for key, sym in aliases.items():
        if re.search(rf"\b{re.escape(key)}\b", up) and sym not in seen:
            seen.add(sym)
            found.append(sym)
    for raw_ticker, pair_sym in _CHAT_USDT_PAIR_ALIASES.items():
        if re.search(rf"\b{re.escape(raw_ticker)}\b", up) and pair_sym not in seen:
            seen.add(pair_sym)
            found.append(pair_sym)
    return found


def detect_agent_from_text(text: str) -> str:
    t = str(text or "").lower()
    mapping = {
        "daryna": ["дарин"],
        "maks": ["макс"],
        "marichka": ["марічк"],
        "news": ["назар"],
        "marko": ["марко"],
        "olesya": ["олес"],
        "memory": ["софі"],
        "psych": ["віктор"],
        "dev": ["артем"],
    }
    for agent, patterns in mapping.items():
        for p in patterns:
            if p in t:
                return agent
    return "lev"


def is_trade_feedback(text: str) -> bool:
    t = str(text or "").lower()
    has_symbol = bool(
        re.search(r"\b[a-z0-9]{2,10}usdt\b", t)
        or any(a in t for a in ["btc", "eth", "sol", "bnb", "xrp", "ada", "dot", "avax"])
    )
    has_result = any(
        k in t
        for k in [
            "відпрацював",
            "не відпрацював",
            "вибило",
            "стоп вибило",
            "в плюс",
            "в мінус",
            "профіт",
            "збиток",
            "закрили",
            "закрив",
            "+%",
            "-%",
        ]
    )
    return has_symbol and has_result


def _kb_session_label() -> str:
    try:
        tz = _briefing_tzinfo()
        h = datetime.now(tz).hour
        if 0 <= h < 9:
            return "ASIA"
        if 9 <= h < 17:
            return "LONDON"
        return "NY"
    except Exception:
        return ""


def parse_tetiana_journal_kb_voice(text: str) -> Optional[Dict[str, Any]]:
    """
    Розпізнавання коротких голосових формул Тетяни для бібліотеки угод
    (окремо від trade_journal / journal_add_feedback).
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if ("закрила" in low or "закрив" in low) and any(
        x in low for x in ("прибут", "профит", "профіт", "плюс")
    ):
        return {"kind": "close", "result": "WIN"}
    if "вибило" in low and ("стоп" in low or "стопу" in low):
        return {"kind": "close", "result": "LOSS"}
    if not any(
        k in low
        for k in (
            "зайшла",
            "зашла",
            "зайшов",
            "зашов",
            "заходжу",
            "заходим",
            "взяла",
            "взяв",
            "зайшли",
        )
    ):
        return None
    syms = extract_symbols_list(raw) or extract_symbols(raw)
    sym = (syms[0] if syms else "").strip().upper()
    if sym and not sym.endswith("USDT"):
        sym = normalize_symbol(sym)
    if not sym:
        return None
    if "лонг" in low or "long" in low:
        direction = "LONG"
    elif "шорт" in low or "short" in low:
        direction = "SHORT"
    else:
        return None
    m = re.search(r"(?:від|от)\s*([\d\s.,]+)", low)
    entry: Optional[float] = None
    if m:
        try:
            entry = float(str(m.group(1)).replace(" ", "").replace(",", "."))
        except Exception:
            entry = None
    return {"kind": "open", "symbol": sym, "direction": direction, "entry_price": entry}


def _feedback_result(text: str) -> str:
    low = str(text or "").lower()
    win_keys = ("відпрацював", "взяли", "тейк", "tp", "профіт", "в плюс", "відмінно")
    loss_keys = ("не відпрацював", "вибило", "стоп", "sl", "збиток", "в мінус", "провалився")
    if any(k in low for k in win_keys) and not any(k in low for k in loss_keys):
        return "WIN"
    if any(k in low for k in loss_keys) and not any(k in low for k in win_keys):
        return "LOSS"
    if "tp1" in low or "частк" in low:
        return "PARTIAL"
    return "PARTIAL"


def is_symbol_only(text: str) -> bool:
    """
    True if text contains only a single coin/pair token.
    Examples: BTC, ETH, SOLUSDT, SOL USDT, COMP, ORDI.
    """
    t = str(text or "").strip().upper()
    if not t:
        return False
    clean = re.sub(r"\s*(USDT|BUSD|USD)?\s*$", "", t).strip()
    clean = clean.replace(" ", "")
    return bool(re.match(r"^[A-Z0-9]{2,10}$", clean))


def normalize_symbol(text: str) -> str:
    """BTC -> BTCUSDT, SOL USDT -> SOLUSDT."""
    t = str(text or "").strip().upper()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"(USDT|BUSD|USD)$", "", t)
    if not t:
        return "BTCUSDT"
    return f"{t}USDT"


def extract_symbols_list(text: str) -> List[str]:
    parts = re.split(r"[,\s]+", str(text or "").strip().upper())
    symbols: List[str] = []
    seen: set[str] = set()
    for p in parts:
        token = str(p or "").strip()
        if not token:
            continue
        clean = re.sub(r"(USDT|BUSD|USD)$", "", token)
        if clean in _CHAT_USDT_PAIR_ALIASES:
            sym = _CHAT_USDT_PAIR_ALIASES[clean]
        elif re.match(r"^[A-Z0-9]{2,10}$", clean) and len(clean) >= 2:
            sym = f"{clean}USDT"
        else:
            continue
        if sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    return symbols[:3]


def _parse_signal_levels_from_text(text: str) -> Dict[str, Optional[float]]:
    """Обгортка: канонічний парсер у office_level_parse."""
    return parse_signal_levels_from_text(text)


def _history_reset() -> None:
    global _chat_history, _chat_history_ts
    _chat_history = []
    _chat_history_ts = 0.0


def _history_add(role: str, content: str) -> None:
    global _chat_history, _chat_history_ts
    txt = str(content or "").strip()
    if role not in ("user", "assistant") or not txt:
        return
    _chat_history.append({"role": role, "content": txt[:2000]})
    if len(_chat_history) > MAX_HISTORY:
        _chat_history = _chat_history[-MAX_HISTORY:]
    _chat_history_ts = time.time()


def _history_prepare() -> List[Dict[str, str]]:
    global _chat_history, _chat_history_ts
    now = time.time()
    if _chat_history_ts > 0 and (now - _chat_history_ts) > HISTORY_TTL_SEC:
        _history_reset()
    return list(_chat_history)


async def full_auto_analysis(
    symbol: str,
    sender,
    db_path: str,
    *,
    watching_signal_id: Optional[str] = None,
    reply_to_user: bool = True,
) -> bool:
    """
    Full automatic desk analysis for a symbol when user sends symbol-only text.

    Returns True if an existing WATCHING row was expired (Lev SKIP — зупинка циклу).
    Проактивний скан/зона: без LLM і без Telegram (reply_to_user=False).
    """
    if not reply_to_user:
        print(f"[desk] skip proactive LLM/Telegram for {symbol}")
        return False
    analyzing_hint: Optional[asyncio.Task] = None

    async def _analyzing_after_delay() -> None:
        await asyncio.sleep(10.0)
        await sender(f"🔍 Аналізую {symbol}...")

    analyzing_hint = asyncio.create_task(_analyzing_after_delay())
    try:
        try:
            from office_market_data import (
                fetch_atr_context,
                fetch_candles,
                fetch_funding_rate,
                fetch_key_levels,
                fetch_liquidations_proxy,
                fetch_long_short_ratio,
                fetch_market_regime,
                fetch_open_interest,
                fetch_ote_levels,
                fetch_probability_score,
            )
        except Exception as exc:
            await agent_say(sender, "lev", f"Не можу підняти модулі аналізу для {symbol}: {exc}")
            return False

        try:
            candles_1h = fetch_candles(symbol, "1h", 5)
            candles_4h = fetch_candles(symbol, "4h", 5)
            atr = fetch_atr_context(symbol)
            oi = fetch_open_interest(symbol)
            liq = fetch_liquidations_proxy(symbol)
            ls = fetch_long_short_ratio(symbol)
            levels = fetch_key_levels(symbol)
            ote = fetch_ote_levels(symbol, "1h")
            funding = fetch_funding_rate(symbol)
        except Exception as exc:
            await agent_say(sender, "lev", f"Не змогла зібрати ринкові дані по {symbol}: {exc}")
            return False

        def _tf_snapshot(label: str, candles: Any) -> str:
            if not isinstance(candles, list) or len(candles) < 2:
                return f"{label}: n/a"
            try:
                last_price = float((candles[-1] or {}).get("close"))
                prev_price = float((candles[-2] or {}).get("close"))
                if prev_price == 0:
                    return f"{label}: {last_price:.6f} (+0.0%)"
                change = (last_price - prev_price) / prev_price * 100.0
                return f"{label}: {last_price:.6f} ({change:+.1f}%)"
            except Exception:
                return f"{label}: n/a"

        system = f"{LEV_RULE}"
        current_price = liq.get("current_price") if isinstance(liq, dict) else None
        h1_snapshot = _tf_snapshot("H1", candles_1h)
        h4_snapshot = _tf_snapshot("H4", candles_4h)
        context = (
            f"Монета: {symbol}\n\n"
            f"Поточна ціна: {current_price}\n\n"
            f"ATR стан: {(atr.get('assessment') if isinstance(atr, dict) else None)}\n"
            f"Пройдено за день: {(atr.get('day_used_pct') if isinstance(atr, dict) else None)}%\n\n"
            f"Funding: {(funding.get('funding_rate_pct') if isinstance(funding, dict) else None)}%\n\n"
            f"OI тренд: {(oi.get('history', []) if isinstance(oi, dict) else [])}\n\n"
            f"Long/Short: {(ls.get('current_ratio') if isinstance(ls, dict) else None)}\n\n"
            f"Ліквідності:\n"
            f"Зверху: {(liq.get('liq_zone_above') if isinstance(liq, dict) else None)}\n"
            f"Знизу: {(liq.get('liq_zone_below') if isinstance(liq, dict) else None)}\n\n"
            f"Ключові рівні: {(levels.get('levels', []) if isinstance(levels, dict) else [])}\n\n"
            f"OTE зона: {ote}\n\n"
            f"{h1_snapshot}\n"
            f"{h4_snapshot}\n"
            f"current_price: {current_price}\n"
        )
        try:
            prob = fetch_probability_score(symbol, db_path)
            regime = fetch_market_regime(symbol)
            context += f"""
    Додаткові дані:
    Хто контролює: {regime.get('controller', '')}
    Очікувана цінність (EV): {prob.get('expected_value', '')}
    EV позитивне: {prob.get('ev_positive', '')}
    Ймовірність маніпуляції: {prob.get('sweep_probability', '')}%
    Ймовірність фейкового пробою: {prob.get('fake_breakout_prob', '')}%
    """
        except Exception:
            pass
        print(f"[debug] lev context tail: {context[-300:]}")
        response = clean_llm_note(
            ask_agent("lev", system, context, max_tokens=3000, db_path=db_path)
        )
        if response:
            # Повна відповідь для парсингу рівнів (обрізка до N рядків лише для Telegram).
            response_for_parse = response
            lines = response.split('\n')
            lines = [l for l in lines if l.strip()]
            if len(lines) > 16:
                response_send = '\n'.join(lines[:16])
            else:
                response_send = response
            _sent = False
            if not _sent:
                msg_out = response_send
                if len(msg_out) > 3900:
                    msg_out = msg_out[:3897] + "..."
                await agent_say(sender, "lev", msg_out)
                _sent = True

            no_entry_phrases = [
                "не входжу",
                "не входимо",
                "пропуск",
                "пропускаю",
                "пропускаємо",
                "немає входу",
                "no entry",
            ]

            levels = apply_zone_sanity(
                _parse_signal_levels_from_text(response_for_parse),
                current_price,
            )
            parsed = levels
            if levels.get("entry_low"):
                print(f"[signal] {symbol} levels OK: {levels}")
            else:
                print(f"[signal] {symbol} no levels in response")
            low_resp = response_for_parse.lower()
            if any(p in low_resp for p in no_entry_phrases):
                if watching_signal_id and should_keep_watching_on_skip():
                    if parsed.get("entry_low") is not None:
                        gate_keep = apply_skip_watching_gate(
                            db_path,
                            symbol=symbol,
                            direction="SHORT"
                            if ("SHORT" in response_for_parse.upper() or "ШОРТ" in response_for_parse.upper())
                            else "LONG",
                            entry_low=parsed.get("entry_low"),
                            entry_high=parsed.get("entry_high") or parsed.get("entry_low"),
                            timeframe="1h",
                            now_ts=time.time(),
                            current_price=current_price,
                        )
                        record_skip_if_valid(
                            db_path,
                            gate_keep,
                            symbol=symbol,
                            timeframe="1h",
                        )
                print(f"[desk] {symbol}: Lev SKIP — WATCHING stays, Olesya silent")
                return True
                # T3: новий WATCHING після SKIP лише якщо сценарій ще не скіпали і зони немає.
                if parsed.get("entry_low") is not None:
                    correlation = check_portfolio_correlation(db_path)
                    if not correlation.get("safe"):
                        await agent_say(sender, "daryna", correlation["message"])
                        return False
                    direction_watch = "LONG"
                    up_watch = response_for_parse.upper()
                    if "SHORT" in up_watch or "ШОРТ" in up_watch:
                        direction_watch = "SHORT"
                    elif "LONG" in up_watch or "ЛОНГ" in up_watch:
                        direction_watch = "LONG"
                    now_ts = time.time()
                    gate = apply_skip_watching_gate(
                        db_path,
                        symbol=symbol,
                        direction=direction_watch,
                        entry_low=parsed.get("entry_low"),
                        entry_high=parsed.get("entry_high") or parsed.get("entry_low"),
                        timeframe="1h",
                        now_ts=now_ts,
                        current_price=current_price,
                    )
                    if gate.get("create"):
                        signal_id = f"watch-{symbol}-{int(now_ts)}"
                        signal_upsert(
                            db_path,
                            signal_id=signal_id,
                            symbol=symbol,
                            direction=direction_watch,
                            entry_low=parsed.get("entry_low"),
                            entry_high=parsed.get("entry_high") or parsed.get("entry_low"),
                            sl=parsed.get("sl"),
                            tp1=parsed.get("tp1"),
                            tp2=parsed.get("tp2"),
                            rr=parsed.get("rr"),
                            status="WATCHING",
                            analysis_note=response_for_parse,
                        )
                        print(
                            f"[desk] {symbol} WATCHING zone "
                            f"{parsed.get('entry_low')}–{parsed.get('entry_high') or parsed.get('entry_low')} (Telegram silent)"
                        )
                    else:
                        print(f"[relay] T3 skip duplicate WATCHING {symbol} key={gate.get('key')}")
                    record_skip_if_valid(
                        db_path,
                        gate,
                        symbol=symbol,
                        timeframe="1h",
                    )
                return False
            if parsed.get("entry_low") is not None and parsed.get("sl") is not None and (
                parsed.get("tp1") is not None or parsed.get("tp2") is not None
            ):
                candles_check = fetch_candles(symbol, "1h", 1)
                if not candles_check:
                    await sender(f"{symbol} — символ не знайдено на Binance.")
                    return False
                direction = "LONG"
                up = response_for_parse.upper()
                if "SHORT" in up or "ШОРТ" in up:
                    direction = "SHORT"
                elif "LONG" in up or "ЛОНГ" in up:
                    direction = "LONG"
                correlation = check_portfolio_correlation(db_path)
                if not correlation.get("safe"):
                    await agent_say(sender, "daryna", correlation["message"])
                    return False
                from office_legacy_guard import legacy_requires_lev, legacy_scenario_status, lev_cycle_for_symbol

                manual_cycle: Dict[str, Any] = {}
                if legacy_requires_lev():
                    manual_cycle = await asyncio.to_thread(lev_cycle_for_symbol, db_path, symbol, None)
                legacy = legacy_scenario_status(manual_cycle, direction=direction, enforce=legacy_requires_lev())
                signal_id = f"manual-{symbol}-{int(time.time())}"
                signal_upsert(
                    db_path,
                    signal_id=signal_id,
                    symbol=symbol,
                    direction=direction,
                    entry_low=parsed.get("entry_low"),
                    entry_high=parsed.get("entry_high"),
                    sl=parsed.get("sl"),
                    tp1=parsed.get("tp1"),
                    tp2=parsed.get("tp2"),
                    rr=parsed.get("rr"),
                    status=legacy["status"],
                    analysis_note=(legacy["note_prefix"] + response_for_parse)[:4000],
                )
                if legacy["status"] != "ACTIVE":
                    print(f"[signal] {symbol} manual LLM levels → WATCHING: {legacy['reason']}")
            print(f"[signal] saved {symbol} {direction} (Olesya journal silent)")
        else:
            await agent_say(sender, "lev", f"По {symbol} зараз немає повної відповіді від LLM. Спробуй ще раз через хвилину.")
        return False

    finally:
        if analyzing_hint is not None and not analyzing_hint.done():
            analyzing_hint.cancel()

async def office_free_chat(
    sender,
    text: str,
    db_path: str,
) -> None:
    history = _history_prepare()
    _history_add("user", text)

    symbols_batch = extract_symbols_list(text)
    if len(symbols_batch) >= 2:
        parts = [p for p in re.split(r"[,\s]+", str(text or "").strip().upper()) if p]
        if parts and len(parts) == len(symbols_batch):
            for sym in symbols_batch:
                await full_auto_analysis(sym, sender, db_path)
            return
    if is_symbol_only(text):
        symbol = normalize_symbol(text)
        await full_auto_analysis(symbol, sender, db_path)
        return

    kb_voice = parse_tetiana_journal_kb_voice(text)
    if kb_voice:
        try:
            if kb_voice.get("kind") == "open":
                sym = str(kb_voice.get("symbol") or "").strip().upper()
                direc = str(kb_voice.get("direction") or "").strip().upper()
                entry_p = kb_voice.get("entry_price")
                rid = trade_journal_add(
                    db_path,
                    symbol=sym,
                    direction=direc,
                    entry_price=entry_p,
                    session=_kb_session_label(),
                    source_text=text[:500],
                )
                await agent_say(
                    sender,
                    "olesya",
                    f"Занесла {sym} {direc} у бібліотеку угод (запис #{rid or '—'}).",
                    0.06,
                )
                if rid and sym and direc:
                    sim = [
                        s
                        for s in trade_journal_search_similar(db_path, sym, direc, limit=10)
                        if int(s.get("id") or 0) != int(rid)
                    ][:6]
                    if sim:
                        sim_txt = "\n".join(
                            f"· {s.get('symbol')} {s.get('direction')} → {s.get('result') or 'відкрито'} "
                            f"(вхід {s.get('entry_price')}, закриття {s.get('ts_closed') or '—'})"
                            for s in sim
                        )
                        ctx_mem = f"Останній запис Тетяни: {sym} {direc}, вхід {entry_p}.\nСхожі з бібліотеки:\n{sim_txt}"
                        sof = clean_llm_note(
                            ask_agent(
                                "memory",
                                "Ти Софія. Дві короткі фрази українською: що повторюється в історії і на що звернути увагу.",
                                ctx_mem,
                                max_tokens=220,
                                db_path=db_path,
                            )
                        )
                        if sof:
                            await agent_say(sender, "memory", sof, 0.08)
            elif kb_voice.get("kind") == "close":
                res = str(kb_voice.get("result") or "LOSS").upper()
                auto_lesson = (
                    "Закриття з прибутком — закріплюємо дисципліну входу."
                    if res == "WIN"
                    else "Стоп — пауза, без відіграшу і без форсу наступного входу."
                )
                rid = trade_journal_add(
                    db_path,
                    finalize_last=True,
                    result=res,
                    lesson=auto_lesson,
                    source_text=text[:500],
                )
                if rid:
                    await agent_say(sender, "olesya", "Оновила запис у бібліотеці: результат зафіксовано.", 0.06)
                    recent0 = trade_journal_get_recent(db_path, 1)
                    row = recent0[0] if recent0 else {}
                    sym = str(row.get("symbol") or "").strip().upper()
                    direc = str(row.get("direction") or "").strip().upper()
                    if sym and direc:
                        sim = [
                            s
                            for s in trade_journal_search_similar(db_path, sym, direc, limit=10)
                            if s.get("result")
                        ][:6]
                        if sim:
                            sim_txt = "\n".join(
                                f"· {s.get('symbol')} {s.get('direction')} → {s.get('result')} "
                                f"(pnl% {s.get('pnl_pct')}, урок: {(s.get('lesson') or '')[:80]})"
                                for s in sim
                            )
                            ctx_mem = f"Щойно закрито: {sym} {direc} як {res}.\nСхожі закриті угоди:\n{sim_txt}"
                            sof = clean_llm_note(
                                ask_agent(
                                    "memory",
                                    "Ти Софія. Дві короткі фрази українською: що вже було в схожих кейсах.",
                                    ctx_mem,
                                    max_tokens=220,
                                    db_path=db_path,
                                )
                            )
                            if sof:
                                await agent_say(sender, "memory", sof, 0.08)
                else:
                    await agent_say(
                        sender,
                        "olesya",
                        "Не знайшла відкритого запису в бібліотеці — спочатку напиши вхід (зайшла … LONG/SHORT …).",
                        0.08,
                    )
        except Exception as exc_kb:
            print(f"[journal-kb] {exc_kb}")
            await agent_say(sender, "olesya", "Не вдалося записати в бібліотеку — перевір формат повідомлення.", 0.08)
        return

    if is_trade_feedback(text):
        symbol = _extract_first_usdt_symbol(text)
        if not symbol:
            syms = extract_symbols(text)
            if syms:
                symbol = syms[0]
        if not symbol:
            symbol = "BTCUSDT"
        agent_suggested = detect_agent_from_text(text)
        result = _feedback_result(text)
        result_lit: Literal["WIN", "LOSS", "PARTIAL"] = "PARTIAL"
        if result == "WIN":
            result_lit = "WIN"
        elif result == "LOSS":
            result_lit = "LOSS"
        learning_note = ""
        if result == "LOSS":
            learning_note = "Минулий кейс завершився стопом: наступний вхід тільки після підтвердження і без форсу."
        elif result == "WIN":
            learning_note = "Минулий кейс дав профіт: повторюємо дисципліну і точний таймінг входу."
        else:
            learning_note = "Минулий кейс частково відпрацював: далі працюємо від підтвердження продовження."
        saved = journal_add_feedback(
            db_path=db_path,
            symbol=symbol,
            result=result_lit,
            agent_suggested=agent_suggested,
            feedback_text=text,
            feedback_source="tetiana",
            learning_note=learning_note,
        )
        if saved:
            await agent_say(sender, "olesya", "Зафіксувала. Додаю в базу для навчання.")
        else:
            await agent_say(sender, "olesya", f"Прийняла фідбек по {symbol}, але не знайшла кейс у журналі. Перевір symbol/угоду.")
        return

    language_block = (
        "МОВА: Говориш ВИКЛЮЧНО українською. Це абсолютне правило. "
        "Заборонені слова: сейчас, растет, ничего/ничого, беспокоит/беспокоїть, "
        "можно, нормально (рос), нет (рос), вчорашній (неправильна відмінка), "
        "будь-які інші російські слова. "
        "Якщо думка прийшла російською — перекладай правильною українською."
    )
    personalities = {
        "lev": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Ти Лев — голова столу. Спокійний, впевнений; з Тетяною говориш як з партнером, не як з інструкцією."
        ),
        "maks": (
            f"{DESK_BASE_RULE}"
            f"{language_block}\n"
            "Ти Макс — твій стиль як у радара: помітив дивне в цифрах — сказав; якщо все рівно — не розводиш."
        ),
        "marichka": (
            f"{MARICHKA_RULE}"
            f"{language_block}\n"
            "Ти Марічка — говориш просто, образами; як подруга, яка дивиться на графік разом з Тетяною."
        ),
        "daryna": (
            f"{DESK_BASE_RULE}"
            f"{language_block}\n"
            "Ти Дарина — скеля: тепло не втрачаєш, але про ризик говориш прямо. "
            "Якщо питають про відкриті позиції чи PnL — чесно: зараз цього в чаті не видно, глянь Mini App."
        ),
        "marko": (
            f"{DESK_BASE_RULE}"
            f"{language_block}\n"
            "Ти Марко — людина-дія: що робити зараз, куди дивитись, без зайвих абзаців."
        ),
        "news": (
            f"{DESK_BASE_RULE}"
            f"{language_block}\n"
            "Ти Назар — як у кого календар у голові: коротко «тихо» або «тут уважно», без лекцій."
        ),
        "olesya": (
            f"{OLESYA_RULE}\n"
            f"{language_block}\n"
        ),
        "memory": (
            f"{DESK_BASE_RULE}"
            f"{language_block}\n"
            "Ти Софія — пам'ять офісу: нагадуєш історію людською мовою, без сухих таблиць. "
            "Про відкриті позиції / точний PnL у чаті не вигадуй — відсилай до Mini App."
        ),
        "psych": (
            f"{VICTOR_RULE}\n"
            f"{language_block}\n"
        ),
        "dev": (
            f"{ARTEM_RULE}"
            f"{language_block}\n"
            "Ти Артем — свій у техніці: якщо все ок, кажеш коротко; якщо ні — без паніки, по кроках."
        ),
    }

    market_context = ""
    low = str(text or "").lower()
    if any(w in low for w in ("btc", "біток", "ринок", "ціна", "тренд", "сигнал", "позиція")):
        try:
            from office_market_data import fetch_candles, fetch_liquidations_proxy

            symbols = list(extract_symbols(text))
            if not symbols:
                symbols = list(extract_symbols_list(text))
            if not symbols and "позиція" in low:
                act_mc = signal_get_active(db_path)
                if act_mc:
                    s0 = str(act_mc[0].get("symbol") or "").strip().upper()
                    if s0:
                        symbols = [s0]
            if not symbols:
                symbols = ["BTCUSDT"]
            lines: List[str] = ["Поточний контекст ринку:"]
            for sym in symbols:
                liq = fetch_liquidations_proxy(sym)
                candles = fetch_candles(sym, "4h", 3)
                if not isinstance(candles, list) or not candles:
                    lines.append(f"{sym}: немає даних з Binance")
                    continue
                px = liq.get("current_price", "невідомо") if isinstance(liq, dict) else "невідомо"
                lines.append(f"{sym} ціна: {px}")
                lines.append(f"{sym} H4 свічки: {candles}")
            market_context = "\n".join(lines)
        except Exception:
            market_context = ""

    context = (
        "Контекст: Ти в AI Trading Desk — торговий офіс крипто ф'ючерсів на Binance Futures.\n"
        "'Позиції' = відкриті торгові угоди, не вакансії компанії.\n\n"
        "Тетяна написала в офіс:\n"
        f"\"{text}\"\n\n"
        f"{market_context}\n\n"
        "Відповідь має бути голосом правильного агента."
    )
    symbols_in_text = extract_symbols_list(text)
    if symbols_in_text:
        active_by_symbol = signal_get_by_symbol(db_path, symbols_in_text[0])
        if active_by_symbol:
            context = (
                f"Активна позиція Тетяни: {active_by_symbol.get('symbol')} {active_by_symbol.get('direction')}\n"
                f"Entry: {active_by_symbol.get('entry_low')}\n"
                f"SL: {active_by_symbol.get('sl')}\n"
                f"TP1: {active_by_symbol.get('tp1')}\n"
                + context
            )
        else:
            # Пам'ять про вже закритий/неактивний сигнал по символу: щоб Лев не казав
            # "сетапу немає", коли позиція щойно закрита по стопу або згоріла.
            last_sig = signal_get_latest_by_symbol(db_path, symbols_in_text[0])
            if last_sig:
                status_ua = {
                    "ACTIVE": "позиція активна",
                    "HIT_ENTRY": "вхід відбувся, позиція активна",
                    "HIT_TP1": "перша ціль взята",
                    "HIT_TP2": "позиція закрита в плюс (друга ціль)",
                    "HIT_SL": "позиція закрита по стопу",
                    "EXPIRED": "сигнал згорів без входу",
                }.get(
                    str(last_sig.get("status") or "").upper(),
                    str(last_sig.get("status") or "невідомо"),
                )
                context = (
                    f"Раніше по {last_sig.get('symbol')} був сигнал {last_sig.get('direction')}: "
                    f"Entry {last_sig.get('entry_low')}-{last_sig.get('entry_high')}, "
                    f"SL {last_sig.get('sl')}, TP1 {last_sig.get('tp1')}, TP2 {last_sig.get('tp2')}. "
                    f"Статус: {status_ua} "
                    f"(час {last_sig.get('ts_updated') or last_sig.get('ts_created')}). "
                    "Тетяна питає саме про цю угоду — відповідай у її контексті, "
                    "не кажи що сетапу немає.\n"
                    + context
                )
    if not symbols_in_text:
        active = signal_get_active(db_path)
        if active:
            last_symbol = str(active[0].get("symbol", "") or "").strip().upper()
            if last_symbol:
                context = (
                    f"Активна позиція Тетяни: {last_symbol} {active[0].get('direction')}\n"
                    f"Entry: {active[0].get('entry_low')}\n"
                    f"SL: {active[0].get('sl')}\n"
                    f"TP1: {active[0].get('tp1')}\n"
                    + context
                )
    chosen_agent = detect_agent_from_text(text)
    if chosen_agent == "lev":
        if time.time() - _lev_last_response.get("lev", 0) < 30:
            return
        _lev_last_response["lev"] = time.time()
    answer_system = (
        f"{personalities.get(chosen_agent, personalities['lev'])}\n\n"
        "Ти в Telegram груповому чаті офісу. Без таблиць, без ## заголовків.\n"
        "Звертайся до Тетяни по імені. Відповідай природно як людина."
    )
    if chosen_agent == "lev":
        answer_system += (
            "\nДва окремі інструменти на Binance Futures: UBUSDT і BUSDT (тікер саме BUSDT, не BUUSDT). "
            "Якщо в тексті UB / UBUSDT — дані та сетап по UBUSDT. "
            "Якщо BUSDT — по BUSDT. Не змішуй ціни й entry між ними."
        )
    free_chat_tokens = 1200 if chosen_agent == "lev" else 2000
    response = clean_llm_note(
        ask_agent(
            chosen_agent,
            answer_system,
            context,
            max_tokens=free_chat_tokens,
            messages_history=history,
            db_path=db_path,
        )
    )
    if chosen_agent == "lev" and response:
        lines = [l for l in response.split('\n') if l.strip()]
        if len(lines) > 18:
            response = '\n'.join(lines[:18])
        tail_needed = response.rstrip().endswith(("…", "...")) or response.rstrip().lower().endswith(
            (" зі", " далі", "далі…", "далі...")
        )
        if tail_needed:
            tail = clean_llm_note(
                ask_agent(
                    "lev",
                    answer_system,
                    context + "\n\nЗаверши попередню думку одним коротким реченням: що робити зараз.",
                    max_tokens=120,
                    db_path=db_path,
                )
            )
            if tail:
                tail_line = str(tail).strip().split("\n")[0].strip()
                if tail_line:
                    response = f"{response}\n{tail_line}"
    if response:
        _history_add("assistant", f"{chosen_agent}: {response}")
        await agent_say(sender, chosen_agent, response)


def _env_int_set(name: str) -> set[int]:
    """
    Parse env like "123,456" into a set of ints.
    """
    raw = os.getenv(name, "").strip()
    out: set[int] = set()
    if not raw:
        return out
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except Exception:
            continue
    return out


def _env_int(name: str, default: int = 0) -> Optional[int]:
    """Число з env. Назва гілки («Загальний») не валить процес."""
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default or None
    try:
        v = int(raw)
    except ValueError:
        print(
            f"[relay][WARN] {name}={raw!r} не число — потрібен message_thread_id, "
            "не назва форуму. Ігнорую."
        )
        return default or None
    return v or None


async def pick_chats(client: TelegramClient) -> Tuple[int, int]:
    items: List[DialogItem] = []
    i = 1
    print("\n=== Вибери чати зі списку ===")
    async for d in client.iter_dialogs():
        title = (d.name or "").strip()
        if not title:
            continue
        items.append(DialogItem(i, d.id, title))
        try:
            print(f"[{i}] {title}  (id={d.id})")
        except UnicodeEncodeError:
            # Windows cp1251 console may fail on emoji in chat titles.
            safe_title = title.encode("cp1251", "replace").decode("cp1251", "replace")
            print(f"[{i}] {safe_title}  (id={d.id})")
        i += 1

    if len(items) < 2:
        raise RuntimeError("Замало чатів у списку.")

    def resolve_choice(label: str) -> DialogItem:
        raw = input(label).strip()
        if not raw:
            raise RuntimeError("Порожній ввід. Перезапусти і введи номер зі списку або chat_id.")

        # 1) Prefer list index like "[12] 12"
        try:
            as_int = int(raw)
        except ValueError:
            raise RuntimeError(f"Некоректне число: {raw!r}. Введи номер зі списку або chat_id.")

        by_idx = next((x for x in items if x.idx == as_int), None)
        if by_idx is not None:
            return by_idx

        # 2) Fallback: treat as Telegram chat_id (e.g. 8733881643 or -100123...)
        by_id = next((x for x in items if int(x.chat_id) == as_int), None)
        if by_id is not None:
            return by_id

        known_ids = ", ".join(str(x.chat_id) for x in items[:25])
        more = "" if len(items) <= 25 else " ..."
        raise RuntimeError(
            "Не знайшов такий чат у списку.\n"
            f"Ти ввела: {raw}\n"
            "Правильно:\n"
            "- або номер зліва в квадратних дужках `[N]`\n"
            "- або точний `id=...` з того ж списку\n"
            f"Приклади перших id: {known_ids}{more}"
        )

    main = resolve_choice("\nВведи номер MAIN чату (де сигнали) або chat_id: ")
    office = resolve_choice("Введи номер OFFICE чату (AI Office) або chat_id: ")
    return main.chat_id, office.chat_id


def _prompt(label: str, default: str = "") -> str:
    """Render/cloud: stdin не TTY — input() кидає EOFError і процес падає з exit 1."""
    try:
        if not sys.stdin.isatty():
            print("[relay] skip prompt (no TTY)")
            return default
        return input(label).strip()
    except EOFError:
        print("[relay] EOF on prompt; continue without input")
        return default


async def run() -> None:
    global _RELAY_OFFICE_STARTUP_PING_SENT
    print("=== AI Office Wizard ===")
    cfg_path = relay_config_path()
    cfg = load_relay_config()
    print(f"[relay] config file: {cfg_path.resolve()}")

    force_setup = os.getenv("RELAY_FORCE_SETUP", "").strip() == "1"
    interactive = os.getenv("RELAY_INTERACTIVE", "").strip() == "1"
    tg_bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
    if tg_bot_token:
        # Хмара: жодних input(), навіть якщо RELAY_INTERACTIVE=1.
        interactive = False
        print("[relay] cloud mode: prompts disabled (TG_BOT_TOKEN set)")
    has_saved = bool(cfg.get("tg_api_id") and cfg.get("tg_api_hash") and cfg.get("main_chat_id") and cfg.get("office_chat_id"))
    if has_saved and not force_setup and interactive:
        ans = _prompt("Знайдено збережені налаштування. Використати їх? (Y/n): ").lower()
        if ans and ans not in ("y", "yes", "д", "так"):
            preserved_tokens = cfg.get("agent_bot_tokens")
            cfg = {}
            if isinstance(preserved_tokens, dict) and preserved_tokens:
                cfg["agent_bot_tokens"] = preserved_tokens
            has_saved = False
    elif has_saved and not force_setup and not interactive:
        print("[relay] using saved config (set RELAY_INTERACTIVE=1 to confirm/override)")

    api_id_raw = (os.getenv("TG_API_ID", "").strip() or cfg.get("tg_api_id", "").strip())
    api_hash = (os.getenv("TG_API_HASH", "").strip() or cfg.get("tg_api_hash", "").strip())
    if not api_id_raw:
        api_id_raw = _prompt("TG_API_ID: ")
    if not api_hash:
        api_hash = _prompt("TG_API_HASH: ")

    api_id = int(api_id_raw)
    # Файл сесії Telethon: за замовчуванням поруч із кодом (як було). На Render там тимчасова ФС — сесія зникає при кожному
    # deploy і worker логіниться заново (FloodWait). OFFICE_RELAY_SESSION_PATH=/var/data/office_relay_wizard — постійний диск.
    session_name = os.getenv("OFFICE_RELAY_SESSION_PATH", "").strip() or "office_relay_wizard"
    try:
        _sdir = os.path.dirname(session_name)
        if _sdir:
            os.makedirs(_sdir, exist_ok=True)
        print(f"[relay] session file: {session_name}.session")
    except OSError as exc_sess:
        print(f"[relay] session dir {session_name}: {exc_sess} — беру стандартний шлях")
        session_name = "office_relay_wizard"
    db_path = (
        os.getenv("DATABASE_URL", "").strip()
        or os.getenv("OFFICE_DB_PATH", "office_bridge.db").strip()
        or "office_bridge.db"
    )

    client = TelegramClient(session_name, api_id, api_hash)
    while True:
        try:
            if tg_bot_token:
                # Non-interactive startup for cloud runtime (Render).
                await client.start(bot_token=tg_bot_token)
            else:
                # Local interactive mode (user account login via phone/code).
                await client.start()
            break
        except asyncio.CancelledError:
            print("[relay] shutdown during Telegram start")
            return
        except FloodWaitError as exc:
            wait_sec = int(getattr(exc, "seconds", 0) or 0)
            if wait_sec <= 0:
                wait_sec = 300
            wait_sec += 5
            print(f"[relay][WARN] FloodWait під час авторизації. Чекаю {wait_sec}с і пробую знову...")
            await asyncio.sleep(wait_sec)
        except Exception as exc:
            print(f"[relay][WARN] Telegram start failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(15)
    init_office_db(db_path)
    _db_ident = office_db_identity(db_path)
    print(
        f"[relay] DB identity: {_db_ident.get('backend')} "
        f"fingerprint={_db_ident.get('fingerprint')} "
        f"(звір з Mini App /api/summary → db_identity)"
    )
    memory_stores = await init_office_memory_stores()
    if memory_stores.get("lev"):
        print("[memory] Lev Memory Store is ready")
    if memory_stores.get("memory"):
        print("[memory] Sofia Memory Store is ready")
    _tzp = _briefing_tzinfo()
    _tzn = getattr(_tzp, "key", None) or ("UTC" if _tzp is timezone.utc else repr(_tzp))
    print(f"[relay] briefing TZ active: {_tzn} (OFFICE_BRIEFING_TZ; пакет tzdata у venv допомагає на Windows)")

    main_chat_id: int
    office_chat_id: int

    cloud_mode = bool(tg_bot_token)
    env_main = os.getenv("MAIN_CHAT_ID", "").strip()
    env_office = os.getenv("OFFICE_CHAT_ID", "").strip()
    if cloud_mode:
        # In cloud mode use only env vars to avoid stale local config IDs.
        main_raw = env_main
        office_raw = env_office
        if not (main_raw and office_raw):
            raise RuntimeError(
                "Cloud mode requires MAIN_CHAT_ID and OFFICE_CHAT_ID env vars. "
                "Set both in Render Environment."
            )
    else:
        main_raw = (env_main or str(cfg.get("main_chat_id", "") or "").strip())
        office_raw = (env_office or str(cfg.get("office_chat_id", "") or "").strip())
    if cloud_mode:
        # Env IDs already required above. RELAY_FORCE_SETUP не викликає pick_chats (input/EOF).
        main_chat_id = int(main_raw)
        office_chat_id = int(office_raw)
    elif force_setup or not (main_raw and office_raw):
        main_chat_id, office_chat_id = await pick_chats(client)
    else:
        repick = os.getenv("RELAY_REPICK_CHATS", "").strip() == "1"
        if interactive and not repick:
            reuse = _prompt(
                f"MAIN/OFFICE з конфігу:\n- MAIN={main_raw}\n- OFFICE={office_raw}\n"
                "Залишити як є? (Y/n): "
            ).lower()
            if reuse and reuse not in ("y", "yes", "д", "так"):
                main_chat_id, office_chat_id = await pick_chats(client)
            else:
                main_chat_id = int(main_raw)
                office_chat_id = int(office_raw)
        elif repick:
            main_chat_id, office_chat_id = await pick_chats(client)
        else:
            main_chat_id = int(main_raw)
            office_chat_id = int(office_raw)

    main_entity = await client.get_entity(main_chat_id)
    office_entity = await client.get_entity(office_chat_id)
    agent_bot_tokens: Dict[str, str] = {}
    try:
        agent_bot_tokens = load_agent_bot_tokens() or {}
    except Exception:
        agent_bot_tokens = {}
    agent_bot_usernames: Dict[str, str] = {}
    try:
        agent_bot_usernames = load_agent_bot_usernames()
    except Exception:
        agent_bot_usernames = {}
    bot_http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    me = await client.get_me()
    owner_user_id: Optional[int] = None
    owner_env = os.getenv("OFFICE_OWNER_USER_ID", "").strip()
    if owner_env:
        try:
            owner_user_id = int(owner_env)
        except Exception:
            owner_user_id = None
    if owner_user_id is None and not tg_bot_token:
        try:
            owner_user_id = int(getattr(me, "id", 0) or 0) or None
        except Exception:
            owner_user_id = None
    bot_user_ids: set[int] = set()
    for k in sorted(agent_bot_tokens.keys()):
        ok_chk, note_chk, bot_id = await check_bot_api_access(bot_http, agent_bot_tokens[k], office_chat_id)
        if bot_id is not None:
            bot_user_ids.add(int(bot_id))
    if tg_bot_token:
        ok_main, note_main, main_bot_id = await check_bot_api_access(bot_http, tg_bot_token, office_chat_id)
        if main_bot_id is not None:
            bot_user_ids.add(int(main_bot_id))
        _ = (ok_main, note_main)  # keep diagnostics side-effect without extra logging here
    print(f"\nMAIN={main_chat_id}")
    print(f"OFFICE={office_chat_id}")

    # Persist successful selections (local file next to this script).
    cfg.update(
        {
            "tg_api_id": str(api_id),
            "tg_api_hash": api_hash,
            "main_chat_id": str(main_chat_id),
            "office_chat_id": str(office_chat_id),
        }
    )
    save_relay_config(cfg)
    print(f"[relay] saved config -> {cfg_path.resolve()}")
    print("\nRelay запущено. Залиш це вікно відкритим.")

    mini_verify = os.getenv("OFFICE_MINI_VERIFY_URL", "").strip()
    if mini_verify and os.getenv("OFFICE_MINI_VERIFY_DISABLE", "").strip() != "1":
        fp_r = str(_db_ident.get("fingerprint") or "")
        surl = mini_verify.rstrip("/") + "/api/summary"
        try:
            async with bot_http.get(surl, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    print(f"[relay][WARN] Mini App verify HTTP {resp.status}: {surl}")
                else:
                    data = await resp.json()
                    di = data.get("db_identity") if isinstance(data, dict) else {}
                    di = di if isinstance(di, dict) else {}
                    fp_m = str(di.get("fingerprint") or "")
                    if fp_m and fp_r and fp_m.lower() == fp_r.lower():
                        print(
                            f"[relay][OK] Mini App fingerprint збігається з relay ({fp_r}) — MASTER п.17 (авто)"
                        )
                    else:
                        print(
                            f"[relay][WARN] Mini App fingerprint ≠ relay: mini={fp_m!r} relay={fp_r!r} · {surl}"
                        )
        except Exception as exc:
            print(f"[relay][WARN] Mini App verify недоступний ({surl}): {exc}")

    if agent_bot_tokens:
        print(f"[relay] multi-bot mode enabled for: {', '.join(sorted(agent_bot_tokens.keys()))}")
    else:
        print("[relay] multi-bot mode disabled (no AGENT_BOT_TOKEN_* found)")
    if agent_bot_tokens:
        seen_ids: Dict[int, str] = {}
        for k in sorted(agent_bot_tokens.keys()):
            ok_chk, note_chk, bot_id = await check_bot_api_access(bot_http, agent_bot_tokens[k], office_chat_id)
            if bot_id is not None and bot_id in seen_ids:
                print(f"[relay][WARN] duplicate token: {k} same bot_id as {seen_ids[bot_id]} ({bot_id})")
            elif bot_id is not None:
                seen_ids[bot_id] = k
            lvl = "OK" if ok_chk else "WARN"
            print(f"[relay][{lvl}] bot-check {k}: {note_chk}")

    if agent_bot_usernames:
        print(
            f"[relay] bot-to-bot usernames (AGENT_BOT_USERNAME_* / config): "
            f"{', '.join(sorted(agent_bot_usernames.keys()))}"
        )

    general_thread_id = _env_int("OFFICE_GENERAL_THREAD_ID")
    tasks_thread_id = _env_int("OFFICE_TASKS_THREAD_ID")
    tech_thread_id = _env_int("OFFICE_TECH_THREAD_ID")
    print(
        f"[relay] threads general={general_thread_id} tasks={tasks_thread_id} tech={tech_thread_id}"
    )

    def _thread_for_stream(stream: str) -> Optional[int]:
        s = str(stream or "general").strip().lower()
        if s == "tasks":
            return tasks_thread_id or general_thread_id
        if s == "tech":
            return tech_thread_id or general_thread_id
        return general_thread_id

    def _lev_risk_review(cycle: Dict[str, Any], sym: str, *, candles_ltf: Any, market_context: Any) -> Dict[str, Any]:
        """Risk Officer після Лева. Shadow: лише журнал. Enforce: помилка = WAIT (fail closed)."""
        from office_feed_quality import gate_send_on_fresh_data
        from office_risk_context import apply_risk_officer, enforce_enabled

        cycle = gate_send_on_fresh_data(cycle, candles_ltf, interval=_ltf_interval(candles_ltf))
        try:
            return apply_risk_officer(
                cycle, db_path=db_path, symbol=sym,
                candles_ltf=candles_ltf, market_context=market_context,
            )
        except Exception as exc:
            print(f"[risk] review error {sym}: {type(exc).__name__}: {exc}")
            if enforce_enabled() and cycle.get("send"):
                return {**cycle, "action": "WAIT", "send": False,
                        "reason": "ризик-контроль недоступний — план не передається"}
            return cycle

    def _ltf_interval(candles: Any) -> str:
        """Інтервал LTF за кроком часу двох останніх свічок (5m або 15m у викликах Лева)."""
        try:
            a = datetime.fromisoformat(str(candles[-2]["ts"]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(candles[-1]["ts"]).replace("Z", "+00:00"))
            step = int((b - a).total_seconds())
            return {60: "1m", 300: "5m", 900: "15m", 3600: "1h"}.get(step, "15m")
        except Exception:
            return "15m"

    def _lev_record_thesis(cycle: Dict[str, Any], candles_by_tf: Dict[str, Any]) -> None:
        """Версія тези Лева в журнал. Помилка журналу не змінює рішення."""
        try:
            from office_thesis_journal import record_thesis

            record_thesis(db_path, cycle, candles_by_tf=candles_by_tf)
        except Exception as exc:
            print(f"[thesis] journal error: {type(exc).__name__}: {exc}")

    async def send_office(
        message: str,
        reply_to_message_id: Optional[int] = None,
        stream: str = "general",
        allow_draft: bool = False,
        *,
        intent: str = "",
        event_type: str = "",
        symbol: str = "",
        direction: str = "",
        skip_gate: bool = False,
        scenario_id: str = "",
    ) -> Optional[int]:
        if not skip_gate:
            tg = gate_outbound_telegram(
                intent=intent or "ANALYTICAL",
                text=message,
                event_type=event_type or EVENT_TRADE_UPDATE,
                db_path=db_path,
                symbol=symbol or _extract_first_usdt_symbol(_strip_agent_tag(message)),
                direction=direction,
            )
            if not tg.get("send"):
                print(
                    f"[relay] blocked send_office {intent or 'ANALYTICAL'}: "
                    f"{tg.get('reason')} {str(message or '')[:160]}"
                )
                return None
        async def _send_single(
            text_part: str,
            *,
            reply_to: Optional[int],
            use_markup: bool,
        ) -> Optional[int]:
            agent_key = detect_agent_key(message)
            thread_id = _thread_for_stream(stream)
            btn_markup: Optional[Dict[str, Any]] = None
            if use_markup:
                from office_telegram_policy import mini_app_button

                btn_markup = mini_app_button(
                    symbol=_extract_first_usdt_symbol(text_part) or "",
                    scenario_id=scenario_id,
                    base_url=os.getenv("OFFICE_MINI_PUBLIC_URL", "https://ai-office-miniapp.onrender.com"),
                )
            token = agent_bot_tokens.get(agent_key or "")
            _rel: Dict[str, Any] = {"retries": 2, "timeout_sec": 30.0} if btn_markup else {}
            # sendMessageDraft ігнорує/кидає форумну тему в корінь «General» —
            # для desk лише sendMessage + thread_id «Загальний».
            if token:
                try:
                    ok, reason, msg_id = False, "", None
                    if allow_draft:
                        ok, reason, msg_id = await send_via_bot_streaming(
                            bot_http,
                            token,
                            office_chat_id,
                            text_part,
                            thread_id=thread_id,
                            reply_to=reply_to,
                        )
                    if not ok:
                        ok, reason, msg_id = await send_via_bot_api(
                            bot_http,
                            token,
                            office_chat_id,
                            text_part,
                            reply_to_message_id=reply_to,
                            message_thread_id=thread_id,
                            reply_markup=btn_markup,
                            **_rel,
                        )
                except Exception:
                    ok, reason, msg_id = await send_via_bot_api(
                        bot_http,
                        token,
                        office_chat_id,
                        text_part,
                        reply_to_message_id=reply_to,
                        message_thread_id=thread_id,
                        reply_markup=btn_markup,
                            **_rel,
                    )
                if ok:
                    return msg_id
                if "message to be replied not found" in str(reason).lower() and reply_to is not None:
                    ok2, reason2, msg_id2 = await send_via_bot_api(
                        bot_http,
                        token,
                        office_chat_id,
                        text_part,
                        reply_to_message_id=None,
                        message_thread_id=thread_id,
                        reply_markup=btn_markup,
                            **_rel,
                    )
                    if ok2:
                        print(f"[relay][WARN] bot-send reply fallback for {agent_key}: sent without reply_to")
                        return msg_id2
                    reason = f"{reason}; retry_without_reply failed: {reason2}"
                print(f"[relay][WARN] bot-send failed for {agent_key}: {reason} (fallback user client)")
            if tg_bot_token:
                ok, reason, msg_id = await send_via_bot_api(
                    bot_http,
                    tg_bot_token,
                    office_chat_id,
                    text_part,
                    reply_to_message_id=reply_to,
                    message_thread_id=thread_id,
                    reply_markup=btn_markup,
                            **_rel,
                )
                if ok:
                    return msg_id
                print(f"[relay][WARN] fallback bot-send failed: {reason} (trying Telethon client)")
            telethon_reply = reply_to if reply_to is not None else thread_id
            sent = await client.send_message(office_entity, text_part[:3900], reply_to=telethon_reply)
            try:
                return int(getattr(sent, "id", 0) or 0) or None
            except Exception:
                return None

        clean_message = _strip_agent_tag(message)
        parts = split_long_message(clean_message)
        first_id: Optional[int] = None
        for i, part in enumerate(parts):
            prefixed = part if i == 0 else f"...{part}"
            sent_id = await _send_single(
                prefixed,
                reply_to=reply_to_message_id if i == 0 else None,
                use_markup=(i == 0),
            )
            if i == 0:
                first_id = sent_id
            if len(parts) > 1 and i < len(parts) - 1:
                await asyncio.sleep(0.5)
        return first_id

    async def send_office_photo(
        photo_path: str,
        caption: str,
        stream: str = "general",
        *,
        reply_to_message_id: Optional[int] = None,
        scenario_id: str = "",
        intent: str = "",
        event_type: str = "",
        symbol: str = "",
        direction: str = "",
        skip_gate: bool = False,
    ) -> Optional[int]:
        if not skip_gate:
            tg = gate_outbound_telegram(
                intent=intent or "ANALYTICAL",
                text=caption,
                event_type=event_type or EVENT_TRADE_UPDATE,
                db_path=db_path,
                symbol=symbol or _extract_first_usdt_symbol(_strip_agent_tag(caption)),
                direction=direction,
            )
            if not tg.get("send"):
                print(
                    f"[relay] blocked send_office_photo: {tg.get('reason')} "
                    f"{str(caption or '')[:160]}"
                )
                return None
        thread_id = _thread_for_stream(stream)
        cap = _strip_agent_tag(caption)[:1024]
        token = agent_bot_tokens.get("lev") or tg_bot_token
        from office_telegram_policy import mini_app_button

        photo_btn = mini_app_button(
            symbol=symbol or _extract_first_usdt_symbol(cap) or "",
            scenario_id=scenario_id,
            base_url=os.getenv("OFFICE_MINI_PUBLIC_URL", "https://ai-office-miniapp.onrender.com"),
        )
        if token:
            ok, reason, msg_id = await send_via_bot_photo(
                bot_http,
                token,
                office_chat_id,
                photo_path,
                caption=cap,
                reply_to_message_id=reply_to_message_id,
                message_thread_id=thread_id,
                reply_markup=photo_btn,
            )
            if ok:
                return msg_id
            if reply_to_message_id and "message to be replied not found" in str(reason).lower():
                ok, reason, msg_id = await send_via_bot_photo(
                    bot_http,
                    token,
                    office_chat_id,
                    photo_path,
                    caption=cap,
                    message_thread_id=thread_id,
                    reply_markup=photo_btn,
                )
                if ok:
                    print("[relay][WARN] photo reply root missing: sent without reply_to")
                    return msg_id
            print(f"[relay][WARN] photo send failed: {reason}")
        try:
            sent = await client.send_file(
                office_entity,
                photo_path,
                caption=cap,
                reply_to=reply_to_message_id or thread_id,
            )
            return int(getattr(sent, "id", 0) or 0) or None
        except Exception as exc:
            print(f"[relay][WARN] photo telethon failed: {exc}")
            return await send_office(
                caption,
                stream=stream,
                intent=intent,
                event_type=event_type,
                symbol=symbol,
                direction=direction,
                skip_gate=skip_gate,
            )

    def _render_entry_chart(sym: str, direction: str, message: str) -> Dict[str, Any]:
        import re

        from office_chart_png import chart_levels, render_signal_chart
        from office_market_data import fetch_candles
        from office_topdown import asian_session_range
        from office_trade_steer import midnight_open_price, plan_strong_candle_ote, parse_sc_zone_note

        def _scenario_tf_from_text(text: str) -> str:
            m = re.search(r"сценарій\s+(M\d+|H\d+|D1)", str(text or ""), flags=re.I)
            return str(m.group(1)).upper() if m else ""

        def _line_roles(text: str, side: str) -> Dict[str, str]:
            wait = (
                "Чекаю відкату в зону. Входу ще немає."
                if "LONG" in str(side or "").upper()
                else "Чекаю реакції M5 у зоні. Входу ще немає."
            )
            why = cancel = prev = ""
            for line in str(text or "").splitlines():
                raw = line.strip()
                low = raw.lower()
                if not raw:
                    continue
                if low.startswith("попередній") and "скасовано" in low:
                    prev = raw
                    continue
                if "чекаю" in low:
                    wait = raw
                    continue
                if low.startswith("що скасує") or "інвалідац" in low and "не визначено" in low:
                    cancel = raw
                    continue
                if low.startswith("конкретну умову m5"):
                    continue
                if low.startswith("це зона") or "місце спостереження" in low or "окрема зона" in low:
                    why = raw
            return {"wait": wait, "why": why, "cancel": cancel, "prev": prev}

        m15 = fetch_candles(sym, "15m", 96)
        h1 = fetch_candles(sym, "1h", 48)
        if not isinstance(m15, list):
            m15 = []
        if not isinstance(h1, list):
            h1 = []
        parsed = parse_signal_levels_from_text(message) or {}
        sc = plan_strong_candle_ote(
            direction=direction or str(parsed.get("direction") or ""),
            candles=m15 if m15 else h1,
            price=parsed.get("entry") or parsed.get("entry_low"),
        )
        asia = asian_session_range(m15 if m15 else h1)
        mo = midnight_open_price(m15 if m15 else h1)
        sc_lo = sc_hi = None
        if sc.get("data_status") == "DATA_OK":
            sc_lo, sc_hi = sc.get("low"), sc.get("high")
        else:
            z = parse_sc_zone_note(message)
            if z:
                sc_lo, sc_hi = z
        b60 = b40 = None
        for b in sc.get("buckets") or []:
            if int(b.get("pct") or 0) == 60:
                b60 = b.get("price")
            if int(b.get("pct") or 0) == 40:
                b40 = b.get("price")
        from office_chart_png import _f as _pxf
        from office_desk_card import _calc_entry_px

        roles = _line_roles(message, direction)
        elo = parsed.get("entry_low") or parsed.get("entry") or sc.get("ote_lo")
        ehi = parsed.get("entry_high") or parsed.get("entry") or sc.get("ote_hi")
        side = str(direction or parsed.get("direction") or "").upper()
        calc = _calc_entry_px(direction=side, elo=_pxf(elo), ehi=_pxf(ehi), entry=_pxf(parsed.get("entry")))
        lv = chart_levels(
            sl=parsed.get("sl") or sc.get("sl"),
            tp1=parsed.get("tp1") or parsed.get("tp"),
            tp2=parsed.get("tp2"),
            tp3=parsed.get("tp3"),
            entry_low=elo,
            entry_high=ehi,
            sc_low=sc_lo,
            sc_high=sc_hi,
            sweep=parsed.get("sweep"),
            asian_high=(asia or {}).get("high"),
            asian_low=(asia or {}).get("low"),
            mo=mo,
            bucket_60=b60,
            bucket_40=b40,
            last_price=(m15[-1] or {}).get("close") if m15 else ((h1[-1] or {}).get("close") if h1 else None),
            status="WATCHING" if "чекаю" in str(message or "").lower() or "входу немає" in str(message or "").lower() else "",
            scenario_tf=_scenario_tf_from_text(message),
            chart_tf="M15",
            wait_line=roles["wait"],
            why_line=roles["why"],
            cancel_line=roles["cancel"],
            prev_line=roles["prev"],
            calc_entry=calc,
            demo="DEMO" in str(message or "").upper() or "OFFLINE" in str(message or "").upper(),
        )
        return render_signal_chart(
            symbol=sym,
            candles_m15=m15,
            candles_h1=h1,
            levels=lv,
            direction=side,
        )

    async def send_proactive(
        event_type: str,
        message: str,
        reply_to_message_id: Optional[int] = None,
        stream: str = "general",
        *,
        kind: str = "",
        symbol: str = "",
        sl: Any = None,
        direction: str = "",
        intent: str = "",
        confirmed_position: bool = False,
        position_id: str = "",
        position_open: bool = False,
        canonical_id: str = "",
        scenario_event: str = "",
    ) -> Optional[int]:
        if not may_send_proactive(event_type):
            print(f"[relay] silent {event_type}: {str(message or '')[:160]}")
            return None
        from office_telegram_policy import outbound_allowed as _tg_allowed

        if not _tg_allowed(event_type=event_type, kind=kind, intent=intent, confirmed_position=confirmed_position, position_open=position_open):
            print(f"[relay] silent (у Telegram лише готовий сигнал і ведення позначеної угоди) {event_type}/{kind}/{intent}: {str(message or '')[:120]}")
            return None
        tg = gate_outbound_telegram(
            intent=intent,
            text=message,
            in_position=confirmed_position,
            position_id=position_id,
            position_open=position_open,
            event_type=event_type,
            db_path=db_path,
            symbol=symbol,
            direction=direction,
        )
        if not tg.get("send"):
            print(f"[relay] blocked outbound {intent or event_type}: {tg.get('reason')} {str(message or '')[:160]}")
            return None
        ev = str(event_type or "").strip().upper()
        st = str(stream or "general").strip().lower() or "general"
        dedup_key = ""
        if ev in (EVENT_TRADE_UPDATE, EVENT_TRADE_CLOSED, EVENT_SIGNAL_ENTRY):
            st = TRADE_UPDATE_STREAM
            if len(trade_update_streams()) != 1:
                print("[relay] WARN: more than one trade stream configured")
            gate = should_send_trade_telegram(
                text=message,
                kind=kind or ev,
                symbol=symbol,
                sl=sl,
                stream=st,
                canonical_id=canonical_id,
                event=scenario_event or ev,
            )
            if not gate.get("send"):
                print(f"[relay] silent dup {ev} {kind}: {gate.get('reason')} {str(message or '')[:160]}")
                return None
            dedup_key = str(gate.get("key") or "")
        # Opt-in only after an explicit, owner-approved DB migration. A missing
        # ledger table/error fails closed rather than sending an untracked event.
        ledger_enabled = os.environ.get("OFFICE_TG_PERSISTENT_DEDUP", "").strip() == "1"
        ledger_token = None
        ledger_stable = bool(str(canonical_id or "").strip() and str(scenario_event or ev).strip())
        if dedup_key and ledger_enabled:
            try:
                ledger_token = reserve_delivery(db_path, dedup_key, stable=ledger_stable)
            except Exception as exc:
                finish_trade_telegram(key=dedup_key, delivered=False)
                print(f"[relay] BLOCKED ledger unavailable: {type(exc).__name__}: {exc}")
                return None
            if ledger_token is None:
                finish_trade_telegram(key=dedup_key, delivered=False)
                print(f"[relay] silent persistent duplicate {ev} {kind}")
                return None
        ledger_heartbeat = None
        ledger_heartbeat_stop = asyncio.Event()
        ledger_lease_lost = asyncio.Event()
        ledger_sender_task = asyncio.current_task()
        if ledger_token:
            async def _renew_telegram_lease() -> None:
                while not ledger_heartbeat_stop.is_set():
                    try:
                        await asyncio.wait_for(ledger_heartbeat_stop.wait(), timeout=30.0)
                        return
                    except asyncio.TimeoutError:
                        pass
                    try:
                        renewed = await asyncio.to_thread(
                            renew_delivery, db_path, dedup_key, ledger_token,
                        )
                        if not renewed:
                            print("[relay] ERROR Telegram lease lost during send")
                            ledger_lease_lost.set()
                            if ledger_sender_task is not None:
                                ledger_sender_task.cancel()
                            return
                    except Exception as exc:
                        print(f"[relay] ERROR Telegram lease renewal: {type(exc).__name__}: {exc}")
                        ledger_lease_lost.set()
                        if ledger_sender_task is not None:
                            ledger_sender_task.cancel()
                        return
            ledger_heartbeat = asyncio.create_task(_renew_telegram_lease())
        # One chain per canonical scenario: later events reply to the first card.
        thread_sid = str(canonical_id or "").strip() if ledger_enabled else ""
        thread_starts = False
        if thread_sid and reply_to_message_id is None:
            try:
                reply_to_message_id = get_scenario_root(db_path, thread_sid)
                thread_starts = reply_to_message_id is None
            except Exception as exc:
                print(f"[relay] WARN scenario thread lookup: {type(exc).__name__}: {exc}")
        delivered_id = None
        send_attempted = False
        skip_text = False
        ledger_committed = not ledger_enabled or not dedup_key
        try:
            if ev == EVENT_SIGNAL_ENTRY:
                sym = str(symbol or "").upper().strip() or _extract_first_usdt_symbol(_strip_agent_tag(message))
                try:
                    drawn = _render_entry_chart(sym, str(direction or ""), _strip_agent_tag(message))
                except Exception as exc_ch:
                    print(f"[chart] render failed {sym}: {type(exc_ch).__name__}: {exc_ch}")
                    drawn = {}
                if drawn.get("ok") and drawn.get("path"):
                    send_attempted = True
                    msg_id = await send_office_photo(
                        str(drawn["path"]),
                        message,
                        stream=st,
                        reply_to_message_id=reply_to_message_id,
                        scenario_id=str(canonical_id or ""),
                        intent=intent,
                        event_type=event_type,
                        symbol=sym,
                        direction=direction,
                        skip_gate=True,
                    )
                    if msg_id:
                        print(f"[chart] SIGNAL_ENTRY photo {sym} {drawn['path']}")
                        delivered_id = msg_id
                        skip_text = True
                    else:
                        # A None response is not proof that Telegram rejected
                        # the photo. Never send a second text copy.
                        print(f"[chart] photo outcome ambiguous {sym}; no fallback text")
                        skip_text = True
                else:
                    print(f"[chart] DATA_UNAVAILABLE {sym}: {drawn.get('reason')}")
            if not skip_text:
                send_attempted = True
                delivered_id = await send_office(
                    message,
                    reply_to_message_id=reply_to_message_id,
                    stream=st,
                    allow_draft=False,
                    intent=intent,
                    event_type=event_type,
                    symbol=symbol,
                    direction=direction,
                    skip_gate=True,
                    scenario_id=str(canonical_id or ""),
                )

        finally:
            ledger_heartbeat_stop.set()
            if ledger_heartbeat is not None:
                try:
                    await ledger_heartbeat
                except Exception as exc:
                    print(f"[relay] ERROR Telegram heartbeat shutdown: {type(exc).__name__}: {exc}")
            ledger_committed = not ledger_enabled or not dedup_key
            if ledger_token:
                try:
                    if ledger_lease_lost.is_set() or (send_attempted and not delivered_id):
                        quarantined = mark_delivery_uncertain(db_path, dedup_key, ledger_token)
                        print(f"[relay] ambiguous Telegram send quarantined={quarantined}")
                        ledger_committed = False
                    else:
                        ledger_committed = finish_delivery(
                        db_path, dedup_key, ledger_token,
                        delivered=bool(delivered_id), stable=ledger_stable,
                    )
                except Exception as exc:
                    ledger_committed = False
                    print(f"[relay] ERROR ledger commit: {type(exc).__name__}: {exc}")
                    if send_attempted:
                        try:
                            quarantined = mark_delivery_uncertain(db_path, dedup_key, ledger_token)
                            print(f"[relay] ambiguous delivery quarantined={quarantined}")
                        except Exception as quarantine_exc:
                            print(
                                "[relay] CRITICAL ambiguous Telegram delivery: "
                                f"ledger and quarantine unavailable: {type(quarantine_exc).__name__}: {quarantine_exc}"
                            )
            if dedup_key:
                finish_trade_telegram(
                    key=dedup_key,
                    delivered=bool(delivered_id) and bool(ledger_committed),
                )
            if ledger_token and delivered_id and not ledger_committed:
                print("[relay] BLOCKED lifecycle: delivery not committed in ledger")
            if thread_starts and delivered_id and ledger_committed:
                try:
                    remember_scenario_root(db_path, thread_sid, int(delivered_id))
                except Exception as exc:
                    print(f"[relay] WARN scenario thread root not saved: {type(exc).__name__}: {exc}")
        return delivered_id if ledger_committed else None
    try:
        if not _RELAY_OFFICE_STARTUP_PING_SENT:
            _RELAY_OFFICE_STARTUP_PING_SENT = True
            print(
                "[relay] startup ping logged only (no Telegram). "
                "Duplicate pings mean two Worker processes or a restart loop; "
                "_RELAY_OFFICE_STARTUP_PING_SENT is per-process."
            )

        # П.19: технічний канал Артема — короткий health у гілку «Техніка» (якщо задано OFFICE_TECH_THREAD_ID).
        tech_health_off = os.getenv("RELAY_TECH_HEALTH_ON_START", "0").strip() == "0"
        if tech_thread_id and not tech_health_off:
            try:
                db_kind = (
                    "PostgreSQL"
                    if str(db_path).strip().lower().startswith(("postgres://", "postgresql://"))
                    else "SQLite"
                )
                _ident = office_db_identity(db_path)
                _fp = _ident.get("fingerprint", "?")
                health_plain = (
                    "🛠️ Техніка: все працює.\n"
                    f"База: {db_kind} · fingerprint `{_fp}`."
                )
                if os.getenv("OFFICE_TG_TECH_PINGS", "").strip() == "1":   # службові повідомлення в Telegram — лише за явним дозволом
                    await send_office(fmt_agent_line("dev", polish_agent_message(health_plain)), stream="tech")
                    print("[relay] tech health (Artem) sent -> TECH thread")
                else:
                    print("[relay] tech health: без Telegram (OFFICE_TG_TECH_PINGS не задано)")
            except Exception as exc:
                print(f"[relay][WARN] tech health ping failed: {exc}")

        send_agent_cards = os.getenv("RELAY_SEND_AGENT_CARDS", "").strip() == "1"
        # Optional: startup visual cards (disabled by default to keep OFFICE chat clean).
        photo_candidates = {
            "lev": [
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4628-8d05ee5a-9ee6-478a-80c8-672f0c6022b4.png",
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4634-23085bb4-5a7a-48e7-ad5d-82983e6bf0bf.png",
            ],
            "maks": [
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4631-9ebac4e0-8dac-49f1-838a-abdbb90ec346.png",
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4636-e4769164-72ef-4023-a69f-542524e0ad7b.png",
            ],
            "daryna": [
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4633-28681e11-8101-4765-b1ed-edcba524bccc.png",
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4635-63540880-d30a-4552-8710-d6bc996b18bc.png",
            ],
            "marko": [
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4629-0cc48cb6-1ee5-4f7d-8402-501e1100b15c.png",
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4634-23085bb4-5a7a-48e7-ad5d-82983e6bf0bf.png",
            ],
            "olesya": [
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4632-42cd0935-8158-4f55-81ed-6d11c8d0b608.png",
                r"C:\Users\Pentagon\.cursor\projects\C-Users-Pentagon-AppData-Local-Temp-07d40f9e-ec21-4d7d-bc54-c797470e57f7\assets\c__Users_Pentagon_AppData_Roaming_Cursor_User_workspaceStorage_1776115782677_images_IMG_4635-63540880-d30a-4552-8710-d6bc996b18bc.png",
            ],
        }
        if send_agent_cards:
            for key in ("lev", "maks", "daryna", "marko", "olesya"):
                variants = photo_candidates.get(key, [])
                p = next((Path(v) for v in variants if Path(v).exists()), None)
                caption = get_agent_card_text(key)
                if p is not None and p.exists():
                    await client.send_file(office_entity, file=str(p), caption=caption)
                    print(f"[relay] agent card photo sent: {key}")
                else:
                    await send_office(caption)
                    print(f"[relay] agent card text only: {key}")
        else:
            print("[relay] startup agent cards disabled (set RELAY_SEND_AGENT_CARDS=1 to enable)")
    except Exception as exc:
        print(f"[relay][ERROR] cannot send startup ping to OFFICE: {exc}")

    source_raw = os.getenv("SOURCE_CHAT_ID", "").strip()
    source_chat_id = int(source_raw) if source_raw else None
    source_entity = await client.get_entity(source_chat_id) if source_chat_id is not None else None
    signal_source_bot_ids = _env_int_set("OFFICE_SIGNAL_SOURCE_BOT_IDS")
    signal_source_bot_username = os.getenv("OFFICE_SIGNAL_SOURCE_BOT_USERNAME", "").strip().lstrip("@").lower()
    last_source_msg_id = 0
    if source_chat_id is not None:
        print(f"[relay] mode: source bridge enabled ({source_chat_id} -> {main_chat_id}), MAIN ingest only")
    else:
        print("[relay] mode: strict source filter (MAIN chat only)")
    active_positions: Dict[str, ActivePosition] = {}
    last_news_level = "SAFE"
    last_daily_report_date = ""
    news_api_key = os.getenv("NEWS_API_KEY", "").strip()
    if not news_api_key:
        news_api_key = str(cfg.get("news_api_key", "") or "").strip()
    if not news_api_key:
        if interactive or not cfg.get("news_api_key"):
            news_api_key = _prompt("NEWS_API_KEY (optional, Enter to skip): ")
        else:
            # Silent mode: keep last saved key without prompting.
            news_api_key = str(cfg.get("news_api_key", "") or "").strip()
    elif interactive and not force_setup:
        ans = _prompt("NEWS_API_KEY знайдено у збережених налаштуваннях. Використати? (Y/n): ").lower()
        if ans and ans not in ("y", "yes", "д", "так"):
            news_api_key = _prompt("NEWS_API_KEY (optional, Enter to skip): ")

    cfg["news_api_key"] = news_api_key
    save_relay_config(cfg)

    last_desk_qa_mono = 0.0
    last_main_fingerprint_by_msg: Dict[int, str] = {}
    main_lev_automation_last = 0.0

    @client.on(events.NewMessage())
    async def on_message(event):  # type: ignore[no-redef]
        try:
            nonlocal last_source_msg_id, main_lev_automation_last
            text = event.raw_text or ""
            if not text.strip():
                return
            src_chat_id = getattr(event, "chat_id", None)
            msg_id = int(getattr(event, "id", 0) or 0)

            # OFFICE interactive desk Q&A (explicit command only -> reduces spam/chaos)
            if src_chat_id is not None and int(src_chat_id) == int(office_chat_id):
                sender_id = getattr(event, "sender_id", None)
                low = (text or "").strip().lower()
                if (text or "").strip().lower() in ("/status", "!status", "статус", "/статус"):
                    ident = office_db_identity(db_path)
                    fp = str(ident.get("fingerprint") or "?")
                    await send_office(fmt_agent_line("dev", f"Статус: все працює. fingerprint `{fp}`."), stream="tech")
                    return
                if low in ("/rules", "!rules", "правила", "/правила"):
                    await send_office(OFFICE_RULES_BRIEF_UA, stream="tasks")
                    return
                if low in ("/officeprompt", "!officeprompt", "промпт", "/промпт"):
                    full = _read_text_head(MASTER_PROMPT_PATH, max_chars=3600)
                    if not full:
                        await send_office("Не знайшла файл OFFICE_MASTER_PROMPT_UA.md у репозиторії.", stream="tech")
                        return
                    await send_office("📘 OFFICE MASTER PROMPT (скорочено):\n" + full, stream="tasks")
                    return
                if low.startswith("/stats") or low.startswith("!stats") or low.startswith("статистика"):
                    from office_signal_stats import build_stats_report

                    rep = build_stats_report(db_path)
                    await send_office(fmt_agent_line("olesya", str(rep.get("message") or "DATA_UNAVAILABLE")))
                    return
                t1 = parse_t1_command(text)
                if t1 is not None:
                    kind, _body = t1
                    if kind == "review":
                        card = handle_review_command(text, db_path)
                        await send_office(str(card.get("message") or ""))
                    else:
                        card = handle_position_command(text, db_path)
                        await send_office(str(card.get("message") or ""))
                    print(f"[relay] T1 {kind} office opens_position={card.get('opens_position')}")
                    return
                if low.startswith("/chart") or low.startswith("!chart") or low.startswith("графік"):
                    parts = (text or "").split()
                    raw_sym = parts[1] if len(parts) > 1 else ""
                    sym = _extract_first_usdt_symbol(raw_sym or text) or "BTCUSDT"
                    if not str(raw_sym).strip() and " " not in (text or "").strip():
                        await send_office(fmt_agent_line("lev", "Формат: /chart SYMBOL"))
                        return
                    try:
                        drawn = _render_entry_chart(sym, "", f"{sym}")
                    except Exception as exc_c:
                        drawn = {"ok": False, "reason": str(exc_c)}
                    if drawn.get("ok") and drawn.get("path"):
                        cap = f"📍 {sym} · графік на запит\nКартка сетапу, не ордер."
                        sent = await send_office_photo(str(drawn["path"]), cap, stream="general")
                        if sent:
                            return
                        print(f"[chart] /chart photo failed {sym}: {drawn.get('reason')}")
                    await send_office(
                        fmt_agent_line(
                            "lev",
                            f"{sym}: графік DATA_UNAVAILABLE ({drawn.get('reason') or 'немає свічок'}).",
                        )
                    )
                    return
                lev_q = _lev_dialog.parse_command(text)
                if lev_q is None:
                    lev_q = _lev_dialog.parse_followup(text)   # «а інвалідація?» після відповіді Лева — про ту саму монету
                if lev_q is not None:
                    # Лев відповідає лише з фактичного циклу на свіжих свічках і з БД (без LLM); NO TRADE — нормальна відповідь.
                    try:
                        ans = await asyncio.to_thread(_lev_dialog.ask, db_path, lev_q)
                        await send_office(str(ans["text"])[:3800], stream="general")
                    except Exception as exc_l:
                        print(f"[lev-dialog] error: {type(exc_l).__name__}: {exc_l}")
                        await send_office(fmt_agent_line("lev", "Не вдалося отримати аналіз: NO TRADE, доки не буде свіжих даних."), stream="tech")
                    return
                scenario_key = _parse_scenario_command(text)
                if scenario_key is not None:
                    async def sender(msg: str) -> None:
                        await send_office(msg[:3900])
                    if not scenario_key:
                        await send_office(
                            "ℹ️ Формат: `!scenario morning` або `!scenario loss_streak`.\n"
                            "Доступні: `asia_strong, weak_skip, daryna_question, win_close, loss_streak, morning`",
                            stream="tasks",
                        )
                        return
                    await office_run_scenario(sender=sender, scenario_key=scenario_key, db_path=db_path)
                    print(f"[relay] scenario run: {scenario_key}")
                    return
                q = _parse_desk_command(text)
                if q:
                    nonlocal last_desk_qa_mono
                    now_m = time.monotonic()
                    if now_m - last_desk_qa_mono < 8.0:
                        await send_office("⏳ Desk: зачекай 5–10 секунд між питаннями (антиспам).")
                        return
                    last_desk_qa_mono = now_m

                    sym = _extract_first_usdt_symbol(q + "\n" + text)
                    timeout = aiohttp.ClientTimeout(total=12)
                    try:
                        async with aiohttp.ClientSession(timeout=timeout) as http:
                            snap = await build_desk_market_snapshot(http, sym)
                    except Exception as exc:
                        await send_office(f"Не вдалося зняти ринковий зріз з Binance: {exc}", stream="tech")
                        return

                    gold_line = ""
                    if snap.get("gold_symbol"):
                        gold_line = (
                            f"Золото-проксі `{snap.get('gold_symbol')}` 24г `{float(snap.get('gold_change_pct', 0.0)):+.2f}%`\n"
                        )

                    fp = snap.get("factor_pack_v2") or {}
                    fund = fp.get("funding_rate_pct")
                    liq = fp.get("liquidity_tier")
                    fund_line = ""
                    if fund is not None:
                        fund_line = f"Funding (остання ставка, %): `{fund:.4f}`\n"
                    liq_line = f"Ліквідність (яр): `{liq}`\n" if liq else ""

                    await send_office(
                        "📌 Ринковий зріз (Binance USDT-M) · Factor Pack v2\n"
                        f"BTCUSDT 24г `{float(snap.get('btc_change_pct', 0.0)):+.2f}%`\n"
                        f"{sym} 24г `{float(snap.get('sym_change_pct', 0.0)):+.2f}%` · "
                        f"vol `{float(snap.get('quote_volume_usdt', 0.0)):.0f}` USDT notional\n"
                        f"{fund_line}"
                        f"{liq_line}"
                        f"{gold_line}"
                        f"Оцінка ринку (діапазон HL): `{float(snap.get('volatility_pct', 0.0)):.2f}%`",
                        stream="tasks",
                    )

                    async def sender(msg: str) -> None:
                        await send_office(msg[:3900], stream="tasks")

                    await office_desk_user_question(
                        sender=sender,
                        question=q,
                        symbol=sym,
                        market=snap,
                        db_path=db_path,
                    )
                    print("[relay] desk_qa done")
                    return

                # Free-form office chat: owner message -> addressed agent reply.
                sender_id = getattr(event, "sender_id", None)
                sender_id_int = int(sender_id) if sender_id is not None else 0
                if sender_id_int in bot_user_ids:
                    return
                sender_obj = await event.get_sender()
                if bool(getattr(sender_obj, "bot", False)):
                    return
                if owner_user_id is not None and sender_id_int != owner_user_id:
                    return
                async def send_office_fn(msg: str) -> None:
                    await send_office(msg[:3900], stream="general")
                await office_free_chat(
                    send_office_fn,
                    text,
                    db_path,
                )
                return

            # Optional sidecar bridge: forward signal-like messages from SOURCE chat to MAIN chat.
            # Keeps trade-core untouched while enabling automatic feed into MAIN.
            if source_chat_id is not None and src_chat_id is not None and int(src_chat_id) == int(source_chat_id):
                last_source_msg_id = max(last_source_msg_id, int(getattr(event, "id", 0) or 0))
                if looks_like_signal(text):
                    await client.send_message(main_entity, text[:3900])
                    print(f"[relay] forwarded SOURCE -> MAIN id={event.id} chat_id={src_chat_id}")
                return

            # Hard gate: process trading signals only from MAIN room.
            # This prevents accidental mirroring from any other dialog/log stream.
            if src_chat_id is None or int(src_chat_id) != int(main_chat_id):
                return
            # If the same message id is re-delivered with identical text
            # (e.g. duplicate update callback), ignore it.
            fp = f"{msg_id}:{text.strip()}"
            if msg_id > 0 and last_main_fingerprint_by_msg.get(msg_id) == fp:
                return
            if msg_id > 0:
                last_main_fingerprint_by_msg[msg_id] = fp
            t1_main = parse_t1_command(text)
            if t1_main is not None:
                kind, _body = t1_main
                if kind == "review":
                    card = handle_review_command(text, db_path)
                else:
                    card = handle_position_command(text, db_path)
                await send_office(str(card.get("message") or ""))
                print(f"[relay] T1 {kind} main opens_position={card.get('opens_position')}")
                return
            sender_id = getattr(event, "sender_id", None)
            sender_username = ""
            try:
                sender_obj = await event.get_sender()
                sender_username = str(getattr(sender_obj, "username", "") or "").strip().lower()
            except Exception:
                sender_obj = None  # noqa: F841

            from_scanner = False
            try:
                if sender_id is not None and int(sender_id) in signal_source_bot_ids:
                    from_scanner = True
            except Exception:
                pass
            if signal_source_bot_username and sender_username == signal_source_bot_username:
                from_scanner = True

            if not from_scanner and not looks_like_signal(text):
                if os.getenv("OFFICE_CHAT_AUTOMATION", "").strip() == "1":
                    try:
                        if sender_obj is not None and not bool(getattr(sender_obj, "bot", False)):
                            sid = int(sender_id) if sender_id is not None else 0
                            if owner_user_id is None or sid == int(owner_user_id):
                                now_m = time.monotonic()
                                if now_m - main_lev_automation_last >= 45.0:
                                    lev_tok = (agent_bot_tokens or {}).get("lev")
                                    if lev_tok:
                                        auto_sys = (
                                            f"{LEV_RULE}\n"
                                            "Ти відповідаєш у головному торговому чаті (MAIN), не в офісі. "
                                            "Коротко по-людськи, без сигналу й без таблиць, українською. "
                                            "Якщо вітання — підтримай тоном. Якщо питання по ринку — одне чітке речення."
                                        )
                                        raw = ask_agent(
                                            "lev",
                                            auto_sys,
                                            f"Повідомлення в MAIN:\n{text.strip()[:900]}",
                                            max_tokens=200,
                                            db_path=db_path,
                                        )
                                        reply = clean_self_naming(clean_llm_note(raw), "lev")
                                        if reply.strip():
                                            out = _strip_agent_tag(fmt_agent_line("lev", reply.strip()))
                                            ok_auto, reason_auto, _ = await send_via_bot_api(
                                                bot_http,
                                                lev_tok,
                                                int(main_chat_id),
                                                out,
                                                reply_to_message_id=msg_id if msg_id > 0 else None,
                                            )
                                            if ok_auto:
                                                main_lev_automation_last = now_m
                                            else:
                                                print(f"[relay][WARN] MAIN automation (Lev) failed: {reason_auto}")
                    except Exception as exc_auto:
                        print(f"[relay][WARN] OFFICE_CHAT_AUTOMATION failed: {exc_auto}")
                if os.getenv("RELAY_LOG_NONSIGNAL_MAIN", "").strip() == "1":
                    prev = " ".join((text or "").split())[:180]
                    print(f"[relay][DEBUG] MAIN message ignored (not signal) id={event.id}: {prev}")
                return
            print(
                f"[relay] matched message id={event.id} chat_id={src_chat_id}"
                + (" (scanner-forced)" if from_scanner else "")
            )
            _history_reset()
            sig = parse_signal(text, event.id)
            # T8: зовнішній бот — незалежний розбір, оригінал без змін, не ордер.
            try:
                _ext_orig = ingest_external_signal(
                    text=text,
                    msg_id=event.id,
                    received_at=getattr(event, "date", None),
                )
                persist_external_original(db_path, _ext_orig)
                if _ext_orig.get("symbol") and str(_ext_orig.get("direction") or "").upper() in ("LONG", "SHORT"):
                    try:
                        _ext_ms = market_state_get(db_path, _ext_orig.get("symbol") or "") or {}
                    except Exception:
                        _ext_ms = {}
                    _ext_mkt = gather_external_market(
                        str(_ext_orig.get("symbol") or ""),
                        bot_action=_ext_ms.get("bot_action"),
                    )
                    _ext_rev = review_external_signal(_ext_orig, market=_ext_mkt)
                    _ext_candles = list(_ext_mkt.get("candles") or [])
                    _trader = compose_trader_plan(
                        _ext_orig,
                        _ext_rev,
                        market=_ext_mkt,
                        t7_snap=BTC_FORCE_ORDER_BOOK.snapshot(),
                        candles=_ext_candles or None,
                        asof=str(_ext_mkt.get("quote_asof") or _ext_orig.get("received_at") or ""),
                    )
                    await send_office(format_trader_plan(_trader))
                    if _trader.skip is not None:
                        persist_skip_case(db_path, _trader.skip, now_ts=time.time())
                    print(
                        f"[relay] external review {_ext_orig.get('symbol')} "
                        f"verdict={_ext_rev.verdict} skip_llm_chain=1"
                    )
                    return
            except Exception as exc_ext:
                print(f"[relay][WARN] external signal review failed: {type(exc_ext).__name__}: {exc_ext}")
            # T5: SOURCE форвард вище не чіпаємо. BLOCKED лише зупиняє kickoff/ENTER.
            try:
                _ms = market_state_get(db_path, getattr(sig, "symbol", "") or "")
            except Exception as exc_ms:
                print(f"[relay][WARN] market_state_get failed: {type(exc_ms).__name__}: {exc_ms}")
                _ms = None
            if scanner_signal_blocked((_ms or {}).get("bot_action")):
                print(f"[relay] scanner BLOCKED by office symbol={getattr(sig, 'symbol', '')} (Telegram silent)")
                return
            if news_api_key:
                news_timeout = aiohttp.ClientTimeout(total=10)
                try:
                    async with aiohttp.ClientSession(timeout=news_timeout) as news_http:
                        live_news = await fetch_news_risk(news_http, news_api_key)
                    risk_level = str(live_news.level).upper()
                    mapped_risk = "SAFE"
                    if risk_level in ("HIGH RISK", "HIGH"):
                        mapped_risk = "HIGH"
                    elif risk_level == "RISK":
                        mapped_risk = "RISK"
                    sig.meta["news_risk"] = mapped_risk
                    sig.meta["minutes_to_event"] = int(live_news.minutes_to_event)
                    sig.meta["news_event_name"] = live_news.event_name or ""
                    sig.meta["news_currency"] = live_news.currency or "USD"
                    sig.meta["news_event_time_utc"] = live_news.event_time_utc or ""
                    sig.meta["news_importance"] = live_news.importance or "low"
                except Exception as exc:
                    print(f"[relay][WARN] live news risk refresh failed: {type(exc).__name__}: {exc}")
            print(
                f"[relay] scanner auto {getattr(sig, 'symbol', '')}: "
                "no kickoff/desk LLM (proactive SKIP silent; SIGNAL_ENTRY comes from radar card)"
            )
            return
        except Exception as exc:
            print(f"[relay][ERROR] handler failed: {exc}")

    @client.on(events.MessageEdited())
    async def on_message_edited(event):  # type: ignore[no-redef]
        # My Crypto Scanner can publish a skeleton message and then edit it with full signal.
        # Reuse the same handler path so office flow starts automatically on edits too.
        await on_message(event)

    async def monitor_source_bridge() -> None:
        nonlocal last_source_msg_id
        while True:
            try:
                if source_entity is None:
                    await asyncio.sleep(10)
                    continue
                newest_id = last_source_msg_id
                batch = []
                async for m in client.iter_messages(source_entity, limit=20):
                    mid = int(getattr(m, "id", 0) or 0)
                    if mid <= 0:
                        continue
                    newest_id = max(newest_id, mid)
                    if mid <= last_source_msg_id:
                        continue
                    batch.append(m)
                for m in reversed(batch):
                    txt = str(getattr(m, "raw_text", "") or "")
                    if looks_like_signal(txt):
                        await client.send_message(main_entity, txt[:3900])
                        print(f"[relay] poll-forward SOURCE -> MAIN id={m.id}")
                last_source_msg_id = newest_id
            except Exception as exc:
                print(f"[relay][WARN] monitor_source_bridge failed: {exc}")
            await asyncio.sleep(5)

    async def monitor_positions() -> None:
        http_timeout = aiohttp.ClientTimeout(total=10)
        http_session = aiohttp.ClientSession(timeout=http_timeout)
        while True:
            try:
                if not active_positions:
                    await asyncio.sleep(30)
                    continue
                now = time.time()
                for sig_id in list(active_positions.keys()):
                    p = active_positions[sig_id]
                    age = now - p.opened_ts

                    async def sender(msg: str) -> None:
                        await send_proactive(EVENT_TRADE_UPDATE, msg[:3900])

                    # LIVE PRICE trigger: initialize entry from first fetched price.
                    try:
                        px = await fetch_mark_price(http_session, p.symbol)
                    except Exception as exc:
                        print(f"[relay][WARN] price fetch failed {p.symbol}: {exc}")
                        px = 0.0
                    if px > 0:
                        if p.entry_price <= 0:
                            p.entry_price = px
                        p.last_price = px

                    # If still no live price, fallback to time cadence.
                    if p.entry_price <= 0:
                        if p.stage == 0 and age >= 60:
                            await office_position_event(
                                sender=sender,
                                symbol=p.symbol,
                                event_type="PARTIAL_CLOSE",
                                details="Через 60с немає живої ціни: часткова фіксація 50% у запасному режимі.",
                                db_path=db_path,
                            )
                            await send_proactive(
                                EVENT_TRADE_UPDATE,
                                f"{p.symbol}: часткова фіксація 50%.",
                            )
                            p.stage = 1
                            continue
                        if p.stage == 1 and age >= 120:
                            await office_position_event(
                                sender=sender,
                                symbol=p.symbol,
                                event_type="MOVE_SL",
                                details="Через 120с: переносимо стоп у беззбиток у запасному режимі.",
                                db_path=db_path,
                            )
                            await send_proactive(
                                EVENT_TRADE_UPDATE,
                                f"{p.symbol}: стоп у беззбиток.",
                            )
                            p.stage = 2
                            continue
                        if p.stage == 2 and age >= 180:
                            await office_position_event(
                                sender=sender,
                                symbol=p.symbol,
                                event_type="EXIT",
                                details="Через 180с: вихід у запасному режимі.",
                                db_path=db_path,
                            )
                            await office_trade_closed(
                                sender=sender,
                                symbol=p.symbol,
                                outcome="BE",
                                pnl_pct=0.0,
                                note="Fallback close (no live price)",
                                db_path=db_path,
                            )
                            journal_close_trade(
                                db_path,
                                trade_id=sig_id,
                                outcome="BE",
                                exit_price=(p.last_price if p.last_price > 0 else None),
                                pnl_pct=0.0,
                                exit_reason="Закриття у запасному режимі за таймером",
                                mistake_tags=["no_live_price"],
                                review_note="Закриття по часу без live ціни.",
                            )
                            active_positions.pop(sig_id, None)
                        continue

                    # LIVE trigger logic by price change from entry.
                    move_pct = 0.0
                    if p.direction == "LONG":
                        move_pct = ((p.last_price - p.entry_price) / p.entry_price) * 100.0
                    else:
                        move_pct = ((p.entry_price - p.last_price) / p.entry_price) * 100.0

                    if not p.partial_sent and move_pct >= 1.2:
                        await office_position_event(
                            sender=sender,
                            symbol=p.symbol,
                            event_type="PARTIAL_CLOSE",
                            details=f"Жива ціна +{move_pct:.2f}%: часткова фіксація 50%.",
                            db_path=db_path,
                        )
                        await send_proactive(
                            EVENT_TRADE_UPDATE,
                            f"{p.symbol}: часткова фіксація 50%.",
                        )
                        p.partial_sent = True
                        continue
                    if p.partial_sent and (not p.moved_sl) and move_pct >= 2.0:
                        await office_position_event(
                            sender=sender,
                            symbol=p.symbol,
                            event_type="MOVE_SL",
                            details=f"Жива ціна +{move_pct:.2f}%: переносимо стоп у беззбиток.",
                            db_path=db_path,
                        )
                        await send_proactive(
                            EVENT_TRADE_UPDATE,
                            f"{p.symbol}: стоп у беззбиток.",
                        )
                        p.moved_sl = True
                        continue
                    if p.moved_sl and move_pct >= 3.0:
                        await office_position_event(
                            sender=sender,
                            symbol=p.symbol,
                            event_type="EXIT",
                            details=f"Жива ціна +{move_pct:.2f}%: вихід по тейк-профіту.",
                            db_path=db_path,
                        )
                        await office_trade_closed(
                            sender=sender,
                            symbol=p.symbol,
                            outcome="WIN",
                            pnl_pct=move_pct,
                            note="Live trigger exit",
                            db_path=db_path,
                        )
                        journal_close_trade(
                            db_path,
                            trade_id=sig_id,
                            outcome="WIN",
                            exit_price=(p.last_price if p.last_price > 0 else None),
                            pnl_pct=move_pct,
                            exit_reason="LIVE TP trigger",
                            mistake_tags=[],
                            review_note="Плановий TP вихід по live тригеру.",
                        )
                        active_positions.pop(sig_id, None)
                        continue
                    if move_pct <= -1.0:
                        await office_position_event(
                            sender=sender,
                            symbol=p.symbol,
                            event_type="EXIT",
                            details=f"Жива ціна {move_pct:.2f}%: захисний вихід (зона стопа).",
                            db_path=db_path,
                        )
                        await office_trade_closed(
                            sender=sender,
                            symbol=p.symbol,
                            outcome="LOSS",
                            pnl_pct=move_pct,
                            note="Live trigger stop-loss exit",
                            db_path=db_path,
                        )
                        tags, review_note = build_stoploss_postmortem(
                            move_pct=move_pct,
                            age_sec=age,
                            volatility_pct=p.initial_volatility_pct,
                            news_risk=p.initial_news_risk,
                            had_partial=p.partial_sent,
                        )
                        journal_close_trade(
                            db_path,
                            trade_id=sig_id,
                            outcome="LOSS",
                            exit_price=(p.last_price if p.last_price > 0 else None),
                            pnl_pct=move_pct,
                            exit_reason="LIVE SL trigger",
                            mistake_tags=tags,
                            review_note=review_note,
                            context_patch={"stoploss_analysis": {"tags": tags, "age_sec": int(age), "move_pct": move_pct}},
                        )
                        await send_proactive(
                            EVENT_TRADE_CLOSED,
                            f"{p.symbol} закрито по стопу. {review_note}",
                        )
                        active_positions.pop(sig_id, None)
            except Exception as exc:
                print(f"[relay][ERROR] monitor_positions failed: {exc}")
            await asyncio.sleep(30)

    asyncio.create_task(monitor_positions())

    async def monitor_news() -> None:
        nonlocal last_news_level
        http_timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=http_timeout) as session:
            while True:
                try:
                    risk = await fetch_news_risk(session, news_api_key)
                    if risk.level != last_news_level:
                        async def sender(msg: str) -> None:
                            await send_proactive(EVENT_NEWS_CRITICAL, msg[:3900], stream="tech")
                        await office_news_trigger(
                            sender=sender,
                            risk_level=risk.level,  # type: ignore[arg-type]
                            headline=risk.headline,
                            minutes_to_event=risk.minutes_to_event,
                            db_path=db_path,
                            event_name=risk.event_name,
                            event_time_utc=risk.event_time_utc,
                            data_status=risk.data_status,
                        )
                        print(f"[relay] news trigger -> {risk.level} ({risk.minutes_to_event}m) {risk.data_status}")
                        last_news_level = risk.level
                except Exception as exc:
                    print(f"[relay][WARN] monitor_news failed: {type(exc).__name__}: {exc}")
                    # Fail-closed: timeout/помилка — Назар мовчить, у Telegram нічого.
                await asyncio.sleep(120)

    asyncio.create_task(monitor_news())

    async def _marichka_dynamic_symbols() -> List[str]:
        """USDT perpetuals: обсяг і добовий рух; плюс активні сигнали; max 20."""
        _skip = ("USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD")
        try:
            to = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=to) as _s:
                async with _s.get("https://fapi.binance.com/fapi/v1/ticker/24hr") as _r:
                    _tickers = await _r.json()
            if not isinstance(_tickers, list):
                raise ValueError("ticker 24hr not a list")
            _candidates: List[Dict[str, Any]] = []
            for _t in _tickers:
                if not isinstance(_t, dict):
                    continue
                _sym = str(_t.get("symbol") or "")
                if not _sym.endswith("USDT"):
                    continue
                if any(_sk in _sym for _sk in _skip):
                    continue
                try:
                    _vol = float(_t.get("quoteVolume") or 0)
                    _chg = abs(float(_t.get("priceChangePercent") or 0))
                except (TypeError, ValueError):
                    continue
                if _vol < 5_000_000:
                    continue
                if not (2.0 <= _chg <= 20.0):
                    continue
                _candidates.append({"symbol": _sym, "volume": _vol})
            _candidates.sort(key=lambda x: float(x["volume"]), reverse=True)

            symbols: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            _active = signal_get_active(db_path)
            for _a in _active:
                if not isinstance(_a, dict):
                    continue
                _sym_a = str(_a.get("symbol") or "").strip().upper()
                if _sym_a and _sym_a not in symbols:
                    symbols.append(_sym_a)
            for _c in _candidates[:30]:
                _sym_c = str(_c.get("symbol") or "").strip().upper()
                if _sym_c and _sym_c not in symbols:
                    symbols.append(_sym_c)
            return symbols[:20]
        except Exception:
            return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    last_marichka_evening_date = ""

    async def run_evening_homework() -> None:
        """
        Щовечора о 21:00 команда готує домашнє завдання на завтра.

        Структура:
        1. Марічка сканує ринок (топ монети)
        2. Знаходить кандидатів
        3. Для кожного — повний top-down
        4. Лев дає фінальний план на завтра
        """
        try:
            from office_market_data import (
                fetch_atr_context,
                fetch_candles,
                fetch_fvg,
                fetch_liquidity_sweep,
                fetch_long_short_ratio,
                fetch_market_structure,
                fetch_open_interest,
                fetch_order_blocks,
                fetch_order_book_walls,
                fetch_pd_array,
                fetch_session_levels,
            )

            symbols = await _marichka_dynamic_symbols()
            candidates: List[Dict[str, Any]] = []

            for symbol in symbols[:20]:
                try:
                    atr = fetch_atr_context(symbol)
                    atr_d = atr if isinstance(atr, dict) else {}
                    day_used = float(atr_d.get("day_used_pct") or 100.0)
                    # ATR>80 не викидає монету зі скану — лише позначає блок входу.

                    structure = fetch_market_structure(symbol, "4h")
                    struct_d = structure if isinstance(structure, dict) else {}
                    pd_arr = fetch_pd_array(symbol, "1d")
                    pd_d = pd_arr if isinstance(pd_arr, dict) else {}
                    sweep = fetch_liquidity_sweep(symbol, "4h")
                    sw_d = sweep if isinstance(sweep, dict) else {}

                    ev = str(struct_d.get("event") or "").upper()
                    has_structure = ev in (
                        "BOS_BULLISH",
                        "BOS_BEARISH",
                        "CHOCH",
                        "HH_HL",
                        "LH_LL",
                    )
                    has_sweep = bool(sw_d.get("bsl_sweep") or sw_d.get("ssl_sweep"))
                    z = str(pd_d.get("zone") or "").upper()
                    has_discount_premium = z in ("PREMIUM", "DISCOUNT")

                    if has_structure or has_sweep or has_discount_premium:
                        candidates.append(
                            {
                                "symbol": symbol,
                                "day_used": day_used,
                                "structure": struct_d,
                                "pd_arr": pd_d,
                                "sweep": sw_d,
                                "atr": atr_d,
                                "entry_blocked_atr80": bool(day_used > 80.0),
                            }
                        )
                except Exception:
                    continue

            if not candidates:
                print("[homework] no candidates — silent")
                return

            candidates.sort(key=lambda x: float(x.get("day_used") or 100.0))
            top5 = candidates[:5]

            homework_results: List[Dict[str, Any]] = []

            from office_evening_homework import (
                build_homework_facts,
                format_facts_block,
                homework_card_text,
                lev_system_prompt,
                marichka_system_prompt,
                recent_setups_note,
                split_telegram_chunks,
                unexplained_levels,
                collect_allowed_prices,
                validate_card_text,
            )
            from office_market_data import fetch_edge_score, fetch_funding_rate, fetch_probability_score
            from office_bridge import signal_get_recent

            for cand in top5:
                symbol = str(cand.get("symbol") or "")
                if not symbol:
                    continue
                try:
                    weekly = fetch_candles(symbol, "1w", 3)
                    daily = fetch_candles(symbol, "1d", 5)
                    session = fetch_session_levels(symbol)
                    fvg_data = fetch_fvg(symbol, "4h")
                    ob_data = fetch_order_blocks(symbol, "4h")
                    dom = fetch_order_book_walls(symbol)
                    ls = fetch_long_short_ratio(symbol)
                    oi = fetch_open_interest(symbol)
                    funding = fetch_funding_rate(symbol)
                    edge = fetch_edge_score(symbol)
                    probability = fetch_probability_score(symbol, db_path)

                    weekly_high = weekly_low = None
                    if isinstance(weekly, list) and weekly:
                        highs = [float(c.get("high", 0) or 0) for c in weekly if isinstance(c, dict)]
                        lows = [float(c.get("low", 0) or 0) for c in weekly if isinstance(c, dict)]
                        if highs:
                            weekly_high = max(highs)
                        if lows:
                            weekly_low = min(lows)

                    current = 0.0
                    if isinstance(daily, list) and daily and isinstance(daily[-1], dict):
                        current = float(daily[-1].get("close") or 0.0)

                    facts = build_homework_facts(
                        symbol=symbol,
                        price=current,
                        weekly_high=weekly_high,
                        weekly_low=weekly_low,
                        session=session if isinstance(session, dict) else {},
                        structure=cand.get("structure") if isinstance(cand.get("structure"), dict) else {},
                        pd_arr=cand.get("pd_arr") if isinstance(cand.get("pd_arr"), dict) else {},
                        sweep=cand.get("sweep") if isinstance(cand.get("sweep"), dict) else {},
                        fvg=fvg_data if isinstance(fvg_data, dict) else {},
                        order_blocks=ob_data if isinstance(ob_data, dict) else {},
                        dom=dom if isinstance(dom, dict) else {},
                        ls=ls if isinstance(ls, dict) else {},
                        oi=oi if isinstance(oi, dict) else {},
                        atr_day_used=cand.get("day_used"),
                        funding=funding if isinstance(funding, dict) else None,
                        edge=edge if isinstance(edge, dict) else None,
                        probability=probability if isinstance(probability, dict) else None,
                    )
                    context = format_facts_block(facts)
                    response = clean_llm_note(
                        ask_agent(
                            "marichka",
                            marichka_system_prompt(),
                            context,
                            max_tokens=1000,
                            db_path=db_path,
                        )
                    )
                    check = validate_card_text(response or "", facts)
                    card = homework_card_text(
                        facts=facts,
                        llm_text=response or "немає тексту моделі",
                        issues=list(check.get("issues") or []),
                    )
                    homework_results.append(
                        {
                            "symbol": symbol,
                            "analysis": card,
                            "facts": facts,
                            "confirmed": bool(facts.get("confirmed") and check.get("ok")),
                        }
                    )
                    try:
                        briefing_save(db_path, symbol, "evening", card)
                    except Exception as save_exc:
                        print(f"[homework] briefing_save {symbol}: {save_exc}")
                    for chunk in split_telegram_chunks(
                        fmt_agent_line("marichka", card),
                    ):
                        print(f"[homework] silent card {symbol}: {chunk[:80]}")
                    await asyncio.sleep(2.0)
                except Exception as e:
                    print(f"[homework] {symbol}: {e}")
                    continue

            if not homework_results:
                print("[homework] nothing interesting — silent")
                return

            any_bad = any(not r.get("confirmed") for r in homework_results)
            facts_joined = "\n\n".join(format_facts_block(r["facts"]) for r in homework_results if r.get("facts"))
            analyses = "\n\n".join(f"{r['symbol']}:\n{r['analysis']}" for r in homework_results)
            setups = []
            try:
                setups = signal_get_recent(db_path, limit=5)
            except Exception:
                setups = []
            if any_bad:
                lev_body = (
                    "дані не підтверджені — готовий торговий план не складаємо.\n"
                    "Марічка передала суперечливі або неповні факти. "
                    "Нових entry/SL/TP немає.\n"
                    f"{recent_setups_note(setups)}\n\n{facts_joined}"
                )
                for chunk in split_telegram_chunks(fmt_agent_line("lev", lev_body)):
                    print(f"[homework] silent lev incomplete: {chunk[:80]}")
                try:
                    briefing_save(db_path, "ALL", "evening_homework", lev_body)
                except Exception as save_exc:
                    print(f"[homework] briefing_save ALL evening_homework: {save_exc}")
                return

            lev_context = (
                f"{recent_setups_note(setups)}\n\n"
                f"ФАКТИ по монетах (єдине джерело рівнів):\n{facts_joined}\n\n"
                f"Тексти Марічки:\n{analyses}\n\n"
                "Склади огляд. Не додавай рівнів поза ФАКТАМИ. "
                "SKIP/ATR_DEAD/EXPIRED — не угоди."
            )
            lev_response = clean_llm_note(
                ask_agent(
                    "lev",
                    lev_system_prompt(),
                    lev_context,
                    max_tokens=1200,
                    db_path=db_path,
                )
            )
            lev_text = lev_response or "немає тексту"
            allowed: set = set()
            for r in homework_results:
                allowed |= collect_allowed_prices(r.get("facts") or {})
            extra = unexplained_levels(lev_text, allowed)
            extra = [x for x in extra if not (1.0 <= x <= 10.0)]
            if extra:
                lev_text = (
                    "дані не підтверджені — готовий торговий план не складаємо.\n"
                    "У відповіді з'явились рівні без джерела: "
                    + ", ".join(f"{x:g}" for x in extra[:8])
                    + "\n\n"
                    + format_facts_block(homework_results[0]["facts"])
                )
            for chunk in split_telegram_chunks(fmt_agent_line("lev", f"Огляд на завтра:\n\n{lev_text}")):
                print(f"[homework] silent lev: {chunk[:80]}")
            try:
                briefing_save(db_path, "ALL", "evening_homework", lev_text)
            except Exception as save_exc:
                print(f"[homework] briefing_save ALL evening_homework: {save_exc}")
        except Exception as e:
            print(f"[evening-homework] error: {e}")

    async def marichka_evening_briefing() -> None:
        """Щодня ~21:00 за OFFICE_BRIEFING_TZ — командне вечірнє домашнє завдання (Марічка + Лев)."""
        nonlocal last_marichka_evening_date
        while True:
            try:
                if os.getenv("OFFICE_MARICHKA_EVENING_DISABLE", "").strip() == "1":
                    await asyncio.sleep(600)
                    continue
                tz = _briefing_tzinfo()
                now = datetime.now(tz)
                today = now.strftime("%Y-%m-%d")
                # Зсув від desk-брифінгу (за замовчуванням 21:10), щоб не дублювати о 21:00.
                eve_h, eve_m = _parse_hh_mm(os.getenv("OFFICE_MARICHKA_EVENING_TIME", "21:10"), 21, 10)
                # Вікно 5 хв, щоб не пропустити хвилину при sleep(30).
                if now.hour == eve_h and eve_m <= now.minute < eve_m + 5 and last_marichka_evening_date != today:
                    await run_evening_homework()
                    last_marichka_evening_date = today
                    print("[relay] evening homework (team) sent")
                    await asyncio.sleep(3660)
                else:
                    await asyncio.sleep(30)
            except Exception as exc:
                print(f"[marichka-evening] scheduler: {exc}")
                await asyncio.sleep(60)

    asyncio.create_task(marichka_evening_briefing())

    async def run_marichka_morning() -> None:
        """Ранок: той самий динамічний список пар + вечірній план з БД."""
        from office_market_data import (
            fetch_atr_context,
            fetch_candles,
            fetch_market_structure,
            fetch_session_levels,
        )

        symbols = await _marichka_dynamic_symbols()
        system_morning = """Ти Марічка. 26 років.
Говориш як подруга — просто і зрозуміло.
Жодних англійських слів.

bias → напрямок
bullish → вгору
bearish → вниз
OTE → зона входу
FVG → незаповнений розрив
BOS → зламала структуру
PDH/PDL → вчорашній максимум/мінімум
liquidity → ліквідність
sweep → маніпуляція

ПИШИ ТІЛЬКИ ПРО ЦІКАВІ МОНЕТИ:
Якщо монета нецікава — мовчи.
Якщо є сетап — пиши коротко:

SYMBOL
Що сталось: (1 речення)
Вчорашній максимум/мінімум: X / Y
Напрямок: вгору/вниз/нейтрально
Зона входу: X–Y
Чекаємо: (1 речення)

Максимум 3-4 монети за ранок.
Краще мало але якісно."""
        for symbol in symbols:
            try:
                candles_1h = fetch_candles(symbol, "1h", 8)
                if not isinstance(candles_1h, list) or not candles_1h:
                    continue
                last_c = candles_1h[-1]
                if not isinstance(last_c, dict):
                    continue
                session = fetch_session_levels(symbol)
                structure = fetch_market_structure(symbol, "1h")
                atr = fetch_atr_context(symbol)

                sess_d = session if isinstance(session, dict) else {}
                asia_high = sess_d.get("asia_high", "N/A")
                asia_low = sess_d.get("asia_low", "N/A")
                current = float(last_c.get("close") or 0.0)

                evening_plan = briefing_get_last(db_path, symbol, "evening")

                tail = candles_1h[-3:] if len(candles_1h) >= 3 else candles_1h
                context = (
                    f"Символ: {symbol}\n"
                    f"Час: ранкове підтвердження (розклад OFFICE_BRIEFING_TZ, ціль 08:00 Київ).\n\n"
                    f"Вечірній план (вчора о 21:00):\n{evening_plan or 'немає даних'}\n\n"
                    f"Нічний коридор (азійська сесія):\nверх: {asia_high}\nниз: {asia_low}\n\n"
                    f"Поточна ціна (остання годинна свічка): {current}\n"
                    f"Структура на 1 год: {structure}\n"
                    f"Рух за день відносно норми (ATR): {atr}\n"
                    f"Останні до трьох свічок по годині: {tail}\n"
                )

                response = clean_llm_note(
                    ask_agent(
                        "marichka",
                        system_morning,
                        context,
                        max_tokens=400,
                    )
                )
                if response:
                    print(f"[marichka-morning] silent {symbol}: {response[:80]}")
            except Exception as exc:
                print(f"[marichka-morning] {symbol}: {exc}")
                continue

    async def marichka_morning_briefing() -> None:
        """Щодня ~08:00 за OFFICE_BRIEFING_TZ — ранкове підтвердження Марічки."""
        last_date = None
        while True:
            try:
                if os.getenv("OFFICE_MARICHKA_MORNING_DISABLE", "").strip() == "1":
                    await asyncio.sleep(600)
                    continue
                tz = _briefing_tzinfo()
                now = datetime.now(tz)
                today = now.date()
                # Зсув від desk-брифінгу (за замовчуванням 08:10), щоб не дублювати о 08:00.
                mor_h, mor_m = _parse_hh_mm(os.getenv("OFFICE_MARICHKA_MORNING_TIME", "08:10"), 8, 10)
                if (
                    now.hour == mor_h
                    and mor_m <= now.minute < mor_m + 5
                    and last_date != today
                ):
                    last_date = today
                    await run_marichka_morning()
                    await asyncio.sleep(3660)
                else:
                    await asyncio.sleep(30)
            except Exception as e:
                print(f"[marichka-morning] {e}")
                await asyncio.sleep(60)

    asyncio.create_task(marichka_morning_briefing())

    async def run_session_playbook(session: str) -> None:
        """
        На початку кожної ключової сесії (Київ) Лев звіряє вечірній план з реальністю
        і дає конкретний playbook.

        session: 'asia' | 'london' | 'ny'
        """
        try:
            if os.getenv("OFFICE_SESSION_PLAYBOOK_DISABLE", "").strip() == "1":
                return
            print(f"[session-playbook] skip LLM/Telegram for {session} (PR41 quiet office)")
            return
            from office_market_data import (
                fetch_atr_context,
                fetch_liquidity_sweep,
                fetch_long_short_ratio,
                fetch_order_book_walls,
                fetch_session_levels,
            )

            evening_plan = briefing_get_last(db_path, "ALL", "evening_homework")

            session_names = {
                "asia": "Азія (03:00–11:00 Київ)",
                "london": "Лондон (11:00–14:00 Київ)",
                "ny": "Нью-Йорк (16:00–19:00 Київ)",
            }

            session_mode = {
                "asia": "Агресивний режим. Шукаємо маніпуляції Asian Range.",
                "london": "Моментум або маніпуляція. Лондон sweep → вхід.",
                "ny": "Захисний режим. Тільки мажори з підтвердженням.",
            }

            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            market_snapshot: List[str] = []

            for symbol in symbols:
                try:
                    session_lvl = fetch_session_levels(symbol)
                    sweep = fetch_liquidity_sweep(symbol, "1h")
                    dom = fetch_order_book_walls(symbol)
                    atr = fetch_atr_context(symbol)
                    ls = fetch_long_short_ratio(symbol)

                    sl = session_lvl if isinstance(session_lvl, dict) else {}
                    sw = sweep if isinstance(sweep, dict) else {}
                    dm = dom if isinstance(dom, dict) else {}
                    at = atr if isinstance(atr, dict) else {}
                    ls_d = ls if isinstance(ls, dict) else {}
                    ls_hist = ls_d.get("history")
                    ls_last = ls_hist[-1] if isinstance(ls_hist, list) and ls_hist else {}
                    long_pct_v = ls_last.get("long_pct") if isinstance(ls_last, dict) else ""

                    snapshot = f"""
{symbol}:
Asian Range: {sl.get("asia_high", "")} / {sl.get("asia_low", "")}
PDH/PDL: {sl.get("pdh", "")} / {sl.get("pdl", "")}
Sweep: {sw.get("description", "")}
Кити: {dm.get("description", "")}
ATR використано: {at.get("day_used_pct", "")}%
L/S: {ls_d.get("current_ratio", "")} ({long_pct_v}% лонгів)
"""
                    market_snapshot.append(snapshot)
                except Exception:
                    continue

            context = f"""
Сесія: {session_names.get(session, session)}
Режим: {session_mode.get(session, "")}

Вечірній план команди:
{evening_plan or "Немає плану — аналізуй поточний ринок"}

Поточний стан ринку:
{"".join(market_snapshot)}
"""

            system = f"""Ти Лев.
Відкривається {session_names.get(session, session)}.
Режим: {session_mode.get(session, "")}

Звір вечірній план з реальністю.
Дай конкретний playbook на цю сесію:

1. Чи реалізується вечірній сценарій?
2. Де зараз ліквідність (Asian low/high)?
3. Чи є sweep маніпуляція?
4. Куди йдуть кити (стакан)?
5. Конкретний план: символ, напрямок, зона входу

Якщо немає сетапу — одне речення і мовчиш.
Якщо є — Entry/SL/TP/RR чітко.
Тільки українська. Максимум 8 речень."""

            response = clean_llm_note(
                ask_agent(
                    "lev",
                    system,
                    context,
                    max_tokens=500,
                    db_path=db_path,
                )
            )

            if not response:
                return

            skip_phrases = [
                "немає сетапу",
                "пропускаємо",
                "нічого цікавого",
            ]

            session_emoji = {
                "asia": "🌏",
                "london": "🇬🇧",
                "ny": "🇺🇸",
            }

            emoji = session_emoji.get(session, "📊")
            sn = session_names.get(session, session)

            if not any(p in response.lower() for p in skip_phrases):
                print(f"[session-playbook] silent {session}: {(response or '')[:120]}")
            else:
                print(f"[session-playbook] silent {session}: no setup")
        except Exception as e:
            print(f"[session-playbook] {e}")

    async def session_announcer() -> None:
        """Повідомляє про початок/кінець ключових вікон за Києвом."""
        announced: set[str] = set()
        while True:
            try:
                tz = _briefing_tzinfo()
                now = datetime.now(tz)
                key = f"{now.date()}_{now.hour}"
                if key not in announced:
                    msg: Optional[str] = None
                    if now.hour == 3:
                        msg = (
                            "🌏 Азіатська сесія відкрилась\n"
                            f"🕐 {format_kyiv_time(now)} за Києвом"
                        )
                    elif now.hour == 11:
                        msg = (
                            "🇬🇧 Лондон відкрився\n"
                            "⚡ Kill Zone почалась (з 11 год до 14 год за Києвом)\n"
                        )
                    elif now.hour == 14:
                        msg = (
                            "🇬🇧 Лондон Kill Zone закрилась\n"
                            "Між сесіями до 16 год"
                        )
                    elif now.hour == 16:
                        msg = (
                            "🇺🇸 Нью-Йорк відкрився\n"
                            "⚡ Kill Zone почалась (з 16 год до 19 год за Києвом)\n"
                        )
                    elif now.hour == 19:
                        msg = (
                            "🇺🇸 NY Kill Zone закрилась\n"
                            "Торговий день завершено."
                        )
                    if msg:
                        announced.add(key)
                        print(f"[session-announcer] silent: {msg.splitlines()[0]}")
                        if now.hour == 3:
                            asyncio.create_task(run_session_playbook("asia"))
                        elif now.hour == 11:
                            asyncio.create_task(run_session_playbook("london"))
                        elif now.hour == 16:
                            asyncio.create_task(run_session_playbook("ny"))
                if len(announced) > 400:
                    announced.clear()
                await asyncio.sleep(55)
            except Exception as e:
                print(f"[session-announcer] {e}")
                await asyncio.sleep(60)

    asyncio.create_task(session_announcer())

    async def proactive_market_scan() -> None:
        """
        Кожні 15 хвилин агенти самі сканують ринок і якщо знаходять сетап —
        пишуть Тетяні першими.
        Kill Zone / сесійні банери — лише в session_announcer(), щоб не дублювати чат.
        """
        try:
            utc_now = datetime.now(timezone.utc)
            h = utc_now.hour
            m = utc_now.minute
            minute_of_day = h * 60 + m
            # Kill Zone за UTC ринку (London/NY вікна); локальний OFFICE_BRIEFING_TZ лише для текстів часу в чаті.
            in_london = 480 <= minute_of_day < 660
            in_ny = 780 <= minute_of_day < 960
            print(f"[scanner] tick UTC={utc_now.hour}:{utc_now.minute} in_ny={in_ny} in_london={in_london}")
            if not (in_london or in_ny):
                return  # поза Kill Zone — мовчимо

            drawdown = check_drawdown_alert(db_path)
            if not drawdown.get("safe"):
                print(f"[scanner] drawdown hold (silent): {drawdown.get('message')}")
                return  # зупиняємо сканер

            async def _scan_sender(msg: str) -> None:
                print(f"[scanner] silent: {str(msg)[:160]}")

            from office_market_data import (
                fetch_atr_context,
                fetch_candles,
                fetch_edge_score,
                fetch_funding_rate,
                fetch_key_levels,
                fetch_liquidations_proxy,
                fetch_long_short_ratio,
                fetch_market_regime,
                fetch_ote_levels,
                fetch_open_interest,
                fetch_probability_score,
                fetch_top_movers,
            )
            from office_gerchik_kernel import compute_gerchik_ops

            EXCLUDED_FROM_SCANNER = {"BTCUSDT", "ETHUSDT"}
            ticker24_map: Dict[str, Dict[str, float]] = {}
            try:
                timeout_scan = aiohttp.ClientTimeout(total=12)
                async with aiohttp.ClientSession(timeout=timeout_scan) as s_scan:
                    async with s_scan.get("https://fapi.binance.com/fapi/v1/ticker/24hr") as r_scan:
                        rows_24 = await r_scan.json()
                if isinstance(rows_24, list):
                    for it in rows_24:
                        if not isinstance(it, dict):
                            continue
                        sym = str(it.get("symbol") or "").upper().strip()
                        if not sym.endswith("USDT") or sym in EXCLUDED_FROM_SCANNER:
                            continue
                        try:
                            qv = float(it.get("quoteVolume") or 0.0)
                            ch = float(it.get("priceChangePercent") or 0.0)
                        except Exception:
                            continue
                        ticker24_map[sym] = {
                            "quote_volume": qv,
                            "change_pct": ch,
                        }
            except Exception:
                ticker24_map = {}

            by_volume = sorted(
                ticker24_map.items(),
                key=lambda kv: float((kv[1] or {}).get("quote_volume") or 0.0),
                reverse=True,
            )
            top_volume_syms = [s for s, _ in by_volume[:30]]
            gainers = fetch_top_movers("gainers", 5)
            losers = fetch_top_movers("losers", 5)
            candidates: List[str] = []
            for sym in top_volume_syms:
                if sym and sym not in candidates:
                    candidates.append(sym)
            combined = (gainers or []) + (losers or [])
            for m_item in combined:
                sym = str((m_item or {}).get("symbol") or "").upper().strip() if isinstance(m_item, dict) else ""
                if sym and sym not in candidates:
                    candidates.append(sym)
            candidates = [s for s in candidates if s not in EXCLUDED_FROM_SCANNER][:50]

            accumulation: List[Dict[str, Any]] = []
            for symbol in top_volume_syms:
                if symbol in EXCLUDED_FROM_SCANNER:
                    continue
                try:
                    candles_d = fetch_candles(symbol, "1d", 7)
                    if not isinstance(candles_d, list) or len(candles_d) < 3:
                        continue
                    highs = [float((c or {}).get("high") or 0.0) for c in candles_d]
                    lows = [float((c or {}).get("low") or 0.0) for c in candles_d]
                    if not highs or not lows:
                        continue
                    weekly_high = max(highs)
                    weekly_low = min(lows)
                    if weekly_low <= 0:
                        continue
                    weekly_range = (weekly_high - weekly_low) / weekly_low * 100.0
                    oi = fetch_open_interest(symbol)
                    hist = (oi or {}).get("history") if isinstance(oi, dict) else []
                    oi_rising = False
                    if isinstance(hist, list) and len(hist) >= 2:
                        try:
                            first_oi = float((hist[0] or {}).get("oi") or 0.0)
                            last_oi = float((hist[-1] or {}).get("oi") or 0.0)
                            oi_rising = last_oi > first_oi > 0
                        except Exception:
                            oi_rising = False
                    if weekly_range < 15.0 and oi_rising:
                        accumulation.append(
                            {
                                "symbol": symbol,
                                "days": len(candles_d),
                                "low": weekly_low,
                                "high": weekly_high,
                                "weekly_range": weekly_range,
                            }
                        )
                except Exception:
                    continue

            setups_found: List[Dict[str, Any]] = []
            for symbol in candidates[:10]:
                try:
                    if symbol in EXCLUDED_FROM_SCANNER:
                        continue
                    t24 = ticker24_map.get(symbol, {})
                    quote_volume = float((t24 or {}).get("quote_volume") or 0.0)
                    change_pct = float((t24 or {}).get("change_pct") or 0.0)
                    if quote_volume <= 3_000_000:
                        continue
                    if abs(change_pct) >= 20.0:
                        continue
                    last_ts = float(_last_signal_time.get(symbol, 0.0) or 0.0)
                    if (time.time() - last_ts) < 7200:
                        continue
                    if symbol == "BTCUSDT" and any("BTC" in str(s.get("symbol") or "") for s in setups_found):
                        continue
                    atr = fetch_atr_context(symbol)
                    atr_used = float((atr or {}).get("day_used_pct", 100) or 100)
                    atr_cls = classify_atr_day_used(atr_used)
                    skip_enter = bool(atr_cls.get("gerchik_entry_blocked") or atr_cls.get("t0_entry_blocked"))
                    try:
                        btc_reg = str((fetch_market_regime("BTCUSDT") or {}).get("regime") or "").upper()
                    except Exception:
                        btc_reg = ""
                    if symbol != "BTCUSDT" and btc_reg in ("NEWS_CHAOS", "PANIC", "LOW_LIQUIDITY"):
                        continue

                    gops = compute_gerchik_ops(symbol)
                    gscore = gops.get("gerchik_ops_score") if isinstance(gops, dict) else None
                    if gscore is not None and int(gscore) <= 4:
                        continue
                    if isinstance(gops, dict) and gops.get("gerchik_atr_trend_veto") and not (
                        str(gops.get("gerchik_ops_reasons") or "").find("ЛП") >= 0
                        or any("sweep" in str(x).lower() or "ЛП" in str(x) for x in (gops.get("gerchik_ops_reasons") or []))
                    ):
                        skip_enter = True

                    edge_data = fetch_edge_score(symbol)
                    if skip_enter or not edge_data.get("has_edge"):
                        try:
                            fac = edge_data.get("factors") or []
                            factors_txt = "; ".join(str(x) for x in fac)[:500]
                            signal_upsert(
                                db_path,
                                signal_id=f"watch-edge-{symbol}",
                                symbol=symbol,
                                direction=str(edge_data.get("recommendation") or "NO_TRADE"),
                                entry_low=None,
                                entry_high=None,
                                sl=None,
                                tp1=None,
                                tp2=None,
                                rr=None,
                                status="WATCHING",
                                analysis_note=(
                                    f"edge_score={edge_data.get('edge_score')} "
                                    f"grade={edge_data.get('grade')} "
                                    f"{edge_data.get('verdict', '')}. {factors_txt}"
                                ),
                            )
                        except Exception as exc_w:
                            print(f"[scanner] watch-edge {symbol}: {exc_w}")
                        continue

                    setup_direction = str(edge_data.get("recommendation") or "").upper().strip()
                    if setup_direction not in ("LONG", "SHORT"):
                        continue

                    ls = fetch_long_short_ratio(symbol)
                    funding = fetch_funding_rate(symbol)
                    ote = fetch_ote_levels(symbol, "1h")
                    levels = fetch_key_levels(symbol)

                    funding_pct = float((funding or {}).get("funding_rate_pct", 0) or 0)
                    ls_ratio = float((ls or {}).get("current_ratio", 1) or 1)

                    setups_found.append(
                        {
                            "symbol": symbol,
                            "direction": setup_direction,
                            "atr_used": edge_data.get("day_used_pct", atr_used),
                            "funding": funding_pct,
                            "ls_ratio": ls_ratio,
                            "ote": ote,
                            "levels": levels,
                            "atr": atr,
                            "quote_volume": quote_volume,
                            "change_pct": change_pct,
                            "edge_score": edge_data.get("edge_score"),
                            "edge_grade": edge_data.get("grade"),
                            "edge_verdict": edge_data.get("verdict"),
                            "gerchik_ops": gops,
                            "gerchik_ops_score": gscore,
                        }
                    )
                    _last_signal_time[symbol] = time.time()
                except Exception:
                    continue

            if accumulation:
                # Quiet mode: announce max 1 accumulation candidate per scan.
                accumulation.sort(key=lambda x: float(x.get("weekly_range") or 999.0))
                for acc in accumulation[:1]:
                    acc_symbol = str(acc.get("symbol") or "")
                    acc_low = float(acc.get("low") or 0.0)
                    acc_high = float(acc.get("high") or 0.0)
                    acc_days = int(acc.get("days") or 7)
                    skip_acc, skip_acc_reason = signal_should_skip_proactive_scan(
                        db_path, acc_symbol, cooldown_hours=24.0
                    )
                    if skip_acc:
                        print(f"[scanner] wyckoff skip {acc_symbol}: {skip_acc_reason}")
                        continue
                    acc_key = f"ACC::{acc_symbol}"
                    last_acc_ts = float(_last_signal_time.get(acc_key, 0.0) or 0.0)
                    if (time.time() - last_acc_ts) < 24 * 3600:
                        continue
                    correlation = check_portfolio_correlation(db_path)
                    if not correlation.get("safe"):
                        print(f"[scanner] wyckoff correlation silent: {correlation.get('message')}")
                        continue
                    _last_signal_time[acc_key] = time.time()
                    print(
                        f"[scanner] wyckoff WATCHING {acc_symbol} {acc_days}d "
                        f"{acc_low:.6f}–{acc_high:.6f} (Telegram silent)"
                    )
                    signal_upsert(
                        db_path,
                        signal_id=f"watch-acc-{acc_symbol}-{int(time.time())}",
                        symbol=acc_symbol,
                        direction="LONG",
                        entry_low=acc_low,
                        entry_high=acc_high,
                        sl=None,
                        tp1=None,
                        tp2=None,
                        rr=None,
                        status="WATCHING",
                        analysis_note=f"Accumulation {acc_days}d range {acc_low:.6f}-{acc_high:.6f}",
                    )

            if not setups_found:
                return

            correlation = check_portfolio_correlation(db_path)
            if not correlation.get("safe"):
                print(f"[scanner] correlation hold silent: {correlation.get('message')}")
                return

            best = min(setups_found, key=lambda x: float(x.get("atr_used") or 100))
            symbol = str(best.get("symbol") or "BTCUSDT")
            direction = str(best.get("direction") or "LONG")
            print(
                f"[scanner] skip desk LLM/Telegram for {symbol} {direction} "
                "(PR41: ПРОПУСК мовчки; SIGNAL_ENTRY лише з радара після свіпу/BOS)"
            )
            return
            skip_pro, skip_reason = signal_should_skip_proactive_scan(db_path, symbol)
            if skip_pro:
                print(f"[scanner] proactive skip {symbol}: {skip_reason}")
                return
            liq_now = fetch_liquidations_proxy(symbol)
            oi_now = fetch_open_interest(symbol)
            candles_h1 = fetch_candles(symbol, "1h", 6)
            candles_h4 = fetch_candles(symbol, "4h", 6)
            current_price = liq_now.get("current_price") if isinstance(liq_now, dict) else None
            news_risk = "SAFE"
            news_mins = 999
            news_event_name = ""
            news_kyiv_time = ""
            news_data_status = DATA_UNAVAILABLE
            if news_api_key:
                try:
                    timeout_news = aiohttp.ClientTimeout(total=10)
                    async with aiohttp.ClientSession(timeout=timeout_news) as s_news:
                        n = await fetch_news_risk(s_news, news_api_key)
                        news_risk = str(n.level)
                        news_mins = int(n.minutes_to_event)
                        news_event_name = str(n.event_name or n.headline or "")
                        news_data_status = str(n.data_status or DATA_UNAVAILABLE)
                        if news_mins >= 0:
                            news_kyiv_time = _to_kyiv_time_from_utc(
                                str(getattr(n, "event_time_utc", "") or ""),
                                news_mins,
                            )
                except Exception:
                    news_data_status = DATA_UNAVAILABLE
            risk_snapshot = live_risk_snapshot(db_path)
            active_signals = signal_get_active(db_path)

            def _tf_snapshot(label: str, candles: Any) -> str:
                if not isinstance(candles, list) or len(candles) < 2:
                    return f"{label}: n/a"
                try:
                    last_price = float((candles[-1] or {}).get("close"))
                    prev_price = float((candles[-2] or {}).get("close"))
                    if prev_price == 0:
                        return f"{label}: {last_price:.6f} (+0.0%)"
                    change = (last_price - prev_price) / prev_price * 100.0
                    return f"{label}: {last_price:.6f} ({change:+.1f}%)"
                except Exception:
                    return f"{label}: n/a"

            async def _send_agent_turn(agent_key: str, text: str) -> None:
                if not text:
                    return
                # Text is already shortened by _trim_lines.
                body = clean_self_naming(str(text).strip(), agent_key)
                msg = fmt_agent_line(agent_key, body)
                await send_office(msg[:3800], stream="general")

            await _send_agent_turn("lev", f"Тетяно, бачу сетап 👀\n{direction} {symbol} — команда, аналіз.")
            await asyncio.sleep(1.5)

            maks_ctx = (
                f"Символ: {symbol}\nНапрямок: {direction}\nПоточна ціна: {current_price}\n"
                f"OI: {oi_now}\nFunding: {best.get('funding')}%\nL/S: {best.get('ls_ratio')}\n"
                f"Ліквідації: {liq_now}\n"
                f"Герчик_бал: {best.get('gerchik_ops_score')}\n"
                f"Герчик_причини: {best.get('gerchik_ops')}"
            )
            maks_msg = clean_llm_note(
                ask_agent(
                    "maks",
                    f"{DESK_BASE_RULE}\nТи Макс. Дай коротко ринкові дані: OI/funding/liquidations, "
                    "модель Герчика (відбій/пробій/ЛП) і висновок по імпульсу. Українською.",
                    maks_ctx,
                    max_tokens=900,
                )
            )
            maks_msg = _trim_lines(maks_msg, 4)
            await _send_agent_turn("maks", maks_msg or "OI/funding/ліквідації підтверджують робочий сценарій.")
            await asyncio.sleep(1.5)

            mar_ctx = (
                f"Символ: {symbol}\n"
                f"Напрямок: {direction}\n"
                f"{_tf_snapshot('H1', candles_h1)}\n"
                f"{_tf_snapshot('H4', candles_h4)}\n"
                "Без сирих OHLCV: дай тільки висновок."
            )
            mar_msg = clean_llm_note(
                ask_agent(
                    "marichka",
                    "Ти Марічка. Дай bias по H4/Daily і чи є рівень/дзеркало/ЛП. Коротко. Українською.",
                    mar_ctx,
                    max_tokens=900,
                )
            )
            mar_msg = _trim_lines(mar_msg, 4)
            await _send_agent_turn("marichka", mar_msg or "На H4/Daily структура підтверджує поточний напрямок.")
            await asyncio.sleep(1.5)

            news_msg = format_nazar_update(
                data_status=news_data_status,
                minutes_to_event=news_mins,
                event_name=news_event_name,
                event_time_ua=news_kyiv_time,
            )
            if news_msg:
                news_msg = _trim_lines(news_msg, 3)
                await _send_agent_turn("news", news_msg)
            await asyncio.sleep(1.5)

            daryna_ctx = (
                f"Символ: {symbol}\nНапрямок: {direction}\nATR: {best.get('atr')}\n"
                f"Live risk snapshot: {risk_snapshot}\nНовини: {news_risk}\n"
                f"Герчик_бал: {best.get('gerchik_ops_score')} (0–4 = вето)"
            )
            daryna_msg = clean_llm_note(
                ask_agent(
                    "daryna",
                    f"{DESK_BASE_RULE}\nТи Дарина. Дай ризик-висновок і вето/допуск коротко, українською. "
                    "Герчик_бал ≤4 або ATR≥80% по тренду без ЛП — вето.",
                    daryna_ctx,
                    max_tokens=900,
                )
            )
            daryna_msg = _trim_lines(daryna_msg, 4)
            await _send_agent_turn("daryna", daryna_msg or "Ризик контрольований, можна працювати тільки по плану.")
            await asyncio.sleep(1.5)

            marko_ctx = (
                f"Символ: {symbol}\nНапрямок: {direction}\nПоточна ціна: {current_price}\n"
                f"OTE: {best.get('ote')}\nКлючові рівні: {best.get('levels')}\n"
                "Дай execution-план з Entry/SL/TP1/TP2/RR і блоком 'ЩО РОБИТИ ЗАРАЗ'."
            )
            marko_msg = clean_llm_note(
                ask_agent(
                    "marko",
                    f"{DESK_BASE_RULE}\nТи Марко. Дай конкретний execution-план: Entry/SL/TP1/TP2/RR≥3 + що робити зараз. Українською.",
                    marko_ctx,
                    max_tokens=900,
                )
            )
            marko_msg = _trim_lines(marko_msg, 5)
            await _send_agent_turn("marko", marko_msg or f"ЩО РОБИТИ ЗАРАЗ (ціна {current_price}): чекаємо підтвердження в зоні Entry.")
            await asyncio.sleep(1.5)

            active_signals_short = []
            for s in active_signals[:6]:
                active_signals_short.append(
                    f"{str(s.get('symbol') or '')}:{str(s.get('status') or '')}"
                )
            try:
                prob = fetch_probability_score(symbol, db_path)
                regime = fetch_market_regime(symbol)
                lev_extra = f"""
Додаткові дані:
Хто контролює: {regime.get('controller', '')}
Очікувана цінність (EV): {prob.get('expected_value', '')}
EV позитивне: {prob.get('ev_positive', '')}
Ймовірність маніпуляції: {prob.get('sweep_probability', '')}%
Ймовірність фейкового пробою: {prob.get('fake_breakout_prob', '')}%
"""
            except Exception:
                lev_extra = ""
            team_pack = (
                f"Макс: {maks_msg}\n"
                f"Марічка: {mar_msg}\n"
                f"Назар: {news_msg}\n"
                f"Дарина: {daryna_msg}\n"
                f"Марко: {marko_msg}\n"
                f"Символ: {symbol}\nНапрямок: {direction}\nЦіна: {current_price}\n"
                f"Активні сигнали (коротко): {active_signals_short}\n"
                "Якщо по цьому символу вже є активний — дай UPDATE а не новий сигнал."
                f"Герчик_бал: {best.get('gerchik_ops_score')}\n"
                f"{lev_extra}"
            )
            lev_final_system = (
                f"{LEV_RULE}"
                "Ти Лев. На базі реплік команди дай фінальне рішення: ВХІД/ЧЕКАЄМО/ПРОПУСК. "
                "Обов'язково: Модель Герчика і Герчик_бал. Українською."
            )
            lev_final = clean_llm_note(
                ask_agent(
                    "lev",
                    lev_final_system,
                    team_pack,
                    max_tokens=600,
                )
            )
            lev_final = _trim_lines(lev_final, 7)
            lev_low = (lev_final or "").lower()
            skip_words = [
                "пропуск",
                "пропускаємо",
                "не входжу",
                "не входимо",
                "чекаю",
                "немає входу",
            ]
            is_skip = any(w in lev_low for w in skip_words)
            if is_skip:
                levels_skip = apply_zone_sanity(
                    _parse_signal_levels_from_text(lev_final or ""),
                    current_price,
                )
                el = levels_skip.get("entry_low")
                if el is not None:
                    try:
                        gate = apply_skip_watching_gate(
                            db_path,
                            symbol=symbol,
                            direction=direction,
                            entry_low=levels_skip.get("entry_low"),
                            entry_high=levels_skip.get("entry_high"),
                            timeframe="1h",
                            now_ts=time.time(),
                            current_price=current_price,
                        )
                        if gate.get("create"):
                            signal_upsert(
                                db_path,
                                signal_id=f"proactive-watch-{symbol}-{int(time.time())}",
                                symbol=symbol,
                                direction=direction,
                                entry_low=levels_skip.get("entry_low"),
                                entry_high=levels_skip.get("entry_high"),
                                sl=levels_skip.get("sl"),
                                tp1=levels_skip.get("tp1"),
                                tp2=levels_skip.get("tp2"),
                                rr=levels_skip.get("rr"),
                                status="WATCHING",
                                analysis_note=(lev_final or "")[:2000],
                            )
                            eh = levels_skip.get("entry_high")
                            print(
                                f"[scanner] {symbol} → WATCHING тихо "
                                f"{el}-{eh if eh is not None else el}"
                            )
                        else:
                            print(
                                f"[scanner] T3 skip duplicate WATCHING {symbol} "
                                f"key={gate.get('key')}"
                            )
                        record_skip_if_valid(
                            db_path,
                            gate,
                            symbol=symbol,
                            timeframe="1h",
                        )
                    except Exception as exc_w:
                        print(f"[scanner] silent WATCHING upsert failed {symbol}: {exc_w}")
                return

            has_entry = any(
                w in lev_low
                for w in ("entry:", "вхід:", "входь")
            )
            has_sl = "sl:" in lev_low
            if not (has_entry and has_sl):
                print(f"[scanner] {symbol} → немає чіткого сетапу, мовчимо")
                return

            # LLM-текст «entry/sl» не є висновком Лева: ACTIVE лише якщо lev_cycle дав SEND
            # у тому самому напрямку. Інакше — тихий WATCHING (OFFICE_LEGACY_ACTIVE_REQUIRES_LEV=0
            # повертає стару поведінку).
            from office_legacy_guard import legacy_requires_lev, legacy_scenario_status, lev_cycle_for_symbol

            legacy_cycle: Dict[str, Any] = {}
            if legacy_requires_lev():
                legacy_cycle = await asyncio.to_thread(lev_cycle_for_symbol, db_path, symbol, current_price)
            legacy = legacy_scenario_status(legacy_cycle, direction=direction, enforce=legacy_requires_lev())
            if legacy["status"] == "ACTIVE":
                await _send_agent_turn("lev", lev_final or "Рішення: чекаємо відкату в Entry-зону. Якщо не дійде — пропускаємо.")
            else:
                print(f"[scanner] {symbol} LLM-сетап без підтвердження Лева → WATCHING тихо: {legacy['reason']}")

            parsed = _parse_signal_levels_from_text(marko_msg or lev_final or "")
            signal_id = f"proactive-{symbol}-{int(time.time())}"
            signal_upsert(
                db_path,
                signal_id=signal_id,
                symbol=symbol,
                direction=direction,
                entry_low=parsed.get("entry_low"),
                entry_high=parsed.get("entry_high"),
                sl=parsed.get("sl"),
                tp1=parsed.get("tp1"),
                tp2=parsed.get("tp2"),
                rr=parsed.get("rr"),
                status=legacy["status"],
                analysis_note=(legacy["note_prefix"] + (lev_final or ""))[:2000],
            )
            if legacy["status"] != "ACTIVE":
                return
            # ФІКС 4: Олеся автоматично заносить сигнал у бібліотеку угод.
            try:
                rid = trade_journal_add(
                    db_path,
                    symbol=symbol,
                    direction=direction,
                    entry_price=parsed.get("entry_low"),
                    sl=parsed.get("sl"),
                    tp=parsed.get("tp1"),
                    setup_type="proactive_scan",
                    session=_kb_session_label(),
                    source_text=(lev_final or "")[:500],
                )
                await _send_agent_turn(
                    "olesya",
                    f"Записала {symbol} {direction} в журнал (#{rid or '—'}).",
                )
            except Exception as exc_j:
                print(f"[olesya-journal] {exc_j}")
        except Exception as e:
            print(f"[scanner] error: {e}")

    async def monitor_proactive_scanner() -> None:
        while True:
            await proactive_market_scan()
            await asyncio.sleep(3600)

    asyncio.create_task(monitor_proactive_scanner())

    _victor_sl_streak_prev = -1

    async def check_victor_trigger() -> None:
        nonlocal _victor_sl_streak_prev
        try:
            sl_streak = victor_recent_sl_streak(db_path, 5)
            if sl_streak < 3:
                _victor_sl_streak_prev = sl_streak
                return
            crossed = sl_streak >= 3 and _victor_sl_streak_prev < 3
            if crossed:
                response = clean_llm_note(
                    ask_agent(
                        "psych",
                        VICTOR_RULE,
                        f"Ситуація: {sl_streak} стопів підряд. Тетяна може бути в стресі.",
                        max_tokens=150,
                        db_path=db_path,
                    )
                )
                if response:
                    print(f"[victor] silent (no Telegram): {response[:160]}")
            _victor_sl_streak_prev = sl_streak
        except Exception as e:
            print(f"[victor] error: {e}")

    async def _agent_live_reaction(agent_key: str, context: str, max_tokens: int = 60) -> None:
        try:
            from office_bridge import (
                LEV_RULE as _br_lev,
                DESK_BASE_RULE as _br_desk,
                MARICHKA_RULE as _br_mar,
                ARTEM_RULE as _br_art,
                OLESYA_RULE as _br_olesya,
                VICTOR_RULE as _br_vic,
            )

            key = str(agent_key or "").strip().lower()
            rules = {
                "lev": _br_lev,
                "olesya": _br_olesya,
                "psych": _br_vic,
                "marko": _br_desk,
                "maks": _br_desk,
                "marichka": _br_mar,
                "news": _br_desk,
                "daryna": _br_desk,
                "memory": _br_desk,
                "dev": _br_art,
            }
            system = rules.get(key) or _br_desk
            response = clean_llm_note(
                ask_agent(
                    key,
                    system,
                    context,
                    max_tokens=max_tokens,
                    db_path=db_path,
                )
            )
            if response:
                response = clean_self_naming(response, key)
                print(f"[agent-live] skip telegram {key}: {response[:120]}")
        except Exception as exc:
            print(f"[agent-live] {agent_key}: {exc}")

    async def _olesya_live_signal_line(context: str, max_tokens: int = 80) -> None:
        await _agent_live_reaction("olesya", context, max_tokens=max_tokens)

    async def monitor_active_signals() -> None:
        from office_market_data import (
            fetch_liquidations_proxy,
            fetch_candles,
            fetch_atr_context,
        )
        _ = fetch_candles
        def _allow_notify(sym: str, event: str) -> bool:
            key = f"{str(sym or '').upper()}::{event}"
            now_ts = time.time()
            last_ts = float(_last_notified.get(key, 0.0) or 0.0)
            ev_u = str(event or "").upper()
            # Трейл/HOLD дедупляться по значенню SL / стану, не 30-хв вікном.
            if ev_u in ("TRAIL", "HOLD", "CONT", "ADD", "RSI_EXTREME"):
                window = 2.0
            else:
                window = ZONE_REACHED_COOLDOWN_SEC if event in ("WATCHING_REANALYZE", "ZONE_REACHED") else 1800
            if (now_ts - last_ts) < window:
                return False
            _last_notified[key] = now_ts
            return True

        WATCHING_COOLDOWN_SEC = 4 * 3600

        def _lev_msg(sym: str, happened: str, action_now: str, sl_after: str) -> str:
            sls = format_px(sl_after, sym) or str(sl_after or "")
            return (
                f"Тетяно, {sym}: {happened}\n"
                f"Що робити зараз: {action_now}\n"
                f"SL після дії: {sls}"
            )
        _win_streak_celebrated_at = 0
        while True:
            utc_now = datetime.now(timezone.utc)
            minute_of_day = utc_now.hour * 60 + utc_now.minute
            # Kill Zone за UTC (ренок); fast_poll не змішувати з київським часом у повідомленнях.
            in_london = 480 <= minute_of_day < 660
            in_ny = 780 <= minute_of_day < 960
            fast_poll = in_london or in_ny
            try:
                active_rows = signal_get_active(db_path)
                processed_watching_symbols: set[str] = set()
                for row in active_rows:
                    try:
                        signal_id = str(row.get("signal_id") or "")
                        symbol = str(row.get("symbol") or "")
                        direction = str(row.get("direction") or "LONG").upper()
                        status = str(row.get("status") or "ACTIVE").upper()
                        entry_low = row.get("entry_low")
                        entry_high = row.get("entry_high")
                        sl = row.get("sl")
                        tp1 = row.get("tp1")
                        tp2 = row.get("tp2")
                        ts_created = str(row.get("ts_created") or "")
                        from office_scenario_memory import parse_note_meta

                        scenario_meta = parse_note_meta(row.get("analysis_note"))
                        canonical_sid = str(scenario_meta.get("scenario_id") or "")
                        if not signal_id or not symbol:
                            continue

                        now_utc = datetime.now(timezone.utc)
                        try:
                            created_dt = datetime.fromisoformat(ts_created.replace("Z", "+00:00"))
                            if created_dt.tzinfo is None:
                                created_dt = created_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            created_dt = now_utc

                        if status == "CONFIRMED":
                            # План надіслано, угоду власниця не позначала: термін дії/скасування за закриттям H1 — лише БД, у Telegram НІКОЛИ.
                            try:
                                _pos_open = bool(get_explicit_open_position(db_path, symbol, direction).get("ok"))
                                _h1x = None
                                if not _pos_open and sl is not None:
                                    _h1x = fetch_candles(symbol, "1h", 60)
                                act_c = _lc.confirmed_plan_action(ts_updated=row.get("ts_updated"), tf=scenario_meta.get("timeframe") or "H1", sl=sl,
                                                                  direction=direction, candles_h1=_h1x, has_position=_pos_open,
                                                                  tp1=tp1, tp2=row.get("tp2"), price=((_h1x[-1] or {}).get("close") if isinstance(_h1x, list) and _h1x else None))
                                if act_c:
                                    signal_update(db_path, signal_id=signal_id, status=act_c["status"], outcome=act_c["outcome"], analysis_note=act_c["note"])
                                    print(f"[signals] {symbol} підтверджений план знято без Telegram: {act_c['status']} ({act_c.get('reason')})")
                                    if act_c.get("reason") == "TIME":   # зняття за часом перевіряємо заднім числом: чи не вбили хорошу ідею (FALSE_EXPIRY)
                                        import office_signal_track as _trk2

                                        _trk2.record_expiry(db_path, scenario_id=canonical_sid or signal_id, symbol=symbol, direction=direction,
                                                            zone_lo=entry_low, zone_hi=entry_high, sl=sl, tp1=tp1, expired_ts=time.time())
                            except Exception as exc_cc:
                                print(f"[signals] confirmed-plan check {symbol}: {type(exc_cc).__name__}: {exc_cc}")
                            continue

                        from office_lifecycle import watching_ttl_enabled, watching_ttl_exceeded

                        if watching_ttl_enabled() and watching_ttl_exceeded(status, created_dt, now_utc):
                            signal_update(db_path, signal_id=signal_id, status="EXPIRED", outcome="TTL")
                            try:
                                log_event(db_path, "SCENARIO_EXPIRED", {"symbol": symbol, "reason": "WATCHING TTL 4h",
                                                                         "from": status}, signal_id)
                                apply_setup_event(canonical_sid or signal_id, "EXPIRED", expired=True)
                            except Exception as exc_ttl:
                                print(f"[ttl] {symbol} expire bookkeeping: {exc_ttl}")
                            print(f"[ttl] {symbol} {signal_id} WATCHING → EXPIRED (TTL)")
                            continue

                        if status == "ACTIVE" and (now_utc - created_dt).total_seconds() > 4 * 3600:
                            signal_update(db_path, signal_id=signal_id, status="EXPIRED", outcome="EXPIRED")
                            continue

                        liq_now = fetch_liquidations_proxy(symbol)
                        current_price = float((liq_now or {}).get("current_price") or 0.0) if isinstance(liq_now, dict) else 0.0
                        if current_price <= 0:
                            continue
                        pos_info = get_explicit_open_position(db_path, symbol, direction)
                        in_pos_row = bool(pos_info.get("ok"))
                        pos_tid = str(pos_info.get("trade_id") or "")

                        e_low = float(entry_low) if entry_low is not None else None
                        e_high = float(entry_high) if entry_high is not None else None
                        sl_v = float(sl) if sl is not None else None
                        tp1_v = float(tp1) if tp1 is not None else None
                        tp2_v = float(tp2) if tp2 is not None else None

                        if status == "WATCHING" and e_low is not None:
                            sym_u = symbol.upper()
                            if sym_u in processed_watching_symbols:
                                continue
                            processed_watching_symbols.add(sym_u)
                            # ATR рахуємо лише коли ціна вже в зоні: інакше WATCHING
                            # зникав до алерту (IRYS). Поріг >90 лишається блоком входу.
                            day_used_row: float | None = None
                            watch_high = e_high if e_high is not None else e_low
                            in_zone_now = (
                                watch_high is not None
                                and min(e_low, watch_high) <= current_price <= max(e_low, watch_high)
                            )
                            if in_zone_now:
                                try:
                                    atr_row = fetch_atr_context(symbol)
                                    day_used_row = float((atr_row or {}).get("day_used_pct", 0) or 0)
                                except Exception:
                                    day_used_row = None
                            plan = plan_watching_zone_hit(
                                current_price=current_price,
                                entry_low=e_low,
                                entry_high=e_high,
                                day_used_pct=day_used_row,
                                sl=sl_v,
                                tp1=tp1_v,
                                tp2=tp2_v,
                                symbol=symbol,
                            )
                            if plan.in_zone:
                                zkey = canonical_sid or origin_key(
                                    symbol=symbol,
                                    direction=direction,
                                    zone_lo=e_low,
                                    zone_hi=e_high if e_high is not None else e_low,
                                    origin="t0",
                                )
                                apply_setup_event(zkey, "ZONE_IN", in_zone=True)
                                zg = may_emit_telegram(
                                    key=zkey,
                                    intent="ZONE_IN",
                                    in_zone=True,
                                )
                                if _allow_notify(signal_id, "ZONE_REACHED"):
                                    log_event(
                                        db_path,
                                        "ZONE_REACHED",
                                        {
                                            "symbol": symbol,
                                            "price": current_price,
                                            "signal": "YES" if plan.signal_ok else "NO",
                                            "reason": plan.block_reason or zg.get("reason"),
                                        },
                                        signal_id,
                                    )
                                    # Навіть SIGNAL=YES: зона ≠ «можна входити». Telegram тихий.
                                    if zone_reached_to_telegram(plan) and not text_grants_entry(
                                        format_zone_signal_entry(
                                            symbol=symbol,
                                            current_price=current_price,
                                            entry_low=e_low,
                                            entry_high=e_high if e_high is not None else e_low,
                                            sl=sl_v,
                                            tp1=tp1_v,
                                            tp2=tp2_v,
                                        )
                                    ):
                                        pass
                                    print(f"[t0] ZONE_REACHED silent {symbol}: {plan.message[:200]}")
                                post = after_zone_reached_action(
                                    analysis_note=row.get("analysis_note"),
                                    plan=plan,
                                )
                                # T0-PROBE: зупинка одразу після алерту, пороги ATR/edge без змін.
                                if post == "STOP":
                                    signal_update(
                                        db_path,
                                        signal_id=signal_id,
                                        status="EXPIRED",
                                        outcome="T0_PROBE",
                                        analysis_note=str(row.get("analysis_note") or T0_PROBE_PREFIX),
                                    )
                                    continue
                                if post == "EXPIRE_ATR":
                                    signal_update(
                                        db_path,
                                        signal_id=signal_id,
                                        status="EXPIRED",
                                        outcome="ATR_DEAD",
                                        analysis_note="WATCHING: ZONE_REACHED, ATR day_used_pct>90, вхід заблоковано",
                                    )
                                    continue
                                if plan.promote_active:
                                    # Не піднімаємо ACTIVE з факту «ціна в зоні».
                                    print(f"[t0] skip promote_active {symbol} (zone ≠ entry)")
                                    continue
                                if plan.run_reanalyze:
                                    print(
                                        f"[t0] skip proactive desk LLM for {symbol} "
                                        f"(ZONE_REACHED SIGNAL=NO, saved {2} LLM calls)"
                                    )
                                    signal_touch_updated(db_path, signal_id=signal_id)
                                continue

                        scz = parse_sc_zone_note(row.get("analysis_note"))
                        if status == "ACTIVE" and scz is not None:
                            try:
                                m15_can = fetch_candles(symbol, "15m", 4)
                            except Exception:
                                m15_can = []
                            last_cl = None
                            if isinstance(m15_can, list) and m15_can:
                                last_cl = (m15_can[-1] or {}).get("close")
                            if last_cl is None:
                                last_cl = current_price
                            if sc_setup_cancelled(
                                direction=direction,
                                close=last_cl,
                                sc_low=scz[0],
                                sc_high=scz[1],
                            ):
                                signal_update(
                                    db_path,
                                    signal_id=signal_id,
                                    status="EXPIRED",
                                    outcome="CANCELLED",
                                    analysis_note=f"SC cancel close={last_cl} zone={scz[0]}-{scz[1]}",
                                )
                                try:
                                    journal_close_trade(
                                        db_path,
                                        trade_id=office_signal_trade_id(signal_id),
                                        outcome="BE",
                                        exit_price=float(last_cl or current_price),
                                        pnl_pct=0.0,
                                        exit_reason="скасовано до входу (закриття за зоною SC)",
                                        context_patch={"result": "CANCELLED"},
                                    )
                                except Exception:
                                    pass
                                if _allow_notify(symbol, "SC_CANCEL"):
                                    await send_proactive(
                                        EVENT_TRADE_CLOSED,
                                        f"❌ Скасовано · {symbol}: закриття за межею зони сильної свічки, вхід не відкриваємо.",
                                        stream="general",
                                    )
                                continue

                        if status == "ACTIVE" and e_low is not None and e_high is not None and e_low <= current_price <= e_high:
                            missing_levels_active = sl_v is None or (tp1_v is None and tp2_v is None)
                            if missing_levels_active:
                                print(f"[t0] ACTIVE incomplete SL/TP {symbol}: silent, no desk LLM")
                                continue
                            hkey = canonical_sid or origin_key(
                                symbol=symbol,
                                direction=direction,
                                zone_lo=e_low,
                                zone_hi=e_high,
                                origin="t0",
                            )
                            apply_setup_event(hkey, "HIT_ENTRY", in_zone=True)
                            hg = may_emit_telegram(key=hkey, intent="HIT_ENTRY_PRICE", in_zone=True)
                            print(
                                f"[t0] HIT_ENTRY blocked {symbol}: {hg.get('reason')} "
                                f"zone={format_level_span(e_low, e_high)} px={format_px(current_price)}"
                            )
                            continue

                        if status in ("ACTIVE", "HIT_ENTRY") and tp1_v is not None:
                            hit_tp1 = (direction == "LONG" and current_price >= tp1_v) or (
                                direction == "SHORT" and current_price <= tp1_v
                            )
                            if hit_tp1:
                                signal_update(db_path, signal_id=signal_id, status="HIT_TP1", outcome="PARTIAL")
                                be_level = None
                                if e_high is not None:
                                    be_level = e_high * (1.001 if direction == "LONG" else 0.999)
                                if in_pos_row and _allow_notify(symbol, "HIT_TP1"):
                                    entry_px = e_high if e_high is not None else e_low
                                    if direction == "SHORT" and e_low is not None:
                                        entry_px = e_low
                                    lev_note = format_tp1_hit(
                                        symbol=symbol,
                                        direction=direction,
                                        entry=entry_px,
                                        tp1=tp1_v,
                                        tp2=tp2_v,
                                    )
                                    await send_proactive(
                                        EVENT_TRADE_UPDATE,
                                        lev_note,
                                        stream="general",
                                        intent="POSITION_MANAGE",
                                        confirmed_position=True,
                                        position_id=pos_tid,
                                        position_open=True,
                                        symbol=symbol,
                                        kind="TP1",
                                    )
                                continue

                        if (
                            status == "HIT_ENTRY"
                            and e_low is not None
                            and e_high is not None
                            and sl_v is not None
                            and e_low <= current_price <= e_high
                        ):
                            in_pos = has_explicit_position(db_path, symbol, direction)
                            ag = may_emit_telegram(
                                key=origin_key(
                                    symbol=symbol,
                                    direction=direction,
                                    zone_lo=e_low,
                                    zone_hi=e_high,
                                    origin="t0",
                                ),
                                intent="ADD_ON",
                                in_position=in_pos,
                                in_zone=True,
                            )
                            print(
                                f"[t0] ADD_ON blocked {symbol}: {ag.get('reason')} "
                                f"zone={format_level_span(e_low, e_high, symbol)} "
                                f"px={format_px(current_price, symbol)} pos={in_pos}"
                            )

                        if status == "HIT_TP1" and tp2_v is not None:
                            try:
                                c4 = fetch_candles(symbol, "4h", 3)
                            except Exception:
                                c4 = []
                            if isinstance(c4, list) and len(c4) >= 2:
                                try:
                                    prev_close = float((c4[-2] or {}).get("close") or 0.0)
                                    last_close = float((c4[-1] or {}).get("close") or 0.0)
                                except Exception:
                                    prev_close = 0.0
                                    last_close = 0.0
                                if prev_close > 0:
                                    change_pct = (last_close - prev_close) / prev_close * 100.0
                                    rev_long = direction == "LONG" and change_pct <= -0.5 and current_price < tp2_v
                                    rev_short = direction == "SHORT" and change_pct >= 0.5 and current_price > tp2_v
                                    if (rev_long or rev_short) and in_pos_row and _allow_notify(symbol, "REVERSAL_WARN"):
                                        rev_note = _lev_msg(
                                            symbol,
                                            f"4H свічка дала розворот {change_pct:+.2f}% після TP1",
                                            "розглянь фіксацію ще 50% поки в плюсі",
                                            f"{sl_v}",
                                        )
                                        await send_proactive(
                                            EVENT_TRADE_UPDATE,
                                            rev_note,
                                            stream="general",
                                            intent="POSITION_MANAGE",
                                            confirmed_position=True,
                                            position_id=pos_tid,
                                            position_open=True,
                                            symbol=symbol,
                                            kind="REVERSAL_WARN",
                                        )

                        # ФІКС 3: попередження про наближення до SL / TP1 (до фактичного спрацювання).
                        if status in ("ACTIVE", "HIT_ENTRY", "HIT_TP1"):
                            near_pct = 0.5
                            if sl_v is not None and sl_v > 0:
                                if direction == "LONG":
                                    near_sl = current_price > sl_v and (current_price - sl_v) / sl_v * 100.0 < near_pct
                                else:
                                    near_sl = current_price < sl_v and (sl_v - current_price) / sl_v * 100.0 < near_pct
                                # «Близько до стопу» лише для /position, не для office_signals.
                                if near_sl:
                                    print(
                                        f"[signals] {symbol} near SL {sl_v} @ {current_price} "
                                        "(office signal — мовчки до TRADE_CLOSED)"
                                    )
                            if tp1_v is not None and tp1_v > 0 and status in ("ACTIVE", "HIT_ENTRY"):
                                if direction == "LONG":
                                    near_tp1 = current_price < tp1_v and (tp1_v - current_price) / tp1_v * 100.0 < near_pct
                                else:
                                    near_tp1 = current_price > tp1_v and (current_price - tp1_v) / tp1_v * 100.0 < near_pct
                                if near_tp1 and in_pos_row and _allow_notify(symbol, "TP1_NEAR"):
                                    await send_proactive(
                                        EVENT_TRADE_UPDATE,
                                        format_manage_update(
                                            symbol=symbol,
                                            direction=direction,
                                            price=current_price,
                                            tp1=tp1_v,
                                            sl=sl_v,
                                        ),
                                        stream="general",
                                        intent="POSITION_MANAGE",
                                        confirmed_position=True,
                                        position_id=pos_tid,
                                        position_open=True,
                                        symbol=symbol,
                                        kind="TP1_NEAR",
                                    )

                        if status in ("ACTIVE", "HIT_ENTRY", "HIT_TP1") and sl_v is not None:
                            hit_sl = (direction == "LONG" and current_price <= sl_v) or (
                                direction == "SHORT" and current_price >= sl_v
                            )
                            pre_entry_cancel = status == "ACTIVE" and not in_pos_row
                            if hit_sl and pre_entry_cancel:
                                # до входу скасування — лише за закриттям годинної свічки за рівнем (як написано на картці)
                                from office_scenario_lifecycle import _ts as _lc_ts, closed_h1_beyond

                                try:
                                    _h1c = fetch_candles(symbol, "1h", 8)
                                except Exception:
                                    _h1c = None
                                hit_sl = bool(closed_h1_beyond(_h1c, side=direction, level=sl_v,
                                                               since_ts=_lc_ts(ts_created) or 0.0, now_ts=time.time()))
                            if hit_sl:
                                from office_confluence import format_cancel_card
                                from office_lev_authority import (
                                    had_confirmed_entry,
                                    recommend_close_text,
                                )

                                analysis_note = f"HIT_SL {symbol} @ {current_price} sl={sl_v}"
                                if pre_entry_cancel:  # до входу це скасування плану, а не збиткова угода
                                    analysis_note = f"CANCELLED H1-close beyond {sl_v} @ {current_price}"
                                signal_update(
                                    db_path,
                                    signal_id=signal_id,
                                    status="CANCELLED" if pre_entry_cancel else "HIT_SL",
                                    outcome="CANCELLED" if pre_entry_cancel else "LOSS",
                                    analysis_note=analysis_note,
                                )
                                pos_sl = None
                                try:
                                    pos_sl = float(pos_info.get("sl")) if pos_info.get("sl") is not None else None
                                except (TypeError, ValueError):
                                    pos_sl = None
                                hit_pos_sl = False
                                if in_pos_row and pos_sl is not None:
                                    hit_pos_sl = (direction == "LONG" and current_price <= pos_sl) or (
                                        direction == "SHORT" and current_price >= pos_sl
                                    )
                                entered = had_confirmed_entry(status) or bool(in_pos_row)
                                if _allow_notify(symbol, "HIT_SL"):
                                    if in_pos_row and hit_pos_sl and pos_tid:
                                        stop_note = recommend_close_text(
                                            symbol=symbol, price=current_price, sl=pos_sl
                                        )
                                        await send_proactive(
                                            EVENT_TRADE_CLOSED,
                                            stop_note,
                                            stream="general",
                                            intent="POSITION_MANAGE",
                                            confirmed_position=True,
                                            position_id=pos_tid,
                                            position_open=True,
                                            symbol=symbol,
                                            direction=direction,
                                            kind="SL",
                                        )
                                    elif in_pos_row and not hit_pos_sl:
                                        print(
                                            f"[signals] {symbol} scenario SL {sl_v} ≠ position SL {pos_sl} "
                                            "— сценарій скасовано, позицію не чіпаємо"
                                        )
                                        await send_proactive(
                                            EVENT_TRADE_UPDATE,
                                            format_cancel_card(
                                                symbol=symbol,
                                                direction=direction,
                                                reason="ціна за стопом сценарію до/без удару SL позиції",
                                            ),
                                            stream="general",
                                            intent="ANALYTICAL",
                                            symbol=symbol,
                                            direction=direction,
                                            kind="CANCEL_SCENARIO",
                                        )
                                    else:
                                        await send_proactive(
                                            EVENT_TRADE_UPDATE,
                                            format_cancel_card(
                                                symbol=symbol,
                                                direction=direction,
                                                reason=_lc.cancel_reason_h1(direction, sl_v, symbol),
                                            ),
                                            stream="general",
                                            intent="ANALYTICAL",
                                            symbol=symbol,
                                            direction=direction,
                                            kind="CANCEL_BEFORE_ENTRY",
                                            canonical_id=canonical_sid or signal_id,
                                            scenario_event="CANCELLED",
                                        )
                                        print(
                                            f"[signals] {symbol} CANCELLED_BEFORE_ENTRY "
                                            f"@ {current_price} sl={sl_v} (не /position)"
                                        )
                                if in_pos_row and hit_pos_sl and pos_tid:
                                    try:
                                        journal_close_trade(
                                            db_path,
                                            trade_id=pos_tid,
                                            outcome="LOSS",
                                            exit_price=float(current_price),
                                            pnl_pct=0.0,
                                            exit_reason="SL",
                                            context_patch={"result": "SL"},
                                        )
                                    except Exception as exc_js:
                                        print(f"[steer] journal SL failed: {exc_js}")
                                if not entered:
                                    print(
                                        f"[steer] no reentry after CANCELLED_BEFORE_ENTRY {symbol} "
                                        f"{signal_id} — потрібен новий цикл Лева"
                                    )
                                    continue
                                try:
                                    m15_sl = fetch_candles(symbol, "15m", 16)
                                    h1_sl = fetch_candles(symbol, "1h", 12)
                                except Exception:
                                    m15_sl, h1_sl = [], []
                                last_c = m15_sl[-1] if isinstance(m15_sl, list) and m15_sl else None
                                reclaim = e_high if direction == "SHORT" else e_low
                                if reclaim is None:
                                    reclaim = e_low if e_low is not None else e_high
                                day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                                ck = signal_case_key(
                                    symbol=symbol,
                                    direction=direction,
                                    timeframe="H1",
                                    day=day_key,
                                )
                                re_plan = plan_sweep_reentry(
                                    case_key=ck,
                                    already_reentered=ck in _reentry_done,
                                    direction=direction,
                                    sl=sl_v,
                                    reclaim_level=reclaim,
                                    last_candle=last_c,
                                    candles_h1=h1_sl if isinstance(h1_sl, list) else None,
                                )
                                if re_plan.get("allow"):
                                    _reentry_done.add(ck)
                                    planned = plan_stop_behind_manipulation(
                                        entry=current_price,
                                        tp1=tp1_v,
                                        direction=direction,
                                        candles_m15=m15_sl if isinstance(m15_sl, list) else None,
                                        candles_h1=h1_sl if isinstance(h1_sl, list) else None,
                                        current_sl=sl_v,
                                    )
                                    new_sl = planned.get("sl") if planned.get("send") else None
                                    if new_sl is not None and planned.get("send"):
                                        sweep_ext = re_plan.get("wick_extreme")
                                        note = (
                                            f"Стоп вибило свіпом до {sweep_ext} — "
                                            f"ціна повернулась {'нижче' if direction == 'SHORT' else 'вище'} {reclaim}"
                                        )
                                        card = format_signal_steer_card(
                                            symbol=symbol,
                                            direction=direction,
                                            timeframe="H1",
                                            entry=current_price,
                                            sl=new_sl,
                                            tp1=tp1_v,
                                            tp2=tp2_v,
                                            trigger=format_entry_trigger(
                                                direction=direction,
                                                tf="M15",
                                                level=reclaim,
                                                entry=current_price,
                                                already_done=True,
                                            ),
                                            reentry=True,
                                            sweep_note=note,
                                        )
                                        new_id = f"reentry-{symbol}-{int(time.time())}"
                                        signal_upsert(
                                            db_path,
                                            signal_id=new_id,
                                            symbol=symbol,
                                            direction=direction,
                                            entry_low=float(current_price),
                                            entry_high=float(current_price),
                                            sl=float(new_sl),
                                            tp1=tp1_v,
                                            tp2=tp2_v,
                                            rr=planned.get("rr"),
                                            status="WATCHING",
                                            analysis_note=f"origin=desk tf=H1 new-after-stop {ck}",
                                        )
                                        print(
                                            f"[steer] новий WATCHING {new_id} після SL /position "
                                            f"{symbol} — без автоматичного SIGNAL_ENTRY"
                                        )
                                    else:
                                        print(f"[steer] reentry skip {symbol}: {planned.get('reason')}")
                                else:
                                    print(f"[steer] no reentry {symbol}: {re_plan.get('reason')}")
                                continue

                        if status in ("ACTIVE", "HIT_ENTRY", "HIT_TP1") and tp2_v is not None:
                            hit_tp2 = (direction == "LONG" and current_price >= tp2_v) or (
                                direction == "SHORT" and current_price <= tp2_v
                            )
                            if hit_tp2:
                                signal_update(db_path, signal_id=signal_id, status="HIT_TP2", outcome="WIN")
                                status = "HIT_TP2"
                                if _allow_notify(symbol, "HIT_TP2"):
                                    trail_lv = e_high if direction == "LONG" else e_low
                                    if direction == "LONG" and e_low is not None:
                                        trail_lv = e_low
                                    if in_pos_row and pos_tid:
                                        await send_proactive(
                                            EVENT_TRADE_UPDATE,
                                            (
                                                f"✅ TP2 · {symbol} {direction}\n"
                                                "Закрий ще частину\n"
                                                f"SL на {tp1_v if tp1_v is not None else trail_lv}"
                                            ),
                                            stream="general",
                                            intent="POSITION_MANAGE",
                                            confirmed_position=True,
                                            position_id=pos_tid,
                                            position_open=True,
                                            symbol=symbol,
                                            kind="TP2",
                                        )
                                    else:
                                        print(
                                            f"[t0] HIT_TP2 scenario (не /position) {symbol} "
                                            "без інструкції змінити ордер"
                                        )
                                try:
                                    ent = float(e_low or e_high or current_price)
                                    sl_b = float(sl_v or ent)
                                    t1_b = float(tp1_v or ent)
                                    book = _ensure_steer_book(
                                        signal_id=signal_id,
                                        symbol=symbol,
                                        direction=direction,
                                        entry=ent,
                                        sl=sl_b,
                                        tp1=t1_b,
                                        tp2=tp2_v,
                                        status="HIT_TP2",
                                    )
                                    book.state = "TP2"
                                    book.last_event = "TP2"
                                    book.trail_sl = float(tp1_v) if tp1_v is not None else book.entry
                                    _journal_signal_excursions(
                                        db_path, signal_id, book, extra={"result": "TP2"}
                                    )
                                except Exception as exc_b:
                                    print(f"[steer] tp2 book failed: {exc_b}")

                        if status == "HIT_TP2" and sl_v is not None and tp1_v is not None:
                            try:
                                m15_now = fetch_candles(symbol, "15m", 24)
                            except Exception:
                                m15_now = []
                            if not isinstance(m15_now, list):
                                m15_now = []
                            try:
                                d1_now = fetch_candles(symbol, "1d", 5)
                            except Exception:
                                d1_now = []
                            last_m = m15_now[-1] if m15_now else {}
                            hi = last_m.get("high") if isinstance(last_m, dict) else None
                            lo = last_m.get("low") if isinstance(last_m, dict) else None
                            try:
                                h1_rsi_bars = fetch_candles(symbol, "1h", 40)
                            except Exception:
                                h1_rsi_bars = []
                            try:
                                h4_rsi_bars = fetch_candles(symbol, "4h", 40)
                            except Exception:
                                h4_rsi_bars = []
                            rsi1 = rsi_from_candles(h1_rsi_bars if isinstance(h1_rsi_bars, list) else [])
                            rsi4 = rsi_from_candles(h4_rsi_bars if isinstance(h4_rsi_bars, list) else [])
                            exh = exhaustion_candle(last_m, side=direction)
                            try:
                                ent = float(e_low or e_high or current_price)
                                book = _ensure_steer_book(
                                    signal_id=signal_id,
                                    symbol=symbol,
                                    direction=direction,
                                    entry=ent,
                                    sl=float(sl_v),
                                    tp1=float(tp1_v),
                                    tp2=tp2_v,
                                    status="HIT_TP2",
                                )
                                if book.tp3 is None:
                                    book.tp3 = tp3_from_liquidity(
                                        direction=direction,
                                        daily_candles=d1_now if isinstance(d1_now, list) else None,
                                    )
                                ev = next_manage_event(
                                    book,
                                    price=current_price,
                                    candles_m15=m15_now,
                                    high=hi,
                                    low=lo,
                                    rsi_h1=rsi1,
                                    rsi_h4=rsi4,
                                    exhaustion=exh,
                                    confirmed_position=in_pos_row,
                                )
                                peak = None
                                if rsi1 is not None or rsi4 is not None:
                                    vals = [x for x in (rsi1, rsi4) if x is not None]
                                    peak = max(vals) if vals else None
                                _journal_signal_excursions(
                                    db_path,
                                    signal_id,
                                    book,
                                    extra={
                                        "rsi_h1": rsi1,
                                        "rsi_h4": rsi4,
                                        "rsi_peak": peak,
                                    },
                                )
                                if ev and _allow_notify(symbol, str(ev.get("kind") or ev.get("event"))):
                                    await send_proactive(
                                        str(ev.get("event") or EVENT_TRADE_UPDATE),
                                        fmt_agent_line("lev", str(ev.get("message") or "")),
                                        stream=TRADE_UPDATE_STREAM,
                                        kind=str(ev.get("kind") or ""),
                                        symbol=symbol,
                                        sl=ev.get("trail_sl"),
                                        intent="POSITION_MANAGE",
                                        confirmed_position=True,
                                        position_id=pos_tid,
                                        position_open=True,
                                    )
                                    if str(ev.get("event")) == EVENT_TRADE_CLOSED:
                                        signal_update(
                                            db_path,
                                            signal_id=signal_id,
                                            status="CLOSED",
                                            outcome="WIN" if str(ev.get("kind")) != "SL" else "LOSS",
                                            analysis_note=str(ev.get("kind") or ""),
                                        )
                                        try:
                                            if pos_tid:
                                                journal_close_trade(
                                                    db_path,
                                                    trade_id=pos_tid,
                                                outcome="LOSS" if str(ev.get("kind")) == "SL" else "WIN",
                                                exit_price=float(current_price),
                                                pnl_pct=float(book.mfe if str(ev.get("kind")) != "SL" else -book.mae),
                                                exit_reason=str(ev.get("kind") or "TRADE_CLOSED"),
                                                context_patch={
                                                    "result": str(ev.get("kind")),
                                                    "mfe_pct": book.mfe,
                                                    "mae_pct": book.mae,
                                                },
                                            )
                                        except Exception as exc_c:
                                            print(f"[steer] journal close failed: {exc_c}")
                            except Exception as exc_m:
                                print(f"[steer] manage tick failed: {exc_m}")

                    except Exception as exc_row:
                        print(f"[signals] row monitor failed: {exc_row}")
                from office_desk_card import (
                    format_near_stop,
                    list_confirmed_open_positions,
                    may_send_near_stop,
                )

                for pos in list_confirmed_open_positions(db_path):
                    psym = str(pos.get("symbol") or "")
                    psl = pos.get("sl")
                    if not psym or psl is None:
                        continue
                    try:
                        liq_p = fetch_liquidations_proxy(psym)
                        px = float((liq_p or {}).get("current_price") or 0.0) if isinstance(liq_p, dict) else 0.0
                    except Exception:
                        px = 0.0
                    if px <= 0:
                        continue
                    try:
                        slp = float(psl)
                    except (TypeError, ValueError):
                        continue
                    if slp <= 0:
                        continue
                    pdir = str(pos.get("direction") or "LONG").upper()
                    near_pct = 0.5
                    if pdir == "LONG":
                        near_ok = px > slp and (px - slp) / slp * 100.0 < near_pct
                    else:
                        near_ok = px < slp and (slp - px) / slp * 100.0 < near_pct
                    if near_ok and may_send_near_stop(
                        trade_id=str(pos.get("trade_id") or ""),
                        confirmed_position=True,
                    ):
                        await send_proactive(
                            EVENT_TRADE_UPDATE,
                            format_near_stop(symbol=psym, price=px, sl=slp),
                            stream="general",
                            intent="POSITION_MANAGE",
                            confirmed_position=True,
                            position_id=str(pos.get("trade_id") or ""),
                            position_open=True,
                            symbol=psym,
                            kind="NEAR_STOP",
                        )
            except Exception as exc:
                print(f"[signals] monitor failed: {exc}")
            await asyncio.sleep(120 if fast_poll else 900)

    asyncio.create_task(monitor_active_signals())

    async def monitor_trade_radar() -> None:
        """T6: радар BTC. T8: боковик + всесвіт альтів/золота без копіювання BTC."""
        from office_market_data import fetch_atr_context, fetch_candles, fetch_liquidations_proxy
        from office_confluence import hydrate_live_from_db
        from office_alert_gate import hydrate_alert_gate_from_db

        try:
            n_h = hydrate_live_from_db(db_path)
            n_g = hydrate_alert_gate_from_db(db_path)
            print(f"[confluence] hydrated live keys={n_h} alert_gate={n_g}")
        except Exception as exc_h:
            print(f"[confluence] hydrate failed: {type(exc_h).__name__}: {exc_h}")

        _range_fp: Dict[str, str] = {}
        _level_fp: Dict[str, str] = {}
        while True:
            sent_this_cycle: Set[str] = set()

            async def _desk_send(
                sym: str,
                tag: str,
                *,
                direction: str,
                timeframe: str,
                entry: Any,
                sl: Any,
                tp1: Any,
                tp2: Any = None,
                tp3: Any = None,
                add_px: Any = None,
                atr_h1: Any = None,
                score: Any = None,
                min_score: Any = 10,
                setup_type: str = "",
                m15_close: Any = None,
                candle: Any = None,
                cancel_level: Any = None,
                confluence: Any = None,
                lev_note: str = "",
            ) -> bool:
                from office_desk_card import prepare_desk_send
                from office_trade_steer import atr_from_candles

                now_ts = time.time()
                _cd = _lc.cooldown_active(db_path, sym, direction, now_ts=now_ts)
                if _cd:
                    print(f"[{tag}] {sym} {direction} hold: щойно скасовано {_cd} — нову картку в ту саму сторону не шлю (пауза {_lc.cooldown_sec()//60} хв)")
                    return False
                last_feed = float(_last_notified.get("__FEED_COOLDOWN__", 0.0) or 0.0)
                gate = allow_proactive_telegram(
                    kind=KIND_SIGNAL,
                    symbol=sym,
                    sent_symbols=sent_this_cycle,
                    last_feed_ts=last_feed,
                    now_ts=now_ts,
                )
                if not gate.get("send"):
                    print(f"[{tag}] {sym} hold: {gate.get('reason')}")
                    return False
                atr_v = atr_h1
                h1_bars = None
                try:
                    h1_bars = fetch_candles(sym, "1h", 48)
                    if atr_v is None:
                        atr_v = atr_from_candles(h1_bars)
                except Exception:
                    h1_bars = h1_bars
                m15_bars = d1_bars = h4_bars = m5_bars = w_bars = None
                try:
                    m15_bars = fetch_candles(sym, "15m", 96)
                except Exception:
                    m15_bars = None
                try:
                    h4_bars = fetch_candles(sym, "4h", 48)
                except Exception:
                    h4_bars = None
                try:
                    d1_bars = fetch_candles(sym, "1d", 30)
                except Exception:
                    d1_bars = None
                try:
                    w_bars = fetch_candles(sym, "1w", 12)
                except Exception:
                    w_bars = None
                wait_tf = "M15" if str(timeframe or "").upper() in ("H1", "H4", "D1") else "M5"
                try:
                    m5_bars = fetch_candles(sym, "5m" if wait_tf == "M5" else "15m", 48)
                except Exception:
                    m5_bars = m15_bars
                last_px = entry
                try:
                    src = m15_bars or h1_bars or []
                    if isinstance(src, list) and src:
                        last_px = float((src[-1] or {}).get("close") or entry or 0) or entry
                except Exception:
                    last_px = entry
                from office_lev_verdict import ACTION_SKIP, ACTION_WAIT, lev_cycle

                cycle = lev_cycle(
                    symbol=sym,
                    price=last_px,
                    timeframe=timeframe,
                    candles_m5=m5_bars,
                    candles_m15=m15_bars,
                    candles_h1=h1_bars,
                    candles_h4=h4_bars,
                    candles_d1=d1_bars,
                    candles_w=w_bars,
                    candles_ltf=m5_bars,
                    atr_h1=atr_v,
                    now_ts=now_ts,
                    market_context={"data_status": "DATA_UNAVAILABLE"},
                )
                cycle = _lev_risk_review(
                    cycle, sym, candles_ltf=m5_bars, market_context={"data_status": "DATA_UNAVAILABLE"},
                )
                _lev_record_thesis(cycle, {"H4": h4_bars, "H1": h1_bars, "M15": m15_bars, "LTF": m5_bars})
                if str(cycle.get("action") or "") in (ACTION_SKIP, ACTION_WAIT):
                    print(f"[{tag}] {sym} hold lev_cycle: {cycle.get('action')} {cycle.get('reason')}")
                    return False
                if lev_note:
                    lev_note = f"{lev_note} · {cycle.get('reason') or ''}".strip(" ·")
                else:
                    lev_note = str(cycle.get("reason") or cycle.get("note") or "")
                prep = prepare_desk_send(
                    db_path=db_path,
                    symbol=sym,
                    direction=direction,
                    timeframe=timeframe,
                    entry=entry,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                    tp3=tp3,
                    add_px=add_px,
                    atr_h1=atr_v,
                    score=score,
                    min_score=min_score,
                    setup_type=setup_type or tag,
                    m15_close=m15_close,
                    candle=candle,
                    candles_m15=m15_bars,
                    candles_h1=h1_bars,
                    candles_h4=h4_bars,
                    candles_d1=d1_bars,
                    candles_w=w_bars,
                    candles_ltf=m5_bars,
                    price=last_px,
                    now_ts=now_ts,
                    confluence=confluence,
                    lev_note=lev_note,
                )
                if not prep.get("send"):
                    conf_hold = prep.get("confluence") if isinstance(prep.get("confluence"), dict) else {}
                    if str(prep.get("reason") or "") == "менше 2 збігів":
                        from office_confluence import note_db_only

                        key_db = str(conf_hold.get("setup_key") or "")
                        if note_db_only(key_db):
                            try:
                                log_event(
                                    db_path,
                                    "CONFLUENCE_DB",
                                    {
                                        "symbol": sym,
                                        "direction": direction,
                                        "tags": conf_hold.get("tags") or [],
                                        "confirms": conf_hold.get("confirms") or [],
                                        "n": conf_hold.get("n"),
                                        "grade": conf_hold.get("grade") or "",
                                    },
                                )
                            except Exception:
                                pass
                    print(f"[{tag}] {sym} hold: {prep.get('reason')}")
                    return False
                # Сценарій без підтвердження в Telegram НЕ шлемо (це WATCHING: «входу немає»). Він зберігається в БД, видно в Mini App,
                # а worker стежить за умовами; у Telegram піде лише повний план після підтвердження (вхід, стоп, цілі) і події вже надісланого.
                print(f"[{tag}] {sym} {direction} сценарій записано без Telegram (WATCHING): {str(prep.get('text') or '').splitlines()[:1]}")
                sid = str(prep.get("scenario_id") or prep.get("setup_key") or f"desk-{tag}-{sym}-{int(now_ts)}")
                e_px = prep.get("entry")
                try:
                    e_px = float(e_px) if e_px is not None else (float(entry) if entry is not None else None)
                except Exception:
                    e_px = None
                sl_px = prep.get("sl")
                conf = prep.get("confluence") if isinstance(prep.get("confluence"), dict) else {}
                extra_j = {
                    "confluence_tags": conf.get("tags") or [],
                    "confirm_tags": conf.get("confirms") or [],
                    "grade": conf.get("grade") or "",
                    "setup_key": prep.get("setup_key") or "",
                    "zone_lo": conf.get("zone_lo"),
                    "zone_hi": conf.get("zone_hi"),
                }
                try:
                    from office_scenario_memory import stamp_scenario_note

                    scenario_note = stamp_scenario_note(
                        (
                            f"{setup_type or tag}"
                            + (f" cancel={cancel_level}" if cancel_level is not None else "")
                            + (f" ckey={conf.get('zone_key')}" if conf.get("zone_key") else "")
                        ),
                        origin="desk",
                        timeframe=timeframe,
                        scenario_id=sid,
                        basis=str(prep.get("market_basis") or conf.get("market_basis") or ""),
                    )
                    signal_upsert(
                        db_path,
                        signal_id=sid,
                        symbol=sym,
                        direction=str(direction or "LONG"),
                        entry_low=conf.get("zone_lo") or e_px,
                        entry_high=conf.get("zone_hi") or e_px,
                        sl=sl_px,
                        tp1=tp1,
                        tp2=tp2,
                        rr=None,
                        status="WATCHING",
                        analysis_note=scenario_note[:2000],
                    )
                    apply_setup_event(sid, "FOUND")
                    from office_confluence import mark_live as _mark_live

                    _mark_live(sid, {
                        "symbol": sym, "direction": str(direction or "LONG"), "timeframe": str(timeframe or "H1"), "origin": "desk",
                        "signal_id": sid, "scenario_id": sid, "sl": sl_px, "tp1": tp1, "tp2": tp2,
                        "zone_lo": conf.get("zone_lo") or e_px, "zone_hi": conf.get("zone_hi") or e_px,
                        "entry_low": conf.get("zone_lo") or e_px, "entry_high": conf.get("zone_hi") or e_px,
                        "basis": str(prep.get("market_basis") or conf.get("market_basis") or ""), "status": "WATCHING", "ts": now_ts,
                    })
                except Exception as exc_jf:
                    print(f"[steer] journal feed {sym} failed: {exc_jf}")
                return True

            async def _try_signal_feed(sym: str, text: str, tag: str, **extra: Any) -> bool:
                parsed = parse_signal_levels_from_text(text) or {}
                return await _desk_send(
                    sym,
                    tag,
                    direction=str(extra.get("direction") or parsed.get("direction") or "LONG"),
                    timeframe=str(extra.get("timeframe") or parsed.get("timeframe") or "H1"),
                    entry=extra.get("entry") or parsed.get("entry") or parsed.get("entry_low"),
                    sl=extra.get("sl") or parsed.get("sl"),
                    tp1=extra.get("tp1") or parsed.get("tp1") or parsed.get("tp"),
                    tp2=extra.get("tp2") or parsed.get("tp2"),
                    tp3=extra.get("tp3"),
                    add_px=extra.get("add_px"),
                    atr_h1=extra.get("atr_h1"),
                    score=extra.get("score"),
                    min_score=extra.get("min_score", 10),
                    setup_type=str(extra.get("setup_type") or tag),
                    m15_close=extra.get("m15_close"),
                    candle=extra.get("candle"),
                    cancel_level=extra.get("cancel_level"),
                )

            try:
                for symbol in RADAR_SYMBOLS:
                    try:
                        ms = market_state_get(db_path, symbol) or {}
                        if scanner_signal_blocked(ms.get("bot_action")):
                            print(f"[radar] skip BLOCKED {symbol}")
                            continue
                        daily = fetch_candles(symbol, "1d", 30)
                        h1 = fetch_candles(symbol, "1h", 10)
                        m15 = fetch_candles(symbol, "15m", 8)
                        m5 = fetch_candles(symbol, "5m", 12)
                        m1 = fetch_candles(symbol, "1m", 20)
                        if not isinstance(daily, list) or not isinstance(h1, list) or not daily or not h1:
                            print(f"[radar] no candles {symbol}")
                            continue
                        price = 0.0
                        try:
                            liq = fetch_liquidations_proxy(symbol)
                            if isinstance(liq, dict):
                                price = float(liq.get("current_price") or 0.0)
                        except Exception:
                            price = 0.0
                        if price <= 0:
                            try:
                                price = float((h1[-1] or {}).get("close") or 0.0)
                            except Exception:
                                price = 0.0
                        day_used = None
                        try:
                            atr = fetch_atr_context(symbol) or {}
                            if atr.get("day_used_pct") is not None:
                                day_used = float(atr.get("day_used_pct"))
                        except Exception:
                            day_used = None
                        res = evaluate_radar(
                            symbol=symbol,
                            price=price,
                            daily_candles=daily,
                            sweep_candles=h1,
                            m15_candles=m15 if isinstance(m15, list) else [],
                            day_used_pct=day_used,
                            bot_action=ms.get("bot_action"),
                        )
                        sres = evaluate_session_radar(
                            symbol=symbol,
                            price=price,
                            level_price=res.level_price,
                            sweep_candles=h1,
                            m15_candles=m15 if isinstance(m15, list) else [],
                            m5_candles=m5 if isinstance(m5, list) else [],
                            m1_candles=m1 if isinstance(m1, list) else [],
                            day_used_pct=day_used,
                        )
                        if res.status == "NONE" and sres.status != "NONE":
                            res.status = sres.status
                            res.direction = sres.direction or res.direction
                            res.level_price = sres.level_price or res.level_price
                            res.reason = sres.reason
                            if sres.card:
                                res.card = sres.card
                        if res.status == "NONE":
                            continue
                        if res.status == "WATCHING" and res.level_price is not None:
                            gate = apply_skip_watching_gate(
                                db_path,
                                symbol=symbol,
                                direction=res.direction or "LONG",
                                entry_low=float(res.level_price),
                                entry_high=float(res.level_price),
                                timeframe="1h",
                                now_ts=time.time(),
                                current_price=price,
                            )
                            if gate.get("create"):
                                signal_upsert(
                                    db_path,
                                    signal_id=f"radar-watch-{symbol}-{int(time.time())}",
                                    symbol=symbol,
                                    direction=res.direction or "LONG",
                                    entry_low=float(res.level_price),
                                    entry_high=float(res.level_price),
                                    sl=None,
                                    tp1=None,
                                    tp2=None,
                                    rr=None,
                                    status="WATCHING",
                                            analysis_note=(
                                        f"{res.reason or 'T6 radar watching'}\n"
                                        f"{format_radar_liq_summary(BTC_FORCE_ORDER_BOOK)}"
                                    )[:2000],
                                )
                                print(f"[radar] WATCHING {symbol} {res.level_price}")
                        if res.status == "SIGNAL":
                            nkey = f"{symbol}::RADAR_SIGNAL"
                            now_ts = time.time()
                            last_ts = float(_last_notified.get(nkey, 0.0) or 0.0)
                            if (now_ts - last_ts) < 1800:
                                print(f"[radar] SIGNAL cooldown {symbol}")
                            else:
                                card = res.card or {}
                                from office_trade_steer import atr_from_candles

                                atr_h = atr_from_candles(h1)
                                m15_cl = None
                                try:
                                    if isinstance(m15, list) and m15:
                                        m15_cl = float((m15[-1] or {}).get("close") or 0.0) or None
                                except Exception:
                                    m15_cl = None
                                sent = await _desk_send(
                                    symbol,
                                    "radar",
                                    direction=str(res.direction or "LONG"),
                                    timeframe="H1",
                                    entry=card.get("entry_low") or card.get("entry") or price,
                                    sl=card.get("sl"),
                                    tp1=card.get("tp") or card.get("tp1"),
                                    tp2=card.get("tp2"),
                                    atr_h1=atr_h,
                                    score=card.get("score"),
                                    min_score=card.get("min_score") or 8,
                                    setup_type=str(card.get("setup_type") or "РАДАР"),
                                    m15_close=m15_cl,
                                    candle=(m15[-1] if isinstance(m15, list) and m15 else None),
                                    cancel_level=card.get("cancel") or res.level_price,
                                )
                                if sent:
                                    _last_notified[nkey] = now_ts
                                    print(f"[radar] SIGNAL card {symbol} (no position)")
                    except Exception as exc_sym:
                        print(f"[radar] {symbol}: {type(exc_sym).__name__}: {exc_sym}")
                tickers_24: Any = None
                try:
                    timeout_sc = aiohttp.ClientTimeout(total=12)
                    async with aiohttp.ClientSession(timeout=timeout_sc) as s_sc:
                        async with s_sc.get("https://fapi.binance.com/fapi/v1/ticker/24hr") as r_sc:
                            tickers_24 = await r_sc.json()
                except Exception as exc_sc:
                    print(f"[scout] ticker 24hr unavailable: {type(exc_sc).__name__}: {exc_sc}")
                    tickers_24 = None
                screen = screen_futures_market(tickers_24 if isinstance(tickers_24, list) else None)
                extra_req = [
                    x.strip().upper()
                    for x in str(os.getenv("OFFICE_SCOUT_EXTRA_SYMBOLS") or "").split(",")
                    if x.strip()
                ]
                watching_now: List[str] = []
                try:
                    for _aw in signal_get_active(db_path) or []:
                        if isinstance(_aw, dict) and _aw.get("symbol"):
                            watching_now.append(str(_aw.get("symbol")))
                except Exception:
                    watching_now = []
                import office_scan_funnel as _fun

                _fun_now = time.time()
                _fun_rows: Dict[str, Dict[str, Any]] = {}
                if not getattr(_fun.STATE, "hydrated", False):
                    try:
                        _fun.hydrate(db_path)
                    except Exception as exc_fh:  # noqa: BLE001
                        print(f"[funnel] hydrate: {type(exc_fh).__name__}")
                    _fun.STATE.hydrated = True
                if screen.data_status == "DATA_OK":
                    _fun_rows = {str(r.get("symbol")): r for r in screen.rows if isinstance(r, dict)}
                    for _r in screen.rows:   # дуже сильний рух — одразу PULLBACK WATCH, глибокий слот не витрачаємо (не наздоганяємо)
                        if abs(float(_r.get("change_pct") or 0.0)) >= _fun.EXTENDED_PCT:
                            _fun.register_pullback(_r["symbol"], _r, reason=f"сильний рух {float(_r.get('change_pct') or 0):+.1f}% за 24 год — не наздоганяємо, чекаємо відкат".replace(".", ","), now=_fun_now)
                    _fun.update_pullbacks(screen.rows, _fun_now)
                    _short = _fun.select_deep(screen.rows, screen.gainers, screen.losers, user_symbols=extra_req,
                                              active_watching=watching_now, now=_fun_now)
                else:
                    _short = shortlist_with_reasons(screen, extra_user_symbols=extra_req, active_watching=watching_now)
                deep_syms = [x["symbol"] for x in _short]
                _why = {x["symbol"]: x["reason"] for x in _short}
                print("[scout] shortlist: " + "; ".join(f"{x['symbol']} ({x['reason']})" for x in _short[:40]))
                try:
                    print("[funnel] " + json.dumps({**_fun.counts_report(_short), **_fun.coverage(len(_fun_rows))}, ensure_ascii=False))
                except Exception:  # noqa: BLE001
                    pass
                btc_ctx = btc_context_only(screen)
                print(
                    f"[scout] screened={screen.screened} status={screen.data_status} "
                    f"deep={len(deep_syms)} gold={((screen.gold or {}).get('source'))}"
                )
                for rsym in deep_syms:
                    try:
                        rd1 = fetch_candles(rsym, "1d", 30)
                        rh4 = fetch_candles(rsym, "4h", 30)
                        rh1 = fetch_candles(rsym, "1h", 30)
                        rm15 = fetch_candles(rsym, "15m", 96)
                        rm5 = fetch_candles(rsym, "5m", 20)
                        if not isinstance(rh1, list) or len(rh1) < 8:
                            continue
                        rprice = 0.0
                        try:
                            rprice = float((rh1[-1] or {}).get("close") or 0.0)
                        except Exception:
                            rprice = 0.0
                        rsi1 = rsi_from_candles(rh1 if isinstance(rh1, list) else [])
                        rsi4 = rsi_from_candles(rh4 if isinstance(rh4, list) else [])
                        try:
                            record_scan_facts(
                                db_path,
                                rsym,
                                rsi_h1=rsi1,
                                rsi_h4=rsi4,
                                decision="WATCH",
                                data_quality="OK" if rsi1 is not None else "UNAVAILABLE",
                                scout_reason=_why.get(rsym),
                            )
                        except Exception as exc_ms:
                            print(f"[scout] market_state {rsym}: {type(exc_ms).__name__}")
                        r_used = None
                        try:
                            r_atr = fetch_atr_context(rsym) or {}
                            if r_atr.get("day_used_pct") is not None:
                                r_used = float(r_atr.get("day_used_pct"))
                        except Exception:
                            r_used = None
                        try:
                            from office_trade_steer import atr_from_candles as _atr_h1

                            m15_cl = None
                            try:
                                if isinstance(rm15, list) and rm15:
                                    m15_cl = float((rm15[-1] or {}).get("close") or 0.0) or None
                            except Exception:
                                m15_cl = None
                            from office_scenario_memory import btc_context_usable

                            btc_ctx = btc_context_only(screen)
                            mctx = (
                                btc_ctx
                                if btc_context_usable(btc_ctx)
                                else {
                                    "data_status": "DATA_UNAVAILABLE",
                                    "note": "BTC-контекст не підтверджений даними — не вигадую",
                                }
                            )
                            cycle = lev_cycle(
                                symbol=rsym,
                                price=rprice,
                                timeframe="H1",
                                candles_m5=rm5 if isinstance(rm5, list) else None,
                                candles_m15=rm15 if isinstance(rm15, list) else None,
                                candles_h1=rh1,
                                candles_h4=rh4 if isinstance(rh4, list) else None,
                                candles_d1=rd1 if isinstance(rd1, list) else None,
                                candles_ltf=rm5 if isinstance(rm5, list) else rm15,
                                atr_h1=_atr_h1(rh1),
                                day_used_pct=r_used,
                                market_context=mctx,
                            )
                            cycle = _lev_risk_review(
                                cycle, rsym,
                                candles_ltf=rm5 if isinstance(rm5, list) else rm15,
                                market_context=mctx,
                            )
                            _lev_record_thesis(cycle, {"H1": rh1, "M15": rm15, "M5": rm5})
                            _fun.mark_deep(rsym, time.time())
                            _fun.mark_checked(rsym, time.time())
                            _frow = _fun_rows.get(rsym) or {}
                            _fent = _fun.STATE.pullbacks.get(rsym)
                            _imp = (_fent or {}).get("impulse") or _fun.impulse_of(_frow)
                            _gate_hold = False
                            if _imp and str(cycle.get("direction") or "") in ("LONG", "SHORT") and str(cycle.get("action") or "") in ("SEND", "WAIT", "WATCHING"):
                                _g_ok, _g_why = _fun.direction_gate(str(cycle.get("direction")), _imp, reversal_ok=_fun.reversal_confirmed(rh1, _imp))
                                if not _g_ok:
                                    _gate_hold = True
                                    cycle = {**cycle, "send": False, "action": "WATCHING", "reason": _g_why}
                            _t0 = ((cycle.get("draft") or {}).get("atr") or {})
                            if str(cycle.get("action") or "") == "SKIP" and (_t0.get("t0_entry_blocked") or _t0.get("gerchik_entry_blocked")) and _fun.impulse_of(_frow):
                                _fun.register_pullback(rsym, _frow, reason="T0/ATR заблокував вхід після сильного руху — чекаємо відкат", now=time.time(), t0_blocked=True)
                            print(
                                f"[lev] {rsym} {cycle.get('action')} {cycle.get('direction')} "
                                f"{cycle.get('reason')}"
                            )
                            if cycle.get("send"):
                                if await _desk_send(
                                    rsym,
                                    "lev",
                                    direction=str(cycle.get("direction") or ""),
                                    timeframe="H1",
                                    entry=cycle.get("entry"),
                                    sl=cycle.get("sl"),
                                    tp1=cycle.get("tp1"),
                                    tp2=cycle.get("tp2"),
                                    atr_h1=_atr_h1(rh1),
                                    score=12,
                                    min_score=10,
                                    setup_type="ЛЕВ",
                                    m15_close=m15_cl,
                                    candle=(rm15[-1] if isinstance(rm15, list) and rm15 else None),
                                    cancel_level=cycle.get("sl"),
                                    confluence=cycle.get("confluence"),
                                    lev_note=str(cycle.get("lev_note") or ""),
                                ):
                                    print(f"[lev] {rsym} SEND {cycle.get('direction')}")
                            elif str(cycle.get("action") or "") in ("WAIT", "WATCHING") and not _gate_hold:
                                zlo = (cycle.get("confluence") or {}).get("zone_lo")
                                zhi = (cycle.get("confluence") or {}).get("zone_hi")
                                if zlo is not None and zhi is not None:
                                    gate_w = apply_skip_watching_gate(
                                        db_path,
                                        symbol=rsym,
                                        direction=str(cycle.get("direction") or "LONG"),
                                        entry_low=float(zlo),
                                        entry_high=float(zhi),
                                        timeframe="1h",
                                        now_ts=time.time(),
                                        current_price=rprice,
                                    )
                                    if gate_w.get("create"):
                                        signal_upsert(
                                            db_path,
                                            signal_id=f"lev-watch-{rsym}-{int(time.time())}",
                                            symbol=rsym,
                                            direction=str(cycle.get("direction") or "LONG"),
                                            entry_low=float(zlo),
                                            entry_high=float(zhi),
                                            sl=cycle.get("sl"),
                                            tp1=cycle.get("tp1"),
                                            tp2=cycle.get("tp2"),
                                            rr=None,
                                            status="WATCHING",
                                            analysis_note=(
                                                f"{cycle.get('action')} {cycle.get('reason') or ''} "
                                                f"{cycle.get('recheck') or ''}"
                                            )[:1900]
                                            + (f" cancel={cycle.get('sl')}" if cycle.get("sl") is not None else "")
                                            + " confirm=M15",
                                        )
                        except Exception as exc_pd:
                            print(f"[lev] {rsym}: {type(exc_pd).__name__}: {exc_pd}")
                        rres = evaluate_range_radar(
                            symbol=rsym,
                            candles=rh1,
                            confirm_candles=rm15 if isinstance(rm15, list) else rh1,
                            price=rprice,
                            day_used_pct=r_used,
                            btc_context=btc_ctx,
                            prev_fingerprint=_range_fp.get(rsym, ""),
                            d1_candles=rd1 if isinstance(rd1, list) else None,
                            h4_candles=rh4 if isinstance(rh4, list) else None,
                            m15_candles=rm15 if isinstance(rm15, list) else None,
                            m5_candles=rm5 if isinstance(rm5, list) else None,
                        )
                        _fp = str((rres.extras or {}).get("fingerprint") or "")
                        if _fp:
                            _range_fp[rsym] = _fp
                        if rres.opens_position:
                            continue
                        has_intra = (isinstance(rm5, list) and len(rm5) > 0) or (
                            isinstance(rm15, list) and len(rm15) > 0
                        )
                        r_asof = newest_quote_asof(rm5, rm15, rh1)
                        r_stale = quote_is_stale(r_asof, has_intraday=has_intra)
                        chase_rng = False
                        if rres.card and already_ran_without_entry(
                            direction=rres.direction,
                            entry=(rres.card or {}).get("entry"),
                            price=rprice,
                            sl=(rres.card or {}).get("sl"),
                        ):
                            print(f"[scout] skip chase {rsym} range-alert only")
                            chase_rng = True
                        rng_txt = range_result_to_alert(
                            rres,
                            quote_asof=r_asof,
                            chase=chase_rng,
                            quote_stale=r_stale,
                        )
                        if rng_txt:
                            if await _try_signal_feed(rsym, rng_txt, "боковик"):
                                print(f"[range] {rsym} ALERT {rres.status}")
                        elif rres.should_notify:
                            print(f"[range] {rsym} hold {rres.status} {rres.event} (not telegram)")
                        level_hits: Dict[str, str] = {}
                        for _mode, _candles, _confirm in (
                            ("intraday", rh1, rm15 if isinstance(rm15, list) else rh1),
                            ("scalp", rm5 if isinstance(rm5, list) and rm5 else rh1, rm5 if isinstance(rm5, list) and rm5 else rm15),
                        ):
                            book = evaluate_level_book(
                                symbol=rsym,
                                candles=_candles if isinstance(_candles, list) else rh1,
                                confirm_candles=_confirm if isinstance(_confirm, list) else rh1,
                                price=rprice,
                                day_used_pct=r_used,
                                mode=_mode,
                                prev_fingerprint=_level_fp.get(f"{rsym}:{_mode}", ""),
                                d1_candles=rd1 if isinstance(rd1, list) else None,
                                h4_candles=rh4 if isinstance(rh4, list) else None,
                                m15_candles=rm15 if isinstance(rm15, list) else None,
                                m5_candles=rm5 if isinstance(rm5, list) else None,
                            )
                            _lfp = str((book.extras or {}).get("fingerprint") or "")
                            if _lfp:
                                _level_fp[f"{rsym}:{_mode}"] = _lfp
                            if book.opens_position:
                                continue
                            chase_lvl = False
                            for _sc in book.scenarios:
                                if _sc.status == "CONFIRMED" and already_ran_without_entry(
                                    direction=_sc.direction,
                                    entry=_sc.entry,
                                    price=rprice,
                                    sl=_sc.sl,
                                ):
                                    chase_lvl = True
                                    break
                            ltxt = level_book_to_alert(
                                book,
                                quote_asof=r_asof,
                                chase=chase_lvl,
                                quote_stale=r_stale,
                            )
                            if ltxt:
                                level_hits[_mode] = ltxt
                                print(f"[levels] {rsym} {_mode} candidate")
                            wtxt = level_book_to_watching(book)
                            if wtxt:
                                try:
                                    sw = ((book.extras or {}).get("topdown") or {}).get("sweep") or {}
                                    lv = sw.get("level")
                                    side = next((s.direction for s in book.scenarios if s.direction), "LONG")
                                    signal_upsert(
                                        db_path,
                                        signal_id=f"watch-sweep-{rsym}-{_mode}",
                                        symbol=rsym,
                                        direction=str(side),
                                        entry_low=float(lv) if lv is not None else None,
                                        entry_high=float(lv) if lv is not None else None,
                                        sl=None,
                                        tp1=None,
                                        tp2=None,
                                        rr=None,
                                        status=db_status_for("WAITING_SWEEP"),
                                        analysis_note=wtxt[:2000],
                                    )
                                except Exception as exc_ws:
                                    print(f"[levels] {rsym} watching upsert: {exc_ws}")
                                hold_w = allow_proactive_telegram(kind=KIND_WATCHING, symbol=rsym)
                                print(f"[levels] {rsym} {_mode} WATCHING db-only ({hold_w.get('reason')})")
                            atxt = level_book_to_sweep_approach(book, price=rprice)
                            if atxt:
                                try:
                                    sw = ((book.extras or {}).get("topdown") or {}).get("sweep") or {}
                                    lv = sw.get("level")
                                    side = next((s.direction for s in book.scenarios if s.direction), "LONG")
                                    signal_upsert(
                                        db_path,
                                        signal_id=f"watch-near-{rsym}-{_mode}",
                                        symbol=rsym,
                                        direction=str(side),
                                        entry_low=float(lv) if lv is not None else None,
                                        entry_high=float(lv) if lv is not None else None,
                                        sl=None,
                                        tp1=None,
                                        tp2=None,
                                        rr=None,
                                        status=db_status_for("NEAR_SWEEP"),
                                        analysis_note=("NEAR_SWEEP\n" + atxt)[:2000],
                                    )
                                except Exception as exc_n:
                                    print(f"[levels] {rsym} near upsert: {exc_n}")
                                hold_n = allow_proactive_telegram(kind=KIND_SWEEP_NEAR, symbol=rsym)
                                print(f"[levels] {rsym} {_mode} NEAR db-only ({hold_n.get('reason')})")
                            elif book.should_notify and not ltxt and not wtxt:
                                print(f"[levels] {rsym} {_mode} hold (not telegram)")
                        if level_hits:
                            pick_mode = preferred_scan_mode(level_hits.keys())
                            pick_txt = level_hits.get(pick_mode) or next(iter(level_hits.values()))
                            if await _try_signal_feed(rsym, pick_txt, "levels"):
                                print(f"[levels] {rsym} {pick_mode} ALERT")
                    except Exception as exc_range:
                        print(f"[range] {rsym}: {type(exc_range).__name__}: {exc_range}")
                try:
                    log_event(db_path, "BTC_FORCE_ORDERS", BTC_FORCE_ORDER_BOOK.snapshot())
                    try:
                        import office_liq_map as _lm2

                        _lm2.persist(db_path)   # раз на 30 хв: зліпок усього ринку для Mini App
                    except Exception:
                        pass
                    print("[liq] " + format_radar_liq_summary(BTC_FORCE_ORDER_BOOK).replace("\n", " | "))
                except Exception as exc_liq:
                    print(f"[liq] snapshot failed: {exc_liq}")
            except Exception as exc:
                print(f"[radar] monitor failed: {exc}")
            try:
                from office_confluence import (
                    follow_setup,
                    format_cancel_card,
                    format_confirm_card,
                    live_drop,
                    live_items,
                )

                for key, st in live_items():
                    sym_f = str(st.get("symbol") or "")
                    if not sym_f:
                        continue
                    if str(st.get("status") or "WATCHING").upper() not in ("WATCHING", "ACTIVE", "ZONE_REACHED"):
                        continue
                    tf_wait = "5m" if str(st.get("timeframe") or "M15").upper() in ("M15", "M5", "M1") else "15m"
                    try:
                        ltf = await asyncio.to_thread(fetch_candles, sym_f, tf_wait, 40)
                    except Exception:
                        ltf = []
                    px_f = None
                    try:
                        if isinstance(ltf, list) and ltf:
                            px_f = float((ltf[-1] or {}).get("close") or 0) or None
                    except Exception:
                        px_f = None
                    try:
                        h1_f = await asyncio.to_thread(fetch_candles, sym_f, "1h", 60)
                    except Exception:
                        h1_f = None
                    fu = await asyncio.to_thread(follow_setup, setup=st, price=px_f, candles_ltf=ltf, candles_h1=h1_f if isinstance(h1_f, list) else None)
                    act = str(fu.get("action") or "")
                    if act == "confirm":
                        okey = str(st.get("scenario_id") or key)
                        cg = may_emit_telegram(
                            key=okey,
                            intent="CONFIRM",
                            ltf_confirmed=True,
                            chase=bool(fu.get("need_retest")),
                        )
                        if not cg.get("send"):
                            print(f"[confluence] confirm hold {key}: {cg.get('reason')}")
                            continue
                        plan_px = fu.get("price") or px_f
                        try:
                            _m15, _d1, _w1 = await asyncio.gather(asyncio.to_thread(fetch_candles, sym_f, "15m", 96), asyncio.to_thread(fetch_candles, sym_f, "1d", 20),
                                                                  asyncio.to_thread(fetch_candles, sym_f, "1w", 4))
                            tgt = _targets.structural_targets(
                                direction=str(st.get("direction") or ""), entry=plan_px, tp1=st.get("tp1"),
                                lv=_targets.levels(m15=_m15, daily=_d1, weekly=_w1))
                        except Exception as exc_t:
                            print(f"[confluence] targets {sym_f}: {type(exc_t).__name__}: {exc_t}")
                            tgt = {}
                        import office_ready_core as _rc

                        _tp2_m, _tp3_m = _rc.message_targets(direction=str(st.get("direction") or ""), entry=plan_px, tp1=st.get("tp1"), tp2=st.get("tp2"),
                                                             tp3_structural=((tgt or {}).get("tp3") or {}).get("price"))
                        try:
                            plan_bad = _lev_watch.check_plan(sym_f, str(st.get("direction") or ""),
                                                             {"entry": plan_px, "sl": st.get("sl"), "tp1": st.get("tp1"), "tp2": _tp2_m},   # гейт і повідомлення — одні й ті самі цілі
                                                             st.get("zone_lo"), st.get("zone_hi"))
                        except Exception as exc_p:
                            plan_bad = f"Перевірку плану виконати не вдалося ({type(exc_p).__name__})."
                        from office_alert_gate import max_entry_price
                        from office_position_size import plan_position_size
                        import office_signal_track as _trk

                        _dir_c = str(st.get("direction") or "")
                        _tf_c2 = str(st.get("timeframe") or "H1")
                        _now_c = time.time()
                        if plan_bad:  # умови збіглися, але плану для входу немає: внутрішній стан, у Telegram не шлемо; результат відстежуємо мовчки
                            if okey not in _CONFIRM_REJECT_LOGGED:
                                _CONFIRM_REJECT_LOGGED.add(okey)
                                if await asyncio.to_thread(_trk.rejected_recently, db_path, okey, str(plan_bad)[:200]):
                                    continue
                                print(f"[confluence] confirm без готового плану {key}: {plan_bad} — мовчу, стан лише в Mini App")
                                try:
                                    _trk.record_plan(db_path, scenario_id=okey, symbol=sym_f, direction=_dir_c, tf=_tf_c2, entry=plan_px, sl=st.get("sl"),
                                                     tp1=st.get("tp1"), tp2=_tp2_m,
                                                     tp3=None, max_entry=None, confirmed_ts=_now_c,
                                                     valid_until_ts=_lc.valid_until_ts(_now_c, _tf_c2), rejected=True, reason=str(plan_bad)[:200],
                                                     gate=_rc.gate_snapshot(direction=_dir_c, entry=plan_px, sl=st.get("sl"), tp1=st.get("tp1"), tp2=_tp2_m,
                                                                            plan_bad=str(plan_bad)[:200]))
                                except Exception as exc_rj:
                                    print(f"[track] record rejected failed: {exc_rj}")
                            continue
                        _max_e = max_entry_price(_dir_c, st.get("sl"), st.get("tp1"), _tp2_m)
                        if _max_e is not None and px_f is not None and ((_dir_c.upper() != "SHORT" and px_f > _max_e) or (_dir_c.upper() == "SHORT" and px_f < _max_e)):
                            print(f"[confluence] confirm {key}: ціна {px_f} вже за межею входу {_max_e} — сигнал неактуальний, мовчу")
                            continue
                        _dup = await asyncio.to_thread(_rc.find_duplicate, db_path, symbol=sym_f, direction=_dir_c, entry=plan_px, scenario_id=okey)
                        if _dup:   # та сама незавершена ідея вже показана: другий READY не шлемо (інший scenario_id/basis ідею не змінює)
                            print(f"[confluence] confirm {key}: дубль незавершеної ідеї {_dup.get('scenario_id')} (вхід {_dup.get('entry')}) — мовчу")
                            apply_setup_event(okey, _rc.dup_setup_event(_dup, okey), ltf_ok=True)   # той самий сценарій уже має READY → CONFIRMED, а не «скасовано»
                            live_drop(key)
                            continue
                        _valid_c = _lc.valid_until_ts(_now_c, _tf_c2)
                        _sz = plan_position_size(entry=plan_px, sl=st.get("sl"), score=12, min_score=10, direction=_dir_c)
                        _gate_snap = _rc.gate_snapshot(direction=_dir_c, entry=plan_px, sl=st.get("sl"), tp1=st.get("tp1"), tp2=_tp2_m, tp3=_tp3_m,
                                                       max_entry=_max_e, min_tp1_pct=_desk_card_min_tp1(sym_f), confirm=_rc.confirm_basis(fu),
                                                       tp3_why=(((tgt or {}).get("tp3") or {}).get("why") or "") if _tp3_m is not None else "")
                        _story = _rc.story_for(symbol=sym_f, direction=_dir_c, confirm=_gate_snap.get("confirm"), gate=_gate_snap, entry=plan_px,
                                               zone_lo=st.get("zone_lo"), zone_hi=st.get("zone_hi"), tf=_tf_c2)
                        _mctx: Dict[str, Any] = {}
                        try:   # ринок і календарна структура на момент сигналу: лише з реальних свічок; збій → рядків просто немає
                            import office_market_view as _mview

                            _mctx = await asyncio.wait_for(asyncio.to_thread(_mview.for_signal, sym_f, _dir_c, _now_c), timeout=20.0) or {}
                            if _mctx.get("snapshot"):
                                _gate_snap["context"] = _mctx["snapshot"]
                        except Exception as exc_mv:
                            print(f"[market] контекст сигналу недоступний {sym_f}: {exc_mv}")
                        confirm_msg_id = await send_proactive(
                            EVENT_TRADE_UPDATE,
                            _msgs.ready_signal(
                                symbol=sym_f, direction=_dir_c, entry=plan_px, sl=st.get("sl"), tp1=st.get("tp1"),
                                tp2=_tp2_m, tp3=_tp3_m, max_entry=_max_e, setup=str(_story.get("name") or ""), why=_story.get("why") or [], tp3_why=_gate_snap.get("tp3_why") or "",
                                market=(list(_mctx.get("lines") or []) + list(_mctx.get("calendar") or [])) or "",
                                size_usdt=_sz.get("size_usdt") if _sz.get("ok") else None,
                                risk_usd=(float(_sz.get("depo") or 0) * float(_sz.get("risk_pct") or 0)) if _sz.get("ok") else None,
                                valid_until=_rc.kyiv_stamp(_valid_c)),
                            symbol=sym_f,
                            kind="CONFIRM",
                            intent="CONFIRM",
                            canonical_id=okey,
                            scenario_event="CONFIRM",
                        )
                        if not confirm_msg_id:
                            print(f"[confluence] CONFIRM delivery not verified {okey}: keep pending for retry")
                            continue
                        mark_confirm_sent(okey)
                        apply_setup_event(okey, "CONFIRMED", ltf_ok=True)
                        try:  # мовчазне відстеження кожного «Плану готовий» для статистики (не залежить від кнопки «Я відкрила угоду»)
                            _trk.record_plan(db_path, scenario_id=okey, symbol=sym_f, direction=_dir_c, tf=_tf_c2, entry=plan_px, sl=st.get("sl"),
                                             tp1=st.get("tp1"), tp2=_tp2_m, tp3=_tp3_m,
                                             max_entry=_max_e, confirmed_ts=_now_c, valid_until_ts=_valid_c,
                                             rejected=False, confirm_msg_id=confirm_msg_id,
                                             gate=_gate_snap)
                        except Exception as exc_tr:
                            print(f"[track] record plan failed: {exc_tr}")
                        try:
                            from office_scenario_memory import apply_confirmed_status

                            apply_confirmed_status(
                                db_path,
                                symbol=sym_f,
                                direction=str(st.get("direction") or ""),
                                timeframe=str(st.get("timeframe") or ""),
                                origin=str(st.get("origin") or "desk"),
                                zone_lo=st.get("zone_lo"),
                                zone_hi=st.get("zone_hi"),
                                signal_id=str(st.get("signal_id") or ""),
                                price=fu.get("price"),
                            )
                        except Exception as exc_cu:
                            print(f"[confluence] status CONFIRMED {sym_f}: {exc_cu}")
                        live_drop(key)
                        print(f"[confluence] confirmed {key}")
                    elif act == "cancel":
                        # Скасування внутрішнього сценарію (до готового плану) — не подія для Telegram: лише БД/Mini App.
                        print(f"[confluence] cancel {key}: {fu.get('reason')} ({fu.get('kind')}) — без Telegram")
                        if fu.get("kind") == "TIME":
                            try:
                                import office_signal_track as _trk3

                                _trk3.record_expiry(db_path, scenario_id=str(st.get("scenario_id") or key), symbol=sym_f, direction=str(st.get("direction") or ""),
                                                    zone_lo=st.get("zone_lo"), zone_hi=st.get("zone_hi"), sl=st.get("sl"), tp1=st.get("tp1"), expired_ts=time.time())
                            except Exception as exc_ex:
                                print(f"[track] record expiry failed: {exc_ex}")
                        ckey = str(st.get("scenario_id") or key)
                        apply_setup_event(ckey, "CANCELLED")
                        try:
                            from office_bridge import signal_update

                            signal_update(
                                db_path,
                                signal_id=str(st.get("signal_id") or ckey),
                                status="CANCELLED",
                                outcome="CANCELLED",
                            )
                        except Exception as exc_cancel:
                            print(f"[confluence] status CANCELLED {sym_f}: {exc_cancel}")
                        live_drop(key)
                        print(f"[confluence] cancelled {key}")
            except Exception as exc_fu:
                print(f"[confluence] follow failed: {exc_fu}")
            try:   # реєстр PULLBACK WATCH і покриття ротації переживають перезапуск worker (не частіше, ніж раз на 10 хв)
                import office_scan_funnel as _fun_p

                if time.time() - float(getattr(_fun_p.STATE, "persisted_at", 0.0)) >= 600 and (_fun_p.STATE.pullbacks or _fun_p.STATE.last_deep):
                    await asyncio.to_thread(_fun_p.persist, db_path)
                    _fun_p.STATE.persisted_at = time.time()
            except Exception as exc_fp:  # noqa: BLE001
                print(f"[funnel] persist: {type(exc_fp).__name__}")
            utc_now = datetime.now(timezone.utc)
            minute_of_day = utc_now.hour * 60 + utc_now.minute
            fast = (480 <= minute_of_day < 660) or (780 <= minute_of_day < 960)
            await asyncio.sleep(180 if fast else 600)

    asyncio.create_task(monitor_trade_radar())
    asyncio.create_task(run_btc_force_order_loop(BTC_FORCE_ORDER_BOOK))
    try:   # карта ліквідацій по всьому ринку (безкоштовний потік !forceOrder@arr); OFFICE_LIQ_MAP=0 вимикає
        import office_liq_map as _liq_map

        if _liq_map.start():
            print("[liq-map] потік ліквідацій усього ринку запущено")
    except Exception as exc_lm:
        print(f"[liq-map] не запущено: {type(exc_lm).__name__}: {exc_lm}")

    async def process_tv_signal(signal: Dict[str, Any]) -> None:
        """
        Обробляє сигнал від TradingView.
        Лев додає ICT аналіз і дає рішення.
        """
        row_id = int(signal.get("id") or 0)
        try:
            symbol = str(signal.get("symbol", "")).strip()
            pattern = str(signal.get("pattern", ""))
            direction = str(signal.get("direction", "")).strip()
            price_raw = signal.get("price", 0)
            try:
                price = float(price_raw) if price_raw is not None else 0.0
            except Exception:
                price = 0.0
            tf = str(signal.get("timeframe", "1h") or "1h")
            strength = str(signal.get("strength", ""))

            if not symbol or direction not in ("LONG", "SHORT"):
                if row_id:
                    tv_signal_mark_processed(db_path, row_id)
                return

            print(f"[tv-webhook] silent {symbol} {direction} {pattern} (no desk LLM/Telegram)")
            if row_id:
                tv_signal_mark_processed(db_path, row_id)
            return
        except Exception as e:
            print(f"[tv-webhook] error: {e}")

    async def monitor_tradingview_signals() -> None:
        while True:
            try:
                for sig in tv_signal_fetch_unprocessed(db_path, limit=6):
                    await process_tv_signal(sig)
            except Exception as exc:
                print(f"[relay][WARN] monitor_tradingview_signals: {exc}")
            await asyncio.sleep(15)

    asyncio.create_task(monitor_tradingview_signals())

    async def morning_macro_brief() -> None:
        """Daily 09:00 Kyiv macro — лише лог (PR41)."""
        print("[relay] macro briefing silent (no Telegram/LLM)")

    async def monitor_briefing_scheduler() -> None:
        """MASTER п.28: ранковий брифінг + вечірній debrief за локальним часом."""
        last_macro_date = ""
        last_morning_date = ""
        last_evening_date = ""
        bh, bm = _parse_hh_mm(os.getenv("OFFICE_MACRO_BRIEFING_TIME", "09:00"), 9, 0)
        mh, mm = _parse_hh_mm(os.getenv("OFFICE_BRIEFING_MORNING", "08:00"), 8, 0)
        eh, em = _parse_hh_mm(os.getenv("OFFICE_BRIEFING_EVENING", "21:00"), 21, 0)
        http_timeout = aiohttp.ClientTimeout(total=15)
        while True:
            try:
                if os.getenv("OFFICE_BRIEFING_DISABLE", "").strip() == "1":
                    await asyncio.sleep(600)
                    continue
                tz = _briefing_tzinfo()
                now = datetime.now(tz)
                today = now.strftime("%Y-%m-%d")
                h, mi = now.hour, now.minute

                if h == bh and mi == bm and last_macro_date != today:
                    await morning_macro_brief()
                    last_macro_date = today
                    print("[relay] auto macro briefing sent")

                if h == mh and mi == mm and last_morning_date != today:
                    last_morning_date = today
                    print("[relay] auto morning briefing silent")

                if h == eh and mi == em and last_evening_date != today:
                    async def sender_e(msg: str) -> None:
                        await send_proactive(EVENT_EVENING_DEBRIEF, msg[:3900])

                    sent = await office_evening_debrief(
                        sender_e,
                        db_path=db_path,
                    )
                    last_evening_date = today
                    print(f"[relay] auto evening debrief sent={bool(sent)}")
            except Exception as exc:
                print(f"[relay][WARN] monitor_briefing_scheduler failed: {exc}")
            await asyncio.sleep(40)

    asyncio.create_task(monitor_briefing_scheduler())

    async def monitor_weekly_review() -> None:
        """MASTER п.29: тижневий текстовий зріз журналу за розкладом."""
        last_week_key = ""
        wh, wm = _parse_hh_mm(os.getenv("OFFICE_WEEKLY_TIME", "20:00"), 20, 0)
        try:
            target_dow = int(os.getenv("OFFICE_WEEKLY_ISO_DOW", "7") or "7")
        except Exception:
            target_dow = 7
        if target_dow < 1 or target_dow > 7:
            target_dow = 7
        while True:
            try:
                if os.getenv("OFFICE_WEEKLY_DISABLE", "").strip() == "1":
                    await asyncio.sleep(600)
                    continue
                tz = _briefing_tzinfo()
                now = datetime.now(tz)
                iso = now.isocalendar()
                week_key = f"{iso[0]}-W{iso[1]:02d}"
                h, mi = now.hour, now.minute
                if now.isoweekday() == target_dow and h == wh and mi == wm and last_week_key != week_key:
                    report = build_weekly_journal_report(db_path)
                    print(f"[relay] weekly journal silent: {report[:120]}")
                    last_week_key = week_key
                    print("[relay] weekly journal report sent")
            except Exception as exc:
                print(f"[relay][WARN] monitor_weekly_review failed: {exc}")
            await asyncio.sleep(45)

    asyncio.create_task(monitor_weekly_review())

    async def run_meta_intelligence() -> None:
        """Запускає Meta Intelligence аналіз."""
        try:
            report = get_meta_intelligence_report(db_path)
            if report.get("error"):
                print(f"[meta] report error: {report.get('error')}")
                return
            print(f"[meta] silent stats signals={report.get('total_signals')}")
            return

            context = f"""
Статистика офісу за 7 днів:

Всього сигналів: {report['total_signals']}
Досягли першого тейку: {report['hit_tp1']}
Досягли другого тейку: {report['hit_tp2']}
Вибило по стопу: {report['hit_sl']}
Не відпрацювали: {report['expired']}
В очікуванні: {report['watching']}

Результативність: {report['win_rate']}%
Лонгів: {report['longs']}
Шортів: {report['shorts']}

Топ монети: {report['top_symbols']}
"""

            system = """Ти Лев.
Аналізуй тижневу статистику офісу.
Говориш українською просто і чесно.

Дай відповідь на питання:
1. Які результати за тиждень?
2. Що працює добре?
3. Де є слабкі місця?
4. Що змінити на наступний тиждень?
5. Загальна оцінка роботи офісу.

Максимум 10 речень. Конкретно."""

            response = clean_llm_note(
                ask_agent(
                    "lev",
                    system,
                    context,
                    max_tokens=600,
                    db_path=db_path,
                )
            )

            if response:
                print(f"[meta] silent week report: {response[:120]}")

        except Exception as e:
            print(f"[meta] error: {e}")

    async def meta_intelligence_weekly() -> None:
        """Щотижневий Meta Intelligence звіт."""
        last_date: Optional[Any] = None
        while True:
            try:
                if os.getenv("OFFICE_META_INTELLIGENCE_DISABLE", "").strip() == "1":
                    await asyncio.sleep(600)
                    continue
                tz = _briefing_tzinfo()
                now = datetime.now(tz)
                today = now.date()
                if (
                    now.weekday() == 6
                    and now.hour == 20
                    and now.minute < 5
                    and last_date != today
                ):
                    last_date = today
                    await run_meta_intelligence()
                    await asyncio.sleep(3660)
                else:
                    await asyncio.sleep(60)
            except Exception as e:
                print(f"[meta-weekly] {e}")
                await asyncio.sleep(60)

    asyncio.create_task(meta_intelligence_weekly())

    async def monitor_risk_committee() -> None:
        """MASTER п.30: один нагадувальний пост на день при серії SL або багатьох денних лоссах."""
        global _risk_committee_last_sent
        last_sent_day = ""
        while True:
            try:
                if os.getenv("OFFICE_RISK_COMMITTEE_DISABLE", "").strip() == "1":
                    await asyncio.sleep(600)
                    continue
                try:
                    need_day = int(os.getenv("OFFICE_RISK_COMMITTEE_DAY_LOSSES", "4") or "4")
                except Exception:
                    need_day = 4
                try:
                    need_streak = int(os.getenv("OFFICE_RISK_COMMITTEE_STREAK", "3") or "3")
                except Exception:
                    need_streak = 3
                tz = _briefing_tzinfo()
                today = datetime.now(tz).strftime("%Y-%m-%d")
                if last_sent_day == today:
                    await asyncio.sleep(120)
                    continue
                day_losses = _journal_today_loss_count(db_path)
                streak = journal_consecutive_loss_streak(db_path)
                if day_losses >= need_day or streak >= need_streak:
                    total = journal_total_closed(db_path)
                    if total < 5:
                        await asyncio.sleep(120)
                        continue
                    if (time.time() - _risk_committee_last_sent) < 86400:
                        await asyncio.sleep(120)
                        continue
                    log_event(
                        db_path,
                        "RISK_COMMITTEE",
                        {"day_losses": day_losses, "streak": streak, "thresholds": [need_day, need_streak]},
                    )
                    print(
                        "[relay] risk committee silent: "
                        f"LOSS {day_losses} streak {streak}"
                    )
                    last_sent_day = today
                    _risk_committee_last_sent = time.time()
                    print("[relay] risk committee notice sent")
            except Exception as exc:
                print(f"[relay][WARN] monitor_risk_committee failed: {exc}")
            await asyncio.sleep(90)

    asyncio.create_task(monitor_risk_committee())

    async def monitor_funding_atr_alerts() -> None:
        """MASTER п.32–33: екстремальний funding BTC та «втома» ATR (24h range %) — з cooldown."""
        last_fund_mono = 0.0
        last_atr_mono = 0.0
        http_timeout = aiohttp.ClientTimeout(total=25)
        while True:
            try:
                if os.getenv("OFFICE_MARKET_ALERTS_DISABLE", "").strip() == "1":
                    await asyncio.sleep(600)
                    continue
                try:
                    fund_thr = float(os.getenv("OFFICE_FUNDING_ALERT_ABS_PCT", "0.07") or "0.07")
                except Exception:
                    fund_thr = 0.07
                try:
                    atr_thr = float(os.getenv("OFFICE_ATR_ALERT_VOL_PCT", "7.5") or "7.5")
                except Exception:
                    atr_thr = 7.5
                try:
                    cooldown = float(os.getenv("OFFICE_MARKET_ALERT_COOLDOWN_SEC", "3600") or "3600")
                except Exception:
                    cooldown = 3600.0
                async with aiohttp.ClientSession(timeout=http_timeout) as http:
                    prem = await fetch_binance_premium_index(http, "BTCUSDT")
                    btc = await fetch_binance_futures_ticker(http, "BTCUSDT")
                now_m = time.monotonic()
                fr = prem.get("funding_rate_pct") if prem else None
                if fr is not None and abs(float(fr)) >= fund_thr and (now_m - last_fund_mono) >= cooldown:
                    print(
                        f"[relay] funding alert silent BTC |{float(fr):.4f}|%"
                    )
                    last_fund_mono = now_m
                vol = float(btc.get("volatility_pct") or 0.0)
                if vol >= atr_thr and (now_m - last_atr_mono) >= cooldown:
                    print(f"[relay] btc vol alert silent {vol:.2f}%")
                    last_atr_mono = now_m
            except Exception as exc:
                print(f"[relay][WARN] monitor_funding_atr_alerts failed: {exc!r}")
            await asyncio.sleep(int(os.getenv("OFFICE_MARKET_ALERT_POLL_SEC", "180") or "180"))

    asyncio.create_task(monitor_funding_atr_alerts())

    async def monitor_lev_watches() -> None:
        """Лев відстежує умови, які сам оголосив (чекаємо → в зоні → підтверджено/скасовано/час минув/дані застаріли).
        Події пишуться завжди; у Telegram (OFFICE-чат) — лише за OFFICE_LEV_WATCH_NOTIFY=1, по одному повідомленню на зміну."""
        await asyncio.sleep(45)
        _n = 0
        while True:
            try:
                _n += 1
                if _n % 3 == 1 or (_n <= 12):   # раз на ~15 хв (перші ~годину — щоцикл): статистика джерела (429, вага IP, WebSocket, кеш)
                    from office_market_data import source_health

                    try:
                        import office_data_stability as _stab

                        _stab.set_db(db_path)
                        _stab.tick(db=db_path)   # щогодинний облік стабільності свічок (для авто-вмикання стакана)
                        _stab_txt = f" stability={_stab.status(db_path)}"
                    except Exception:
                        _stab_txt = ""
                    print(f"[data] binance {source_health()} depth={__import__('office_market_data').depth_stats()}{_stab_txt}")
                items = await asyncio.to_thread(_lev_watch.tick, db_path)
                for it in items:
                    # той самий безпечний маршрут, що й картки Лева: політика, дедуп за (умова, подія), журнал доставки
                    mid = await send_proactive(
                        EVENT_TRADE_UPDATE,
                        str(it["text"])[:3800],
                        symbol=str(it["symbol"]),
                        direction=str(it.get("direction") or ""),
                        kind=str(it["event"]),
                        intent="ANALYTICAL",
                        canonical_id=str(it["watch_id"]),
                        scenario_event=str(it["event"]),
                    )
                    await asyncio.to_thread(_lev_watch.mark_result, db_path, str(it["watch_id"]), str(it["event"]), bool(mid), mid)
                    print(f"[lev-watch] {'sent' if mid else 'NOT DELIVERED'} {it['symbol']} {it['event']}{' (retry)' if it.get('retry') else ''} id={mid}")
            except Exception as exc:
                print(f"[lev-watch][WARN] tick failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(int(os.getenv("OFFICE_LEV_WATCH_POLL_SEC", "300") or "300"))

    asyncio.create_task(monitor_lev_watches())

    async def _launch_once() -> None:   # одноразова діагностика запуску (календар, replay журналу, потік ліквідацій); результат — у БД (LAUNCH_DIAG), без змінних
        await asyncio.sleep(240)
        try:
            import office_launch_once

            if await asyncio.to_thread(office_launch_once.run, db_path):
                print("[launch-diag] виконано й записано в БД (LAUNCH_DIAG)")
        except Exception as exc_ld:  # noqa: BLE001
            print(f"[launch-diag] помилка: {type(exc_ld).__name__}: {exc_ld}")

    asyncio.create_task(_launch_once())

    async def _pine_parity_once() -> None:   # одноразова звірка Pine-еталон ↔ продакшн на реальних свічках (архів Binance); результат — у БД (LAUNCH_DIAG, pine_parity)
        await asyncio.sleep(420)
        try:
            import office_pine_parity

            if await asyncio.to_thread(office_pine_parity.run_once, db_path):
                print("[pine-parity] виконано й записано в БД (LAUNCH_DIAG)")
        except Exception as exc_pp:  # noqa: BLE001
            print(f"[pine-parity] помилка: {type(exc_pp).__name__}: {exc_pp}")

    asyncio.create_task(_pine_parity_once())

    async def _ui_check_once() -> None:   # одноразова перевірка Mini App на живих даних (новини українською, статуси джерел, шари графіка по ТФ); результат — у БД
        await asyncio.sleep(540)
        try:
            import office_ui_check

            if await asyncio.to_thread(office_ui_check.run_once, db_path):
                print("[ui-check] виконано й записано в БД (LAUNCH_DIAG)")
        except Exception as exc_uc:  # noqa: BLE001
            print(f"[ui-check] помилка: {type(exc_uc).__name__}: {exc_uc}")

    asyncio.create_task(_ui_check_once())

    async def _funnel_check_once() -> None:   # одноразова shadow-перевірка воронки скану на живих даних (покриття монет, Gainers/Losers, PULLBACK WATCH, шлях до READY); результат — у БД
        await asyncio.sleep(660)
        try:
            import office_funnel_check

            if await asyncio.to_thread(office_funnel_check.run_once, db_path):
                print("[funnel-check] виконано й записано в БД (LAUNCH_DIAG)")
        except Exception as exc_fc:  # noqa: BLE001
            print(f"[funnel-check] помилка: {type(exc_fc).__name__}: {exc_fc}")

    asyncio.create_task(_funnel_check_once())

    # Одноразові запуски replay і аналізу RR (OFFICE_REPLAY_ON_START / OFFICE_RR_ANALYSIS_ON_START) виконано 2026-09-30, результати — у docs/state-notes; хуки прибрано.
    # Повторити вручну: office_replay.run_all() / office_rr_analysis.run(<db>) на машині з доступом до БД і до архіву data.binance.vision.

    async def monitor_signal_tracks() -> None:
        """Мовчазне відстеження результатів «Плану готовий» і відхилених планів (для навчання). У Telegram нічого не шле."""
        import office_signal_track as trk

        await asyncio.sleep(120)
        while True:
            try:
                res = await asyncio.to_thread(trk.tick, db_path)
                for fx_ in await asyncio.to_thread(trk.check_false_expiry, db_path):
                    print(f"[track] зняття за часом {fx_['symbol']} {fx_['direction']}: {'FALSE_EXPIRY (ідея відпрацювала)' if fx_['false_expiry'] else 'ок'}")
                for r in res:
                    print(f"[track] {r['symbol']} {r['direction']} {'відхилений' if r['rejected'] else 'сигнал'} → {r['outcome']} MFE {r['mfe_pct']} MAE {r['mae_pct']}")
            except Exception as exc:
                print(f"[track][WARN] tick failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(600)

    asyncio.create_task(monitor_signal_tracks())

    async def monitor_scenario_milestones() -> None:
        """Подія рівня для КОЖНОГО доставленого «Плану готовий»: ціна досягла TP1/TP2/TP3 або стоп-рівня сценарію.
        Не залежить від кнопки «Я відкрила угоду» (та лише додає ведення твоєї позиції). Один раз на рівень, відповіддю на повідомлення плану."""
        import office_signal_track as trk

        await asyncio.sleep(150)
        while True:
            try:
                for m in await asyncio.to_thread(trk.pending_milestones, db_path):
                    if m.get("silent"):   # ENTRY / EXPIRED: життя сценарію для статистики, без Telegram
                        await asyncio.to_thread(trk.record_milestone, db_path, m, None)
                        print(f"[milestone] {m['symbol']} {m['level']} (тихо, лише БД)")
                        continue
                    mid = await send_proactive(
                        EVENT_TRADE_UPDATE,
                        _msgs.scenario_event(symbol=str(m["symbol"]), direction=str(m["direction"]), level=str(m["level"]), price=m.get("price")),
                        reply_to_message_id=m.get("confirm_msg_id"), symbol=str(m["symbol"]), direction=str(m["direction"]),
                        kind="SCENARIO_EVENT", intent="SCENARIO_EVENT", canonical_id=f"{m['scenario_id']}|{m['confirmed_ts']}|{m['level']}",
                        scenario_event=str(m["level"]),
                    )
                    if mid:
                        await asyncio.to_thread(trk.record_milestone, db_path, m, mid)
                        print(f"[milestone] sent {m['symbol']} {m['level']} id={mid}")
                    else:
                        print(f"[milestone] not delivered {m['symbol']} {m['level']} — повторю")
            except Exception as exc_ms:
                print(f"[milestone][WARN] tick failed: {type(exc_ms).__name__}: {exc_ms}")
            await asyncio.sleep(45)

    asyncio.create_task(monitor_scenario_milestones())

    async def monitor_manual_trades() -> None:
        """Ведення угод, які власниця позначила відкритими: TP1/TP2/TP3/стоп — короткий рядок з дією, один раз, відповіддю на сигнал.
        Проходить через send_proactive (шлюз: POSITION_MANAGE + відкрита позиція; додатково OFFICE_TG_POSITION_SUPPORT)."""
        import office_signal_track as trk
        import office_trade_updates as tu
        from office_market_data import fetch_candles as _fc

        def _price(sym: str) -> Optional[float]:
            c = _fc(sym, "1m", 3)
            if isinstance(c, list) and c:
                return float(c[-1].get("close"))
            return None

        await asyncio.sleep(90)
        while True:
            try:
                for it in await asyncio.to_thread(tu.pending, db_path, _price, _fc):
                    pos = it["trade"]
                    reply = await asyncio.to_thread(trk.confirm_msg_for, db_path, str(pos.get("scenario_id") or "")) if pos.get("scenario_id") else None
                    mid = await send_proactive(
                        EVENT_TRADE_UPDATE, it["text"], reply_to_message_id=reply, symbol=str(pos["symbol"]), direction=str(pos["direction"]),
                        kind=it["code"], intent="POSITION_MANAGE", confirmed_position=True, position_id=str(pos["trade_id"]), position_open=True,
                        canonical_id=str(pos["trade_id"]), scenario_event=it["code"],
                    )
                    if mid:
                        await asyncio.to_thread(tu.record, db_path, str(pos["trade_id"]), it["code"], mid)
                        print(f"[trade-updates] sent {pos['symbol']} {it['code']} id={mid}")
                    else:
                        print(f"[trade-updates] not delivered {pos['symbol']} {it['code']} (супровід позицій вимкнено або збій)")
            except Exception as exc:
                print(f"[trade-updates][WARN] tick failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(120)

    asyncio.create_task(monitor_manual_trades())

    async def monitor_daily_report() -> None:
        nonlocal last_daily_report_date
        while True:
            try:
                # Київський час (OFFICE_BRIEFING_TZ), а не UTC сервера Render —
                # інакше денний звіт «з'їжджає» на кілька годин.
                now_local = datetime.now(_briefing_tzinfo())
                today = now_local.strftime("%Y-%m-%d")
                if now_local.hour >= 22 and last_daily_report_date != today:
                    report = build_daily_journal_report(db_path)
                    print(f"[relay] daily journal silent: {report[:80]}")
                    last_daily_report_date = today
                    print("[relay] daily journal report sent")
            except Exception as exc:
                print(f"[relay][WARN] monitor_daily_report failed: {exc}")
                print(f"[relay][WARN] monitor_daily_report failed: {exc}")
            await asyncio.sleep(60)

    async def monitor_office_autosave() -> None:
        """
        Автозбереження стану кожні N секунд (дефолт 600 = 10 хв).
        Допомагає швидко відновитись після раптового рестарту/втрати сесії.
        """
        if os.getenv("OFFICE_AUTOSAVE_DISABLE", "").strip() == "1":
            return
        try:
            every_sec = max(60, int(os.getenv("OFFICE_AUTOSAVE_SEC", "600") or "600"))
        except Exception:
            every_sec = 600
        tick = 0
        autosave_dir = ROOT_DIR / "office_autosave"
        while True:
            try:
                tick += 1
                ident = office_db_identity(db_path)
                payload: Dict[str, Any] = {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "db_identity": ident,
                    "main_chat_id": main_chat_id,
                    "office_chat_id": office_chat_id,
                    "checklist_head": _read_text_head(CHECKLIST_PATH, max_chars=700),
                    "runbook_head": _read_text_head(RUNBOOK_PATH, max_chars=500),
                    "master_prompt_head": _read_text_head(MASTER_PROMPT_PATH, max_chars=900),
                    "notes": "autosave by relay; generated every OFFICE_AUTOSAVE_SEC",
                }
                latest_path = autosave_dir / "state_latest.json"
                _safe_json_write(latest_path, payload)
                # Щогодинний снепшот (при дефолті 600 сек = кожні 6 циклів).
                if tick % max(1, int(3600 / every_sec)) == 0:
                    hour_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H00Z")
                    hourly_path = autosave_dir / f"state_{hour_tag}.json"
                    _safe_json_write(hourly_path, payload)
            except Exception as exc:
                print(f"[relay][WARN] monitor_office_autosave failed: {exc}")
            await asyncio.sleep(every_sec)

    asyncio.create_task(monitor_daily_report())
    asyncio.create_task(monitor_source_bridge())
    asyncio.create_task(monitor_office_autosave())

    _last_alert_ts = 0.0
    try:
        while True:
            try:
                if not client.is_connected():
                    print("[relay] telegram reconnecting…")
                    await client.connect()
                await client.run_until_disconnected()
                print("[relay] telegram disconnected; retry in 15s (process stays up)")
            except asyncio.CancelledError:
                print("[relay] shutdown (SIGTERM/cancel) — exit 0, не status 1")
                return
            except Exception as e:
                now_ts = time.time()
                print(f"[relay] session error {type(e).__name__}: {e}")
                if now_ts - _last_alert_ts >= 300:
                    _last_alert_ts = now_ts
                    try:
                        if os.getenv("OFFICE_TG_TECH_PINGS", "").strip() == "1":
                            await send_office(
                                f"⚠️ Relay session: {type(e).__name__}: {str(e)[:200]}"
                                f"\nРеконнект без exit 1."
                            )
                    except Exception as alert_exc:
                        print(f"[relay][WARN] crash alert send failed: {alert_exc}")
            await asyncio.sleep(15)
    finally:
        await bot_http.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("[relay] KeyboardInterrupt — exit 0")
        raise SystemExit(0)
    except asyncio.CancelledError:
        print("[relay] CancelledError — exit 0")
        raise SystemExit(0)

