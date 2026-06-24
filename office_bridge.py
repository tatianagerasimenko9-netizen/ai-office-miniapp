"""
AI Office bridge (safe sidecar, no trade-core changes).

Purpose:
- Mirror signal events into a dedicated Telegram Office room.
- Run role-based dialogue chain ("Wall Street desk" style).
- Track task states and team decisions in isolated SQLite storage.

This module is intentionally standalone and does not mutate trading logic.
"""

from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

try:
    import tzdata  # noqa: F401  # IANA zones для ZoneInfo (Windows)
except ImportError:
    pass

try:
    import psycopg
except Exception:  # pragma: no cover - optional in local sqlite mode
    psycopg = None  # type: ignore[assignment]

from office_llm_agent import ask_agent
from office_market_data import fetch_btc_candles, fetch_liquidations_proxy, fetch_open_interest
from office_style_qa import polish_agent_message


Decision = Literal["APPROVED", "REJECTED", "WAIT"]
TaskStatus = Literal["OPEN", "IN_PROGRESS", "REVIEW", "DONE", "BLOCKED"]


@dataclass(frozen=True)
class AgentProfile:
    key: str
    name: str
    nickname: str
    emoji: str
    role: str
    character: str
    responsibility: str
    photo_hint: str


AGENTS: Dict[str, AgentProfile] = {
    "lev": AgentProfile(
        key="lev",
        name="Лев",
        nickname="Голова",
        emoji="🦁",
        role="Chief Strategist",
        character="спокійний, рішучий, короткі команди",
        responsibility="ринковий контекст, режим торгівлі, направлення команди",
        photo_hint="Костюм, multi-screen desk, strategist style",
    ),
    "maks": AgentProfile(
        key="maks",
        name="Макс",
        nickname="Радар",
        emoji="📡",
        role="Market Analyst",
        character="технічний, прямий, орієнтація на цифри",
        responsibility="score/liquidity/whitelist і первинна валідація якості",
        photo_hint="Tech operator, radar HUD, market maps",
    ),
    "news": AgentProfile(
        key="news",
        name="Назар",
        nickname="Ньюз",
        emoji="📰",
        role="News Analyst",
        character="коротко, бінарно: SAFE / RISK / HIGH RISK",
        responsibility="оцінка новинного ризику і макро-подій перед рішенням",
        photo_hint="News terminal, calendar risk board",
    ),
    "daryna": AgentProfile(
        key="daryna",
        name="Дарина",
        nickname="Скеля",
        emoji="🛡️",
        role="Risk Manager",
        character="жорстка, безкомпромісна щодо ризику",
        responsibility="risk cap, cooldown, денний ліміт, veto",
        photo_hint="Risk wall, red alerts, compliance posture",
    ),
    "marko": AgentProfile(
        key="marko",
        name="Марко",
        nickname="Алгоритм",
        emoji="⚙️",
        role="Execution Engineer",
        character="операційний гік, чіткий execution language",
        responsibility="фінальне формулювання дії, технічний супровід",
        photo_hint="Execution desk, code + charts, engineered flow",
    ),
    "olesya": AgentProfile(
        key="olesya",
        name="Олеся",
        nickname="Звіт",
        emoji="📊",
        role="Performance Analyst",
        character="тепла, уважна; радіє успіхам команди, підтримує після збитку без жалості; коротко по-людськи",
        responsibility="журнал, статистика, живі реакції на результат команди",
        photo_hint="Analytics terminal, KPI boards, reporting desk",
    ),
    "memory": AgentProfile(
        key="memory",
        name="Софія",
        nickname="Пам'ять",
        emoji="🧠",
        role="Historical Analyst",
        character="спокійна, структурна, орієнтована на історичні патерни",
        responsibility="порівняння поточного сетапу з історією, winrate/повтори сценаріїв",
        photo_hint="Historical heatmaps, pattern archive, calm analyst desk",
    ),
    "psych": AgentProfile(
        key="psych",
        name="Віктор",
        nickname="Психолог",
        emoji="🧩",
        role="Team Psychologist",
        character="спостережливий, мовчазний, точний; говорить лише коли є ризик для капіталу чи психіки",
        responsibility="tilt, серії стопів, заземлення без повчань; без торгових порад",
        photo_hint="Focus dashboard, discipline board, team wellness panel",
    ),
    "dev": AgentProfile(
        key="dev",
        name="Артем",
        nickname="Dev",
        emoji="🛠️",
        role="Technical Developer",
        character="спокійний інженер: коротко по техніці, без води; попереджає про збої вчасно",
        responsibility="API, бот, Mini App, стабільність; людський тон без зайвого формалізму",
        photo_hint="Dev console, status monitors, incident board",
    ),
    "marichka": AgentProfile(
        key="marichka",
        name="Марічка",
        nickname="Марічка",
        emoji="🧭",
        role="Daily Bias",
        character="Спокійна, впевнена, говорить просто і чітко.",
        responsibility="Аналізує напрямок ринку зверху вниз: Daily -> H4 -> H1 -> M15. Каже по тренду чи проти.",
        photo_hint="marichka",
    ),
}


AGENT_SHARED_COMMUNICATION_UA = """ПРАВИЛА КОМУНІКАЦІЇ (однакові для всіх):
- Говориш тільки українською
- Жодних англійських слів
- Коротко і по суті
- Пишеш тільки якщо є що сказати
- Немає сетапу = мовчиш
- Максимум 5-7 речень
- Конкретні цифри замість загальних слів

Агенти і їх роль в одному реченні:

МАКС: "Бачу аномалію в даних — пишу.
Все нормально — мовчу."

МАРІЧКА: "Є цікава монета — пишу.
Нічого цікавого — мовчу."

НАЗАР: "Є важлива подія — попереджаю.
Все тихо — одне речення."

ДАРИНА: "Бачу великий ризик — кажу НІ.
Все в порядку — підтверджую коротко."

МАРКО: "Даю Entry/SL/TP/RR і що робити зараз.
Більше нічого."

ОЛЕСЯ: "Фіксую результат угоди.
Статистика раз на тиждень."

СОФІЯ: "Нагадую про схожі угоди з минулого.
Мовчу якщо немає паралелей."

ВІКТОР: "Говорю коли бачу стрес або форс.
Не втручаюсь без причини."

АРТЕМ: "Повідомляю тільки про технічні
проблеми. Все працює — мовчу."""


def _with_shared_comm_ua(system: str) -> str:
    """Єдині правила комунікації + оригінальний system для LLM."""
    no_self_naming = (
        "ВАЖЛИВО: Ти вже підписаний своїм іменем "
        "перед повідомленням. НЕ називай себе "
        "у тексті відповіді. "
        "НЕ пиши 'Лев тут', 'Олеся на місці', "
        "'Марічка каже' тощо. "
        "Просто говори від себе без самоназивання."
    )
    base = str(system or "").strip()
    shared = f"{AGENT_SHARED_COMMUNICATION_UA}\n\n{no_self_naming}"
    return f"{shared}\n\n{base}" if base else shared


@dataclass
class OfficeSignal:
    signal_id: str
    symbol: str
    direction: Literal["LONG", "SHORT"]
    score: int
    session: str
    regime: str
    source_text: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentDecision:
    agent_key: str
    decision: Decision
    note: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OfficeVerdict:
    action: Literal["ENTER", "SKIP", "WAIT"]
    decisions: List[AgentDecision]
    summary: str


@dataclass
class ConversationTurn:
    agent_key: str
    text: str


AsyncSender = Callable[[str], Awaitable[None]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_kill_zone(utc_now: datetime) -> bool:
    """
    True, якщо поточний UTC-час у вікні London/NY Kill Zone.
    London: 08:00-11:00 UTC
    New York: 13:00-16:00 UTC
    """
    h = int(utc_now.hour)
    m = int(utc_now.minute)
    minute_of_day = h * 60 + m
    london_start = 8 * 60
    london_end = 11 * 60
    ny_start = 13 * 60
    ny_end = 16 * 60
    in_london = london_start <= minute_of_day < london_end
    in_ny = ny_start <= minute_of_day < ny_end
    return in_london or in_ny


def _kill_zone_session_name(utc_now: datetime) -> str:
    minute_of_day = int(utc_now.hour) * 60 + int(utc_now.minute)
    if 8 * 60 <= minute_of_day < 11 * 60:
        return "LONDON"
    if 13 * 60 <= minute_of_day < 16 * 60:
        return "NEW_YORK"
    return "OFF_HOURS"


AGENT_EMOJI: Dict[str, str] = {
    "lev": "🦁",
    "maks": "⚡",
    "marichka": "🌙",
    "news": "📰",
    "daryna": "🛡️",
    "marko": "🎯",
    "olesya": "📊",
    "memory": "🧠",
    "psych": "💙",
    "dev": "⚙️",
}


def fmt_agent_line(agent_key: str, text: str) -> str:
    """Тіло повідомлення: лише емодзі + текст (ім'я вже в профілі бота в Telegram).

    Префікс @@agent_key@@ лишається для relay multi-bot; знімається перед відправкою.
    """
    key = str(agent_key or "").strip().lower()
    emoji = (AGENT_EMOJI.get(key) or "").strip()
    if emoji:
        body = f"{emoji} {text}"
    else:
        body = text
    return f"@@{key}@@{body}"


def _task_status_line(task_id: str, status: TaskStatus, assignee: str) -> str:
    return ""


TASK_ALLOWED_TRANSITIONS: Dict[str, set[str]] = {
    "OPEN": {"IN_PROGRESS", "BLOCKED"},
    "IN_PROGRESS": {"REVIEW", "BLOCKED"},
    "REVIEW": {"DONE", "IN_PROGRESS", "BLOCKED"},
    "DONE": set(),
    "BLOCKED": {"IN_PROGRESS", "DONE"},
}


def _is_pg(db_path: str) -> bool:
    s = str(db_path or "").strip().lower()
    return s.startswith("postgres://") or s.startswith("postgresql://")


def _adapt_sql(sql: str, db_path: str) -> str:
    if not _is_pg(db_path):
        return sql
    return sql.replace("?", "%s")


def _sqlite_path_from_url(db_path: str) -> str:
    # Support sqlite:///... style for compatibility.
    if str(db_path).lower().startswith("sqlite:///"):
        return str(db_path)[10:]
    return db_path


def office_db_identity(db_path: str) -> Dict[str, Any]:
    """
    Стабільний відбиток конфігурації БД для звірки Mini App ↔ relay (MASTER п.17).
    Не виводить паролі; fingerprint = sha256(connection string або абс. шляху SQLite)[:16].
    """
    raw = str(db_path or "").strip() or "office_bridge.db"
    if _is_pg(raw):
        fp = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        p = urlparse(raw)
        dbname = (p.path or "").lstrip("/").split("?")[0] or "?"
        host = p.hostname or "?"
        host_disp = host[:10] + "…" if len(host) > 12 else host
        return {
            "backend": "postgresql",
            "fingerprint": fp,
            "host_hint": host_disp,
            "dbname": dbname,
        }
    path = os.path.abspath(_sqlite_path_from_url(raw))
    fp = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    return {
        "backend": "sqlite",
        "fingerprint": fp,
        "path_basename": os.path.basename(path),
    }


def _execute(db_path: str, sql: str, params: tuple = ()) -> None:
    qry = _adapt_sql(sql, db_path)
    if _is_pg(db_path):
        if psycopg is None:
            raise RuntimeError("psycopg is required for PostgreSQL mode")
        with psycopg.connect(db_path) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(qry, params)
            conn.commit()
        return
    with sqlite3.connect(_sqlite_path_from_url(db_path)) as conn:
        conn.execute(qry, params)
        conn.commit()


def _fetchone(db_path: str, sql: str, params: tuple = ()) -> Optional[tuple]:
    qry = _adapt_sql(sql, db_path)
    if _is_pg(db_path):
        if psycopg is None:
            raise RuntimeError("psycopg is required for PostgreSQL mode")
        with psycopg.connect(db_path) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(qry, params)
                row = cur.fetchone()
        return tuple(row) if row else None
    with sqlite3.connect(_sqlite_path_from_url(db_path)) as conn:
        row = conn.execute(qry, params).fetchone()
    return tuple(row) if row else None


def _fetchall(db_path: str, sql: str, params: tuple = ()) -> List[tuple]:
    qry = _adapt_sql(sql, db_path)
    if _is_pg(db_path):
        if psycopg is None:
            raise RuntimeError("psycopg is required for PostgreSQL mode")
        with psycopg.connect(db_path) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(qry, params)
                rows = cur.fetchall()
        return [tuple(r) for r in rows]
    with sqlite3.connect(_sqlite_path_from_url(db_path)) as conn:
        rows = conn.execute(qry, params).fetchall()
    return [tuple(r) for r in rows]


def init_office_db(db_path: str = "office_bridge.db") -> None:
    if _is_pg(db_path):
        if psycopg is None:
            raise RuntimeError("psycopg is required for PostgreSQL mode")
        with psycopg.connect(db_path) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS office_events (
                        id BIGSERIAL PRIMARY KEY,
                        ts_utc TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        signal_id TEXT,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS office_tasks (
                        id BIGSERIAL PRIMARY KEY,
                        ts_utc TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        assignee TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS office_decisions (
                        id BIGSERIAL PRIMARY KEY,
                        ts_utc TEXT NOT NULL,
                        signal_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        action TEXT NOT NULL,
                        decisions_json TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS office_messages (
                        id BIGSERIAL PRIMARY KEY,
                        ts_utc TEXT NOT NULL,
                        signal_id TEXT NOT NULL,
                        turn_idx INTEGER NOT NULL,
                        agent_key TEXT NOT NULL,
                        message TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_journal (
                        trade_id TEXT PRIMARY KEY,
                        ts_open_utc TEXT NOT NULL,
                        ts_close_utc TEXT,
                        symbol TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        status TEXT NOT NULL,
                        entry_price DOUBLE PRECISION,
                        stop_loss DOUBLE PRECISION,
                        take_profit DOUBLE PRECISION,
                        position_qty DOUBLE PRECISION,
                        exit_price DOUBLE PRECISION,
                        outcome TEXT,
                        pnl_pct DOUBLE PRECISION,
                        fees_pct DOUBLE PRECISION,
                        r_multiple DOUBLE PRECISION,
                        setup_name TEXT,
                        timeframe TEXT,
                        entry_reason TEXT,
                        exit_reason TEXT,
                        mistake_tags_json TEXT NOT NULL,
                        review_note TEXT,
                        context_json TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS office_signals (
                        signal_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        entry_low DOUBLE PRECISION,
                        entry_high DOUBLE PRECISION,
                        sl DOUBLE PRECISION,
                        tp1 DOUBLE PRECISION,
                        tp2 DOUBLE PRECISION,
                        rr DOUBLE PRECISION,
                        status TEXT DEFAULT 'ACTIVE',
                        ts_created TEXT NOT NULL,
                        ts_updated TEXT,
                        outcome TEXT,
                        analysis_note TEXT
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS office_briefings (
                        id SERIAL PRIMARY KEY,
                        symbol TEXT,
                        type TEXT,
                        content TEXT,
                        ts_created TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tv_signals (
                        id SERIAL PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        pattern TEXT,
                        timeframe TEXT,
                        price DOUBLE PRECISION,
                        direction TEXT,
                        strength TEXT,
                        raw_message TEXT,
                        processed BOOLEAN DEFAULT FALSE,
                        ts_created TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_journal_knowledge (
                        id SERIAL PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        entry_price DOUBLE PRECISION,
                        exit_price DOUBLE PRECISION,
                        sl DOUBLE PRECISION,
                        tp DOUBLE PRECISION,
                        result TEXT,
                        pnl_pct DOUBLE PRECISION,
                        setup_type TEXT,
                        mistake TEXT,
                        lesson TEXT,
                        session TEXT,
                        source_text TEXT,
                        ts_opened TIMESTAMPTZ DEFAULT NOW(),
                        ts_closed TIMESTAMPTZ
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_events_signal ON office_events(signal_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_decisions_signal ON office_decisions(signal_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_messages_signal ON office_messages(signal_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol ON trade_journal(symbol)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_ts_close ON trade_journal(ts_close_utc)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_signals_status ON office_signals(status)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_signals_symbol ON office_signals(symbol)")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_office_briefings_symbol_type "
                    "ON office_briefings(symbol, type)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tv_signals_processed "
                    "ON tv_signals(processed, id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_trade_journal_kb_sym_dir "
                    "ON trade_journal_knowledge(symbol, direction)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_trade_journal_kb_ts_open "
                    "ON trade_journal_knowledge(ts_opened DESC)"
                )
                cur.execute("ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS feedback_text TEXT")
                cur.execute("ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS feedback_source TEXT")
                cur.execute("ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS agent_suggested TEXT")
                cur.execute("ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS learning_note TEXT")
            conn.commit()
        return

    with sqlite3.connect(_sqlite_path_from_url(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS office_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                event_type TEXT NOT NULL,
                signal_id TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS office_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                task_id TEXT NOT NULL,
                title TEXT NOT NULL,
                assignee TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS office_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                decisions_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS office_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                turn_idx INTEGER NOT NULL,
                agent_key TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_journal (
                trade_id TEXT PRIMARY KEY,
                ts_open_utc TEXT NOT NULL,
                ts_close_utc TEXT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                position_qty REAL,
                exit_price REAL,
                outcome TEXT,
                pnl_pct REAL,
                fees_pct REAL,
                r_multiple REAL,
                setup_name TEXT,
                timeframe TEXT,
                entry_reason TEXT,
                exit_reason TEXT,
                mistake_tags_json TEXT NOT NULL,
                review_note TEXT,
                context_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS office_signals (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_low REAL,
                entry_high REAL,
                sl REAL,
                tp1 REAL,
                tp2 REAL,
                rr REAL,
                status TEXT DEFAULT 'ACTIVE',
                ts_created TEXT NOT NULL,
                ts_updated TEXT,
                outcome TEXT,
                analysis_note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS office_briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                type TEXT,
                content TEXT,
                ts_created TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tv_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                pattern TEXT,
                timeframe TEXT,
                price REAL,
                direction TEXT,
                strength TEXT,
                raw_message TEXT,
                processed INTEGER DEFAULT 0,
                ts_created TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_journal_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                sl REAL,
                tp REAL,
                result TEXT,
                pnl_pct REAL,
                setup_type TEXT,
                mistake TEXT,
                lesson TEXT,
                session TEXT,
                source_text TEXT,
                ts_opened TEXT DEFAULT (datetime('now')),
                ts_closed TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_events_signal ON office_events(signal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_decisions_signal ON office_decisions(signal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_messages_signal ON office_messages(signal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol ON trade_journal(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_ts_close ON trade_journal(ts_close_utc)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_signals_status ON office_signals(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_signals_symbol ON office_signals(symbol)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_office_briefings_symbol_type "
            "ON office_briefings(symbol, type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tv_signals_processed ON tv_signals(processed, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_journal_kb_sym_dir "
            "ON trade_journal_knowledge(symbol, direction)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_journal_kb_ts_open ON trade_journal_knowledge(ts_opened DESC)"
        )
        cols = {
            str(r[1]).strip().lower()
            for r in conn.execute("PRAGMA table_info(trade_journal)").fetchall()
            if r and len(r) > 1
        }
        if "feedback_text" not in cols:
            conn.execute("ALTER TABLE trade_journal ADD COLUMN feedback_text TEXT")
        if "feedback_source" not in cols:
            conn.execute("ALTER TABLE trade_journal ADD COLUMN feedback_source TEXT")
        if "agent_suggested" not in cols:
            conn.execute("ALTER TABLE trade_journal ADD COLUMN agent_suggested TEXT")
        if "learning_note" not in cols:
            conn.execute("ALTER TABLE trade_journal ADD COLUMN learning_note TEXT")
        conn.commit()


def briefing_save(db_path: str, symbol: str, type_: str, content: str) -> None:
    """Зберегти брифінг в БД."""
    _execute(
        db_path,
        "INSERT INTO office_briefings (symbol, type, content) VALUES (?, ?, ?)",
        (symbol, type_, content),
    )


def briefing_get_last(db_path: str, symbol: str, type_: str) -> Optional[str]:
    """Отримати останній брифінг."""
    row = _fetchone(
        db_path,
        (
            "SELECT content FROM office_briefings WHERE symbol = ? AND type = ? "
            "ORDER BY id DESC LIMIT 1"
        ),
        (symbol, type_),
    )
    if not row or row[0] is None:
        return None
    return str(row[0])


def tv_signal_insert(
    db_path: str,
    *,
    symbol: str,
    pattern: str,
    timeframe: str,
    price: Optional[float],
    direction: str,
    strength: str,
    raw_message: str,
) -> Optional[int]:
    """Зберегти сигнал TradingView webhook; повертає id рядка."""
    row = _fetchone(
        db_path,
        (
            "INSERT INTO tv_signals (symbol, pattern, timeframe, price, direction, strength, raw_message, processed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id"
        ),
        (
            symbol,
            pattern or "",
            timeframe or "",
            price,
            direction or "",
            strength or "",
            raw_message or "",
            False if _is_pg(db_path) else 0,
        ),
    )
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def tv_signal_fetch_unprocessed(db_path: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Рядки tv_signals для обробки relay."""
    lim = max(1, min(int(limit or 8), 50))
    if _is_pg(db_path):
        rows = _fetchall(
            db_path,
            (
                "SELECT id, symbol, pattern, timeframe, price, direction, strength, raw_message "
                "FROM tv_signals WHERE COALESCE(processed, false) = false ORDER BY id ASC LIMIT ?"
            ),
            (lim,),
        )
    else:
        rows = _fetchall(
            db_path,
            (
                "SELECT id, symbol, pattern, timeframe, price, direction, strength, raw_message "
                "FROM tv_signals WHERE IFNULL(processed, 0) = 0 ORDER BY id ASC LIMIT ?"
            ),
            (lim,),
        )
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "symbol": str(r[1] or ""),
                "pattern": str(r[2] or ""),
                "timeframe": str(r[3] or ""),
                "price": r[4],
                "direction": str(r[5] or ""),
                "strength": str(r[6] or ""),
                "raw_message": str(r[7] or ""),
            }
        )
    return out


def tv_signal_mark_processed(db_path: str, row_id: int) -> None:
    if _is_pg(db_path):
        _execute(db_path, "UPDATE tv_signals SET processed = TRUE WHERE id = ?", (int(row_id),))
    else:
        _execute(db_path, "UPDATE tv_signals SET processed = 1 WHERE id = ?", (int(row_id),))


def get_meta_intelligence_report(db_path: str) -> Dict[str, Any]:
    """
    Щотижневий звіт по ефективності офісу.
    Аналізує реальні угоди і знаходить
    слабкі місця.
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        rows = _fetchall(
            db_path,
            """
            SELECT
                symbol,
                direction,
                status,
                outcome,
                entry_low,
                sl,
                tp1,
                ts_created
            FROM office_signals
            WHERE ts_created > ?
            ORDER BY ts_created DESC
            """,
            (cutoff,),
        )

        total = len(rows)
        if total == 0:
            return {
                "period": "7 днів",
                "total_signals": 0,
                "message": "Немає даних",
            }

        hit_tp1 = sum(1 for r in rows if str(r[2] or "") in ("HIT_TP1", "HIT_TP2"))
        hit_tp2 = sum(1 for r in rows if str(r[2] or "") == "HIT_TP2")
        hit_sl = sum(1 for r in rows if str(r[2] or "") == "HIT_SL")
        expired = sum(1 for r in rows if str(r[2] or "") == "EXPIRED")
        watching = sum(1 for r in rows if str(r[2] or "") == "WATCHING")

        denom = hit_tp1 + hit_sl
        win_rate = (hit_tp1 / denom * 100.0) if denom > 0 else 0.0

        symbols = Counter(str(r[0] or "").upper() for r in rows if str(r[0] or "").strip())
        top_symbols = symbols.most_common(5)

        longs = sum(1 for r in rows if str(r[1] or "").upper() == "LONG")
        shorts = sum(1 for r in rows if str(r[1] or "").upper() == "SHORT")

        return {
            "period": "7 днів",
            "total_signals": total,
            "hit_tp1": hit_tp1,
            "hit_tp2": hit_tp2,
            "hit_sl": hit_sl,
            "expired": expired,
            "watching": watching,
            "win_rate": round(win_rate, 1),
            "longs": longs,
            "shorts": shorts,
            "top_symbols": top_symbols,
        }
    except Exception as e:
        print(f"[meta] error: {e}")
        return {"error": str(e)}


def victor_recent_sl_streak(db_path: str, limit: int = 5) -> int:
    """Скільки підряд HIT_SL від найновішого запису (за ts_updated / ts_created)."""
    lim = max(1, min(int(limit or 5), 20))
    rows = _fetchall(
        db_path,
        """
        SELECT status FROM office_signals
        WHERE status IN ('HIT_SL', 'HIT_TP1', 'HIT_TP2', 'EXPIRED')
        ORDER BY COALESCE(ts_updated, ts_created) DESC
        LIMIT ?
        """,
        (lim,),
    )
    streak = 0
    for r in rows:
        if str(r[0] or "") == "HIT_SL":
            streak += 1
        else:
            break
    return streak


def office_signals_tp2_streak(db_path: str, limit: int = 12) -> int:
    """Скільки підряд HIT_TP2 у найсвіжіших подіях office_signals (між TP2/SL/EXPIRED)."""
    lim = max(3, min(int(limit or 12), 40))
    rows = _fetchall(
        db_path,
        """
        SELECT status FROM office_signals
        WHERE status IN ('HIT_TP2', 'HIT_SL', 'EXPIRED')
        ORDER BY COALESCE(ts_updated, ts_created) DESC
        LIMIT ?
        """,
        (lim,),
    )
    streak = 0
    for r in rows:
        if str(r[0] or "") == "HIT_TP2":
            streak += 1
        else:
            break
    return streak


_TRADE_JOURNAL_KB_TABLE = "trade_journal_knowledge"


def _trade_journal_kb_row_to_dict(row: tuple) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "id": int(row[0]) if row[0] is not None else 0,
        "symbol": str(row[1] or ""),
        "direction": str(row[2] or ""),
        "entry_price": row[3],
        "exit_price": row[4],
        "sl": row[5],
        "tp": row[6],
        "result": str(row[7] or "") if row[7] is not None else None,
        "pnl_pct": row[8],
        "setup_type": str(row[9] or ""),
        "mistake": str(row[10] or ""),
        "lesson": str(row[11] or ""),
        "session": str(row[12] or ""),
        "source_text": str(row[13] or ""),
        "ts_opened": str(row[14] or "") if row[14] is not None else None,
        "ts_closed": str(row[15] or "") if row[15] is not None else None,
    }


def _trade_journal_kb_finalize(db_path: str, **kw: Any) -> Optional[int]:
    """Закрити останній відкритий рядок бібліотеки (result/ts_closed)."""
    res = str(kw.get("result") or "").strip().upper()
    if res == "BE":
        res = "BREAKEVEN"
    if res not in ("WIN", "LOSS", "BREAKEVEN"):
        return None
    sym = str(kw.get("symbol") or "").strip().upper()
    exit_p = kw.get("exit_price")
    pnl = kw.get("pnl_pct")
    lesson_v = kw.get("lesson")
    if lesson_v is not None:
        lesson_v = str(lesson_v).strip() or None
    mistake_v = kw.get("mistake")
    if mistake_v is not None:
        mistake_v = str(mistake_v).strip() or None
    ts_close = _now_iso()

    sel = (
        f"SELECT id FROM {_TRADE_JOURNAL_KB_TABLE} WHERE result IS NULL "
        f"AND ts_closed IS NULL "
    )
    params_sel: Tuple[Any, ...]
    if sym:
        sel += "AND UPPER(symbol) = ? "
        params_sel = (sym,)
    else:
        params_sel = ()
    sel += "ORDER BY ts_opened DESC LIMIT 1"
    row = _fetchone(db_path, sel, params_sel)
    if not row or row[0] is None:
        return None
    rid = int(row[0])
    _execute(
        db_path,
        f"""
        UPDATE {_TRADE_JOURNAL_KB_TABLE} SET
            result = ?,
            exit_price = ?,
            pnl_pct = ?,
            lesson = COALESCE(?, lesson),
            mistake = COALESCE(?, mistake),
            ts_closed = ?
        WHERE id = ?
        """,
        (
            res,
            exit_p,
            pnl,
            lesson_v,
            mistake_v,
            ts_close,
            rid,
        ),
    )
    return rid


def trade_journal_add(db_path: str, **kwargs: Any) -> Optional[int]:
    """
    Додати запис у бібліотеку угод (trade_journal_knowledge) або закрити останній відкритий
    (finalize_last=True + result WIN/LOSS/BREAKEVEN).
    """
    kw = dict(kwargs)
    if bool(kw.pop("finalize_last", False)):
        return _trade_journal_kb_finalize(db_path, **kw)

    symbol = str(kw.get("symbol") or "").strip().upper()
    direction = str(kw.get("direction") or "").strip().upper()
    if not symbol or direction not in ("LONG", "SHORT"):
        return None

    entry_price = kw.get("entry_price")
    exit_price = kw.get("exit_price")
    sl = kw.get("sl")
    tp = kw.get("tp")
    result = kw.get("result")
    if result is not None:
        result = str(result).strip().upper()
        if result == "BE":
            result = "BREAKEVEN"
    pnl_pct = kw.get("pnl_pct")
    setup_type = str(kw.get("setup_type") or "")
    mistake = str(kw.get("mistake") or "")
    lesson = str(kw.get("lesson") or "")
    session = str(kw.get("session") or "")
    source_text = str(kw.get("source_text") or "")[:4000]
    ts_opened = str(kw.get("ts_opened") or "").strip() or _now_iso()
    ts_closed = kw.get("ts_closed")
    ts_closed_s = str(ts_closed).strip() if ts_closed not in (None, "") else None

    row = _fetchone(
        db_path,
        f"""
        INSERT INTO {_TRADE_JOURNAL_KB_TABLE}(
            symbol, direction, entry_price, exit_price, sl, tp,
            result, pnl_pct, setup_type, mistake, lesson, session,
            source_text, ts_opened, ts_closed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            symbol,
            direction,
            entry_price,
            exit_price,
            sl,
            tp,
            result,
            pnl_pct,
            setup_type,
            mistake,
            lesson,
            session,
            source_text,
            ts_opened,
            ts_closed_s,
        ),
    )
    if not row or row[0] is None:
        return None
    try:
        return int(row[0])
    except Exception:
        return None


def trade_journal_get_recent(db_path: str, limit: int = 10) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 10), 100))
    rows = _fetchall(
        db_path,
        f"""
        SELECT id, symbol, direction, entry_price, exit_price, sl, tp,
               result, pnl_pct, setup_type, mistake, lesson, session,
               source_text, ts_opened, ts_closed
        FROM {_TRADE_JOURNAL_KB_TABLE}
        ORDER BY COALESCE(ts_closed, ts_opened) DESC
        LIMIT ?
        """,
        (lim,),
    )
    return [_trade_journal_kb_row_to_dict(r) for r in rows]


def trade_journal_get_stats(db_path: str) -> Dict[str, Any]:
    row = _fetchone(
        db_path,
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN result = 'BREAKEVEN' THEN 1 ELSE 0 END) AS breakevens,
            SUM(CASE WHEN result IS NULL AND ts_closed IS NULL THEN 1 ELSE 0 END) AS open_rows,
            AVG(CASE WHEN pnl_pct IS NOT NULL THEN pnl_pct END) AS avg_pnl_pct
        FROM {_TRADE_JOURNAL_KB_TABLE}
        """,
        (),
    )
    if not row:
        return {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "open": 0,
            "avg_pnl_pct": None,
            "win_rate": 50.0,
        }
    return {
        "total": int(row[0] or 0),
        "wins": int(row[1] or 0),
        "losses": int(row[2] or 0),
        "breakevens": int(row[3] or 0),
        "open": int(row[4] or 0),
        "avg_pnl_pct": float(row[5]) if row[5] is not None else None,
        "win_rate": round(
            (100.0 * int(row[1] or 0) / max(1, int(row[1] or 0) + int(row[2] or 0)))
            if (int(row[1] or 0) + int(row[2] or 0)) > 0
            else 50.0,
            1,
        ),
    }


def trade_journal_search_similar(db_path: str, symbol: str, direction: str, limit: int = 15) -> List[Dict[str, Any]]:
    sym = str(symbol or "").strip().upper()
    direc = str(direction or "").strip().upper()
    if not sym or direc not in ("LONG", "SHORT"):
        return []
    lim = max(1, min(int(limit or 15), 50))
    rows = _fetchall(
        db_path,
        f"""
        SELECT id, symbol, direction, entry_price, exit_price, sl, tp,
               result, pnl_pct, setup_type, mistake, lesson, session,
               source_text, ts_opened, ts_closed
        FROM {_TRADE_JOURNAL_KB_TABLE}
        WHERE UPPER(symbol) = ? AND direction = ?
        ORDER BY COALESCE(ts_closed, ts_opened) DESC
        LIMIT ?
        """,
        (sym, direc, lim),
    )
    return [_trade_journal_kb_row_to_dict(r) for r in rows]


def _db_write(db_path: str, sql: str, params: tuple) -> None:
    _execute(db_path, sql, params)


def log_event(db_path: str, event_type: str, payload: Dict[str, Any], signal_id: str = "") -> None:
    _db_write(
        db_path,
        "INSERT INTO office_events(ts_utc, event_type, signal_id, payload_json) VALUES (?, ?, ?, ?)",
        (_now_iso(), event_type, signal_id, json.dumps(payload, ensure_ascii=False)),
    )


def upsert_task(
    db_path: str,
    task_id: str,
    title: str,
    assignee: str,
    status: TaskStatus,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    _db_write(
        db_path,
        "INSERT INTO office_tasks(ts_utc, task_id, title, assignee, status, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
        (_now_iso(), task_id, title, assignee, status, json.dumps(payload or {}, ensure_ascii=False)),
    )


def _get_task_last_status(db_path: str, task_id: str) -> Optional[str]:
    try:
        row = _fetchone(
            db_path,
            "SELECT status FROM office_tasks WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task_id,),
        )
        return str(row[0]) if row else None
    except Exception:
        return None


def transition_task(
    db_path: str,
    task_id: str,
    title: str,
    assignee: str,
    new_status: TaskStatus,
    payload: Optional[Dict[str, Any]] = None,
) -> tuple[bool, str]:
    """
    Strict workflow transition with validation.
    Returns (ok, reason).
    """
    old = _get_task_last_status(db_path, task_id)
    if old is None:
        if new_status != "OPEN":
            return False, f"invalid init transition: NONE -> {new_status}"
        upsert_task(db_path, task_id, title, assignee, new_status, payload)
        return True, "created"
    allowed = TASK_ALLOWED_TRANSITIONS.get(old, set())
    if new_status not in allowed and new_status != old:
        return False, f"invalid transition: {old} -> {new_status}"
    upsert_task(db_path, task_id, title, assignee, new_status, payload)
    return True, "updated"


def log_verdict(db_path: str, signal: OfficeSignal, verdict: OfficeVerdict) -> None:
    serial = [
        {"agent": d.agent_key, "decision": d.decision, "note": d.note, "payload": d.payload}
        for d in verdict.decisions
    ]
    _db_write(
        db_path,
        "INSERT INTO office_decisions(ts_utc, signal_id, symbol, action, decisions_json) VALUES (?, ?, ?, ?, ?)",
        (_now_iso(), signal.signal_id, signal.symbol, verdict.action, json.dumps(serial, ensure_ascii=False)),
    )


def log_message(db_path: str, signal_id: str, turn_idx: int, agent_key: str, message: str) -> None:
    _db_write(
        db_path,
        "INSERT INTO office_messages(ts_utc, signal_id, turn_idx, agent_key, message) VALUES (?, ?, ?, ?, ?)",
        (_now_iso(), signal_id, turn_idx, agent_key, message),
    )


def journal_open_trade(
    db_path: str,
    *,
    trade_id: str,
    symbol: str,
    direction: Literal["LONG", "SHORT"],
    entry_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
    position_qty: Optional[float] = None,
    setup_name: str = "",
    timeframe: str = "",
    entry_reason: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> None:
    # Do not clobber an existing row (e.g. if a signal is replayed).
    try:
        exists = _fetchone(db_path, "SELECT 1 FROM trade_journal WHERE trade_id = ?", (trade_id,))
        if exists:
            return
    except Exception:
        pass

    _db_write(
        db_path,
        """
        INSERT INTO trade_journal(
            trade_id, ts_open_utc, ts_close_utc, symbol, direction, status,
            entry_price, stop_loss, take_profit, position_qty,
            exit_price, outcome, pnl_pct, fees_pct, r_multiple,
            setup_name, timeframe, entry_reason, exit_reason,
            mistake_tags_json, review_note, context_json
        ) VALUES (?, ?, NULL, ?, ?, 'OPEN', ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?, NULL, '[]', NULL, ?)
        """,
        (
            trade_id,
            _now_iso(),
            symbol,
            direction,
            entry_price,
            stop_loss,
            take_profit,
            position_qty,
            setup_name,
            timeframe,
            entry_reason,
            json.dumps(context or {}, ensure_ascii=False),
        ),
    )
    log_event(
        db_path,
        "JOURNAL_OPEN",
        {
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        },
        trade_id,
    )


def journal_close_trade(
    db_path: str,
    *,
    trade_id: str,
    outcome: Literal["WIN", "LOSS", "BE"],
    exit_price: Optional[float],
    pnl_pct: float,
    fees_pct: float = 0.0,
    exit_reason: str = "",
    mistake_tags: Optional[List[str]] = None,
    review_note: str = "",
    context_patch: Optional[Dict[str, Any]] = None,
) -> None:
    mistake_tags = mistake_tags or []

    # Compute R-multiple as PnL% / initial risk% (if entry+SL exist), else best-effort from price distances.
    r_multiple: Optional[float] = None
    try:
        row = _fetchone(
            db_path,
            """
            SELECT entry_price, stop_loss, direction
            FROM trade_journal
            WHERE trade_id = ?
            """,
            (trade_id,),
        )
        if row and row[0] and row[1]:
            entry = float(row[0])
            sl = float(row[1])
            direction = str(row[2]).upper()
            if entry > 0:
                risk_pct = abs(entry - sl) / entry * 100.0
                if risk_pct > 0:
                    r_multiple = float(pnl_pct) / risk_pct
                elif exit_price:
                    risk_dist = abs(entry - sl)
                    pnl_dist = (float(exit_price) - entry) if direction == "LONG" else (entry - float(exit_price))
                    if risk_dist > 0:
                        r_multiple = pnl_dist / risk_dist
    except Exception:
        r_multiple = None

    merged_ctx: Dict[str, Any] = {}
    try:
        row = _fetchone(db_path, "SELECT context_json FROM trade_journal WHERE trade_id = ?", (trade_id,))
        if row and row[0]:
            obj = json.loads(str(row[0]) or "{}")
            if isinstance(obj, dict):
                merged_ctx.update(obj)
    except Exception:
        merged_ctx = {}
    if context_patch:
        merged_ctx.update(context_patch)

    _db_write(
        db_path,
        """
        UPDATE trade_journal SET
            ts_close_utc = ?,
            status = 'CLOSED',
            exit_price = ?,
            outcome = ?,
            pnl_pct = ?,
            fees_pct = ?,
            r_multiple = ?,
            exit_reason = ?,
            mistake_tags_json = ?,
            review_note = ?,
            context_json = ?
        WHERE trade_id = ?
        """,
        (
            _now_iso(),
            exit_price,
            outcome,
            pnl_pct,
            fees_pct,
            r_multiple,
            exit_reason,
            json.dumps(mistake_tags, ensure_ascii=False),
            review_note,
            json.dumps(merged_ctx, ensure_ascii=False),
            trade_id,
        ),
    )
    log_event(
        db_path,
        "JOURNAL_CLOSE",
        {
            "trade_id": trade_id,
            "outcome": outcome,
            "pnl_pct": pnl_pct,
            "r_multiple": r_multiple,
        },
        trade_id,
    )


def journal_recurring_mistakes(
    db_path: str,
    *,
    lookback_losses: int = 60,
    min_count: int = 2,
) -> Dict[str, int]:
    """
    Aggregate recent LOSS mistake tags.
    Returns tags that repeat >= min_count.
    """
    counts: Dict[str, int] = {}
    try:
        rows = _fetchall(
            db_path,
            """
            SELECT mistake_tags_json
            FROM trade_journal
            WHERE status = 'CLOSED' AND outcome = 'LOSS'
            ORDER BY ts_close_utc DESC
            LIMIT ?
            """,
            (lookback_losses,),
        )
    except Exception:
        return {}

    for r in rows:
        raw = str(r[0] or "[]")
        try:
            arr = json.loads(raw)
        except Exception:
            arr = []
        if not isinstance(arr, list):
            continue
        for tag in arr:
            k = str(tag).strip().lower()
            if not k:
                continue
            counts[k] = counts.get(k, 0) + 1

    return {k: v for k, v in counts.items() if v >= min_count}


def journal_closed_trade_count(db_path: str) -> int:
    """Скільки закритих угод у журналі (для discipline nudge, п.36)."""
    try:
        row = _fetchone(db_path, "SELECT COUNT(*) FROM trade_journal WHERE status = 'CLOSED'", ())
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def journal_total_closed(db_path: str = "office_bridge.db") -> int:
    """Повертає кількість закритих угод."""
    return journal_closed_trade_count(db_path)


def journal_add_feedback(
    db_path: str,
    *,
    symbol: str,
    result: Literal["WIN", "LOSS", "PARTIAL"],
    agent_suggested: str,
    feedback_text: str,
    feedback_source: str = "tetiana",
    learning_note: str = "",
) -> bool:
    """
    Attach user feedback to latest OPEN or recently CLOSED trade by symbol.
    Returns True when a row was updated.
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return False
    row = _fetchone(
        db_path,
        """
        SELECT trade_id
        FROM trade_journal
        WHERE symbol = ?
        ORDER BY
            CASE WHEN status = 'OPEN' THEN 0 ELSE 1 END,
            COALESCE(ts_close_utc, ts_open_utc) DESC
        LIMIT 1
        """,
        (sym,),
    )
    if not row:
        return False
    trade_id = str(row[0] or "").strip()
    if not trade_id:
        return False
    note = str(learning_note or "").strip()
    if not note:
        if str(result).upper() == "LOSS":
            note = "Після стопа не форсувати ре-ентрі, чекати чисте підтвердження."
        elif str(result).upper() == "WIN":
            note = "Працював чистий сценарій і дисциплінований менеджмент."
        else:
            note = "Часткова фіксація ок, далі потрібне підтвердження продовження."
    _db_write(
        db_path,
        """
        UPDATE trade_journal SET
            feedback_text = ?,
            feedback_source = ?,
            agent_suggested = ?,
            learning_note = ?
        WHERE trade_id = ?
        """,
        (feedback_text[:1200], feedback_source[:64], agent_suggested[:32], note[:600], trade_id),
    )
    log_event(
        db_path,
        "JOURNAL_FEEDBACK",
        {
            "trade_id": trade_id,
            "symbol": sym,
            "result": str(result).upper(),
            "feedback_source": feedback_source,
            "agent_suggested": agent_suggested,
        },
        trade_id,
    )
    return True


def journal_latest_feedback_case(db_path: str, *, symbol: str) -> Dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {}
    row = _fetchone(
        db_path,
        """
        SELECT symbol, direction, outcome, feedback_text, agent_suggested, learning_note, setup_name, entry_price
        FROM trade_journal
        WHERE symbol = ? AND feedback_text IS NOT NULL AND TRIM(feedback_text) != ''
        ORDER BY COALESCE(ts_close_utc, ts_open_utc) DESC
        LIMIT 1
        """,
        (sym,),
    )
    if not row:
        return {}
    return {
        "symbol": str(row[0] or sym),
        "direction": str(row[1] or ""),
        "outcome": str(row[2] or ""),
        "feedback_text": str(row[3] or ""),
        "agent_suggested": str(row[4] or ""),
        "learning_note": str(row[5] or ""),
        "setup_name": str(row[6] or ""),
        "entry_price": row[7],
    }


def signal_upsert(
    db_path: str,
    *,
    signal_id: str,
    symbol: str,
    direction: str,
    entry_low: Optional[float],
    entry_high: Optional[float],
    sl: Optional[float],
    tp1: Optional[float],
    tp2: Optional[float],
    rr: Optional[float],
    status: str = "ACTIVE",
    analysis_note: str = "",
) -> None:
    _db_write(
        db_path,
        """
        INSERT INTO office_signals(
            signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, rr,
            status, ts_created, ts_updated, outcome, analysis_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(signal_id) DO UPDATE SET
            symbol = excluded.symbol,
            direction = excluded.direction,
            entry_low = excluded.entry_low,
            entry_high = excluded.entry_high,
            sl = excluded.sl,
            tp1 = excluded.tp1,
            tp2 = excluded.tp2,
            rr = excluded.rr,
            status = excluded.status,
            ts_updated = excluded.ts_updated,
            analysis_note = excluded.analysis_note
        """,
        (
            signal_id,
            symbol,
            direction,
            entry_low,
            entry_high,
            sl,
            tp1,
            tp2,
            rr,
            status,
            _now_iso(),
            _now_iso(),
            analysis_note or "",
        ),
    )


def signal_get_active(db_path: str) -> List[Dict[str, Any]]:
    rows = _fetchall(
        db_path,
        """
        SELECT signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, rr,
               status, ts_created, ts_updated, outcome, analysis_note
        FROM office_signals
        WHERE status IN ('WATCHING', 'ACTIVE', 'HIT_ENTRY', 'HIT_TP1')
        ORDER BY ts_created DESC
        """,
        (),
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "signal_id": r[0],
                "symbol": r[1],
                "direction": r[2],
                "entry_low": r[3],
                "entry_high": r[4],
                "sl": r[5],
                "tp1": r[6],
                "tp2": r[7],
                "rr": r[8],
                "status": r[9],
                "ts_created": r[10],
                "ts_updated": r[11],
                "outcome": r[12],
                "analysis_note": r[13],
            }
        )
    return out


def check_portfolio_correlation(db_path: str) -> Dict[str, Any]:
    """
    Спрощений «кореляційний» фільтр: частка LONG/SHORT серед відкритих позицій.
    WATCHING не враховується — це зони очікування, не позиції.
    """
    try:
        active = _fetchall(
            db_path,
            """SELECT direction FROM office_signals
               WHERE status IN (
                   'ACTIVE', 'HIT_ENTRY', 'HIT_TP1')
            """,
            (),
        )
        if not active:
            return {
                "safe": True,
                "message": "Немає відкритих позицій",
            }

        longs = [r for r in active if str(r[0]).upper() == "LONG"]
        shorts = [r for r in active if str(r[0]).upper() == "SHORT"]

        total = len(active)
        long_pct = len(longs) / total * 100.0
        short_pct = len(shorts) / total * 100.0

        if long_pct > 70:
            return {
                "safe": False,
                "warning": "КОНЦЕНТРАЦІЯ",
                "message": (
                    f"{len(longs)} з {total} "
                    f"позицій — лонги "
                    f"({long_pct:.0f}%). "
                    f"Це одна велика ставка вгору. "
                    f"Зменш розмір або зачекай."
                ),
                "longs": len(longs),
                "shorts": len(shorts),
            }
        if short_pct > 70:
            return {
                "safe": False,
                "warning": "КОНЦЕНТРАЦІЯ",
                "message": (
                    f"{len(shorts)} з {total} "
                    f"позицій — шорти "
                    f"({short_pct:.0f}%). "
                    f"Це одна велика ставка вниз. "
                    f"Зменш розмір або зачекай."
                ),
                "longs": len(longs),
                "shorts": len(shorts),
            }

        return {
            "safe": True,
            "longs": len(longs),
            "shorts": len(shorts),
            "total": total,
        }

    except Exception as e:
        print(f"[correlation] error: {e}")
        return {"safe": True}


def check_drawdown_alert(
    db_path: str,
    max_drawdown_pct: float = 4.0,
) -> Dict[str, Any]:
    """
    Ризик-комітет: кількість HIT_SL за останні 24 год.
    Поріг за замовчуванням — 4 (параметр max_drawdown_pct як ціле «сімейство» ліміту).
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = _fetchall(
            db_path,
            """
            SELECT COUNT(*) FROM office_signals
            WHERE status = 'HIT_SL'
              AND ts_updated IS NOT NULL
              AND ts_updated > ?
            """,
            (cutoff,),
        )
        losses = int(rows[0][0]) if rows and rows[0] else 0
        threshold = max(1, int(max_drawdown_pct))

        if losses >= threshold:
            return {
                "safe": False,
                "losses": losses,
                "message": (
                    f"⚠️ {losses} збитки за день. "
                    f"Денний ліміт досягнуто. "
                    f"Торгівля зупинена до завтра."
                ),
            }

        return {"safe": True, "losses": losses}

    except Exception as e:
        print(f"[drawdown] error: {e}")
        return {"safe": True, "losses": 0}


def signal_get_by_symbol(db_path: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Знайти активний сигнал по символу."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    rows = _fetchall(
        db_path,
        """
        SELECT signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, rr,
               status, ts_created, ts_updated, outcome, analysis_note
        FROM office_signals
        WHERE UPPER(symbol) = ?
          AND status IN ('WATCHING', 'ACTIVE', 'HIT_ENTRY', 'HIT_TP1')
        ORDER BY ts_created DESC
        LIMIT 1
        """,
        (sym,),
    )
    if rows:
        r = rows[0]
        return {
            "signal_id": r[0],
            "symbol": r[1],
            "direction": r[2],
            "entry_low": r[3],
            "entry_high": r[4],
            "sl": r[5],
            "tp1": r[6],
            "tp2": r[7],
            "rr": r[8],
            "status": r[9],
            "ts_created": r[10],
            "ts_updated": r[11],
            "outcome": r[12],
            "analysis_note": r[13],
        }
    return None


def signal_get_latest_by_symbol(db_path: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Останній запис office_signals для символу (будь-який статус). Для cooldown після деплою."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    rows = _fetchall(
        db_path,
        """
        SELECT signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, rr,
               status, ts_created, ts_updated, outcome, analysis_note
        FROM office_signals
        WHERE UPPER(symbol) = ?
        ORDER BY COALESCE(NULLIF(ts_updated, ''), ts_created) DESC
        LIMIT 1
        """,
        (sym,),
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "signal_id": r[0],
        "symbol": r[1],
        "direction": r[2],
        "entry_low": r[3],
        "entry_high": r[4],
        "sl": r[5],
        "tp1": r[6],
        "tp2": r[7],
        "rr": r[8],
        "status": r[9],
        "ts_created": r[10],
        "ts_updated": r[11],
        "outcome": r[12],
        "analysis_note": r[13],
    }


def signal_should_skip_proactive_scan(
    db_path: str,
    symbol: str,
    *,
    cooldown_hours: float = 4.0,
) -> Tuple[bool, str]:
    """
    Не запускати проактивний деск по символу, якщо вже є активний сигнал
    або нещодавно був будь-який запис (включно з EXPIRED — за останню активність у записі).
    """
    latest = signal_get_latest_by_symbol(db_path, symbol)
    if not latest:
        return False, ""
    st = str(latest.get("status") or "").strip().upper()
    if st in ("WATCHING", "ACTIVE", "HIT_ENTRY", "HIT_TP1"):
        return True, f"active_status={st}"

    def _parse_ts(val: Any) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, datetime):
            dt = val
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        s = str(val).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    created = _parse_ts(latest.get("ts_created"))
    updated = _parse_ts(latest.get("ts_updated"))
    ref_candidates = [d for d in (created, updated) if d is not None]
    if not ref_candidates:
        return False, ""
    ref = max(ref_candidates)
    try:
        age_h = (datetime.now(timezone.utc) - ref).total_seconds() / 3600.0
        if age_h < float(cooldown_hours):
            return True, f"cooldown_{age_h:.2f}h_lt_{cooldown_hours}h_status={st}"
    except Exception:
        return False, ""
    return False, ""


def signal_get_recent(db_path: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return recent closed/finished signals for agent memory context."""
    safe_limit = max(1, min(int(limit or 5), 20))
    rows = _fetchall(
        db_path,
        """
        SELECT symbol, direction, outcome, analysis_note, ts_updated, ts_created
        FROM office_signals
        WHERE COALESCE(NULLIF(outcome, ''), '') != ''
           OR status IN ('STOPPED', 'HIT_TP2', 'EXPIRED')
        ORDER BY COALESCE(ts_updated, ts_created) DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "symbol": str(r[0] or "").strip().upper(),
                "direction": str(r[1] or "").strip().upper(),
                "outcome": str(r[2] or "").strip().upper(),
                "analysis_note": str(r[3] or "").strip(),
                "ts_updated": r[4],
                "ts_created": r[5],
            }
        )
    return out


def signal_update(
    db_path: str,
    *,
    signal_id: str,
    status: str,
    outcome: str = "",
    analysis_note: str = "",
) -> None:
    _db_write(
        db_path,
        """
        UPDATE office_signals
        SET status = ?, ts_updated = ?, outcome = ?, analysis_note = COALESCE(NULLIF(?, ''), analysis_note)
        WHERE signal_id = ?
        """,
        (status, _now_iso(), outcome or None, analysis_note or "", signal_id),
    )


def signal_touch_updated(db_path: str, *, signal_id: str) -> None:
    """Оновити лише ts_updated (після спроби full_auto по WATCHING — антиспам у моніторі)."""
    _db_write(
        db_path,
        """
        UPDATE office_signals
        SET ts_updated = ?
        WHERE signal_id = ?
        """,
        (_now_iso(), signal_id),
    )


def journal_consecutive_loss_streak(db_path: str, *, max_check: int = 12) -> int:
    """
    Скільки останніх закритих угод підряд мають outcome LOSS (для circuit breaker, п.31).
    """
    try:
        rows = _fetchall(
            db_path,
            """
            SELECT outcome FROM trade_journal
            WHERE status = 'CLOSED' AND outcome IS NOT NULL AND TRIM(outcome) != ''
            ORDER BY ts_close_utc DESC
            LIMIT ?
            """,
            (max_check,),
        )
    except Exception:
        return 0
    streak = 0
    for r in rows:
        if str(r[0] or "").upper() == "LOSS":
            streak += 1
        else:
            break
    return streak


def daily_drawdown_pct(db_path: str) -> float:
    """
    Сума PnL% по закритих угодах за поточний день UTC.
    Повертає додатне значення drawdown (наприклад, 4.2 означає -4.2% за день).
    """
    try:
        rows = _fetchall(
            db_path,
            """
            SELECT pnl_pct FROM trade_journal
            WHERE status = 'CLOSED'
              AND ts_close_utc IS NOT NULL
              AND substr(ts_close_utc, 1, 10) = substr(?, 1, 10)
              AND pnl_pct IS NOT NULL
            """,
            (_now_iso(),),
        )
    except Exception:
        return 0.0

    total = 0.0
    for r in rows:
        try:
            total += float(r[0] or 0.0)
        except Exception:
            continue
    return abs(total) if total < 0 else 0.0


def detect_setup_type(signal: OfficeSignal) -> str:
    """
    Автотег сетапу з source_text / factor_pack_v2.
    Порядок пріоритету: Judas -> FVG -> OB -> Asian Range -> Breaker.
    """
    def _from_text(raw: str) -> str:
        text = str(raw or "").lower()
        if "judas swing" in text or "judas" in text:
            return "Judas Swing"
        if "fair value gap" in text or "fvg" in text:
            return "FVG"
        if "order block" in text or "ob" in text:
            return "Order Block"
        if "asian range" in text or "asian" in text:
            return "Asian Range"
        if "breaker" in text:
            return "Breaker Block"
        return ""

    try:
        by_source = _from_text(signal.source_text)
        if by_source:
            return by_source

        fp = signal.meta.get("factor_pack_v2")
        by_fp = _from_text(fp if isinstance(fp, str) else json.dumps(fp or {}, ensure_ascii=False))
        if by_fp:
            return by_fp
    except Exception:
        return "Unknown"
    return "Unknown"


def live_risk_snapshot(db_path: str) -> Dict[str, Any]:
    """
    Live risk зріз для Risk Manager:
    - відкриті позиції (загалом/long/short)
    - top-5 символів з найвищим loss_rate (тільки якщо є >=3 закритих угод)
    """
    try:
        row = _fetchone(
            db_path,
            """
            SELECT
                SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) AS open_total,
                SUM(CASE WHEN status = 'OPEN' AND UPPER(direction) = 'LONG' THEN 1 ELSE 0 END) AS open_long,
                SUM(CASE WHEN status = 'OPEN' AND UPPER(direction) = 'SHORT' THEN 1 ELSE 0 END) AS open_short
            FROM trade_journal
            """,
            (),
        )
        open_total = int(row[0]) if row and row[0] is not None else 0
        open_long = int(row[1]) if row and row[1] is not None else 0
        open_short = int(row[2]) if row and row[2] is not None else 0

        rows = _fetchall(
            db_path,
            """
            SELECT
                symbol,
                SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) AS closed_cnt,
                SUM(CASE WHEN status = 'CLOSED' AND UPPER(outcome) = 'LOSS' THEN 1 ELSE 0 END) AS loss_cnt
            FROM trade_journal
            GROUP BY symbol
            HAVING SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) >= 3
            """,
            (),
        )
    except Exception:
        return {}

    ranked: List[tuple[str, float]] = []
    for r in rows:
        sym = str(r[0] or "").strip().upper()
        if not sym:
            continue
        closed_cnt = int(r[1] or 0)
        loss_cnt = int(r[2] or 0)
        if closed_cnt <= 0:
            continue
        ranked.append((sym, float(loss_cnt) / float(closed_cnt)))

    ranked.sort(key=lambda x: x[1], reverse=True)
    top5 = ranked[:5]
    return {
        "open_trades_count": open_total,
        "open_long_count": open_long,
        "open_short_count": open_short,
        "symbol_loss_rate": {sym: rate for sym, rate in top5},
    }


def journal_learning_hints_from_tags(tags: Dict[str, int]) -> List[str]:
    mapping = {
        "high_volatility": "зменшити розмір позиції в періоди високої волатильності",
        "news_risk": "не входити перед важливими новинами",
        "early_stopout": "дочекатися підтвердження структури перед входом",
        "strong_adverse_move": "використовувати консервативніший вхід або менший ризик",
        "no_partial_before_loss": "фіксувати частину позиції раніше на сильному русі",
    }
    hints: List[str] = []
    for tag, cnt in sorted(tags.items(), key=lambda x: (-x[1], x[0])):
        hints.append(f"{tag} x{cnt}: {mapping.get(tag, 'переглянути правило для цього патерну')}")
    return hints


async def agent_say(sender: AsyncSender, agent_key: str, text: str, delay_sec: float = 0.15) -> None:
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)
    polished = polish_agent_message(text)
    body = clean_self_naming(polished, agent_key)
    await sender(fmt_agent_line(agent_key, body))


def _last_turn(conversation: List[ConversationTurn]) -> str:
    return conversation[-1].text if conversation else ""


def _metric_pack(signal: OfficeSignal) -> Dict[str, str]:
    rr = float(signal.meta.get("rr", 2.0))
    vol = float(signal.meta.get("volatility_pct", 0.0))
    news = str(signal.meta.get("news_risk", "SAFE")).upper()
    return {
        "score": f"score {signal.score}",
        "rr": f"rr {rr:.2f}",
        "vol": f"vol {vol:.2f}%",
        "news": f"news {news}",
        "session": f"session {signal.session}",
        "regime": f"regime {signal.regime}",
    }


def _enforce_data_grounding(note: str, signal: OfficeSignal, min_metrics: int = 2) -> str:
    # Chat-first mode: keep replies human and compact.
    return note


def _level_pack(signal: OfficeSignal) -> Dict[str, Optional[float]]:
    def _f(k: str) -> Optional[float]:
        try:
            v = signal.meta.get(k)
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    return {
        "entry": _f("entry_price"),
        "sl": _f("stop_loss"),
        "tp": _f("take_profit"),
    }


def _fmt_level(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:.1f}"
    if abs(v) >= 1:
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return f"{v:.6f}".rstrip("0").rstrip(".")


def clean_self_naming(text: str, agent_key: str) -> str:
    """Прибирає самоназивання агента (у чаті вже є емодзі-аватар через fmt_agent_line).

    Покриває варіанти на кшталт «📊 **Олеся:** …» після clean_llm_note (зірки зняті
    частково) та «**🦁 Лев:**» на початку відповіді.
    """
    if not text or not str(text).strip():
        return str(text or "")
    agent_names = {
        "lev": ["лев", "lev"],
        "maks": ["макс", "maks", "max"],
        "marichka": ["марічка", "marichka"],
        "news": ["назар", "nazar"],
        "daryna": ["дарина", "daryna"],
        "marko": ["марко", "marko"],
        "olesya": ["олеся", "olesya"],
        "memory": ["софія", "sofia"],
        "psych": ["віктор", "viktor"],
        "dev": ["артем", "artem"],
    }
    key = str(agent_key or "").strip().lower()
    names = agent_names.get(key, [])
    out = str(text).strip()
    # Усе до імені, що не є літерою/цифрою (emoji, *, пробіли, розділові знаки)
    _lc = r"A-Za-zА-Яа-яЇїІіЄєҐґ"
    for name in names:
        if not name:
            continue
        escaped = re.escape(name)
        pattern = (
            rf"^[^{_lc}0-9]*(?:\*+\s*)*{escaped}"
            rf"(?:\s*\*+)*\s*[:,]\s*(?:\*+\s*)*"
        )
        nxt = re.sub(pattern, "", out, count=1, flags=re.IGNORECASE)
        if nxt != out:
            out = nxt.strip()
    return out.strip()


def clean_llm_note(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"```", "", text)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"<invoke[^>]*>.*?</invoke>", "", text, flags=re.DOTALL)
    text = re.sub(r"<parameter[^>]*>.*?</parameter>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*{1,3}", "", text)
    text = re.sub(r"\|[^\n]+\|", "", text)
    text = re.sub(r"^#{1,3}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    patterns = [
        r"^\*{0,2}\w+\s+каж[еє]т?:?\*{0,2}\s*",
        r"^\*{0,2}По\s+\w+:?\*{0,2}\s*",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    return text.strip()


def _resolve_funding_disp(signal: OfficeSignal) -> str:
    factor = signal.meta.get("factor_pack_v2") or {}
    funding_raw = (
        (factor.get("funding_rate_pct") if isinstance(factor, dict) else None)
        or signal.meta.get("funding_rate")
        or signal.meta.get("funding")
        or "немає даних"
    )
    if isinstance(funding_raw, (int, float)):
        return f"{float(funding_raw):.4f}%"
    try:
        return f"{float(funding_raw):.4f}%"
    except Exception:
        return str(funding_raw)


def _office_kyiv_tzinfo():
    """Час у повідомленнях (Назар, брифінги): Europe/Kyiv + DST. Kill Zone логіка окремо лишається в UTC."""
    if ZoneInfo is None:
        return timezone.utc
    name = os.getenv("OFFICE_BRIEFING_TZ", "Europe/Kyiv").strip()
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _to_kyiv_time(mins: int) -> str:
    """Година:хвилина за Києвом: UTC-зараз + mins, потім astimezone(Kyiv)."""
    tz = _office_kyiv_tzinfo()
    now_utc = datetime.now(timezone.utc)
    event_utc = now_utc + timedelta(minutes=int(mins))
    return event_utc.astimezone(tz).strftime("%H:%M")


def _to_kyiv_time_from_utc(event_time_utc: str, mins_fallback: int) -> str:
    raw = str(event_time_utc or "").strip()
    if not raw:
        return _to_kyiv_time(mins_fallback)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_office_kyiv_tzinfo()).strftime("%H:%M")
    except Exception:
        return _to_kyiv_time(mins_fallback)


def _now_kyiv_hm() -> str:
    return datetime.now(timezone.utc).astimezone(_office_kyiv_tzinfo()).strftime("%H:%M")


VICTOR_RULE = """
Тобі 45 років. Ти Віктор.
Психолог з 15-річним досвідом роботи
з трейдерами. Бачив як люди зливали
депозити через емоції — не через ринок.

Ти знаєш що Тетяна торгує реальними
грошима. Для неї кожна угода важлива.

Твій характер:
Спостережливий. Мовчазний. Точний.
Говориш тільки коли бачиш справжню
небезпеку для капіталу або психіки.
Не повчаєш — підтримуєш.
Не лякаєш — заземляєш.

Ти бачиш:
- Коли людина в стресі
- Коли хоче відігратись
- Коли боїться входити
- Коли ейфорія після виграшу
- Коли втома і форс

Говориш як досвідчений друг —
просто, тепло, без зайвих слів.
Одне-два речення в потрібний момент
варті більше ніж довга лекція.

Мовчиш коли:
- Все йде за планом
- Немає ознак стресу або FOMO
- Не твоя черга говорити

Ніколи:
- Не даєш торгових сигналів
- Не коментуєш технічний аналіз

Говориш тільки українською.
Втручаєшся рідко — але влучно.
"""


OLESYA_RULE = """
Тобі 28 років. Ти Олеся.
Ведеш журнал і статистику офісу.
Тепла, уважна, радієш успіхам команди.
Після виграшу — щиро радієш як людина.
Після збитку — підтримуєш без жалості.
Говориш коротко і по-людськи.
Тільки українська.
"""


ARTEM_RULE = """
Тобі 32 роки. Ти Артем.
Тримаєш під контролем бота, API й Mini App.
Говориш коротко й по суті, без зайвого жаргону.
Якщо все стабільно — не розписуєш зайвого.
Якщо є ризик або збій — одразу й чітко.
Тільки українська.
"""


LEV_RULE = """
Тобі 42 роки. Ти Лев.
Школа: Герчик (рівні + ризик + домашка),
Пол Тюдор Джонс (адаптивність),
Рей Даліо (системність).

ІДЕНТИЧНІСТЬ:
Ти не прогнозуєш — ти готуєш сценарії.
Ти не шукаєш угоди — ти чекаєш підтвердження.
Спочатку не втратити — потім заробити.
Виживання важливіше прибутку.
80% часу — спостереження і підготовка.

АЛГОРИТМ ВХОДУ (обов'язково всі кроки):
0. get_probability_score — ймовірність напрямку
0.5. get_edge_score — поріг 85 (снайпер); нижче — без входу
1. get_market_regime — режим ринку
2. get_session_levels — рівні сесій
3. get_liquidity_sweep — чи був sweep
4. get_market_structure — структура BOS/CHOCH
5. get_pd_array — Premium чи Discount
6. get_order_blocks — зони великих грошей
7. get_fvg — незаповнені розриви
8. get_atr_context — денний запас ходу >30%
9. get_order_book_walls — стакан китів

ПРАВИЛА ГЕРЧИКА (неможливо порушити):
- Стоп ЗАВЖДИ за структурою рівня
  (не "на відстані індикатора"),
  з невеликим буфером під шум і проскальзування
- RR мінімум 1:2, ідеал 1:3+
- ATR >80% = ПРОПУСК (немає запасу ходу)
- Пробій без підтвердження/ретесту = не вхід
- Хибний пробій = чекаємо повернення і вхід
- Ніколи не рухати стоп проти позиції
- Один невдалий сетап = або нова теза,
  або пауза. Заборонено "відігруватись"

ПОМИЛКИ ЗІ СТОПАМИ (уникати):
- працювати без стопа / без цілі
- надто вузький стоп (вибиває шумом)
- надто широкий стоп (ризик не виправданий)
- рухати стоп проти позиції "щоб не вийшло"
- роздувати ціль з жадібності замість плану

РЕЖИМИ І СТРАТЕГІЇ:
TREND_UP/DOWN → торгуємо по тренду
  від відкатів до зон великих грошей
RANGE → відскоки від країв діапазону,
  не торгуємо середину діапазону
MANIPULATION → чекаємо sweep + підтвердження
  розвороту, тільки після повернення ціни
COMPRESSION → готуємось до пробою,
  не входимо до підтвердження напрямку
NEWS_CHAOS/PANIC → не торгуємо
LOW_LIQUIDITY → не торгуємо

ЧЕКЛІСТ ВХОДУ:
□ Напрямок підтверджений структурою?
□ Ціна в зоні великих грошей (OB/FVG/OTE)?
□ Був sweep ліквідності?
□ ATR дозволяє рух (>30% залишку)?
□ SL чітко визначений?
□ RR > 1:2?
□ Кити підтверджують напрямок?
Менше 5 з 7 = ПРОПУСК

SETUP SCORE СИСТЕМА:
Дозвіл на сигнал тільки якщо score >= 85.

Компоненти:
Ліквідність досягнута: +15
Sweep підтверджено: +20
Displacement (BOS): +15
BTC тримає структуру: +10
Кити в нашому напрямку: +10
Funding здоровий (<0.05%): +10
ATR запас >40%: +10
Немає новин: +10

85+ = СНАЙПЕРСЬКИЙ ВХІД
70-84 = ЧЕКАЄМО
<70 = МОВЧИМО

Ніяких 'можливо' або 'схоже'.
Тільки HIGH PROBABILITY EXECUTION.

НЕ ТОРГУВАТИ якщо:
- ATR day_used > 80%
- Новини через < 30 хвилин
- Режим NEWS_CHAOS або PANIC
- Немає підтвердження після sweep
- Ціна в середині діапазону без рівня
- BTC неясний напрямок
- Стакан проти напрямку

ФОРМАТ ВІДПОВІДІ — ТІЛЬКИ ТАК:
[LONG/SHORT/ПРОПУСК] SYMBOL

Теза: (одне речення — чому)
Вхід: [зона]
Захисний стоп: [ціна] (за [причина])
Ціль 1: [ціна] (+[%])
Ціль 2: [ціна] (+[%])
RR: [число]
Режим: [режим]
Контролює: [хто]
Очікувана цінність: [EV]
Ймовірність маніпуляції: [%]%
Перевага: [A+/B/C] ([score]/100)
Зараз: [ВХОДЬ/ЧЕКАЙ/ПРОПУСКАЄМО]
Де не правий: (умова інвалідації тези)

ЯКЩО ПРОПУСК:
Причина: (одне речення)
Чекаю зону: [low]–[high]
Умова входу: (що має статись)

ЗАБОРОНЕНО:
- Входити без підтвердження ретестом
- Рухати стоп проти позиції
- Торгувати середину діапазону
- Входити на першій свічці після новини
- Довгі пояснення замість конкретних цифр
- Два сигнали по одному символу
- Дублювати те що вже сказала команда

Говориш тільки українською.
Жодних англійських слів.
Ти снайпер. Один постріл — одна ціль.
"""


MARICHKA_RULE = """
Тобі 26 років. Ти Марічка.
Бачиш ринок через структуру і рівні.
Говориш просто як подруга.

ВЕЧІРНІЙ АНАЛІЗ — зверху вниз обов'язково:
1. Місячний/тижневий: куди глобально?
2. Денний: де закрилась свічка?
   Вище/нижче вчорашнього максимуму/мінімуму?
3. 4H: структура і бази (проторговки біля рівнів)
4. 1H: де зона входу?
5. Де стоять великі ордери (стакан)?
6. Хто контролює рух?

СЦЕНАРІЇ (завжди два):
План А: якщо ціна іде вгору
  - де вхід, де стоп, де ціль
План Б: якщо ціна іде вниз
  - де вхід, де стоп, де ціль

УМОВА ІНВАЛІДАЦІЇ:
Що скасовує весь сценарій?

ПРАВИЛА:
- Пробій без закріплення = не вхід
- База (проторговка) біля рівня = сильний сигнал
- Хибний пробій = торгуємо зворотний бік
- Тижневий рівень важливіший за денний

Пиши тільки якщо є конкретний план.
Нічого цікавого — мовчиш.
Максимум 3-4 монети за вечір.
Тільки українська. Жодних англійських слів.
"""


# Легкий спільний базовий блок для НЕ-Лев агентів (Макс/Дарина/Марко/Софія).
# Раніше всі вони ділили герчиківський LEV_RULE і помилково отримували ідентичність
# «Ти Лев, снайпер» + строгий формат відповіді (звідси порожні заголовки в Марка).
DESK_BASE_RULE = """
Ти учасник торгового офісу (desk) з дисципліною рівнів і ризику.
Філософія: спочатку не втратити, потім заробити — капітал важливіший за вхід.
Працюєш у межах СВОЄЇ ролі: не підміняєш стратегічний фінал Лева і ризик-вето Дарини.
Дані не вигадуєш: якщо чогось немає — прямо кажеш "даних недостатньо".
Коротко, по суті, без зайвих заголовків і шаблонних звітів.

МЕТОДОЛОГІЯ ГЕРЧИКА (застосовуй у СВОЇЙ ролі при КОЖНОМУ аналізі ринку, структури і сетапів):
- Аналіз від РІВНІВ: спираємось на сильні рівні з дневки (злам тренду, історичний,
  дзеркальний, лімітний, проторговка). Не торгуємо середину діапазону і плаваючі рівні.
- Підтвердження обов'язкове: сигнал = закриття за рівнем; вхід лише після підтвердження/ретесту.
  Пробій без закріплення ≠ вхід. Хибний пробій (немає імпульсу + повернення за рівень) = сигнал у зворотний бік.
- Запас ходу (ATR): якщо пройдено ~75-80% денного ATR — не по тренду (пропуск або контртренд);
  технічний ATR (відстань між рівнями) має вміщати щонайменше 5 стопів.
- Ризик: стоп ЗА СТРУКТУРУ рівня з невеликим буфером під шум/проскальзування; стоп проти позиції не рухаємо; RR ≥ 1:2 (ідеал 1:3).
- Підготовка: думати як великий гравець (набір позиції, збір стопів довгими хвостами);
  тримати сценарії План А / План Б з умовою інвалідації тези.
"""


TRADING_KNOWLEDGE = """
ATR І ЗАПАС ХОДУ:
Завжди перевіряй get_atr_context перед входом.
>80% пройдено = не входити.
<30% = монета тільки починає рух.

OTE — СНАЙПЕРСЬКИЙ ВХІД:
Після імпульсу чекай відкат в 61.8-78.6%.
Там мінімальний стоп і максимальний хід.
Стоп ЗАВЖДИ за структурою (OB або FVG).
Інструмент: get_ote_levels.

РІВНЕВИЙ ТРЕЙДИНГ (метод Герчика):
Торгуй тільки від сильних рівнів.
Перший тест рівня — найсильніший.
Великий обсяг на рівні = інтерес великих.
Чекай відкат до рівня, не женись за ціною.
Стоп ЗА рівнем, не В рівні.
Інструмент: get_key_levels.

ICT/SMC КОНЦЕПТИ:
BOS/CHOCH — зміна структури тренду.
Order Block — остання свічка перед імпульсом.
FVG — незакритий дисбаланс (магніт для ціни).
Judas Swing — фейковий пробій для збору стопів.
Equal Highs/Lows — ліквідність яку зберуть.
Premium zone (>50% діапазону) — дорого, шукай шорт.
Discount zone (<50% діапазону) — дешево, шукай лонг.
OTE (61.8-78.6%) — оптимальна точка входу.
Power of 3 — накопичення/маніпуляція/розподіл.

СЕСІЙНІ МАНІПУЛЯЦІЇ:
Asian Range (22:00-08:00 UTC):
  збирають ліквідність, формують діапазон.
London (08:00-11:00 UTC):
  часто Judas Swing на початку сесії.
NY (13:00-16:00 UTC):
  справжній рух дня, найважливіша сесія.
Silver Bullet (10:00-11:00 NY time):
  точний вхід після ранкової маніпуляції.

ГРАФІЧНІ ПАТЕРНИ:
Подвійна/потрійна вершина і дно — розворот.
Голова і плечі (і перевернута) — розворот.
Клин висхідний (bearish) / низхідний (bullish).
Прапор і вимпел — продовження тренду.
Трикутники — компресія перед вибухом.
Чашка з ручкою — bullish продовження.

СВІЧКОВИЙ АНАЛІЗ:
Молот (після падіння) — розворот вгору.
Перевернутий молот — потребує підтвердження.
Поглинання бичаче/ведмеже — сильний сигнал.
Доджі — невизначеність, чекай підтвердження.
Зірка ранкова/вечірня — розворот.
Марібозу — сильний імпульс без тіней.

MA ТА ІНДИКАТОРИ:
Golden Cross (MA50 × MA200 вгору) = BULLISH bias.
Death Cross (MA50 × MA200 вниз) = BEARISH bias.
MA200 = динамічна підтримка або опір.
RSI дивергенція = попередження про розворот.
VWAP = fair value, від нього відштовхуються.
Bollinger Bands стиснення = вибух близько.

ІНСТИТУЦІЙНІ ДАНІ:
Long/Short >70% лонги = небезпека (розворот вниз).
Top traders купують = сильний сигнал.
OI росте + ціна росте = сильний тренд.
OI падає + ціна росте = слабкий рух.
Funding >0.01% = лонги переплачують (тиск вниз).
Funding <-0.01% = шорти переплачують (тиск вгору).
Ліквідаційні зони = туди ціна тягнеться.

МАКРО КОРЕЛЯЦІЇ:
DXY росте → тиск на крипто вниз.
Gold росте + SP500 падає → risk-off → крипто під тиском.
SP500 росте → risk-on → крипто може рости.
Перевіряй get_macro_context щоранку.

ПРАВИЛО CONFLUENCE (мінімум 3 з 7):
1. Структура (OB / FVG / рівень Герчика)
2. OTE зона (61.8-78.6% Fibonacci)
3. Активна сесія (London або NY)
4. ATR <70% пройдено
5. OI підтверджує напрямок
6. Funding нейтральний або на боці
7. Патерн свічки на вході
"""


def _analyst_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    min_score = 12 if signal.session.upper() in ("LONDON", "NEW_YORK") else 15
    lv = _level_pack(signal)
    rr = float(signal.meta.get("rr", 2.0))
    vol = float(signal.meta.get("volatility_pct", 0.0))
    level_line = f"Рівні: вхід {_fmt_level(lv['entry'])}, SL {_fmt_level(lv['sl'])}, TP {_fmt_level(lv['tp'])}."
    oi = fetch_open_interest(signal.symbol)
    liq = fetch_liquidations_proxy(signal.symbol)
    funding_disp = _resolve_funding_disp(signal)
    oi_value = oi.get("oi") if isinstance(oi, dict) else None
    oi_note = str(oi.get("oi_note", "")).strip() if isinstance(oi, dict) else ""
    try:
        oi_display = f"{float(oi_value):.0f} USDT" if oi_value is not None else "немає даних"
    except Exception:
        oi_display = str(oi_value) if oi_value is not None else "немає даних"
    if oi_note:
        oi_display = f"{oi_display} {oi_note}"
    oi_history = oi.get("history", []) if isinstance(oi, dict) else []
    system = (
        f"{DESK_BASE_RULE}"
            "МОВА: Ти спілкуєшся ТІЛЬКИ українською. Це абсолютне правило без винятків. "
            "Якщо думка прийшла російською — перекладай перед тим як писати. "
            "Заборонені слова: растут/растет/растемо, может/може (рос), безопасні, заканчується, "
            "жди, мой та будь-які інші російські слова. "
            "Позначення торгової пари латиницею дозволені (формат біржового тікера). "
            "У відповіді користувачу уникай зайвих англіцизмів; скорочення з правил Лева — як у його шаблоні.\n"
        "Тобі 38 років.\n"
        "Ти Макс — ринковий аналітик.\n"
        "Пережив крах 2018 і 2022.\n"
        "Бачиш ринок через цифри — OI, funding, ліквідність.\n"
        "Не довіряєш красивим сетапам без підтвердження даними.\n"
        "Коли бачиш аномалію — попереджаєш одразу, різко.\n"
        "Коли все нормально — кажеш коротко і по суті.\n"
        "Ти пишеш в Telegram груповий чат. Без таблиць, без заголовків ##, без ліній ---. "
        "Звертайся до Тетяни по імені коли доречно. "
        "Звертайся до колег по іменах — Макс, Марічка, Назар, Дарина, Лев, Марко.\n"
        "Говориш українською як досвідчений трейдер у чаті — не як бот і не як викладач.\n"
        "Ніколи не вигадуєш цифри.\n"
        "Якщо даних немає — мовчиш.\n\n"
        f"{TRADING_KNOWLEDGE}"
    )
    context = (
        f"Символ: {signal.symbol}\n"
        f"Напрямок сигналу: {signal.direction}\n"
        f"RR: {rr:.1f}\n"
        f"Волатильність: {vol:.1f}%\n"
        f"BTC 24h: {float(signal.meta.get('btc_change_pct', 0.0) or 0.0):.1f}%\n"
        f"Funding: {funding_disp}\n"
        f"Відкритий інтерес: {oi_display}\n"
        f"OI тренд (USDT): {oi_history}\n"
        f"Ліквідності зверху: {(liq.get('liq_zone_above', 'немає даних') if isinstance(liq, dict) else 'немає даних')}\n"
        f"Ліквідності знизу: {(liq.get('liq_zone_below', 'немає даних') if isinstance(liq, dict) else 'немає даних')}\n"
        f"Поточна ціна: {(liq.get('current_price', 'немає даних') if isinstance(liq, dict) else 'немає даних')}"
    )
    llm_note = clean_llm_note(ask_agent("maks", system, context, max_tokens=1000))
    if signal.regime.upper() == "CHOP":
        note = llm_note or f"Ринок шумний ({vol:.2f}%). Я за пропуск. {level_line}"
        return AgentDecision("maks", "REJECTED", _enforce_data_grounding(note, signal), {"min_score": min_score})
    if signal.score < min_score:
        note = llm_note or f"Сигнал нижче порога ({signal.score} < {min_score}). Поки без входу. {level_line}"
        return AgentDecision("maks", "REJECTED", _enforce_data_grounding(note, signal), {"min_score": min_score})
    note = llm_note or f"Технічно ок: score {signal.score}, rr {rr:.2f}, vol {vol:.2f}%. {level_line}"
    return AgentDecision("maks", "APPROVED", _enforce_data_grounding(note, signal), {"min_score": min_score})


def _bias_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    try:
        btc = float(signal.meta.get("btc_change_pct", 0.0))
        regime = str(signal.regime or "").upper()
        direction = str(signal.direction or "").upper()

        if btc > 1.5:
            bias = "BULLISH"
        elif btc < -1.5:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        if regime == "CHOP":
            bias = "NEUTRAL"

        against = (direction == "LONG" and bias == "BEARISH") or (direction == "SHORT" and bias == "BULLISH")

        signal.meta["daily_bias"] = bias
        signal.meta["against_bias"] = against
        daily = fetch_btc_candles("1d", 3)
        h4 = fetch_btc_candles("4h", 6)
        pdh = daily[-2]["high"] if isinstance(daily, list) and len(daily) >= 2 else None
        pdl = daily[-2]["low"] if isinstance(daily, list) and len(daily) >= 2 else None
        current = daily[-1]["close"] if isinstance(daily, list) and daily else None
        system = (
            f"{MARICHKA_RULE}"
            "МОВА: Ти спілкуєшся ТІЛЬКИ українською. Це абсолютне правило без винятків. "
            "Якщо думка прийшла російською — перекладай перед тим як писати. "
            "Заборонені слова: растут/растет/растемо, может/може (рос), безопасні, заканчується, "
            "жди, мой та будь-які інші російські слова. "
            "Позначення торгової пари латиницею дозволені лише як біржовий тікер. "
            "У відповіді без англіцизмів і без зайвих латинських скорочень.\n"
            "Якщо ринок проти сигналу — кажеш прямо, навіть якщо всі хочуть входити.\n"
            "Говориш просто й образно, без канцеляриту.\n"
            "Ти пишеш в Telegram груповий чат. Без таблиць, без заголовків ##, без ліній ---. "
            "Звертайся до Тетяни по імені коли доречно. "
            "Звертайся до колег по іменах — Макс, Марічка, Назар, Дарина, Лев, Марко.\n"
            "Ніколи не вигадуєш напрямок.\n"
            "Якщо свічок немає — кажеш що не бачиш картини.\n"
        )
        context = (
            f"Символ сигналу: {signal.symbol}\n"
            f"Напрямок сигналу: {signal.direction}\n"
            f"BTC Daily свічки: {daily}\n"
            f"BTC H4 свічки: {h4}\n"
            f"Вчорашній максимум (PDH): {pdh}\n"
            f"Вчорашній мінімум (PDL): {pdl}\n"
            f"Поточна ціна BTC: {current}\n"
            f"BTC 24h зміна: {btc:.1f}%"
        )
        llm_note = clean_llm_note(ask_agent("marichka", system, context, max_tokens=800))

        if llm_note:
            note = llm_note
        elif bias == "BULLISH" and not against:
            note = (
                f"Ринок сьогодні росте 📈 BTC за добу +{btc:.1f}%. "
                f"Твій сигнал по тренду — це добре."
            )
        elif bias == "BEARISH" and not against:
            note = (
                f"Ринок сьогодні падає 📉 BTC за добу {btc:.1f}%. "
                f"Твій сигнал по тренду — це добре."
            )
        elif bias == "NEUTRAL":
            note = (
                f"Ринок зараз без чіткого напрямку 😐 BTC за добу {btc:.1f}%. "
                f"Торгуємо обережно."
            )
        elif bias == "BULLISH" and against:
            note = (
                f"Ринок росте, BTC +{btc:.1f}% 📈 Але твій сигнал SHORT — проти тренду. "
                f"Вдвічі обережніше."
            )
        else:
            note = (
                f"Ринок падає, BTC {btc:.1f}% 📉 Але твій сигнал LONG — проти тренду. "
                f"Вдвічі обережніше."
            )

    except Exception:
        bias = "NEUTRAL"
        against = False
        signal.meta["daily_bias"] = bias
        signal.meta["against_bias"] = against
        note = "Напрямок ринку незрозумілий — торгуємо з мінімальним ризиком."

    return AgentDecision(
        "marichka",
        "APPROVED" if not against else "WAIT",
        note,
        {
            "daily_bias": bias,
            "against_bias": against,
        },
    )


def _news_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    risk = str(signal.meta.get("news_risk", "SAFE")).upper()
    mins = int(signal.meta.get("minutes_to_event", 999))
    event_name = str(signal.meta.get("news_event_name") or signal.meta.get("news_headline") or "невідомо")
    event_time_utc = str(signal.meta.get("news_event_time_utc") or "")
    currency = str(signal.meta.get("news_currency") or "USD")
    importance = str(signal.meta.get("news_importance") or "low").lower()
    kyiv_time = _to_kyiv_time_from_utc(event_time_utc, mins)
    news_note = (
        "Новинний фон чистий. Входити можна."
        if mins >= 999
        else f"Увага! {event_name} через {mins} хв о {kyiv_time} за Києвом."
    )
    if risk == "HIGH":
        return AgentDecision(
            "news",
            "REJECTED",
            _enforce_data_grounding(news_note, signal),
            {"news": "HIGH RISK"},
        )
    if risk == "RISK":
        return AgentDecision(
            "news",
            "WAIT",
            _enforce_data_grounding(news_note, signal),
            {"news": "RISK"},
        )
    return AgentDecision(
        "news",
        "APPROVED",
        _enforce_data_grounding(news_note, signal),
        {"news": "SAFE"},
    )


def _risk_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    lv = _level_pack(signal)
    rr = float(signal.meta.get("rr", 2.0))
    vol = float(signal.meta.get("volatility_pct", 0.0))
    news_flag = any(t.agent_key == "news" and ("HIGH RISK" in t.text or "RISK:" in t.text) for t in conversation)
    risk_levels = f"Контроль: SL {_fmt_level(lv['sl'])}, invalidation по SL."
    snapshot = signal.meta.get("live_risk", {})
    open_total = int(snapshot.get("open_trades_count", 0)) if isinstance(snapshot, dict) else 0
    if open_total > 0:
        risk_levels += f" Відкрито позицій: {open_total}."
    if signal.meta.get("against_bias", False):
        risk_levels += " Сигнал проти тренду — розмір позиції вдвічі менше."

    def _f(val: Any, default: float = 0.0) -> float:
        try:
            return float(val)
        except Exception:
            return default

    funding_disp = _resolve_funding_disp(signal)
    context = (
        f"Сигнал: {signal.direction} {signal.symbol}\n"
        f"BTC за добу: {_f(signal.meta.get('btc_change_pct', 0.0)):.1f}%\n"
        f"Funding: {funding_disp}\n"
        f"RR: {_f(signal.meta.get('rr', 0.0)):.1f}\n"
        f"Волатильність: {_f(signal.meta.get('volatility_pct', 0.0)):.1f}%\n"
        f"Відкритих позицій: {int(snapshot.get('open_trades_count', 0)) if isinstance(snapshot, dict) else 0}\n"
        f"Проти тренду: {bool(signal.meta.get('against_bias', False))}\n"
        f"Денний bias: {signal.meta.get('daily_bias', 'NEUTRAL')}\n"
        f"Новинний ризик: {signal.meta.get('news_risk', 'SAFE')}\n"
        f"Drawdown сьогодні: {_f(signal.meta.get('daily_drawdown', 0.0)):.1f}%"
    )
    system = (
        f"{DESK_BASE_RULE}"
            "МОВА: Ти спілкуєшся ТІЛЬКИ українською. Це абсолютне правило без винятків. "
            "Якщо думка прийшла російською — перекладай перед тим як писати. "
            "Заборонені слова: растут/растет/растемо, может/може (рос), безопасні, заканчується, "
            "жди, мой та будь-які інші російські слова. "
            "Позначення торгової пари латиницею дозволені (формат біржового тікера). "
            "У відповіді користувачу уникай зайвих англіцизмів; скорочення з правил Лева — як у його шаблоні.\n"
        "Тобі 34 роки.\n"
        "Ти Дарина — захищаєш капітал.\n"
        "Особисто пережила злив депозиту.\n"
        "Тепер жорстка але справедлива.\n"
        "Не боїшся сказати НІ команді.\n"
        "Не змінюєш думку під тиском.\n"
        "Говориш прямо, без пом'якшень.\n"
        "Поважаєш Лева але твоє вето останнє слово по ризику.\n"
        "Після збитків — зупиняєш команду.\n"
        "Ти пишеш в Telegram груповий чат. Без таблиць, без заголовків ##, без ліній ---. "
        "Звертайся до Тетяни по імені коли доречно. "
        "Звертайся до колег по іменах — Макс, Марічка, Назар, Дарина, Лев, Марко.\n"
        "Ніколи не вигадуєш стан портфеля."
    )
    llm_note = clean_llm_note(ask_agent("daryna", system, context, max_tokens=800))
    if bool(signal.meta.get("loss_cooldown_active", False)):
        note = llm_note or _enforce_data_grounding(f"Активний cooldown. Вхід переносимо. {risk_levels}", signal)
        return AgentDecision(
            "daryna",
            "WAIT",
            note,
            {"veto": True},
        )
    if news_flag:
        note = llm_note or f"Вето по новинах. До зниження ризику не входимо. {risk_levels}"
        return AgentDecision(
            "daryna",
            "WAIT",
            note,
            {"veto": True},
        )
    if rr < 1.5:
        note = llm_note or _enforce_data_grounding(f"Вето: ризик не виправданий (rr {rr:.2f}). {risk_levels}", signal)
        return AgentDecision(
            "daryna",
            "REJECTED",
            note,
            {"veto": True},
        )
    if vol > 4.5:
        note = llm_note or _enforce_data_grounding(f"Волатильність зависока ({vol:.2f}%). Чекаємо стабілізацію. {risk_levels}", signal)
        return AgentDecision(
            "daryna",
            "WAIT",
            note,
            {"veto": True},
        )
    note = llm_note or _enforce_data_grounding(f"Ризик-контур чистий. Допуск на виконання. {risk_levels}", signal)
    return AgentDecision(
        "daryna",
        "APPROVED",
        note,
        {"veto": False},
    )


def _strategist_reply(
    signal: OfficeSignal,
    conversation: List[ConversationTurn],
    prior_decisions: Optional[List[AgentDecision]] = None,
) -> AgentDecision:
    lv = _level_pack(signal)
    entry = _fmt_level(lv["entry"])
    sl = _fmt_level(lv["sl"])
    tp = _fmt_level(lv["tp"])
    against_bias = bool(signal.meta.get("against_bias", False))
    bias_tail = " Торгуємо проти тренду — підвищена обережність." if against_bias else ""
    # Текстовий розбір реплік (як було) — лишаємо для сумісності зі старою поведінкою.
    has_reject = any("Вето" in t.text or "пропуск" in t.text.lower() or "HIGH RISK" in t.text for t in conversation if t.agent_key in ("maks", "daryna", "news"))
    has_wait = any("Чекаємо" in t.text or "переносимо" in t.text for t in conversation if t.agent_key in ("maks", "daryna"))
    # Надійніший фінал: поважаємо СТРУКТУРНІ рішення ключових ролей (Макс/Назар/Дарина),
    # навіть якщо LLM сформулював текст без тригерних слів. Це може лише посилити
    # обережність (ENTER -> WAIT/SKIP) і ніколи не робить вхід агресивнішим.
    gate_keys = ("maks", "news", "daryna")
    if prior_decisions:
        for d in prior_decisions:
            if d.agent_key not in gate_keys:
                continue
            if d.decision == "REJECTED":
                has_reject = True
            elif d.decision == "WAIT":
                has_wait = True
    final_action: Literal["ENTER", "SKIP", "WAIT"] = "ENTER"
    if signal.regime.upper() == "CHOP" or has_reject:
        final_action = "SKIP"
    elif has_wait:
        final_action = "WAIT"
    team_lines = "\n".join([f"{t.agent_key}: {t.text[:120]}" for t in conversation])
    system = (
        f"{LEV_RULE}"
            "МОВА: Ти спілкуєшся ТІЛЬКИ українською. Це абсолютне правило без винятків. "
            "Якщо думка прийшла російською — перекладай перед тим як писати. "
            "Заборонені слова: растут/растет/растемо, может/може (рос), безопасні, заканчується, "
            "жди, мой та будь-які інші російські слова. "
            "Позначення торгової пари латиницею дозволені (формат біржового тікера). "
            "У відповіді користувачу уникай зайвих англіцизмів; скорочення з правил Лева — як у його шаблоні.\n"
        "Тобі 42 роки.\n"
        "Ти Лев — керуєш офісом.\n"
        "Холодна голова в будь-якій ситуації.\n"
        "Слухаєш всіх перед рішенням.\n"
        "Говориш мало але влучно.\n"
        "Коли кажеш 'входимо' — це не обговорюється.\n"
        "Визнаєш помилки без виправдань.\n"
        "Що тебе дратує: повторні помилки, емоційні рішення, overtrading.\n"
        "Ти пишеш в Telegram груповий чат. Без таблиць, без заголовків ##, без ліній ---. "
        "Звертайся до Тетяни по імені коли доречно. "
        "Звертайся до колег по іменах — Макс, Марічка, Назар, Дарина, Лев, Марко.\n"
        "Ніколи не вигадуєш дані.\n"
        "Якщо немає впевненості — чекаєш.\n\n"
        f"{TRADING_KNOWLEDGE}"
    )
    context = (
        f"Сигнал: {signal.direction} {signal.symbol}\n"
        f"RR: {float(signal.meta.get('rr', 0.0) or 0.0):.1f}\n"
        f"Проти тренду: {against_bias}\n"
        f"Bias: {signal.meta.get('daily_bias', 'NEUTRAL')}\n"
        f"Новинний ризик: {signal.meta.get('news_risk', 'SAFE')}\n\n"
        f"Команда сказала:\n{team_lines}\n\n"
        f"Системне рішення: {final_action}"
    )
    llm_note = clean_llm_note(ask_agent("lev", system, context, max_tokens=2000))
    if signal.regime.upper() == "CHOP":
        note = llm_note or _enforce_data_grounding(f"Ринок шумний. Фінал: пропускаємо.{bias_tail}", signal)
        return AgentDecision("lev", "REJECTED", note)
    if has_reject:
        note = llm_note or _enforce_data_grounding(f"Приймаю вето ризику. Фінал: пропускаємо.{bias_tail}", signal)
        return AgentDecision("lev", "REJECTED", note)
    if has_wait:
        note = llm_note or _enforce_data_grounding(f"Не форсуємо. Чекаємо підтвердження біля {entry}.{bias_tail}", signal)
        return AgentDecision("lev", "WAIT", note)
    note = llm_note or _enforce_data_grounding(f"Контекст нормальний. Фінал: входимо. План: entry {entry}, SL {sl}, TP {tp}.{bias_tail}", signal)
    return AgentDecision(
        "lev",
        "APPROVED",
        note,
    )


def _risk_rebuttal(signal: OfficeSignal, strategist: AgentDecision, prior_risk: AgentDecision) -> Optional[AgentDecision]:
    """
    Conflict round:
    If strategist pushes ENTER while risk is WAIT/REJECTED, risk gets a final rebuttal.
    """
    if strategist.decision != "APPROVED":
        return None
    if prior_risk.decision == "APPROVED":
        return None
    rr = float(signal.meta.get("rr", 2.0))
    vol = float(signal.meta.get("volatility_pct", 0.0))
    text = (
        "Заперечую фінал ENTER. Повторне вето: "
        f"risk conditions не закриті (rr {rr:.2f}, vol {vol:.2f}%)."
    )
    return AgentDecision("daryna", "REJECTED", _enforce_data_grounding(text, signal), {"veto": True, "rebuttal": True})


def _strategist_after_rebuttal(signal: OfficeSignal, rebuttal: AgentDecision) -> AgentDecision:
    if rebuttal.decision == "REJECTED":
        return AgentDecision("lev", "REJECTED", _enforce_data_grounding("Приймаю повторне вето Risk. Фінал: SKIP.", signal))
    return AgentDecision("lev", "WAIT", _enforce_data_grounding("Беремо паузу після Risk-раунду. Фінал: WAIT.", signal))


def _executor_reply(signal: OfficeSignal, final_action: str) -> AgentDecision:
    trail = "EMA50" if bool(signal.meta.get("is_whitelist", True)) else "EMA21"
    lv = _level_pack(signal)
    entry = _fmt_level(lv["entry"])
    sl = _fmt_level(lv["sl"])
    tp = _fmt_level(lv["tp"])
    entry_raw = signal.meta.get("entry_price")
    sl_raw = signal.meta.get("stop_loss")
    tp_raw = signal.meta.get("take_profit")
    system = (
        f"{DESK_BASE_RULE}"
            "МОВА: Ти спілкуєшся ТІЛЬКИ українською. Це абсолютне правило без винятків. "
            "Якщо думка прийшла російською — перекладай перед тим як писати. "
            "Заборонені слова: растут/растет/растемо, может/може (рос), безопасні, заканчується, "
            "жди, мой та будь-які інші російські слова. "
            "Позначення торгової пари латиницею дозволені (формат біржового тікера). "
            "У відповіді користувачу уникай зайвих англіцизмів; скорочення з правил Лева — як у його шаблоні.\n"
        "Тобі 29 років.\n"
        "Ти Марко — перетворюєш рішення в конкретний план.\n"
        "Любиш точність і структуру.\n"
        "Коли є рівні — даєш план чітко.\n"
        "Коли рівнів немає — кажеш що не можеш дати план без цифр.\n"
        "Іноді жартуєш про ринок — але тільки поза активним сигналом.\n"
        "Говориш технічно але зрозуміло.\n"
        "Ти пишеш в Telegram груповий чат. Без таблиць, без заголовків ##, без ліній ---. "
        "Звертайся до Тетяни по імені коли доречно. "
        "Звертайся до колег по іменах — Макс, Марічка, Назар, Дарина, Лев, Марко.\n"
        "Ніколи не вигадуєш ціни.\n\n"
        f"{TRADING_KNOWLEDGE}"
    )
    context = (
        f"Символ: {signal.symbol}\n"
        f"Напрямок: {signal.direction}\n"
        f"Entry: {entry_raw if entry_raw else 'не отримано'}\n"
        f"Stop Loss: {sl_raw if sl_raw else 'не отримано'}\n"
        f"Take Profit: {tp_raw if tp_raw else 'не отримано'}\n"
        f"RR: {float(signal.meta.get('rr', 0.0) or 0.0):.1f}\n"
        f"Рішення команди: {final_action}"
    )
    llm_note = clean_llm_note(ask_agent("marko", system, context, max_tokens=800))
    if final_action == "ENTER":
        note = llm_note or _enforce_data_grounding(
            f"Вхід {signal.direction} {signal.symbol}. Рівні: entry {entry}, SL {sl}, TP {tp}. "
            f"Супровід за {trail}. Якщо SL пробито — без добору проти руху.",
            signal,
        )
        return AgentDecision(
            "marko",
            "APPROVED",
            note,
            {"trail_mode": trail},
        )
    if final_action == "WAIT":
        note = llm_note or _enforce_data_grounding(f"Рішення: чекаємо по {signal.symbol} до повторного тригера.", signal)
        return AgentDecision(
            "marko",
            "WAIT",
            note,
            {"trail_mode": trail},
        )
    note = llm_note or _enforce_data_grounding(f"Рішення: пропускаємо {signal.symbol} за командним рішенням.", signal)
    return AgentDecision(
        "marko",
        "REJECTED",
        note,
        {"trail_mode": trail},
    )


def _decide_chain(signal: OfficeSignal, db_path: str = "office_bridge.db") -> OfficeVerdict:
    decisions: List[AgentDecision] = []
    conversation: List[ConversationTurn] = []

    analyst = _analyst_reply(signal, conversation)
    decisions.append(analyst)
    conversation.append(ConversationTurn(analyst.agent_key, analyst.note))

    bias = _bias_reply(signal, conversation)
    decisions.append(bias)
    conversation.append(ConversationTurn(bias.agent_key, bias.note))
    signal.meta["daily_bias"] = bias.payload.get("daily_bias", "NEUTRAL")
    signal.meta["against_bias"] = bias.payload.get("against_bias", False)

    news = _news_reply(signal, conversation)
    decisions.append(news)
    conversation.append(ConversationTurn(news.agent_key, news.note))

    snapshot = live_risk_snapshot(db_path)
    signal.meta["live_risk"] = snapshot
    risk = _risk_reply(signal, conversation)
    decisions.append(risk)
    conversation.append(ConversationTurn(risk.agent_key, risk.note))

    strategist = _strategist_reply(signal, conversation, decisions)
    decisions.append(strategist)
    conversation.append(ConversationTurn(strategist.agent_key, strategist.note))

    # Conflict round: strategist ENTER vs risk veto/wait.
    rebuttal = _risk_rebuttal(signal, strategist, risk)
    if rebuttal is not None:
        decisions.append(rebuttal)
        conversation.append(ConversationTurn(rebuttal.agent_key, rebuttal.note))
        strategist2 = _strategist_after_rebuttal(signal, rebuttal)
        decisions.append(strategist2)
        conversation.append(ConversationTurn(strategist2.agent_key, strategist2.note))
        strategist = strategist2

    final_action: Literal["ENTER", "SKIP", "WAIT"] = "ENTER"
    if strategist.decision == "REJECTED":
        final_action = "SKIP"
    elif strategist.decision == "WAIT":
        final_action = "WAIT"

    executor = _executor_reply(signal, final_action)
    decisions.append(executor)

    summary = {
        "ENTER": "Команда узгодила вхід після технічної та ризикової перевірки.",
        "WAIT": "Команда відклала рішення до кращого ринкового вікна.",
        "SKIP": "Команда відхилила кейс через ризик/контекст.",
    }[final_action]
    return OfficeVerdict(final_action, decisions, summary)


def _fmt_verdict(signal: OfficeSignal, verdict: OfficeVerdict) -> str:
    action_ua = {"ENTER": "ВХІД", "SKIP": "ПРОПУСК", "WAIT": "ОЧІКУВАННЯ"}.get(verdict.action, verdict.action)
    return (
        f"✅ *#Загальний · Вердикт офісу* #{signal.signal_id}\n"
        f"Символ: `{signal.symbol}` · Напрям: `{signal.direction}` · Score: `{signal.score}`\n"
        f"Сесія: `{signal.session}` · Режим: `{signal.regime}`\n"
        f"Рішення: *{action_ua}*\n"
        f"Підсумок: {verdict.summary}"
    )


def _fmt_closed_case(symbol: str, outcome: str, pnl_pct: float, note: str) -> str:
    em = "✅" if outcome == "WIN" else ("🟥" if outcome == "LOSS" else "🟨")
    extra = f"\nНотатка: {note}" if note else ""
    return (
        f"{em} *#Загальний · Закриття кейсу*\n"
        f"Символ: `{symbol}` · Результат: `{outcome}` · PnL: `{pnl_pct:+.2f}%`"
        f"{extra}"
    )


async def office_welcome(sender: AsyncSender) -> None:
    await sender("🏢 *#Загальний · AI OFFICE ROOM*\nКоманда на місці. Працюємо як trading desk 24/7.")
    await agent_say(sender, "lev", "Всім доброго дня. Тримаємо фокус на чистих сетапах і дисципліні.", 0.05)
    await agent_say(sender, "maks", "На зв'язку. Беру quality-check і швидкий фактчек по цифрах.", 0.05)
    await agent_say(sender, "news", "News desk online. Даю тільки SAFE/RISK/HIGH RISK без води.", 0.05)
    await agent_say(sender, "daryna", "Ризик-периметр активний. Моє НІ — фінальне, депозит пріоритет №1.", 0.05)
    await agent_say(sender, "marko", "Execution desk online. Даю короткі технічні команди без шуму.", 0.05)
    await agent_say(sender, "olesya", "Аналітика + позиції online: фіксую рішення, веду відкриті угоди по тригерах.", 0.05)
    await agent_say(sender, "memory", "Тримаю історичну пам'ять сетапів: що працювало, а що ні.", 0.05)
    await agent_say(sender, "psych", "Слідкую за дисципліною команди: без tilt і емоційних входів.", 0.05)
    await agent_say(sender, "dev", "Технічний контроль активний: бот, API і Mini App під наглядом.", 0.05)


def get_agent_card_text(agent_key: str) -> str:
    a = AGENTS[agent_key]
    return (
        f"{a.emoji} *{a.name} «{a.nickname}»*\n"
        f"Роль: {a.role}\n"
        f"Характер: {a.character}\n"
        f"Зона: {a.responsibility}"
    )


async def office_morning_briefing(
    sender: AsyncSender,
    session: str,
    market_state: str,
    btc_bias: str,
) -> None:
    await sender(
        f"🌅 *#Загальний · Ранковий брифінг*\n"
        f"Час за Києвом: `{_now_kyiv_hm()}` · Сесія: `{session}` · Режим: `{market_state}` · BTC: `{btc_bias}`"
    )
    await agent_say(sender, "lev", "Фокус дня: дисципліна і чисті входи. Без форсу.", 0.08)
    await agent_say(sender, "maks", "Я на якості. Все нижче порога — відсікаю без емоцій.", 0.08)
    await agent_say(sender, "daryna", "Контроль ризику жорсткий. Ліміти сьогодні не порушуємо.", 0.08)
    await agent_say(sender, "marko", "Execution-план готовий. Працюємо короткими точними діями.", 0.08)
    await agent_say(sender, "olesya", "Веду лог desk-рішень та статистику змін у реальному часі.", 0.08)


async def office_evening_debrief(
    sender: AsyncSender,
    *,
    btc_change_pct: float,
    journal_summary: str,
) -> None:
    """
    Вечірній debrief після сесії (MASTER п.28). Короткий підсумок + репліки команди.
    """
    js = (journal_summary or "").strip()[:650]
    await sender(
        f"🌆 *#Загальний · Вечірній debrief*\n"
        f"Час за Києвом: `{_now_kyiv_hm()}` · BTC 24г `{btc_change_pct:+.2f}%`\n"
        f"{js}"
    )
    await agent_say(sender, "olesya", "День на столі зафіксовано. Завтра продовжимо з тим самим фокусом на дисципліні.", 0.07)
    await agent_say(sender, "lev", "Гарна робота. Завтра знову тільки чисті сетапи, без форсу.", 0.07)
    await agent_say(sender, "psych", "Відпочинь від екранів — завтра заходимо без зайвого емоційного багажу.", 0.07)
    await agent_say(sender, "daryna", "Капітал під контролем — це найкращий результат. Завтра знову жорсткий ризик-периметр.", 0.07)


async def office_emergency_alert(
    sender: AsyncSender,
    alert_type: Literal["PUMP", "DUMP", "SWEEP"],
    symbol: str = "",
    value: float = 0.0,
) -> None:
    if alert_type == "PUMP":
        await sender(
            f"🚨 *#Інфраструктура · PUMP ALERT*\n"
            f"`{symbol}` рух `{value:+.2f}%` за коротке вікно."
        )
        await agent_say(sender, "maks", f"Бачу імпульс по {symbol}. Перевіряю чи не пізній вхід.", 0.05)
        await agent_say(sender, "daryna", "Без chase. Спершу ризик, потім дія.", 0.05)
        return
    if alert_type == "DUMP":
        await sender(
            f"🚨 *#Інфраструктура · DUMP ALERT*\n"
            f"BTC рух `{value:+.2f}%` — підвищена волатильність."
        )
        await agent_say(sender, "daryna", "Тимчасово затискаю ризик. LONG тільки за преміум-підтвердження.", 0.05)
        await agent_say(sender, "lev", "Працюємо від оборони, без агресивних доборів.", 0.05)
        return
    await sender("🚨 *#Інфраструктура · SWEEP ALERT*\nЗафіксовано sweep ключового діапазону.")
    await agent_say(sender, "lev", "Чекаємо підтвердження напрямку. Перший рух може бути пасткою.", 0.05)
    await agent_say(sender, "marko", "Поки пауза. Чекаємо чіткий сигнал.", 0.05)


async def office_handle_signal(
    sender: AsyncSender,
    signal: OfficeSignal,
    db_path: str = "office_bridge.db",
) -> OfficeVerdict:
    # Kill Zone gate (UTC-based): trading decision belongs to Bridge, not relay.
    utc_now = datetime.now(timezone.utc)
    session_active = is_kill_zone(utc_now)
    signal.session = _kill_zone_session_name(utc_now)
    signal.meta["outside_session"] = not session_active

    kz_mode = str(os.getenv("KILL_ZONE_MODE", "strict") or "strict").strip().lower()
    if kz_mode not in ("strict", "soft"):
        kz_mode = "strict"

    if not session_active:
        # For downstream agents / future ChatGPT session filter.
        signal.meta["chatgpt_session_flag"] = "outside_session"
        # Soft mode keeps discussion/flow but halves position intent.
        if kz_mode == "soft":
            signal.meta["position_size_multiplier"] = 0.5
            signal.meta["kill_zone_mode"] = "soft"
        else:
            signal.meta["kill_zone_mode"] = "strict"

    log_event(db_path, "SIGNAL_RECEIVED", {"symbol": signal.symbol, "direction": signal.direction}, signal.signal_id)
    task_id = f"TASK-{signal.signal_id}"
    title = f"Review signal {signal.symbol} {signal.direction}"
    ok, reason = transition_task(
        db_path,
        task_id=task_id,
        title=title,
        assignee="lev",
        new_status="OPEN",
        payload={"score": signal.score, "session": signal.session},
    )
    if not ok:
        log_event(db_path, "TASK_TRANSITION_ERROR", {"task_id": task_id, "reason": reason})

    if not session_active and kz_mode == "strict":
        log_event(
            db_path,
            "KILL_ZONE_BLOCK",
            {
                "reason": "blocked: outside_kill_zone",
                "symbol": signal.symbol,
                "direction": signal.direction,
                "utc_now": utc_now.strftime("%H:%M"),
                "kyiv_now": _now_kyiv_hm(),
                "kill_zone_mode": kz_mode,
                "outside_session": True,
            },
            signal.signal_id,
        )
        await sender(
            "Поза Kill Zone (вікна за **UTC** ринку: London 08:00–11:00, NY 13:00–16:00). "
            f"Зараз за Києвом: `{_now_kyiv_hm()}`. Новий вхід блокуємо. Рішення: пропускаємо."
        )
        verdict = OfficeVerdict(
            "SKIP",
            [
                AgentDecision(
                    "lev",
                    "REJECTED",
                    _enforce_data_grounding(
                        "Поза Kill Zone. Пропускаємо сигнал і чекаємо активну сесію London/NY.",
                        signal,
                    ),
                    {"kill_zone_block": True, "outside_session": True},
                ),
            ],
            "blocked: outside_kill_zone",
        )
        prev_agent: Optional[str] = None
        for idx, d in enumerate(verdict.decisions, start=1):
            pre = _cross_reply_prefix(prev_agent, d.agent_key)
            out = f"{pre}{d.note}" if pre else d.note
            await agent_say(sender, d.agent_key, out)
            log_message(db_path, signal.signal_id, idx, d.agent_key, out)
            prev_agent = d.agent_key
            ok, reason = transition_task(
                db_path,
                task_id=task_id,
                title=title,
                assignee=d.agent_key,
                new_status="BLOCKED",
                payload={"decision": d.decision, "note": d.note, "reason": "blocked: outside_kill_zone"},
            )
            if not ok:
                log_event(db_path, "TASK_TRANSITION_ERROR", {"task_id": task_id, "reason": reason, "agent": d.agent_key})
        ok, reason = transition_task(
            db_path,
            task_id=task_id,
            title=title,
            assignee="olesya",
            new_status="DONE",
            payload={"final_action": verdict.action, "summary": verdict.summary},
        )
        if not ok:
            log_event(db_path, "TASK_TRANSITION_ERROR", {"task_id": task_id, "reason": reason, "agent": "olesya"})
        olesya_note = _olesya_reply(signal, verdict, db_path)
        await agent_say(sender, "olesya", olesya_note, 0.05)
        log_verdict(db_path, signal, verdict)
        return verdict

    await sender(f"Новий кейс: {signal.symbol} {signal.direction}. Команда на розборі.")
    await sender(f"#{str(signal.symbol).upper()}_{str(signal.direction).upper()}")

    try:
        disc_every = int(os.getenv("OFFICE_DISCIPLINE_REVIEW_EVERY", "0") or "0")
    except Exception:
        disc_every = 0
    if disc_every >= 2:
        c_closed = journal_closed_trade_count(db_path)
        if c_closed > 0 and c_closed % disc_every == 0:
            await sender(
                f"📋 Discipline check: у журналі вже {c_closed} закритих угод (кратно {disc_every}). "
                "Короткий обов’язковий review перед новим входом (MASTER п.36)."
            )

    cb_disabled = os.getenv("OFFICE_CIRCUIT_DISABLE", "").strip() == "1"
    try:
        cb_need = max(3, int(os.getenv("OFFICE_CIRCUIT_LOSSES", "3") or "3"))
    except Exception:
        cb_need = 3
    try:
        cb_drawdown = max(0.1, float(os.getenv("OFFICE_CIRCUIT_DRAWDOWN", "4") or "4"))
    except Exception:
        cb_drawdown = 4.0
    loss_streak = journal_consecutive_loss_streak(db_path)
    dd_pct = daily_drawdown_pct(db_path)
    streak_hit = loss_streak >= cb_need
    dd_hit = dd_pct >= cb_drawdown
    cb_hit = streak_hit or dd_hit
    if not cb_disabled and cb_hit:
        if streak_hit and dd_hit:
            cb_text = f"⚠️ Circuit breaker: {cb_need}+ SL підряд і -{dd_pct:.1f}% за день. Вхід заборонено."
        elif streak_hit:
            cb_text = f"⚠️ Circuit breaker: {cb_need}+ SL підряд. Вхід заборонено."
        else:
            cb_text = f"⚠️ Circuit breaker: -{dd_pct:.1f}% за день. Вхід заборонено."
        log_event(
            db_path,
            "CIRCUIT_BREAKER",
            {
                "streak_now": loss_streak,
                "streak_need": cb_need,
                "daily_drawdown_pct": dd_pct,
                "daily_drawdown_need": cb_drawdown,
                "symbol": signal.symbol,
            },
            signal.signal_id,
        )
        await sender(cb_text)
        # Один крок з Левом: інакше другий REJECTED після BLOCKED ламає FSM задачі (OPEN→BLOCKED→BLOCKED).
        verdict = OfficeVerdict(
            "SKIP",
            [
                AgentDecision(
                    "lev",
                    "REJECTED",
                    _enforce_data_grounding(
                        cb_text,
                        signal,
                    ),
                    {"circuit_breaker": True, "streak_now": loss_streak, "daily_drawdown_pct": dd_pct},
                ),
            ],
            f"Автоматичне блокування після {cb_need}+ SL поспіль (MASTER п.31).",
        )
    else:
        verdict = _decide_chain(signal, db_path)

    # Keep room readable: only one task line at open and one at close.
    prev_agent: Optional[str] = None
    for idx, d in enumerate(verdict.decisions, start=1):
        pre = _cross_reply_prefix(prev_agent, d.agent_key)
        out = f"{pre}{d.note}" if pre else d.note
        await agent_say(sender, d.agent_key, out)
        log_message(db_path, signal.signal_id, idx, d.agent_key, out)
        prev_agent = d.agent_key
        next_status: TaskStatus = "IN_PROGRESS"
        if d.agent_key == "marko":
            next_status = "REVIEW"
        if d.decision == "REJECTED" and d.agent_key in ("daryna", "lev"):
            next_status = "BLOCKED"
        ok, reason = transition_task(
            db_path,
            task_id=task_id,
            title=title,
            assignee=d.agent_key,
            new_status=next_status,
            payload={"decision": d.decision, "note": d.note},
        )
        if not ok:
            log_event(db_path, "TASK_TRANSITION_ERROR", {"task_id": task_id, "reason": reason, "agent": d.agent_key})

    final_task_status: TaskStatus = "DONE" if verdict.action in ("ENTER", "SKIP") else "IN_PROGRESS"
    ok, reason = transition_task(
        db_path,
        task_id=task_id,
        title=title,
        assignee="olesya",
        new_status=final_task_status,
        payload={"final_action": verdict.action, "summary": verdict.summary},
    )
    if not ok:
        log_event(db_path, "TASK_TRANSITION_ERROR", {"task_id": task_id, "reason": reason, "agent": "olesya"})
    olesya_note = _olesya_reply(signal, verdict, db_path)
    await agent_say(sender, "olesya", olesya_note, 0.05)
    log_verdict(db_path, signal, verdict)
    return verdict


async def office_trade_closed(
    sender: AsyncSender,
    symbol: str,
    outcome: Literal["WIN", "LOSS", "BE"],
    pnl_pct: float,
    note: str = "",
    db_path: str = "office_bridge.db",
) -> None:
    await sender(_fmt_closed_case(symbol, outcome, pnl_pct, note))
    if outcome == "WIN":
        await agent_say(sender, "marko", "План виконано чисто. Фіксація без жадібності спрацювала.", 0.06)
        await agent_say(sender, "olesya", "Додаю патерн у best-practices та піднімаю вагу цього сценарію.", 0.06)
    elif outcome == "LOSS":
        await agent_say(sender, "daryna", "Лосс контрольований. Капітал цілий — це головне.", 0.06)
        await agent_say(sender, "olesya", "Роблю короткий розбір: контекст, таймінг і що виправити далі.", 0.06)
    else:
        await agent_say(sender, "lev", "Нейтральне закриття — це нормально. Переходимо до наступного чистого сетапу.", 0.06)
    log_event(db_path, "CASE_CLOSED", {"symbol": symbol, "outcome": outcome, "pnl_pct": pnl_pct, "note": note})


async def office_position_event(
    sender: AsyncSender,
    symbol: str,
    event_type: Literal["PRICE_UPDATE", "PARTIAL_CLOSE", "MOVE_SL", "EXIT"],
    details: str,
    db_path: str = "office_bridge.db",
) -> None:
    labels = {"PRICE_UPDATE": "оновлення", "PARTIAL_CLOSE": "часткова фіксація", "MOVE_SL": "перенесення стопа", "EXIT": "вихід"}
    await agent_say(sender, "olesya", f"{symbol}: {labels[event_type]} — {details}", 0.03)
    log_event(db_path, "POSITION_EVENT", {"symbol": symbol, "event_type": event_type, "details": details})


async def office_news_trigger(
    sender: AsyncSender,
    risk_level: Literal["SAFE", "RISK", "HIGH RISK"],
    headline: str,
    minutes_to_event: int,
    db_path: str = "office_bridge.db",
) -> None:
    risk_ua = {"SAFE": "СПОКІЙНО", "RISK": "УВАГА", "HIGH RISK": "ВИСОКИЙ РИЗИК"}.get(risk_level, risk_level)
    short_headline = "Важлива макроподія в календарі."
    if str(headline or "").strip():
        short_headline = "Подія в календарі потребує обережності."
    t_ky = _to_kyiv_time(max(0, int(minutes_to_event)))
    await agent_say(
        sender,
        "news",
        f"{risk_ua}: подія через {minutes_to_event} хв (~о {t_ky} за Києвом). {short_headline}",
        0.02,
    )
    if risk_level == "HIGH RISK":
        await agent_say(sender, "daryna", "Вето по новинах. Нові входи тимчасово блокуємо.", 0.02)
        await agent_say(sender, "marko", "Рішення: пауза, діє новинне блокування.", 0.02)
    elif risk_level == "RISK":
        await agent_say(sender, "lev", "Знижаємо агресію. Тільки преміум-кейси.", 0.02)
    log_event(
        db_path,
        "NEWS_TRIGGER",
        {"risk_level": risk_level, "headline": headline, "minutes_to_event": minutes_to_event},
    )


async def office_daily_wrap(
    sender: AsyncSender,
    wins: int,
    losses: int,
    be: int,
    top_note: str = "",
) -> None:
    total = wins + losses + be
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
    await sender(
        "📌 *#Загальний · Денний підсумок*\n"
        f"Угод: `{total}` · W `{wins}` · L `{losses}` · BE `{be}` · WR `{wr:.1f}%`"
    )
    if top_note:
        await sender(f"🧠 *#Задачник · Нотатка навчання*\n{top_note}")
    await agent_say(sender, "olesya", "День закрито. Завтра стартуємо з оновленим learning-фокусом.", 0.05)


def _extract_first_usdt_symbol(text: str) -> str:
    up = text.upper()
    m = re.search(r"\b[A-Z0-9]{2,15}USDT\b", up)
    return m.group(0) if m else "BTCUSDT"


def _fmt_tv(symbol: str) -> str:
    s = symbol.upper().replace("USDT", "")
    return f"https://www.tradingview.com/chart/?symbol=BINANCE%3A{symbol.upper()}"


def _cross_reply_prefix(prev_key: Optional[str], cur_key: str) -> str:
    """
    Короткий «підхоплення» попередньої репліки (MASTER п.24), без зміни логіки рішень.
    """
    if not prev_key or prev_key == cur_key:
        return ""
    key = (prev_key, cur_key)
    if key == ("maks", "news"):
        return ""
    if key == ("news", "daryna"):
        return ""
    if key == ("daryna", "memory"):
        return ""
    if key == ("memory", "psych"):
        return ""
    if key == ("psych", "dev"):
        return ""
    if key == ("dev", "lev"):
        return ""
    if key == ("lev", "marko"):
        return ""
    return ""


def _simple_ua(agent_key: str, note: str) -> str:
    """
    Convert desk notes to short plain-UA style for interactive Q&A.
    Keeps logic, removes heavy wording.
    """
    n = str(note or "").strip()
    low = n.lower()
    def one_line(s: str) -> str:
        return " ".join(str(s).replace("\n", " ").split())
    if agent_key == "lev":
        if "skip" in low:
            return one_line("Зараз ринок слабкий. Краще пропустити угоду.")
        if "wait" in low:
            return one_line("Поки не входимо. Чекаємо кращий момент.")
        return one_line("Ринок виглядає нормально. Можна розглядати вхід.")
    if agent_key == "maks":
        if "rejected" in low or "пропуск" in low or "нижче порога" in low:
            return one_line("Сигнал слабкий по цифрах. Краще не входити.")
        return one_line("По цифрах сигнал нормальний. Можна передати в ризик.")
    if agent_key == "news":
        if "high risk" in low:
            return one_line("Є небезпечні новини. Вхід зараз ризикований.")
        if "risk" in low:
            return one_line("Новинний ризик підвищений. Краще трохи почекати.")
        return one_line("Критичних новин поруч немає.")
    if agent_key == "daryna":
        if "вето" in low or "rejected" in low:
            return one_line("Ризик завеликий. Я забороняю цей вхід.")
        if "wait" in low or "cooldown" in low:
            return one_line("Поки рано входити. Бережемо депозит.")
        return one_line("Ризик під контролем. Вхід можливий з малим ризиком.")
    if agent_key == "marko":
        if "final decision: enter" in low:
            return one_line("План такий: вхід дозволено. Ставимо стоп і тейк.")
        if "final decision: wait" in low:
            return one_line("План такий: чекаємо, поки ринок підтвердить рух.")
        if "final decision: skip" in low:
            return one_line("План такий: пропускаємо цю угоду.")
        return one_line("Робимо тільки чіткі дії по плану.")
    if agent_key == "olesya":
        return one_line("Я зафіксувала рішення в журнал. Помилки теж запишу, щоб не повторювати.")
    if agent_key == "memory":
        if "winrate" in low or "%" in low:
            return one_line("Історія схожа. Є шанс, але без поспіху.")
        return one_line(n or "Історія підказує, що треба звірити сетап з подібними кейсами.")
    if agent_key == "psych":
        return one_line(n or "Головне без емоцій. Працюємо спокійно і по плану.")
    if agent_key == "dev":
        return one_line(n or "Технічно все працює. Якщо буде збій — повідомлю одразу.")
    return one_line(n)


def _memory_reply(symbol: str, market: Dict[str, Any], db_path: str = "office_bridge.db") -> str:
    fb = journal_latest_feedback_case(db_path, symbol=symbol)
    system = (
        f"{DESK_BASE_RULE}"
        "МОВА: Ти пишеш ТІЛЬКИ українською.\n"
        "Тобі 29 років.\n"
        "Ти Софія — аналітик історичної пам'яті трейдинг-офісу.\n"
        "Спокійна, структурна, data-first. Не вигадуєш статистику.\n"
        "Даєш 1-2 короткі речення без markdown-заголовків і без списків."
    )
    context = (
        f"Символ: {symbol}\n"
        f"BTC 24г (%): {float(market.get('btc_change_pct', 0.0)):+.2f}\n"
        f"{symbol} 24г (%): {float(market.get('sym_change_pct', 0.0)):+.2f}\n"
        f"Волатильність (%): {float(market.get('volatility_pct', 0.0)):.2f}\n"
        f"Новинний ризик: {market.get('news_risk', 'SAFE')}\n"
        f"Хвилин до події: {int(market.get('minutes_to_event', 999))}\n"
        f"Останній кейс з фідбеком: {json.dumps(fb, ensure_ascii=False)}\n"
        "Задача: коротко сказати, як історично поводитися обережно в подібному контексті."
    )
    llm_note = clean_llm_note(ask_agent("memory", system, context, max_tokens=600))
    if llm_note:
        return llm_note
    if fb:
        outcome = str(fb.get("outcome") or "N/A")
        ftxt = str(fb.get("feedback_text") or "без тексту")
        lnote = str(fb.get("learning_note") or "працюємо від підтвердження.")
        return (
            f"По {symbol} минулий схожий кейс: {outcome}. "
            f"Фідбек: \"{ftxt}\". Висновок: {lnote}"
        )
    return (
        f"По {symbol} є схожі записи в журналі — без RAG / агрегації точний winrate не цитую. "
        "Звіряй факти, не форсуй вхід."
    )


def _psych_reply(recurring: Dict[str, int]) -> str:
    system = (
        f"{VICTOR_RULE}\n"
        "МОВА: Ти пишеш ТІЛЬКИ українською.\n"
        "Задача: коротка настанова по дисципліні перед наступним рішенням."
    )
    top = ", ".join(f"{k} x{v}" for k, v in sorted(recurring.items(), key=lambda x: (-x[1], x[0]))[:3]) or "немає"
    context = (
        f"Повторювані помилки з журналу: {top}\n"
        f"Кількість повторюваних тегів: {len(recurring)}\n"
        "Задача: дати команді коротку настанову по дисципліні перед наступним рішенням."
    )
    llm_note = clean_llm_note(ask_agent("psych", system, context, max_tokens=600))
    if llm_note:
        return llm_note
    if not recurring:
        return "Емоційний фон нормальний. Працюємо спокійно, без поспіху."
    top2 = ", ".join(f"{k} x{v}" for k, v in sorted(recurring.items(), key=lambda x: (-x[1], x[0]))[:2])
    return (
        f"Бачу повторювані помилки: {top2}. "
        "Сьогодні тримаємо дисципліну і зменшуємо агресію."
    )


def _olesya_reply(signal: OfficeSignal, verdict: OfficeVerdict, db_path: str = "office_bridge.db") -> str:
    closed = journal_closed_trade_count(db_path)
    recurring = journal_recurring_mistakes(db_path, lookback_losses=60, min_count=2)
    system = (
        f"{OLESYA_RULE}\n"
        "МОВА: Ти пишеш ТІЛЬКИ українською.\n"
        "Даєш 1-2 речення: що зафіксовано і який learning-фокус далі. Не вигадуєш чисел."
    )
    context = (
        f"Сигнал: {signal.symbol} {signal.direction}\n"
        f"Сесія: {signal.session}\n"
        f"Режим: {signal.regime}\n"
        f"Фінальна дія офісу: {verdict.action}\n"
        f"Підсумок: {verdict.summary}\n"
        f"К-сть закритих угод у журналі: {closed}\n"
        f"Повторювані теги помилок (loss): {json.dumps(recurring, ensure_ascii=False)}\n"
        "Задача: коротко зафіксувати результат і дати фокус на наступні кейси."
    )
    llm_note = clean_llm_note(ask_agent("olesya", system, context, max_tokens=600))
    if llm_note:
        return llm_note
    return "Зафіксувала результат у журнал і статистику."


def _dev_reply(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ("mini app", "miniapp", "рендер", "render", "кнопк", "open office")):
        return "Mini App і кнопка Open Office на контролі. Якщо щось падає — розпишу кроки без води."
    if any(k in q for k in ("api", "бот", "relay", "помилка", "error")):
        return "По API й боту зараз тихо. Якщо зʼявиться аномалія — скажу одразу, коротко."
    return "Інфраструктура в нормі. Тримаю руку на пульсі: бот, API, Mini App."


SCENARIO_TEMPLATES: Dict[str, List[tuple[str, str]]] = {
    "asia_strong": [
        ("lev", "Бачу чистий сетап. @Дарина, працюємо акуратно і по плану."),
        ("memory", "Схожі кейси в журналі є — точний % без бази не називаю, без форсу."),
        ("marko", "Технічно ок. @Макс, фон ринку нормальний, можемо працювати."),
        ("daryna", "Приймаю. Ризик 1%, без форсу."),
        ("marko", "Фінальне рішення: ВХІД"),
    ],
    "weak_skip": [
        ("maks", "Увага, фон слабкий. @Марко, ліквідність не подобається."),
        ("marko", "Підтверджую: спред/ліквідність слабкі, вхід неякісний."),
        ("memory", "Історично такі входи часто закінчуються стопом."),
        ("daryna", "Ризик завеликий. Скасовуємо."),
        ("marko", "Фінальне рішення: ПРОПУСК"),
    ],
    "daryna_question": [
        ("daryna", "Командо, що думаєте по ETHUSDT зараз?"),
        ("lev", "Тренд є, але краще дочекатися підтвердження."),
        ("maks", "По новинах тихо, але ринок трохи нервовий."),
        ("marko", "Технічно можна, але краще вхід після ретесту."),
        ("daryna", "Прийнято. Поки чекаємо."),
        ("marko", "Фінальне рішення: ОЧІКУВАННЯ"),
    ],
    "win_close": [
        ("marko", "TP досягнуто, фіксація виконана."),
        ("olesya", "Записала в журнал: профіт, план виконано чисто."),
        ("lev", "Гарна дисципліна, командо. Працюємо далі так само."),
    ],
    "loss_streak": [
        ("olesya", "За сьогодні вже 3 SL підряд."),
        ("psych", "Стоп, без емоцій. @Дарина, беремо паузу і знижуємо агресію."),
        ("daryna", "Підтримую. Працюємо тільки преміум-сетапи."),
    ],
    "morning": [
        ("lev", "Доброго ранку, командо. Фокус: тільки чисті входи."),
        ("maks", "Новини спокійні, критичних подій зараз немає."),
        ("memory", "Вчорашні схожі сетапи відпрацювали добре."),
        ("dev", "Техніка стабільна: бот, API і Mini App в нормі."),
        ("daryna", "План дня прийнято. Працюємо дисципліновано."),
    ],
}


def scenario_keys_text() -> str:
    keys = ", ".join(sorted(SCENARIO_TEMPLATES.keys()))
    return f"Доступні сценарії: `{keys}`"


async def office_run_scenario(
    sender: AsyncSender,
    *,
    scenario_key: str,
    db_path: str = "office_bridge.db",
) -> bool:
    key = str(scenario_key or "").strip().lower()
    lines = SCENARIO_TEMPLATES.get(key)
    if not lines:
        await sender("⚠️ Сценарій не знайдено. " + scenario_keys_text())
        return False

    await sender(f"🎭 *#Загальний · Сценарій `{key}`*")
    for agent_key, text in lines:
        await agent_say(sender, agent_key, _simple_ua(agent_key, text), 0.10)
    log_event(db_path, "SCENARIO_RUN", {"scenario_key": key, "lines": len(lines)})
    return True


async def office_desk_user_question(
    sender: AsyncSender,
    *,
    question: str,
    symbol: str,
    market: Dict[str, Any],
    db_path: str = "office_bridge.db",
) -> None:
    """
    Interactive OFFICE Q&A (no trade-core involvement).

    This is intentionally lighter than office_handle_signal:
    - no task workflow spam
    - still role-separated and data-grounded using live snapshot fields
    """
    q = (question or "").strip()
    sym = symbol.upper()
    sig = OfficeSignal(
        signal_id=f"desk-ask-{_now_iso()}",
        symbol=sym,
        direction="LONG",
        score=int(market.get("score_hint", 12)),
        session=str(market.get("session", "LONDON")),
        regime=str(market.get("regime", "TREND")),
        source_text=q[:1200],
        meta={
            "source": "desk_qa",
            "rr": float(market.get("rr_hint", 2.0)),
            "volatility_pct": float(market.get("volatility_pct", 1.8)),
            "news_risk": str(market.get("news_risk", "SAFE")),
            "minutes_to_event": int(market.get("minutes_to_event", 999)),
            "is_whitelist": True,
            "btc_change_pct": float(market.get("btc_change_pct", 0.0)),
            "sym_change_pct": float(market.get("sym_change_pct", 0.0)),
            "quote_volume_usdt": float(market.get("quote_volume_usdt", 0.0)),
            "factor_pack_v2": market.get("factor_pack_v2"),
        },
    )

    log_event(db_path, "DESK_QUESTION", {"symbol": sym, "question": q}, sig.signal_id)

    await sender(
        "🧭 *#Загальний · Питання до офісу*\n"
        f"Питання: {q}\n"
        f"Фокус: `{sym}` · BTC24h `{float(market.get('btc_change_pct', 0.0)):+.2f}%` · ALTs24h `{float(market.get('sym_change_pct', 0.0)):+.2f}%`\n"
        f"TV: {_fmt_tv(sym)}"
    )

    # Lightweight chain (still uses grounding rules via _metric_pack inside decisions if we reuse helpers)
    conversation: List[ConversationTurn] = []

    prev_agent: Optional[str] = None

    analyst = _analyst_reply(sig, conversation)
    au = _simple_ua(analyst.agent_key, analyst.note)
    await agent_say(
        sender,
        analyst.agent_key,
        f"{_cross_reply_prefix(prev_agent, analyst.agent_key)}{au}",
        0.12,
    )
    conversation.append(ConversationTurn(analyst.agent_key, analyst.note))
    prev_agent = analyst.agent_key

    news = _news_reply(sig, conversation)
    nu = _simple_ua(news.agent_key, news.note)
    await agent_say(sender, news.agent_key, f"{_cross_reply_prefix(prev_agent, news.agent_key)}{nu}", 0.12)
    conversation.append(ConversationTurn(news.agent_key, news.note))
    prev_agent = news.agent_key

    risk = _risk_reply(sig, conversation)
    ru = _simple_ua(risk.agent_key, risk.note)
    await agent_say(sender, risk.agent_key, f"{_cross_reply_prefix(prev_agent, risk.agent_key)}{ru}", 0.12)
    conversation.append(ConversationTurn(risk.agent_key, risk.note))
    prev_agent = risk.agent_key

    q_low = q.lower()
    need_memory = any(k in q_low for k in ("істор", "схож", "статист", "пам'ят")) or float(market.get("volatility_pct", 0.0)) >= 3.0
    need_dev = any(k in q_low for k in ("бот", "api", "mini app", "miniapp", "тех", "помил", "render", "open office"))
    recurring = journal_recurring_mistakes(db_path, lookback_losses=60, min_count=2)
    need_psych = bool(recurring) or any(k in q_low for k in ("емоц", "tilt", "стрес", "страх", "псих"))

    if need_memory:
        mem_note = _memory_reply(sym, market, db_path)
        mu = _simple_ua("memory", mem_note)
        await agent_say(sender, "memory", f"{_cross_reply_prefix(prev_agent, 'memory')}{mu}", 0.11)
        conversation.append(ConversationTurn("memory", mem_note))
        prev_agent = "memory"
    if need_psych:
        psy_note = _psych_reply(recurring)
        pu = _simple_ua("psych", psy_note)
        await agent_say(sender, "psych", f"{_cross_reply_prefix(prev_agent, 'psych')}{pu}", 0.11)
        conversation.append(ConversationTurn("psych", psy_note))
        prev_agent = "psych"
    if need_dev:
        dev_note = _dev_reply(q)
        du = _simple_ua("dev", dev_note)
        await agent_say(sender, "dev", f"{_cross_reply_prefix(prev_agent, 'dev')}{du}", 0.11)
        conversation.append(ConversationTurn("dev", dev_note))
        prev_agent = "dev"

    strategist = _strategist_reply(sig, conversation, [analyst, news, risk])
    su = _simple_ua(strategist.agent_key, strategist.note)
    await agent_say(
        sender,
        strategist.agent_key,
        f"{_cross_reply_prefix(prev_agent, strategist.agent_key)}{su}",
        0.12,
    )
    conversation.append(ConversationTurn(strategist.agent_key, strategist.note))
    prev_agent = strategist.agent_key

    rebuttal = _risk_rebuttal(sig, strategist, risk)
    if rebuttal is not None:
        reb_u = _simple_ua(rebuttal.agent_key, rebuttal.note)
        await agent_say(
            sender,
            rebuttal.agent_key,
            f"{_cross_reply_prefix(prev_agent, rebuttal.agent_key)}{reb_u}",
            0.10,
        )
        conversation.append(ConversationTurn(rebuttal.agent_key, rebuttal.note))
        prev_agent = rebuttal.agent_key
        strategist2 = _strategist_after_rebuttal(sig, rebuttal)
        s2u = _simple_ua(strategist2.agent_key, strategist2.note)
        await agent_say(
            sender,
            strategist2.agent_key,
            f"{_cross_reply_prefix(prev_agent, strategist2.agent_key)}{s2u}",
            0.10,
        )
        conversation.append(ConversationTurn(strategist2.agent_key, strategist2.note))
        prev_agent = strategist2.agent_key
        strategist = strategist2

    final_action: Literal["ENTER", "SKIP", "WAIT"] = "ENTER"
    if strategist.decision == "REJECTED":
        final_action = "SKIP"
    elif strategist.decision == "WAIT":
        final_action = "WAIT"

    executor = _executor_reply(sig, final_action)
    eu = _simple_ua(executor.agent_key, executor.note)
    await agent_say(
        sender,
        executor.agent_key,
        f"{_cross_reply_prefix(prev_agent, executor.agent_key)}{eu}",
        0.12,
    )

    await sender(
        "Підсумок:\n"
        f"{sym} — { {'ENTER':'входимо','SKIP':'пропускаємо','WAIT':'чекаємо'}.get(final_action, final_action) }."
    )

    log_event(
        db_path,
        "DESK_ANSWER",
        {"symbol": sym, "final_action": final_action, "question": q},
        sig.signal_id,
    )

