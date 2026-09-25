"""T3: після SKIP не плодити нові WATCHING того самого сценарію.

Ключ: symbol + timeframe + setup + expiry.
Вже активний WATCHING не гасимо — ZONE_REACHED лишається на T0-моніторі.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from office_bridge import _fetchall, log_event, signal_get_active
from office_level_parse import zone_is_plausible

# Вікно ключа expiry — як історичний WATCHING_COOLDOWN (4 год), не ATR T0.
SKIP_SCENARIO_EXPIRY_SEC = 4 * 3600
T3_SKIP_EVENT = "T3_SKIP_SCENARIO"
DEFAULT_TIMEFRAME = "1h"


def round_level(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, 6)


def setup_from_levels(
    direction: Any,
    entry_low: Any,
    entry_high: Any = None,
    setup_name: str = "",
) -> str:
    name = str(setup_name or "").strip() or "zone"
    lo = round_level(entry_low)
    hi = round_level(entry_high if entry_high is not None else entry_low)
    side = str(direction or "").strip().upper() or "LONG"
    return f"{name}|{side}|{lo}|{hi}"


def expiry_label(now_ts: float, window_sec: float = SKIP_SCENARIO_EXPIRY_SEC) -> str:
    try:
        ts = float(now_ts)
        win = float(window_sec) if float(window_sec) > 0 else float(SKIP_SCENARIO_EXPIRY_SEC)
    except (TypeError, ValueError):
        return "0"
    return str(int(ts // win))


def scenario_key(symbol: str, timeframe: str, setup: str, expiry: str) -> str:
    return "|".join(
        [
            str(symbol or "").strip().upper(),
            str(timeframe or DEFAULT_TIMEFRAME).strip().lower(),
            str(setup or "").strip(),
            str(expiry or "").strip(),
        ]
    )


def should_keep_watching_on_skip() -> bool:
    """SKIP стосується входу, не монітора вже активної зони."""
    return True


def should_create_watching_after_skip(*, already_active: bool, already_skipped: bool) -> bool:
    """Новий WATCHING після SKIP — лише якщо цього сценарію ще немає і його ще не скіпали в цьому expiry."""
    if already_active or already_skipped:
        return False
    return True


def find_active_watching_same_setup(
    db_path: str,
    *,
    symbol: str,
    timeframe: str,
    setup: str,
) -> Optional[Dict[str, Any]]:
    """Збіг відкритого WATCHING без expiry — щоб не дублювати живу зону."""
    want_sym = str(symbol or "").strip().upper()
    want_setup = str(setup or "").strip()
    for row in signal_get_active(db_path):
        if str(row.get("status") or "").upper() != "WATCHING":
            continue
        if str(row.get("symbol") or "").strip().upper() != want_sym:
            continue
        got = setup_from_levels(row.get("direction"), row.get("entry_low"), row.get("entry_high"))
        if got != want_setup:
            continue
        return row
    return None


def record_skip_scenario(
    db_path: str,
    key: str,
    *,
    symbol: str = "",
    timeframe: str = "",
    setup: str = "",
    expiry: str = "",
) -> None:
    log_event(
        db_path,
        T3_SKIP_EVENT,
        {
            "key": key,
            "symbol": str(symbol or "").upper(),
            "timeframe": timeframe or DEFAULT_TIMEFRAME,
            "setup": setup,
            "expiry": expiry,
        },
        signal_id=str(symbol or ""),
    )


def skip_scenario_recorded(db_path: str, key: str, *, limit: int = 200) -> bool:
    if not key:
        return False
    try:
        rows = _fetchall(
            db_path,
            """
            SELECT payload_json FROM office_events
            WHERE event_type = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (T3_SKIP_EVENT, int(limit)),
        )
    except Exception:
        return False
    for r in rows:
        raw = r[0] if r else ""
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            payload = {}
        if str((payload or {}).get("key") or "") == key:
            return True
    return False


def apply_skip_watching_gate(
    db_path: str,
    *,
    symbol: str,
    direction: Any,
    entry_low: Any,
    entry_high: Any = None,
    timeframe: str = DEFAULT_TIMEFRAME,
    setup_name: str = "",
    now_ts: float,
    current_price: Any = None,
) -> Dict[str, Any]:
    """Рішення: створювати новий WATCHING після SKIP чи ні. Активний рядок не чіпаємо.

    Некоректна зона (уламок парсера 82–963) не створює рядок і не пише T3-ключ,
    тож правильна зона 82 963–83 434 лишається вільною.
    """
    setup = setup_from_levels(direction, entry_low, entry_high, setup_name=setup_name)
    expiry = expiry_label(now_ts)
    key = scenario_key(symbol, timeframe, setup, expiry)
    plausible = zone_is_plausible(entry_low, entry_high, current_price)
    if not plausible:
        return {
            "key": key,
            "setup": setup,
            "expiry": expiry,
            "already_active": False,
            "already_skipped": False,
            "create": False,
            "invalid_zone": True,
            "keep_existing": should_keep_watching_on_skip(),
            "active_signal_id": None,
        }
    active = find_active_watching_same_setup(
        db_path, symbol=symbol, timeframe=timeframe, setup=setup
    )
    skipped = skip_scenario_recorded(db_path, key)
    create = should_create_watching_after_skip(
        already_active=bool(active),
        already_skipped=skipped,
    )
    return {
        "key": key,
        "setup": setup,
        "expiry": expiry,
        "already_active": bool(active),
        "already_skipped": skipped,
        "create": create,
        "invalid_zone": False,
        "keep_existing": should_keep_watching_on_skip(),
        "active_signal_id": (active or {}).get("signal_id") if active else None,
    }


def record_skip_if_valid(
    db_path: str,
    gate: Dict[str, Any],
    *,
    symbol: str = "",
    timeframe: str = DEFAULT_TIMEFRAME,
) -> None:
    """T3-ключ лише для правдоподібної зони — сміття 82–963 не дедупиться."""
    if not isinstance(gate, dict):
        return
    if gate.get("invalid_zone"):
        return
    key = str(gate.get("key") or "")
    if not key:
        return
    record_skip_scenario(
        db_path,
        key,
        symbol=symbol,
        timeframe=timeframe,
        setup=str(gate.get("setup") or ""),
        expiry=str(gate.get("expiry") or ""),
    )
