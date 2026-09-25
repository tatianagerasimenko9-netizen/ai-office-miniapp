"""T4: єдиний стан символу (OFFICE ↔ BOT). Поки лише read/write, без чату й ордерів."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from office_bridge import _db_write, _fetchall, _fetchone, _now_iso

MARKET_STATE_BOT_ACTIONS = ("BLOCKED", "ACCEPT", "IGNORE_SOURCE")
MARKET_STATE_DECISIONS = ("NO_TRADE", "SIGNAL", "WATCH")
MARKET_STATE_TRADES = ("none", "PAPER", "MANUAL", "AUTHORIZED")
MARKET_STATE_INTENTS = ("none", "REVIEW", "MY_POSITION")
MARKET_STATE_QUALITY = ("OK", "DEGRADED", "UNAVAILABLE")

_SQL_UPSERT = """
INSERT INTO market_state (
  symbol, regime, watch_json, event, confirmation, signal_json,
  office_decision, bot_action, trade, intent, data_quality, ts_updated
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(symbol) DO UPDATE SET
  regime = excluded.regime,
  watch_json = excluded.watch_json,
  event = excluded.event,
  confirmation = excluded.confirmation,
  signal_json = excluded.signal_json,
  office_decision = excluded.office_decision,
  bot_action = excluded.bot_action,
  trade = excluded.trade,
  intent = excluded.intent,
  data_quality = excluded.data_quality,
  ts_updated = excluded.ts_updated
"""


def _norm_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)


def _loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _default_row(symbol: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "regime": None,
        "watch": [],
        "event": "none",
        "confirmation": "none",
        "signal": None,
        "office_decision": None,
        "bot_action": None,
        "trade": "none",
        "intent": "none",
        "data_quality": "OK",
        "ts_updated": None,
    }


def _row_to_state(row: tuple) -> Dict[str, Any]:
    return {
        "symbol": str(row[0] or "").upper(),
        "regime": row[1],
        "watch": _loads(row[2], []),
        "event": row[3] or "none",
        "confirmation": row[4] or "none",
        "signal": _loads(row[5], None),
        "office_decision": row[6],
        "bot_action": row[7],
        "trade": row[8] or "none",
        "intent": row[9] or "none",
        "data_quality": row[10] or "OK",
        "ts_updated": row[11],
    }


def market_state_get(db_path: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Повернути стан символу або None, якщо рядка немає."""
    sym = _norm_symbol(symbol)
    if not sym:
        return None
    row = _fetchone(
        db_path,
        """
        SELECT symbol, regime, watch_json, event, confirmation, signal_json,
               office_decision, bot_action, trade, intent, data_quality, ts_updated
        FROM market_state
        WHERE symbol = ?
        """,
        (sym,),
    )
    if not row:
        return None
    return _row_to_state(row)


def market_state_upsert(
    db_path: str,
    symbol: str,
    *,
    regime: Any = None,
    watch: Any = None,
    event: Any = None,
    confirmation: Any = None,
    signal: Any = None,
    office_decision: Any = None,
    bot_action: Any = None,
    trade: Any = None,
    intent: Any = None,
    data_quality: Any = None,
) -> Dict[str, Any]:
    """Upsert по symbol. None у.kwargs не затирає існуюче поле (крім першого insert)."""
    sym = _norm_symbol(symbol)
    if not sym:
        raise ValueError("symbol required")
    cur = market_state_get(db_path, sym) or _default_row(sym)

    def _set(key: str, value: Any, allowed: Optional[tuple] = None) -> None:
        if value is None:
            return
        if allowed is not None:
            v = str(value)
            if v not in allowed:
                raise ValueError(f"{key}={v} not in {allowed}")
            cur[key] = v
        else:
            cur[key] = value

    _set("regime", None if regime is None else str(regime))
    if watch is not None:
        if not isinstance(watch, list):
            raise ValueError("watch must be a list")
        cur["watch"] = watch
    _set("event", None if event is None else str(event))
    _set("confirmation", None if confirmation is None else str(confirmation))
    if signal is not None:
        cur["signal"] = signal
    _set("office_decision", office_decision, MARKET_STATE_DECISIONS)
    _set("bot_action", bot_action, MARKET_STATE_BOT_ACTIONS)
    _set("trade", trade, MARKET_STATE_TRADES)
    _set("intent", intent, MARKET_STATE_INTENTS)
    _set("data_quality", data_quality, MARKET_STATE_QUALITY)
    cur["ts_updated"] = _now_iso()

    _db_write(
        db_path,
        _SQL_UPSERT,
        (
            sym,
            cur.get("regime"),
            _dumps(cur.get("watch") or []),
            cur.get("event") or "none",
            cur.get("confirmation") or "none",
            _dumps(cur.get("signal")),
            cur.get("office_decision"),
            cur.get("bot_action"),
            cur.get("trade") or "none",
            cur.get("intent") or "none",
            cur.get("data_quality") or "OK",
            cur["ts_updated"],
        ),
    )
    out = market_state_get(db_path, sym)
    assert out is not None
    return out


def market_state_list(db_path: str, limit: int = 50) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 50), 200))
    rows = _fetchall(
        db_path,
        """
        SELECT symbol, regime, watch_json, event, confirmation, signal_json,
               office_decision, bot_action, trade, intent, data_quality, ts_updated
        FROM market_state
        ORDER BY ts_updated DESC
        LIMIT ?
        """,
        (lim,),
    )
    return [_row_to_state(r) for r in rows]
