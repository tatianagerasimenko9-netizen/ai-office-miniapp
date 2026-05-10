from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
import os
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

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
    clean_llm_note,
    detect_setup_type,
    fmt_agent_line,
    get_agent_card_text,
    init_office_db,
    journal_close_trade,
    journal_consecutive_loss_streak,
    journal_add_feedback,
    journal_learning_hints_from_tags,
    journal_open_trade,
    journal_recurring_mistakes,
    journal_total_closed,
    log_event,
    office_db_identity,
    office_desk_user_question,
    office_evening_debrief,
    office_handle_signal,
    office_morning_briefing,
    office_news_trigger,
    office_position_event,
    office_run_scenario,
    office_trade_closed,
    live_risk_snapshot,
    signal_get_active,
    signal_get_by_symbol,
    signal_update,
    signal_upsert,
    _extract_first_usdt_symbol,
)
from office_llm_agent import ask_agent

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
_risk_committee_last_sent: float = 0.0

OFFICE_RULES_BRIEF_UA = (
    "Правила офісу (коротко):\n"
    "1) Пишемо простою українською, коротко.\n"
    "2) Спочатку безпека депозиту, потім прибуток.\n"
    "3) Рішення по сигналу = командна дискусія ролей, без хаосу.\n"
    "4) Лев фіналить напрямок, Марко дає план виконання.\n"
    "5) При серії збитків ризик має пріоритет, вхід блокується.\n"
    "6) Для повних ролей/деталей: команда /officeprompt."
)
LEV_RULE = (
    "Тобі 42 роки. Ти Лев. "
    "20 років на ринках. "
    "Говориш цифрами. Даєш Entry/SL/TP/RR. "
    "Одне речення після якщо треба. "
    "Старший ТФ в пріоритеті. "
    "Є активний сигнал — UPDATE не новий. "
    "Спочатку Entry/SL/TP/RR — потім все інше. "
    "Говориш тільки українською. "
    "Без таблиць і заголовків."
)


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


async def send_via_bot_api(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
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
    try:
        async with session.post(url, json=payload) as resp:
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
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    params = {"symbol": symbol.upper()}
    async with session.get(url, params=params) as resp:
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
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    params = {"symbol": symbol.upper()}
    async with session.get(url, params=params) as resp:
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
        return NewsRisk("SAFE", "news api key missing", 999, "", "", "USD", "low")
    now = datetime.now(timezone.utc)
    from_s = now.strftime("%Y-%m-%d")
    to_s = from_s
    url = "https://financialmodelingprep.com/stable/economic-calendar"
    params = {"from": from_s, "to": to_s, "apikey": api_key}
    news_timeout = aiohttp.ClientTimeout(total=15)
    async with session.get(url, params=params, timeout=news_timeout) as resp:
        if resp.status != 200:
            return NewsRisk("SAFE", f"news status {resp.status}", 999, "", "", "USD", "low")
        data = await resp.json()
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
        )
    return NewsRisk(
        "SAFE",
        nearest_title,
        nearest_min,
        nearest_title,
        nearest_time_utc,
        nearest_currency,
        nearest_importance,
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
    try:
        is_pg = str(db_path).lower().startswith("postgres://") or str(db_path).lower().startswith("postgresql://")
        if is_pg:
            if psycopg is None:
                raise RuntimeError("psycopg is required for PostgreSQL mode")
            with psycopg.connect(db_path) as conn:  # type: ignore[arg-type]
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT outcome, pnl_pct, r_multiple, mistake_tags_json
                        FROM trade_journal
                        WHERE status = 'CLOSED' AND LEFT(COALESCE(ts_close_utc, ''), 10) = TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD')
                        """
                    )
                    rows = cur.fetchall()
        else:
            if str(db_path).lower().startswith("sqlite:///"):
                db_path = str(db_path)[10:]
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT outcome, pnl_pct, r_multiple, mistake_tags_json
                    FROM trade_journal
                    WHERE status = 'CLOSED' AND date(ts_close_utc) = date('now')
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

    for outcome, pnl_pct, r_multiple, tags_json in rows:
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

    total = wins + losses + be
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
    avg_r = (sum(r_vals) / len(r_vals)) if r_vals else 0.0
    top_tags = sorted(tags_count.items(), key=lambda x: (-x[1], x[0]))[:3]
    tags_text = ", ".join(f"{k} x{v}" for k, v in top_tags) if top_tags else "нема"

    return (
        "Щоденний журнал:\n"
        f"Угод: {total} | W {wins} · L {losses} · BE {be} | WR {wr:.1f}%\n"
        f"PnL сумарно: {pnl_sum:+.2f}% | Avg R: {avg_r:+.2f}\n"
        f"Топ помилок: {tags_text}"
    )


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
        if re.match(r"^[A-Z0-9]{2,10}$", clean) and len(clean) >= 2:
            sym = f"{clean}USDT"
            if sym not in seen:
                seen.add(sym)
                symbols.append(sym)
    return symbols[:3]


def _parse_signal_levels_from_text(text: str) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {
        "entry_low": None,
        "entry_high": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "rr": None,
    }
    src = str(text or "")

    def _to_float(raw: str) -> Optional[float]:
        try:
            s = str(raw or "").replace(" ", "").replace(",", "")
            return float(s)
        except Exception:
            return None

    def _extract_line_value(label: str, line_text: str, hint: Optional[float] = None) -> Optional[float]:
        pat = rf"{label}\s*:\s*([^\n\r]+)"
        m = re.search(pat, line_text, flags=re.IGNORECASE)
        if not m:
            return None
        chunk = str(m.group(1) or "")
        nums = re.findall(r"\d[\d,]*(?:\.\d+)?", chunk)
        values: List[float] = []
        for n in nums:
            v = _to_float(n)
            if v is not None:
                values.append(v)
        if not values:
            return None
        # Ignore percentage-like tail values if a realistic price exists.
        if hint is not None:
            near = [v for v in values if 0.5 * hint <= v <= 1.5 * hint]
            if near:
                return near[0]
        big = [v for v in values if v >= 10]
        return big[0] if big else values[0]
    nums = re.findall(r"\d+(?:\.\d+)?", src)
    if nums:
        pass

    m_entry = re.search(r"Entry:\s*([0-9]+(?:\.[0-9]+)?)\s*[-–]\s*([0-9]+(?:\.[0-9]+)?)", src, flags=re.IGNORECASE)
    if m_entry:
        a = float(m_entry.group(1))
        b = float(m_entry.group(2))
        out["entry_low"] = min(a, b)
        out["entry_high"] = max(a, b)
    else:
        m_entry_one = re.search(r"Entry:\s*([0-9]+(?:\.[0-9]+)?)", src, flags=re.IGNORECASE)
        if m_entry_one:
            v = float(m_entry_one.group(1))
            out["entry_low"] = v
            out["entry_high"] = v
    entry_hint = out["entry_low"] or out["entry_high"]
    sl_v = _extract_line_value("SL", src, hint=entry_hint)
    if sl_v is not None:
        out["sl"] = sl_v
    tp1_v = _extract_line_value("TP1", src, hint=entry_hint)
    if tp1_v is not None:
        out["tp1"] = tp1_v
    tp2_v = _extract_line_value("TP2", src, hint=entry_hint)
    if tp2_v is not None:
        out["tp2"] = tp2_v
    m_rr = re.search(r"RR:\s*([0-9]+(?:\.[0-9]+)?)", src, flags=re.IGNORECASE)
    if m_rr:
        out["rr"] = float(m_rr.group(1))
    return out


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


async def full_auto_analysis(symbol: str, sender, db_path: str) -> None:
    """
    Full automatic desk analysis for a symbol when user sends symbol-only text.
    """
    _ = db_path  # Reserved for future journaling/learning hooks.
    await sender(f"🔍 Аналізую {symbol}...")
    try:
        from office_market_data import (
            fetch_atr_context,
            fetch_candles,
            fetch_funding_rate,
            fetch_key_levels,
            fetch_liquidations_proxy,
            fetch_long_short_ratio,
            fetch_open_interest,
            fetch_ote_levels,
        )
    except Exception as exc:
        await agent_say(sender, "lev", f"Не можу підняти модулі аналізу для {symbol}: {exc}")
        return

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
        return

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
    response = clean_llm_note(ask_agent("lev", system, context, max_tokens=3000))
    if response:
        lines = response.split('\n')
        lines = [l for l in lines if l.strip()]
        if len(lines) > 10:
            response = '\n'.join(lines[:10])
        parts = split_long_message(response)
        for i, part in enumerate(parts):
            await agent_say(sender, "lev", part if i == 0 else "..." + part)
            if len(parts) > 1:
                await asyncio.sleep(1.0)

        parsed = _parse_signal_levels_from_text(response)
        if parsed.get("entry_low") is not None and parsed.get("sl") is not None and (
            parsed.get("tp1") is not None or parsed.get("tp2") is not None
        ):
            candles_check = fetch_candles(symbol, "1h", 1)
            if not candles_check:
                await sender(f"{symbol} — символ не знайдено на Binance.")
                return
            direction = "LONG"
            up = response.upper()
            if "SHORT" in up or "ШОРТ" in up:
                direction = "SHORT"
            elif "LONG" in up or "ЛОНГ" in up:
                direction = "LONG"
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
                status="ACTIVE",
                analysis_note=response,
            )
            await agent_say(
                sender,
                "olesya",
                f"Сигнал {symbol} {direction} зафіксовано в журнал. Моніторинг активовано 24/7.",
            )
    else:
        await agent_say(sender, "lev", f"По {symbol} зараз немає повної відповіді від LLM. Спробуй ще раз через хвилину.")


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
            "Тобі 42 роки. Ти Лев — керівник офісу. "
            "Холодна голова. Відповідаєш Тетяні коротко і впевнено."
        ),
        "maks": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Тобі 38 років. Ти Макс — ринковий аналітик. Бачиш ринок через цифри. Відповідаєш по суті."
        ),
        "marichka": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Тобі 26 років. Ти Марічка — аналітик тренду. Говориш образно і просто."
        ),
        "daryna": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Тобі 34 роки. Ти Дарина — захищаєш капітал. Пряма і чесна. "
            "Якщо питають про відкриті позиції, PnL або статистику — скажи чесно: "
            "'Зараз немає доступу до даних в цьому режимі. Перевір в Mini App.'"
        ),
        "marko": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Тобі 29 років. Ти Марко — технічний виконавець. Точний."
        ),
        "news": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Тобі 31 рік. Ти Назар — стежиш за новинами. Обережний."
        ),
        "olesya": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Ти Олеся — ведеш журнал. Тепла і точна. "
            "Якщо питають про відкриті позиції, PnL або статистику — скажи чесно: "
            "'Зараз немає доступу до даних в цьому режимі. Перевір в Mini App.'"
        ),
        "memory": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Ти Софія — знаєш історію угод. Говориш тільки фактами з журналу. "
            "Якщо питають про відкриті позиції, PnL або статистику — скажи чесно: "
            "'Зараз немає доступу до даних в цьому режимі. Перевір в Mini App.'"
        ),
        "psych": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Тобі 45 років. Ти Віктор. "
            "Психолог команди. "
            "Знаєш що кожна людина торгує своїми грошима — для когось це $100, для когось $100,000. "
            "Сума не важлива — важливий стан. "
            "Говориш рідко але влучно. "
            "Після збитків — зупиняєш від форсу. "
            "Перед великим входом — підтримуєш. "
            "Після WIN серій — нагадуєш про дисципліну. "
            "Бачиш коли людина в стресі і реагуєш. "
            "Говориш тільки українською. "
            "Без таблиць."
        ),
        "dev": (
            f"{LEV_RULE}"
            f"{language_block}\n"
            "Ти Артем — технічний девелопер. Відповідаєш про систему."
        ),
    }

    market_context = ""
    low = str(text or "").lower()
    if any(w in low for w in ("btc", "біток", "ринок", "ціна", "тренд", "сигнал", "позиція")):
        try:
            from office_market_data import fetch_candles, fetch_liquidations_proxy

            symbols = extract_symbols(text)
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
    answer_system = (
        f"{personalities.get(chosen_agent, personalities['lev'])}\n\n"
        "Ти в Telegram груповому чаті офісу. Без таблиць, без ## заголовків.\n"
        "Звертайся до Тетяни по імені. Відповідай природно як людина."
    )
    free_chat_tokens = 800 if chosen_agent == "lev" else 2000
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


async def run() -> None:
    print("=== AI Office Wizard ===")
    cfg_path = relay_config_path()
    cfg = load_relay_config()
    print(f"[relay] config file: {cfg_path.resolve()}")

    force_setup = os.getenv("RELAY_FORCE_SETUP", "").strip() == "1"
    interactive = os.getenv("RELAY_INTERACTIVE", "").strip() == "1"
    has_saved = bool(cfg.get("tg_api_id") and cfg.get("tg_api_hash") and cfg.get("main_chat_id") and cfg.get("office_chat_id"))
    if has_saved and not force_setup and interactive:
        ans = input("Знайдено збережені налаштування. Використати їх? (Y/n): ").strip().lower()
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
    tg_bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not api_id_raw:
        api_id_raw = input("TG_API_ID: ").strip()
    if not api_hash:
        api_hash = input("TG_API_HASH: ").strip()

    api_id = int(api_id_raw)
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
        except FloodWaitError as exc:
            wait_sec = int(getattr(exc, "seconds", 0) or 0)
            if wait_sec <= 0:
                wait_sec = 300
            wait_sec += 5
            print(f"[relay][WARN] FloodWait під час авторизації. Чекаю {wait_sec}с і пробую знову...")
            await asyncio.sleep(wait_sec)
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
    if force_setup or not (main_raw and office_raw):
        main_chat_id, office_chat_id = await pick_chats(client)
    else:
        repick = os.getenv("RELAY_REPICK_CHATS", "").strip() == "1"
        if interactive and not repick:
            reuse = input(
                f"MAIN/OFFICE з конфігу:\n- MAIN={main_raw}\n- OFFICE={office_raw}\n"
                "Залишити як є? (Y/n): "
            ).strip().lower()
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

    general_thread_id = int(os.getenv("OFFICE_GENERAL_THREAD_ID", "0") or "0") or None
    tasks_thread_id = int(os.getenv("OFFICE_TASKS_THREAD_ID", "0") or "0") or None
    tech_thread_id = int(os.getenv("OFFICE_TECH_THREAD_ID", "0") or "0") or None

    def _thread_for_stream(stream: str) -> Optional[int]:
        s = str(stream or "general").strip().lower()
        if s == "tasks":
            return tasks_thread_id or general_thread_id
        if s == "tech":
            return tech_thread_id or general_thread_id
        return general_thread_id

    async def send_office(
        message: str,
        reply_to_message_id: Optional[int] = None,
        stream: str = "general",
    ) -> Optional[int]:
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
                sym_for_btn = _extract_first_usdt_symbol(text_part)
                if sym_for_btn and sym_for_btn != "BTCUSDT":
                    mini_base = os.getenv("OFFICE_MINI_PUBLIC_URL", "https://ai-office-miniapp.onrender.com").strip().rstrip("/")
                    mini_url = f"{mini_base}/?symbol={sym_for_btn}&filterSymbol={sym_for_btn}"
                    btn_markup = {"inline_keyboard": [[{"text": "📊 Графік", "url": mini_url}]]}
            token = agent_bot_tokens.get(agent_key or "")
            if token:
                try:
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
                )
                if ok:
                    return msg_id
                print(f"[relay][WARN] fallback bot-send failed: {reason} (trying Telethon client)")
            sent = await client.send_message(office_entity, text_part[:3900], reply_to=reply_to)
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

    try:
        await send_office("Офіс на зв'язку. Готові працювати.")
        print("[relay] startup ping sent to OFFICE")

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
                await send_office(fmt_agent_line("dev", polish_agent_message(health_plain)), stream="tech")
                print("[relay] tech health (Artem) sent -> TECH thread")
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
            news_api_key = input("NEWS_API_KEY (optional, Enter to skip): ").strip()
        else:
            # Silent mode: keep last saved key without prompting.
            news_api_key = str(cfg.get("news_api_key", "") or "").strip()
    elif interactive and not force_setup:
        ans = input("NEWS_API_KEY знайдено у збережених налаштуваннях. Використати? (Y/n): ").strip().lower()
        if ans and ans not in ("y", "yes", "д", "так"):
            news_api_key = input("NEWS_API_KEY (optional, Enter to skip): ").strip()

    cfg["news_api_key"] = news_api_key
    save_relay_config(cfg)

    last_desk_qa_mono = 0.0
    last_main_fingerprint_by_msg: Dict[int, str] = {}

    @client.on(events.NewMessage())
    async def on_message(event):  # type: ignore[no-redef]
        try:
            nonlocal last_source_msg_id
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
                if low.startswith("/chart") or low.startswith("!chart") or low.startswith("графік"):
                    sym = _extract_first_usdt_symbol(text) or "BTCUSDT"
                    mini_base = os.getenv("OFFICE_MINI_PUBLIC_URL", "https://ai-office-miniapp.onrender.com").strip().rstrip("/")
                    mini_url = f"{mini_base}/?symbol={sym}&filterSymbol={sym}"
                    tv_url = f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{sym}"
                    await send_office(f"Графік {sym}:\nMini App: {mini_url}\nTV: {tv_url}")
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
            kickoff_msg_id = await send_office(build_signal_kickoff(sig.symbol, sig.direction))
            mirror_msg_id = await send_office(
                "🔔 Новий сигнал від My Crypto Scanner:\n"
                f"{text[:3800]}",
                reply_to_message_id=kickoff_msg_id,
            )
            print("[relay] mirror sent")
            thread_root_id = mirror_msg_id or kickoff_msg_id

            async def sender(msg: str) -> None:
                await send_office(msg[:3900], reply_to_message_id=thread_root_id)

            verdict = await office_handle_signal(sender=sender, signal=sig, db_path=db_path)
            if verdict.action == "ENTER":
                recurring = journal_recurring_mistakes(db_path, lookback_losses=60, min_count=2)
                if recurring:
                    hints = journal_learning_hints_from_tags(recurring)[:3]
                    await send_office(
                        "Нагадування перед входом (з минулих помилок):\n"
                        + "\n".join(f"- {h}" for h in hints),
                        stream="tasks",
                    )
                active_positions[sig.signal_id] = ActivePosition(
                    signal_id=sig.signal_id,
                    symbol=sig.symbol,
                    direction=sig.direction,
                    opened_ts=time.time(),
                    stage=0,
                    initial_volatility_pct=float(sig.meta.get("volatility_pct", 0.0)),
                    initial_news_risk=str(sig.meta.get("news_risk", "SAFE")),
                )
                setup_tag = detect_setup_type(sig)
                journal_open_trade(
                    db_path,
                    trade_id=sig.signal_id,
                    symbol=sig.symbol,
                    direction=sig.direction,
                    entry_price=(float(sig.meta.get("entry_price")) if sig.meta.get("entry_price") else None),
                    stop_loss=(float(sig.meta.get("stop_loss")) if sig.meta.get("stop_loss") else None),
                    take_profit=(float(sig.meta.get("take_profit")) if sig.meta.get("take_profit") else None),
                    setup_name=setup_tag,
                    timeframe="auto",
                    entry_reason="Desk ENTER after agent chain",
                    context={
                        "setup_type": setup_tag,
                        "session": sig.session,
                        "regime": sig.regime,
                        "score": sig.score,
                    },
                )
                signal_upsert(
                    db_path,
                    signal_id=sig.signal_id,
                    symbol=sig.symbol,
                    direction=sig.direction,
                    entry_low=(float(sig.meta.get("entry_price")) if sig.meta.get("entry_price") else None),
                    entry_high=(float(sig.meta.get("entry_price")) if sig.meta.get("entry_price") else None),
                    sl=(float(sig.meta.get("stop_loss")) if sig.meta.get("stop_loss") else None),
                    tp1=(float(sig.meta.get("take_profit")) if sig.meta.get("take_profit") else None),
                    tp2=None,
                    rr=(float(sig.meta.get("rr")) if sig.meta.get("rr") else None),
                    status="ACTIVE",
                    analysis_note=str(verdict.summary or ""),
                )
                await agent_say(
                    sender,
                    "olesya",
                    f"Сигнал {sig.symbol} {sig.direction} зафіксовано. Стежу 24/7.",
                )
                await office_position_event(
                    sender=sender,
                    symbol=sig.symbol,
                    event_type="PRICE_UPDATE",
                    details="Позицію відкрито. Моніторинг активовано (24/7).",
                    db_path=db_path,
                )
            print("[relay] office_handle_signal done")
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
                        await send_office(msg[:3900])

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
                            await send_office(f"⚙️ *Марко «Алгоритм»:*\nРішення: частково закрити 50% по {p.symbol}.")
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
                            await send_office(f"⚙️ *Марко «Алгоритм»:*\nРішення: перенести SL в беззбиток по {p.symbol}.")
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
                        await send_office(f"⚙️ *Марко «Алгоритм»:*\nРішення: частково закрити 50% по {p.symbol}.")
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
                        await send_office(f"⚙️ *Марко «Алгоритм»:*\nРішення: перенести SL в беззбиток по {p.symbol}.")
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
                        await send_office(
                            f"STOP REVIEW по {p.symbol}: {review_note}\n"
                            f"Теги: {', '.join(tags)}"
                        )
                        active_positions.pop(sig_id, None)
            except Exception as exc:
                print(f"[relay][ERROR] monitor_positions failed: {exc}")
            await asyncio.sleep(30)

    asyncio.create_task(monitor_positions())

    async def monitor_news() -> None:
        nonlocal last_news_level
        http_timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=http_timeout) as session:
            while True:
                try:
                    risk = await fetch_news_risk(session, news_api_key)
                    if risk.level != last_news_level:
                        async def sender(msg: str) -> None:
                            await send_office(msg[:3900], stream="tech")
                        await office_news_trigger(
                            sender=sender,
                            risk_level=risk.level,  # type: ignore[arg-type]
                            headline=risk.headline,
                            minutes_to_event=risk.minutes_to_event,
                            db_path=db_path,
                        )
                        print(f"[relay] news trigger -> {risk.level} ({risk.minutes_to_event}m)")
                        last_news_level = risk.level
                except Exception as exc:
                    print(f"[relay][WARN] monitor_news failed: {type(exc).__name__}: {exc}")
                    await send_office(f"Технічне попередження news-монітора: {exc}", stream="tech")
                await asyncio.sleep(120)

    asyncio.create_task(monitor_news())

    async def proactive_market_scan() -> None:
        """
        Кожні 15 хвилин агенти самі сканують ринок і якщо знаходять сетап —
        пишуть Тетяні першими.
        """
        try:
            utc_now = datetime.now(timezone.utc)
            h = utc_now.hour
            m = utc_now.minute
            minute_of_day = h * 60 + m
            in_london = 480 <= minute_of_day < 660
            in_ny = 780 <= minute_of_day < 960
            print(f"[scanner] tick UTC={utc_now.hour}:{utc_now.minute} in_ny={in_ny} in_london={in_london}")
            if not (in_london or in_ny):
                return  # поза Kill Zone — мовчимо

            from office_market_data import (
                fetch_atr_context,
                fetch_candles,
                fetch_funding_rate,
                fetch_key_levels,
                fetch_liquidations_proxy,
                fetch_long_short_ratio,
                fetch_ote_levels,
                fetch_open_interest,
                fetch_top_movers,
            )

            EXCLUDED_FROM_SCANNER = {"BTCUSDT", "ETHUSDT"}
            gainers = fetch_top_movers("gainers", 5)
            losers = fetch_top_movers("losers", 5)
            always_watch: List[str] = []

            candidates = always_watch.copy()
            combined = (gainers or []) + (losers or [])
            for m_item in combined:
                sym = str((m_item or {}).get("symbol") or "").upper().strip() if isinstance(m_item, dict) else ""
                if sym and sym not in candidates:
                    candidates.append(sym)

            setups_found: List[Dict[str, Any]] = []
            for symbol in candidates[:8]:
                try:
                    if symbol in EXCLUDED_FROM_SCANNER:
                        continue
                    last_ts = float(_last_signal_time.get(symbol, 0.0) or 0.0)
                    if (time.time() - last_ts) < 7200:
                        continue
                    _last_signal_time[symbol] = time.time()
                    if symbol == "BTCUSDT" and any("BTC" in str(s.get("symbol") or "") for s in setups_found):
                        continue
                    atr = fetch_atr_context(symbol)
                    atr_used = float((atr or {}).get("day_used_pct", 100) or 100)
                    if atr_used > 85:
                        continue

                    ls = fetch_long_short_ratio(symbol)
                    funding = fetch_funding_rate(symbol)
                    ote = fetch_ote_levels(symbol, "1h")
                    levels = fetch_key_levels(symbol)

                    funding_pct = float((funding or {}).get("funding_rate_pct", 0) or 0)
                    ls_ratio = float((ls or {}).get("current_ratio", 1) or 1)

                    has_setup = False
                    setup_direction = ""
                    if funding_pct < -0.005 or ls_ratio < 0.8:
                        has_setup = True
                        setup_direction = "LONG"
                    elif funding_pct > 0.01 or ls_ratio > 2.5:
                        has_setup = True
                        setup_direction = "SHORT"

                    if has_setup:
                        setups_found.append(
                            {
                                "symbol": symbol,
                                "direction": setup_direction,
                                "atr_used": atr.get("day_used_pct") if isinstance(atr, dict) else atr_used,
                                "funding": funding_pct,
                                "ls_ratio": ls_ratio,
                                "ote": ote,
                                "levels": levels,
                                "atr": atr,
                            }
                        )
                except Exception:
                    continue

            if not setups_found:
                return

            best = min(setups_found, key=lambda x: float(x.get("atr_used") or 100))
            symbol = str(best.get("symbol") or "BTCUSDT")
            direction = str(best.get("direction") or "LONG")
            liq_now = fetch_liquidations_proxy(symbol)
            oi_now = fetch_open_interest(symbol)
            candles_h1 = fetch_candles(symbol, "1h", 6)
            candles_h4 = fetch_candles(symbol, "4h", 6)
            current_price = liq_now.get("current_price") if isinstance(liq_now, dict) else None
            news_risk = "SAFE"
            news_mins = 999
            news_event_name = "подія"
            news_kyiv_time = ""
            if news_api_key:
                try:
                    timeout_news = aiohttp.ClientTimeout(total=10)
                    async with aiohttp.ClientSession(timeout=timeout_news) as s_news:
                        n = await fetch_news_risk(s_news, news_api_key)
                        news_risk = str(n.level)
                        news_mins = int(n.minutes_to_event)
                        news_event_name = str(n.event_name or n.headline or "подія")
                        if news_mins >= 0:
                            kyiv_now = datetime.now(timezone.utc) + timedelta(hours=3)
                            news_kyiv_time = (kyiv_now + timedelta(minutes=news_mins)).strftime("%H:%M")
                except Exception:
                    pass
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
                msg = fmt_agent_line(agent_key, text)
                await send_office(msg[:3800], stream="general")

            await _send_agent_turn("lev", f"Тетяно, бачу сетап 👀\n{direction} {symbol} — команда, аналіз.")
            await asyncio.sleep(1.5)

            maks_ctx = (
                f"Символ: {symbol}\nНапрямок: {direction}\nПоточна ціна: {current_price}\n"
                f"OI: {oi_now}\nFunding: {best.get('funding')}%\nL/S: {best.get('ls_ratio')}\n"
                f"Ліквідації: {liq_now}"
            )
            maks_msg = clean_llm_note(
                ask_agent(
                    "maks",
                    "Ти Макс. Дай коротко ринкові дані: OI/funding/liquidations і висновок по імпульсу. Українською.",
                    maks_ctx,
                    max_tokens=600,
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
                    "Ти Марічка. Дай bias по H4/Daily, коротко і чітко. Українською.",
                    mar_ctx,
                    max_tokens=600,
                )
            )
            mar_msg = _trim_lines(mar_msg, 4)
            await _send_agent_turn("marichka", mar_msg or "На H4/Daily структура підтверджує поточний напрямок.")
            await asyncio.sleep(1.5)

            news_msg = (
                "Новинний фон чистий. Входити можна."
                if news_mins >= 999
                else (
                    f"Увага! {news_event_name} через {news_mins} хв "
                    f"о {news_kyiv_time or 'за Києвом'} за Києвом."
                )
            )
            news_msg = _trim_lines(news_msg, 3)
            await _send_agent_turn("news", news_msg or "Новинний фон керований, критичних тригерів поруч немає.")
            await asyncio.sleep(1.5)

            daryna_ctx = (
                f"Символ: {symbol}\nНапрямок: {direction}\nATR: {best.get('atr')}\n"
                f"Live risk snapshot: {risk_snapshot}\nНовини: {news_risk}"
            )
            daryna_msg = clean_llm_note(
                ask_agent(
                    "daryna",
                    "Ти Дарина. Дай ризик-висновок і вето/допуск коротко, українською.",
                    daryna_ctx,
                    max_tokens=600,
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
                    "Ти Марко. Дай конкретний execution-план: Entry/SL/TP1/TP2/RR + що робити зараз. Українською.",
                    marko_ctx,
                    max_tokens=700,
                )
            )
            marko_msg = _trim_lines(marko_msg, 5)
            await _send_agent_turn("marko", marko_msg or f"ЩО РОБИТИ ЗАРАЗ (ціна {current_price}): чекаємо підтвердження в зоні Entry.")
            await asyncio.sleep(1.5)

            team_pack = (
                f"Макс: {maks_msg}\n"
                f"Марічка: {mar_msg}\n"
                f"Назар: {news_msg}\n"
                f"Дарина: {daryna_msg}\n"
                f"Марко: {marko_msg}\n"
                f"Символ: {symbol}\nНапрямок: {direction}\nЦіна: {current_price}\n"
                f"Активні сигнали: {active_signals}\n"
                "Якщо по цьому символу вже є активний — дай UPDATE а не новий сигнал."
            )
            lev_final_system = (
                f"{LEV_RULE}"
                "Ти Лев. На базі реплік команди дай фінальне рішення: ВХІД/ЧЕКАЄМО/ПРОПУСК і чіткий next action. Українською."
            )
            lev_final = clean_llm_note(
                ask_agent(
                    "lev",
                    lev_final_system,
                    team_pack,
                    max_tokens=300,
                )
            )
            lev_final = _trim_lines(lev_final, 7)
            await _send_agent_turn("lev", lev_final or "Рішення: чекаємо відкату в Entry-зону. Якщо не дійде — пропускаємо.")

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
                status="ACTIVE",
                analysis_note=lev_final or "",
            )
        except Exception as e:
            print(f"[scanner] error: {e}")

    async def monitor_proactive_scanner() -> None:
        while True:
            await proactive_market_scan()
            await asyncio.sleep(3600)

    asyncio.create_task(monitor_proactive_scanner())

    async def monitor_active_signals() -> None:
        from office_market_data import (
            fetch_liquidations_proxy,
            fetch_candles,
        )
        _ = fetch_candles
        def _allow_notify(sym: str, event: str) -> bool:
            key = f"{str(sym or '').upper()}::{event}"
            now_ts = time.time()
            last_ts = float(_last_notified.get(key, 0.0) or 0.0)
            if (now_ts - last_ts) < 1800:
                return False
            _last_notified[key] = now_ts
            return True

        def _lev_msg(sym: str, happened: str, action_now: str, sl_after: str) -> str:
            return (
                f"Тетяно, {sym}: {happened}\n"
                f"Що робити зараз: {action_now}\n"
                f"SL після дії: {sl_after}"
            )
        while True:
            try:
                active_rows = signal_get_active(db_path)
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
                        if not signal_id or not symbol:
                            continue

                        now_utc = datetime.now(timezone.utc)
                        try:
                            created_dt = datetime.fromisoformat(ts_created.replace("Z", "+00:00"))
                            if created_dt.tzinfo is None:
                                created_dt = created_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            created_dt = now_utc

                        if status == "ACTIVE" and (now_utc - created_dt).total_seconds() > 4 * 3600:
                            signal_update(db_path, signal_id=signal_id, status="EXPIRED", outcome="EXPIRED")
                            continue

                        liq_now = fetch_liquidations_proxy(symbol)
                        current_price = float((liq_now or {}).get("current_price") or 0.0) if isinstance(liq_now, dict) else 0.0
                        if current_price <= 0:
                            continue

                        e_low = float(entry_low) if entry_low is not None else None
                        e_high = float(entry_high) if entry_high is not None else None
                        sl_v = float(sl) if sl is not None else None
                        tp1_v = float(tp1) if tp1 is not None else None
                        tp2_v = float(tp2) if tp2 is not None else None

                        if status == "ACTIVE" and e_low is not None and e_high is not None and e_low <= current_price <= e_high:
                            signal_update(db_path, signal_id=signal_id, status="HIT_ENTRY")
                            if _allow_notify(symbol, "HIT_ENTRY"):
                                await send_office(
                                    f"Тетяно, {symbol} досяг зони входу {e_low}-{e_high}. "
                                    f"Зараз {current_price}. Можна входити. SL: {sl_v} TP1: {tp1_v}",
                                    stream="general",
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
                                if _allow_notify(symbol, "HIT_TP1"):
                                    be_txt = f"{be_level:.6f}" if isinstance(be_level, (int, float)) else "BE"
                                    lev_note = _lev_msg(
                                        symbol,
                                        f"ціна досягла TP1 {tp1_v}",
                                        f"фіксуй 50%, перенеси SL у BE, решту тримай до TP2 {tp2_v}",
                                        be_txt,
                                    )
                                    await send_office(lev_note, stream="general")
                                continue

                        if status == "HIT_ENTRY" and e_low is not None and e_high is not None and e_low <= current_price <= e_high:
                            if _allow_notify(symbol, "ADD_ON"):
                                add_note = _lev_msg(
                                    symbol,
                                    f"ціна повернулась в entry-зону {e_low}-{e_high}",
                                    "можливий добір позиції малим обсягом у зоні",
                                    f"{sl_v}",
                                )
                                await send_office(add_note, stream="general")

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
                                    if (rev_long or rev_short) and _allow_notify(symbol, "REVERSAL_WARN"):
                                        rev_note = _lev_msg(
                                            symbol,
                                            f"4H свічка дала розворот {change_pct:+.2f}% після TP1",
                                            "розглянь фіксацію ще 50% поки в плюсі",
                                            f"{sl_v}",
                                        )
                                        await send_office(rev_note, stream="general")

                        if status in ("ACTIVE", "HIT_ENTRY", "HIT_TP1") and sl_v is not None:
                            hit_sl = (direction == "LONG" and current_price <= sl_v) or (
                                direction == "SHORT" and current_price >= sl_v
                            )
                            if hit_sl:
                                analysis_note = ""
                                try:
                                    n_risk = "SAFE"
                                    if news_api_key:
                                        timeout_news = aiohttp.ClientTimeout(total=10)
                                        async with aiohttp.ClientSession(timeout=timeout_news) as s_news:
                                            n = await fetch_news_risk(s_news, news_api_key)
                                            n_risk = str(n.level)
                                    system = (
                                        f"{LEV_RULE}"
                                        "Аналізуй чому вибило стоп. Перевір:\n"
                                        "1) Чи були новини в цей момент?\n"
                                        "2) Чи була маніпуляція (sweep)?\n"
                                        "3) Чи правильна була точка входу?\n"
                                        "4) Яка сесія була активна?\n"
                                        "5) Що можна покращити наступного разу?\n"
                                        "Говориш українською. Конкретно."
                                    )
                                    hour = now_utc.hour
                                    sess = "LONDON" if 8 <= hour < 11 else ("NEW_YORK" if 13 <= hour < 16 else "OFF_HOURS")
                                    context = (
                                        f"Сигнал: {direction} {symbol}\n"
                                        f"Entry: {e_low}-{e_high}\n"
                                        f"SL: {sl_v}\n"
                                        f"Час сигналу: {ts_created}\n"
                                        f"Час вибивання: {now_utc.isoformat()}\n"
                                        f"Поточна ціна: {current_price}\n"
                                        f"Новинний ризик зараз: {n_risk}\n"
                                        f"Сесія: {sess}"
                                    )
                                    analysis_note = clean_llm_note(ask_agent("lev", system, context, max_tokens=200))
                                    analysis_note = _trim_lines(analysis_note, max_lines=6)
                                except Exception:
                                    analysis_note = ""
                                signal_update(db_path, signal_id=signal_id, status="HIT_SL", outcome="LOSS", analysis_note=analysis_note)
                                if _allow_notify(symbol, "HIT_SL"):
                                    stop_note = _lev_msg(
                                        symbol,
                                        f"SL перебитий на {sl_v}, структура зламана",
                                        "повний вихід з позиції зараз",
                                        "позиція закрита",
                                    )
                                    await send_office(stop_note, stream="general")
                                    if analysis_note:
                                        for part in split_long_message(analysis_note):
                                            await send_office(part, stream="general")
                                continue

                        if status in ("ACTIVE", "HIT_ENTRY", "HIT_TP1") and tp2_v is not None:
                            hit_tp2 = (direction == "LONG" and current_price >= tp2_v) or (
                                direction == "SHORT" and current_price <= tp2_v
                            )
                            if hit_tp2:
                                signal_update(db_path, signal_id=signal_id, status="HIT_TP2", outcome="WIN")
                                if _allow_notify(symbol, "HIT_TP2"):
                                    await send_office(
                                        f"{symbol} досяг TP2 {tp2_v} 🎯\nВідмінний результат! Фіксуємо і шукаємо наступний сетап.",
                                        stream="general",
                                    )
                                continue
                    except Exception as exc_row:
                        print(f"[signals] row monitor failed: {exc_row}")
            except Exception as exc:
                print(f"[signals] monitor failed: {exc}")
            await asyncio.sleep(1800)

    asyncio.create_task(monitor_active_signals())

    async def morning_macro_brief() -> None:
        """
        Daily 09:00 Kyiv macro briefing from Maks (LLM + live macro data).
        """
        try:
            from office_market_data import fetch_macro_context

            macro = fetch_macro_context()
            system = (
                "Ти Макс, ранковий макро-аналітик трейдинг-офісу. "
                "Пишеш ТІЛЬКИ українською, просто і конкретно. "
                "Завдання: коротко пояснити що зараз роблять DXY, S&P500, золото, BTC і що це означає для ризику по крипті сьогодні. "
                "Формат Telegram: 4-7 коротких речень, без таблиць, без markdown-заголовків."
            )
            context = (
                "Ранковий макро-зріз (live):\n"
                f"{json.dumps(macro, ensure_ascii=False)}\n"
                "Дай практичний висновок для команди: risk-on / risk-off / mixed і як діяти з ризиком."
            )
            response = clean_llm_note(ask_agent("maks", system, context, max_tokens=300))
            await send_office(response or "Ранковий макро-зріз тимчасово недоступний.", stream="general")
        except Exception as exc:
            print(f"[relay][WARN] morning_macro_brief failed: {type(exc).__name__}: {exc}")
            await send_office(f"Технічне попередження macro-brief: {exc}", stream="tech")

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
                    async with aiohttp.ClientSession(timeout=http_timeout) as http:
                        btc = await fetch_binance_futures_ticker(http, "BTCUSDT")
                        regime = "CHOP" if float(btc.get("volatility_pct", 0.0)) >= 6.0 else "TREND"
                        sess = _session_label_from_hour(h)

                        async def sender_m(msg: str) -> None:
                            await send_office(msg[:3900])

                        await office_morning_briefing(
                            sender_m,
                            session=sess,
                            market_state=regime,
                            btc_bias=f"{float(btc.get('pct', 0.0)):+.2f}%",
                        )
                    last_morning_date = today
                    print("[relay] auto morning briefing sent")

                if h == eh and mi == em and last_evening_date != today:
                    report = build_daily_journal_report(db_path)
                    summary = "\n".join(report.split("\n")[:4]).strip()
                    async with aiohttp.ClientSession(timeout=http_timeout) as http:
                        btc = await fetch_binance_futures_ticker(http, "BTCUSDT")
                        btc_pct = float(btc.get("pct", 0.0))

                        async def sender_e(msg: str) -> None:
                            await send_office(msg[:3900])

                        await office_evening_debrief(
                            sender_e,
                            btc_change_pct=btc_pct,
                            journal_summary=summary,
                        )
                    last_evening_date = today
                    print("[relay] auto evening debrief sent")
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
                    await send_office("📆 Тижневий розбір (ролінг 7д):\n" + report[:3600])
                    last_week_key = week_key
                    print("[relay] weekly journal report sent")
            except Exception as exc:
                print(f"[relay][WARN] monitor_weekly_review failed: {exc}")
            await asyncio.sleep(45)

    asyncio.create_task(monitor_weekly_review())

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
                    await send_office(
                        "⚖️ Risk committee:\n"
                        f"За сьогодні LOSS: {day_losses} (поріг {need_day}). "
                        f"Серія SL підряд у журналі: {streak} (поріг {need_streak}).\n"
                        "Короткий обов’язковий розбір: що повторюється, де форс, що вимкнути до завтра."
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
        http_timeout = aiohttp.ClientTimeout(total=12)
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
                    await send_office(
                        f"📈 Funding alert (BTC): |{float(fr):.4f}|% ≥ {fund_thr:.4f}% — перевірити bias/перекіс перед новими входами.",
                        stream="tech",
                    )
                    last_fund_mono = now_m
                vol = float(btc.get("volatility_pct") or 0.0)
                if vol >= atr_thr and (now_m - last_atr_mono) >= cooldown:
                    await send_office(
                        f"📉 ATR/волатильність (BTC 24h range): {vol:.2f}% ≥ {atr_thr:.2f}% — зменшити агресію, більше фільтрації.",
                        stream="tech",
                    )
                    last_atr_mono = now_m
            except Exception as exc:
                print(f"[relay][WARN] monitor_funding_atr_alerts failed: {exc}")
            await asyncio.sleep(int(os.getenv("OFFICE_MARKET_ALERT_POLL_SEC", "180") or "180"))

    asyncio.create_task(monitor_funding_atr_alerts())

    async def monitor_daily_report() -> None:
        nonlocal last_daily_report_date
        while True:
            try:
                now_local = datetime.now()
                today = now_local.strftime("%Y-%m-%d")
                if now_local.hour >= 22 and last_daily_report_date != today:
                    report = build_daily_journal_report(db_path)
                    await send_office(report, stream="tasks")
                    last_daily_report_date = today
                    print("[relay] daily journal report sent")
            except Exception as exc:
                print(f"[relay][WARN] monitor_daily_report failed: {exc}")
                await send_office(f"Технічне попередження daily-report: {exc}", stream="tech")
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
        await client.run_until_disconnected()
    except Exception as e:
        now_ts = time.time()
        if now_ts - _last_alert_ts >= 300:
            _last_alert_ts = now_ts
            try:
                await send_office(
                    f"⚠️ Relay впав: {type(e).__name__}: {str(e)[:200]}"
                    f"\nАвтоперезапуск через 30 сек..."
                )
            except Exception as alert_exc:
                print(f"[relay][WARN] crash alert send failed: {alert_exc}")
        await asyncio.sleep(30)
        raise
    finally:
        await bot_http.close()


if __name__ == "__main__":
    asyncio.run(run())

