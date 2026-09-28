"""Теза Лева з робочого циклу → перевірка контракту → незмінний журнал версій.

Будує ринкову гіпотезу лише з того, що Лев фактично порахував у draft
(зона, збіги, альтернатива, інвалідація) і з часових міток реальних свічок.
Режим ринку береться тільки з market_context; якщо його немає — UNKNOWN,
і контракт office_market_thesis чесно повертає REGIME_NOT_VERIFIED.

Нова версія пишеться в office_events (THESIS_VERSION) лише коли змінився
зміст тези; попередні версії не переписуються. Ордерів і Telegram немає.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from office_lifecycle import WATCHING_EXPIRE_SEC
from office_market_thesis import REGIMES, evaluate_thesis

EVENT = "THESIS_VERSION"
_LAST: Dict[str, str] = {}


TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400, "LTF": 300}


def _last_ts(candles: Any) -> Optional[str]:
    if isinstance(candles, list) and candles and isinstance(candles[-1], dict):
        ts = candles[-1].get("ts")
        return str(ts) if ts else None
    return None


def _observed_at(open_ts: Optional[str], tf: str, now: datetime) -> Optional[str]:
    """Час спостереження = min(відкриття + інтервал, now).

    Формована свічка спостерігається зараз; якщо фід завис, це останнє
    відоме закриття — і тоді доказ чесно старіє.
    """
    if not open_ts:
        return None
    try:
        dt = datetime.fromisoformat(open_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    close = dt + timedelta(seconds=TF_SECONDS.get(tf.upper(), 300))
    return min(close, now.astimezone(timezone.utc)).isoformat()


def _num(v: Any) -> str:
    try:
        return format(float(v), ".6g")
    except (TypeError, ValueError):
        return "?"


def build_thesis(
    cycle: Dict[str, Any],
    *,
    candles_by_tf: Dict[str, Any],
    now_utc: datetime,
    source: str = "binance_futures",
) -> Optional[Dict[str, Any]]:
    """None, якщо Лев не має зони: без зони гіпотези немає, не вигадуємо."""
    draft = cycle.get("draft") or {}
    conf = draft.get("confluence") or {}
    key = str(conf.get("setup_key") or conf.get("scenario_id") or "")
    lo, hi = draft.get("zone_lo"), draft.get("zone_hi")
    side = str(draft.get("direction") or "").upper()
    if not key or lo is None or hi is None or side not in ("LONG", "SHORT"):
        return None
    tf = str(draft.get("timeframe") or "H1").upper()
    tags = [str(t) for t in (conf.get("tags") or []) if t]
    alt = draft.get("alternative") or {}
    ctx = draft.get("market_context") or {}
    regime = str(ctx.get("regime") or "").upper()
    if regime not in REGIMES:
        regime = "UNKNOWN"
    evidence: List[Dict[str, Any]] = []
    for etf, candles in candles_by_tf.items():
        ts = _observed_at(_last_ts(candles), etf, now_utc)
        if ts:
            evidence.append({
                "source": source,
                "observed_at": ts,
                "timeframe": etf,
                "fact": f"остання свічка {etf}; збіги зони: {', '.join(tags) or 'немає'}",
            })
    action = str(cycle.get("action") or "")
    alt_txt = (
        f"{alt.get('direction')}: {alt.get('reason') or 'альтернативна зона'}"
        f" ({_num(alt.get('zone_lo'))}–{_num(alt.get('zone_hi'))})"
        if alt.get("eligible")
        else f"{alt.get('direction') or ('SHORT' if side == 'LONG' else 'LONG')}: підстав немає"
        f"{' — ' + str(alt.get('reason')) if alt.get('reason') else ''}"
    )
    return {
        "thesis_id": key,
        "symbol": str(draft.get("symbol") or "").upper(),
        "direction": side,
        "timeframe": tf,
        "regime": regime,
        "state": "CONFIRMED" if action == "SEND" else "WATCHING",
        "hypothesis": (
            f"{side} від зони {_num(lo)}–{_num(hi)} на {tf}"
            + (f"; збіги: {', '.join(tags)}" if tags else "; незалежних збігів немає")
        ),
        "alternative": alt_txt,
        "invalidation": (
            f"закриття за {_num(draft.get('invalidation'))}" if draft.get("invalidation") is not None else ""
        ),
        "confirmation": draft.get("confirmation") or [],
        "expires_at": (now_utc + timedelta(seconds=WATCHING_EXPIRE_SEC)).isoformat(),
        "evidence": evidence,
        "lev_action": action,
        "lev_reason": str(cycle.get("reason") or ""),
        "opens_position": False,
    }


def canonical_scenario_id(db_path: str, cycle: Dict[str, Any]) -> str:
    """Та сама ідентичність, що й prepare_desk_send: зсув зони ≠ новий сценарій."""
    draft = cycle.get("draft") or {}
    conf = draft.get("confluence") or {}
    try:
        from office_bridge import signal_get_scenarios
        from office_scenario_memory import find_canonical_scenario, market_basis_key, parse_note_meta

        existing = find_canonical_scenario(
            signal_get_scenarios(db_path),
            symbol=str(draft.get("symbol") or ""),
            direction=str(draft.get("direction") or ""),
            timeframe=str(draft.get("timeframe") or "H1"),
            basis=str(conf.get("market_basis") or market_basis_key(conf)),
            zone_lo=draft.get("zone_lo"),
            zone_hi=draft.get("zone_hi"),
        )
    except Exception:
        return ""
    if not existing:
        return ""
    return str(parse_note_meta(existing.get("analysis_note")).get("scenario_id") or existing.get("signal_id") or "")


def _content_hash(thesis: Dict[str, Any]) -> str:
    """Зміст без часових міток: нова версія лише коли змінилась теза, а не годинник."""
    core = {k: thesis.get(k) for k in (
        "thesis_id", "direction", "timeframe", "regime", "state", "hypothesis",
        "alternative", "invalidation", "lev_action",
    )}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def record_thesis(
    db_path: str,
    cycle: Dict[str, Any],
    *,
    candles_by_tf: Dict[str, Any],
    now_utc: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Перевіряє тезу і пише нову версію, якщо зміст змінився. Повертає запис або None."""
    now = now_utc or datetime.now(timezone.utc)
    thesis = build_thesis(cycle, candles_by_tf=candles_by_tf, now_utc=now)
    if thesis is None:
        return None
    canon = canonical_scenario_id(db_path, cycle)
    if canon:
        thesis["thesis_id"] = canon
    digest = _content_hash(thesis)
    tid = thesis["thesis_id"]
    if tid not in _LAST:
        prev = latest_thesis(db_path, tid)  # після рестарту не дублюємо ту саму версію
        if prev and prev.get("version_hash"):
            _LAST[tid] = str(prev["version_hash"])
    if _LAST.get(tid) == digest:
        return None
    check = evaluate_thesis(thesis, now_utc=now)
    record = {**thesis, "version_hash": digest, "recorded_at": now.isoformat(), "check": check}
    from office_bridge import log_event

    log_event(db_path, EVENT, record, signal_id=tid)
    _LAST[tid] = digest
    return record


def latest_thesis(db_path: str, scenario_id: str) -> Optional[Dict[str, Any]]:
    from office_bridge import _fetchone

    try:
        row = _fetchone(
            db_path,
            "SELECT payload_json FROM office_events WHERE event_type = ? AND signal_id = ? ORDER BY id DESC LIMIT 1",
            (EVENT, str(scenario_id or "")),
        )
    except Exception:
        return None
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None
