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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

from office_bridge import (
    OfficeSignal,
    get_agent_card_text,
    init_office_db,
    journal_close_trade,
    journal_learning_hints_from_tags,
    journal_open_trade,
    journal_recurring_mistakes,
    office_desk_user_question,
    office_handle_signal,
    office_news_trigger,
    office_position_event,
    office_run_scenario,
    office_trade_closed,
    _extract_first_usdt_symbol,
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


def load_agent_bot_tokens() -> Dict[str, str]:
    """
    Optional multi-bot mode via env vars:
    AGENT_BOT_TOKEN_LEV, AGENT_BOT_TOKEN_MAKS, AGENT_BOT_TOKEN_DARYNA,
    AGENT_BOT_TOKEN_MARKO, AGENT_BOT_TOKEN_OLESYA, AGENT_BOT_TOKEN_NEWS
    """
    keys = ("lev", "maks", "news", "daryna", "marko", "olesya")
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
    return None


async def send_via_bot_api(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: int,
    text: str,
) -> tuple[bool, str]:
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
    try:
        async with session.post(url, json=payload) as resp:
            body = await resp.json()
            if resp.status != 200:
                return False, f"http {resp.status}: {body}"
            if not bool(body.get("ok")):
                desc = str((body or {}).get("description") or body)
                return False, f"telegram: {desc}"
            return True, "ok"
    except Exception as exc:
        return False, f"exception: {exc}"


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


def _parse_scenario_command(text: str) -> Optional[str]:
    s = (text or "").strip()
    low = s.lower()
    for p in ("!scenario", "/scenario"):
        if low.startswith(p):
            return s[len(p) :].strip().lower()
    return None


def build_signal_kickoff(symbol: str, direction: str) -> str:
    intros = [
        "Друзі, новий сигнал. До роботи!",
        "Командо, маємо свіжий сигнал. Розбираємо спокійно.",
        "Увага офіс: зайшов новий кейс, беремо в роботу.",
        "БКХ, новий сигнал на столі. Працюємо по плану.",
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

    out: Dict[str, Any] = {
        "btc_change_pct": btc["pct"],
        "sym_change_pct": alt["pct"],
        "quote_volume_usdt": alt["quote_volume_usdt"],
        "volatility_pct": alt["volatility_pct"],
        "rr_hint": 2.0,
        "score_hint": max(8, min(18, score_hint)),
        "session": "LONDON",
        "regime": regime,
        "news_risk": "SAFE",
        "minutes_to_event": 999,
    }
    if gold:
        out["gold_symbol"] = str(gold.get("symbol", ""))
        out["gold_change_pct"] = float(gold.get("pct", 0.0))
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
        return NewsRisk("SAFE", "news api key missing", 999)
    now = datetime.now(timezone.utc)
    from_s = now.strftime("%Y-%m-%d")
    to_s = from_s
    url = "https://financialmodelingprep.com/stable/economic-calendar"
    params = {"from": from_s, "to": to_s, "apikey": api_key}
    async with session.get(url, params=params) as resp:
        if resp.status != 200:
            return NewsRisk("SAFE", f"news status {resp.status}", 999)
        data = await resp.json()
    nearest_min = 999
    nearest_title = "no high impact events"
    keys = ("fomc", "fed", "rate", "cpi", "nfp", "powell", "inflation")
    for e in (data if isinstance(data, list) else []):
        title = str(e.get("event") or e.get("title") or "")
        if not title:
            continue
        impact = str(e.get("impact") or e.get("importance") or "").lower()
        is_high = ("high" in impact) or any(k in title.lower() for k in keys)
        if not is_high:
            continue
        dt = _parse_dt_any(str(e.get("date") or e.get("time") or ""))
        if dt is None:
            continue
        mins = int((dt - now).total_seconds() / 60)
        if 0 <= mins < nearest_min:
            nearest_min = mins
            nearest_title = title
    if nearest_min <= 60:
        return NewsRisk("HIGH RISK", nearest_title, nearest_min)
    if nearest_min <= 180:
        return NewsRisk("RISK", nearest_title, nearest_min)
    return NewsRisk("SAFE", nearest_title, nearest_min)


def looks_like_signal(text: str) -> bool:
    up = text.upper()
    hard_keys = ("SMART MONEY SETUP", "ВХОДЬ", "SIGNAL", "СИГНАЛ")
    if any(k in up for k in hard_keys):
        return True
    has_symbol = "USDT" in up
    has_side = ("LONG" in up) or ("SHORT" in up)
    return has_symbol and has_side


def _extract_price_hint(text: str, labels: tuple[str, ...]) -> Optional[float]:
    low = text.lower()
    for lb in labels:
        i = low.find(lb)
        if i < 0:
            continue
        window = text[i : i + 80]
        m = re.search(r"(\d+(?:[.,]\d+)?)", window)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except Exception:
                continue
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


def parse_signal(text: str, msg_id: int) -> OfficeSignal:
    symbol = "UNKNOWNUSDT"
    direction = "LONG"
    for token in text.replace("\n", " ").split():
        t = token.strip().upper()
        if t.endswith("USDT") and 4 <= len(t) <= 15:
            symbol = t
            break
    if "SHORT" in text.upper():
        direction = "SHORT"
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
    db_path = "office_bridge.db"

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
    agent_bot_tokens = load_agent_bot_tokens()
    bot_http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    if agent_bot_tokens:
        print(f"[relay] multi-bot mode enabled for: {', '.join(sorted(agent_bot_tokens.keys()))}")
    else:
        print("[relay] multi-bot mode disabled (no AGENT_BOT_TOKEN_* found)")

    async def send_office(message: str) -> None:
        agent_key = detect_agent_key(message)
        token = agent_bot_tokens.get(agent_key or "")
        if token:
            ok, reason = await send_via_bot_api(bot_http, token, office_chat_id, message)
            if ok:
                return
            print(f"[relay][WARN] bot-send failed for {agent_key}: {reason} (fallback user client)")
        await client.send_message(office_entity, message[:3900])

    try:
        await send_office("Офіс на зв'язку. Готовий ловити сигнали з MAIN чату.")
        print("[relay] startup ping sent to OFFICE")
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

    @client.on(events.NewMessage())
    async def on_message(event):  # type: ignore[no-redef]
        try:
            text = event.raw_text or ""
            if not text.strip():
                return
            src_chat_id = getattr(event, "chat_id", None)

            # OFFICE interactive desk Q&A (explicit command only -> reduces spam/chaos)
            if src_chat_id is not None and int(src_chat_id) == int(office_chat_id):
                scenario_key = _parse_scenario_command(text)
                if scenario_key is not None:
                    async def sender(msg: str) -> None:
                        await send_office(msg[:3900])
                    if not scenario_key:
                        await send_office(
                            "ℹ️ Формат: `!scenario morning` або `!scenario loss_streak`.\n"
                            "Доступні: `asia_strong, weak_skip, daryna_question, win_close, loss_streak, morning`"
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
                        await send_office(f"Не вдалося зняти ринковий зріз з Binance: {exc}")
                        return

                    gold_line = ""
                    if snap.get("gold_symbol"):
                        gold_line = (
                            f"Золото-проксі `{snap.get('gold_symbol')}` 24г `{float(snap.get('gold_change_pct', 0.0)):+.2f}%`\n"
                        )

                    await send_office(
                        "📌 Ринковий зріз (Binance USDT-M)\n"
                        f"BTCUSDT 24г `{float(snap.get('btc_change_pct', 0.0)):+.2f}%`\n"
                        f"{sym} 24г `{float(snap.get('sym_change_pct', 0.0)):+.2f}%` · "
                        f"vol `{float(snap.get('quote_volume_usdt', 0.0)):.0f}` USDT notional\n"
                        f"{gold_line}"
                        f"Оцінка ринку (діапазон HL): `{float(snap.get('volatility_pct', 0.0)):.2f}%`"
                    )

                    async def sender(msg: str) -> None:
                        await send_office(msg[:3900])

                    await office_desk_user_question(
                        sender=sender,
                        question=q,
                        symbol=sym,
                        market=snap,
                        db_path=db_path,
                    )
                    print("[relay] desk_qa done")
                return

            # Hard gate: process trading signals only from MAIN room.
            # This prevents accidental mirroring from any other dialog/log stream.
            if src_chat_id is None or int(src_chat_id) != int(main_chat_id):
                return
            if not looks_like_signal(text):
                return
            print(f"[relay] matched message id={event.id} chat_id={src_chat_id}")
            sig = parse_signal(text, event.id)
            await send_office(build_signal_kickoff(sig.symbol, sig.direction))
            await send_office(f"Отримала сигнал:\n{text[:3500]}")
            print("[relay] mirror sent")

            async def sender(msg: str) -> None:
                await send_office(msg[:3900])

            verdict = await office_handle_signal(sender=sender, signal=sig, db_path=db_path)
            if verdict.action == "ENTER":
                recurring = journal_recurring_mistakes(db_path, lookback_losses=60, min_count=2)
                if recurring:
                    hints = journal_learning_hints_from_tags(recurring)[:3]
                    await send_office(
                        "Нагадування перед входом (з минулих помилок):\n"
                        + "\n".join(f"- {h}" for h in hints)
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
                journal_open_trade(
                    db_path,
                    trade_id=sig.signal_id,
                    symbol=sig.symbol,
                    direction=sig.direction,
                    entry_price=(float(sig.meta.get("entry_price")) if sig.meta.get("entry_price") else None),
                    stop_loss=(float(sig.meta.get("stop_loss")) if sig.meta.get("stop_loss") else None),
                    take_profit=(float(sig.meta.get("take_profit")) if sig.meta.get("take_profit") else None),
                    setup_name="relay_signal",
                    timeframe="auto",
                    entry_reason="Desk ENTER after agent chain",
                    context={"session": sig.session, "regime": sig.regime, "score": sig.score},
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
                            await send_office(msg[:3900])
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
                    print(f"[relay][WARN] monitor_news failed: {exc}")
                await asyncio.sleep(120)

    asyncio.create_task(monitor_news())

    async def monitor_daily_report() -> None:
        nonlocal last_daily_report_date
        while True:
            try:
                now_local = datetime.now()
                today = now_local.strftime("%Y-%m-%d")
                if now_local.hour >= 22 and last_daily_report_date != today:
                    report = build_daily_journal_report(db_path)
                    await send_office(report)
                    last_daily_report_date = today
                    print("[relay] daily journal report sent")
            except Exception as exc:
                print(f"[relay][WARN] monitor_daily_report failed: {exc}")
            await asyncio.sleep(60)

    asyncio.create_task(monitor_daily_report())

    try:
        await client.run_until_disconnected()
    finally:
        await bot_http.close()


if __name__ == "__main__":
    asyncio.run(run())

