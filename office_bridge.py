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
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional
from urllib.parse import urlparse

try:
    import psycopg
except Exception:  # pragma: no cover - optional in local sqlite mode
    psycopg = None  # type: ignore[assignment]

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
        character="аналітична, позитивна, data-first, on-duty по позиціях",
        responsibility="звітність, ретроспектива, A/B learning + супровід відкритих угод (partial/move SL/exit)",
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
        character="спокійний, підтримуючий, дисципліна без тиску",
        responsibility="контроль tilt, серій збитків, ризик-уважність команди",
        photo_hint="Focus dashboard, discipline board, team wellness panel",
    ),
    "dev": AgentProfile(
        key="dev",
        name="Артем",
        nickname="Dev",
        emoji="🛠️",
        role="Technical Developer",
        character="технічний, короткий, без зайвої термінології",
        responsibility="стан API/бота/Mini App, технічні попередження і стабільність",
        photo_hint="Dev console, status monitors, incident board",
    ),
}


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


def fmt_agent_line(agent_key: str, text: str) -> str:
    # Hidden routing tag for relay multi-bot delivery; stripped before sending to Telegram.
    return f"@@{agent_key}@@{text}"


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
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_events_signal ON office_events(signal_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_decisions_signal ON office_decisions(signal_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_office_messages_signal ON office_messages(signal_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol ON trade_journal(symbol)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_ts_close ON trade_journal(ts_close_utc)")
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_events_signal ON office_events(signal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_decisions_signal ON office_decisions(signal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_office_messages_signal ON office_messages(signal_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol ON trade_journal(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_ts_close ON trade_journal(ts_close_utc)")
        conn.commit()


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
    await sender(fmt_agent_line(agent_key, polish_agent_message(text)))


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


def _analyst_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    min_score = 12 if signal.session.upper() in ("LONDON", "NEW_YORK") else 15
    prev = _last_turn(conversation)
    if signal.regime.upper() == "CHOP":
        note = "Ринок шумний, сетап слабкий. Я за пропуск."
        return AgentDecision("maks", "REJECTED", _enforce_data_grounding(note, signal), {"min_score": min_score})
    if signal.score < min_score:
        note = "Сигнал нижче порога. Поки без входу."
        return AgentDecision("maks", "REJECTED", _enforce_data_grounding(note, signal), {"min_score": min_score})
    note = "Технічно ок, можна передавати в ризик-контроль."
    return AgentDecision("maks", "APPROVED", _enforce_data_grounding(note, signal), {"min_score": min_score})


def _news_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    prev = _last_turn(conversation)
    risk = str(signal.meta.get("news_risk", "SAFE")).upper()
    mins = int(signal.meta.get("minutes_to_event", 999))
    if risk == "HIGH":
        return AgentDecision(
            "news",
            "REJECTED",
            _enforce_data_grounding(f"Високий новинний ризик, подія через {mins} хв. Краще пропустити.", signal),
            {"news": "HIGH RISK"},
        )
    if risk == "RISK":
        return AgentDecision(
            "news",
            "WAIT",
            _enforce_data_grounding(f"Є новинний ризик, подія через {mins} хв. Краще зачекати.", signal),
            {"news": "RISK"},
        )
    return AgentDecision(
        "news",
        "APPROVED",
        _enforce_data_grounding("Критичних новин поруч немає.", signal),
        {"news": "SAFE"},
    )


def _risk_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    prev = _last_turn(conversation)
    rr = float(signal.meta.get("rr", 2.0))
    vol = float(signal.meta.get("volatility_pct", 0.0))
    news_flag = any(t.agent_key == "news" and ("HIGH RISK" in t.text or "RISK:" in t.text) for t in conversation)
    if bool(signal.meta.get("loss_cooldown_active", False)):
        return AgentDecision(
            "daryna",
            "WAIT",
            _enforce_data_grounding("Активний cooldown. Вхід переносимо.", signal),
            {"veto": True},
        )
    if news_flag:
        return AgentDecision(
            "daryna",
            "WAIT",
            "Вето по новинах. До зниження ризику не входимо.",
            {"veto": True},
        )
    if rr < 1.5:
        return AgentDecision(
            "daryna",
            "REJECTED",
            _enforce_data_grounding("Вето: ризик не виправданий.", signal),
            {"veto": True},
        )
    if vol > 4.5:
        return AgentDecision(
            "daryna",
            "WAIT",
            _enforce_data_grounding("Волатильність зависока. Чекаємо стабілізацію.", signal),
            {"veto": True},
        )
    return AgentDecision(
        "daryna",
        "APPROVED",
        _enforce_data_grounding("Ризик-контур чистий. Допуск на виконання.", signal),
        {"veto": False},
    )


def _strategist_reply(signal: OfficeSignal, conversation: List[ConversationTurn]) -> AgentDecision:
    has_reject = any("Вето" in t.text or "пропуск" in t.text.lower() or "HIGH RISK" in t.text for t in conversation if t.agent_key in ("maks", "daryna", "news"))
    has_wait = any("Чекаємо" in t.text or "переносимо" in t.text for t in conversation if t.agent_key in ("maks", "daryna"))
    if signal.regime.upper() == "CHOP":
        return AgentDecision("lev", "REJECTED", _enforce_data_grounding("Ринок шумний. Фінал: пропускаємо.", signal))
    if has_reject:
        return AgentDecision("lev", "REJECTED", _enforce_data_grounding("Приймаю вето ризику. Фінал: пропускаємо.", signal))
    if has_wait:
        return AgentDecision("lev", "WAIT", _enforce_data_grounding("Не форсуємо. Фінал: чекаємо.", signal))
    return AgentDecision("lev", "APPROVED", _enforce_data_grounding("Контекст нормальний. Фінал: входимо.", signal))


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
    if final_action == "ENTER":
        return AgentDecision(
            "marko",
            "APPROVED",
            _enforce_data_grounding(f"Рішення: входимо в {signal.direction} {signal.symbol}. Супровід за ковзною {trail}, розмір стандартний.", signal),
            {"trail_mode": trail},
        )
    if final_action == "WAIT":
        return AgentDecision(
            "marko",
            "WAIT",
            _enforce_data_grounding(f"Рішення: чекаємо по {signal.symbol} до повторного тригера.", signal),
            {"trail_mode": trail},
        )
    return AgentDecision(
        "marko",
        "REJECTED",
        _enforce_data_grounding(f"Рішення: пропускаємо {signal.symbol} за командним рішенням.", signal),
        {"trail_mode": trail},
    )


def _decide_chain(signal: OfficeSignal) -> OfficeVerdict:
    decisions: List[AgentDecision] = []
    conversation: List[ConversationTurn] = []

    analyst = _analyst_reply(signal, conversation)
    decisions.append(analyst)
    conversation.append(ConversationTurn(analyst.agent_key, analyst.note))

    news = _news_reply(signal, conversation)
    decisions.append(news)
    conversation.append(ConversationTurn(news.agent_key, news.note))

    risk = _risk_reply(signal, conversation)
    decisions.append(risk)
    conversation.append(ConversationTurn(risk.agent_key, risk.note))

    strategist = _strategist_reply(signal, conversation)
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
        f"Сесія: `{session}` · Режим: `{market_state}` · BTC: `{btc_bias}`"
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
        f"BTC 24г `{btc_change_pct:+.2f}%`\n"
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
    await agent_say(sender, "marko", "Execution на паузі до clear signal.", 0.05)


async def office_handle_signal(
    sender: AsyncSender,
    signal: OfficeSignal,
    db_path: str = "office_bridge.db",
) -> OfficeVerdict:
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
    await sender(f"Новий кейс: {signal.symbol} {signal.direction}. Команда на розборі.")

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
        cb_need = max(2, int(os.getenv("OFFICE_CIRCUIT_LOSSES", "3") or "3"))
    except Exception:
        cb_need = 3
    if not cb_disabled and journal_consecutive_loss_streak(db_path) >= cb_need:
        log_event(
            db_path,
            "CIRCUIT_BREAKER",
            {"streak": cb_need, "symbol": signal.symbol},
            signal.signal_id,
        )
        await sender(
            f"⚠️ Circuit breaker: {cb_need}+ SL підряд у журналі. Новий вхід не відкриваємо — тільки обговорення / пропуск."
        )
        # Один крок з Левом: інакше другий REJECTED після BLOCKED ламає FSM задачі (OPEN→BLOCKED→BLOCKED).
        verdict = OfficeVerdict(
            "SKIP",
            [
                AgentDecision(
                    "lev",
                    "REJECTED",
                    _enforce_data_grounding(
                        f"Circuit breaker: {cb_need} збитки підряд. Вхід заборонено, поки серія не перерветься виграшем або BE.",
                        signal,
                    ),
                    {"circuit_breaker": True},
                ),
            ],
            f"Автоматичне блокування після {cb_need}+ SL поспіль (MASTER п.31).",
        )
    else:
        verdict = _decide_chain(signal)

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
    await agent_say(sender, "olesya", "Зафіксувала результат у журнал і статистику.", 0.05)
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
        await agent_say(sender, "olesya", "Роблю post-mortem: контекст, таймінг, чи був early/late entry.", 0.06)
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
    await agent_say(
        sender,
        "news",
        f"{risk_ua}: подія через {minutes_to_event} хв. {short_headline}",
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
        return "Макс, підхоплюю: "
    if key == ("news", "daryna"):
        return "Назаре, враховую: "
    if key == ("daryna", "memory"):
        return "До ризику додаю пам'ять: "
    if key == ("memory", "psych"):
        return "Додам по дисципліні: "
    if key == ("psych", "dev"):
        return "І технічно: "
    if key == ("dev", "lev"):
        return "Техніка ок. "
    if key == ("lev", "marko"):
        return "У execution: "
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


def _memory_reply(symbol: str, market: Dict[str, Any]) -> str:
    return (
        f"По {symbol} є схожі записи в журналі — без RAG / агрегації точний winrate не цитую. "
        "Звіряй факти, не форсуй вхід."
    )


def _psych_reply(recurring: Dict[str, int]) -> str:
    if not recurring:
        return "Емоційний фон нормальний. Працюємо спокійно, без поспіху."
    top = ", ".join(f"{k} x{v}" for k, v in sorted(recurring.items(), key=lambda x: (-x[1], x[0]))[:2])
    return (
        f"Бачу повторювані помилки: {top}. "
        "Сьогодні тримаємо дисципліну і зменшуємо агресію."
    )


def _dev_reply(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ("mini app", "miniapp", "рендер", "render", "кнопк", "open office")):
        return "Mini App і кнопка Open Office під контролем. Якщо є збій, даю фікс по кроках."
    if any(k in q for k in ("api", "бот", "relay", "помилка", "error")):
        return "Технічний стан нормальний. API/relay перевіряємо перед входом."
    return "Технічна частина стабільна. Інфраструктура готова до роботи."


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
        mem_note = _memory_reply(sym, market)
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

    strategist = _strategist_reply(sig, conversation)
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
        "🧾 *#Загальний · Підсумок обговорення*\n"
        f"`{sym}` · обсяг `{float(market.get('quote_volume_usdt', 0.0)):.0f}` USDT (24г)\n"
        f"Фінальне рішення офісу: `{ {'ENTER':'ВХІД','SKIP':'ПРОПУСК','WAIT':'ОЧІКУВАННЯ'}.get(final_action, final_action) }`"
    )

    log_event(
        db_path,
        "DESK_ANSWER",
        {"symbol": sym, "final_action": final_action, "question": q},
        sig.signal_id,
    )

