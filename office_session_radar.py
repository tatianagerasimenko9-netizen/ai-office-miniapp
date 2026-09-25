"""Сесійний радар: Азія / Лондон / Нью-Йорк, типи сетапів, M5/M1.

Не відкриває позиції. WATCHING після SKIP. LONG↔SHORT лише після нового
незалежного підтвердження (sweep/reclaim + M5/M1), не через сам факт стопа.
Пороги ATR 80/90 не змінює — бере office_atr_policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from office_atr_policy import classify_atr_day_used
from office_radar import (
    DEFAULT_RR,
    MIN_RR,
    card_levels,
    classify_proximity,
    detect_sweep_from_candles,
    m15_confirmation,
)

SESSION_WINDOWS_UTC: Dict[str, Tuple[int, int]] = {
    "asia": (0, 8),
    "london": (8, 16),
    "ny": (13, 21),
}
SETUP_TYPES = ("sweep_reclaim", "continuation", "breakout_retest", "reversal")
KIND_SIGNAL = "signal"
KIND_WATCHING = "watching"
KIND_PAPER = "paper"
KIND_LIVE = "live"


def session_at_utc(ts: Optional[datetime] = None) -> str:
    dt = ts or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    h = int(dt.astimezone(timezone.utc).hour)
    names: List[str] = []
    for name, (a, b) in SESSION_WINDOWS_UTC.items():
        if a <= h < b:
            names.append(name)
    if not names:
        return "off_session"
    if "ny" in names and "london" in names:
        return "london_ny_overlap"
    return names[0]


def session_clock(ts: Optional[datetime] = None) -> Dict[str, Any]:
    """Активна сесія і хвилини до наступної. З годинника, не з вигаданого ринку."""
    dt = ts or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    active = session_at_utc(dt)
    label = {
        "asia": "ASIA",
        "london": "LONDON",
        "ny": "NY",
        "london_ny_overlap": "NY",
        "off_session": "OFF",
    }.get(active, active.upper() if active else None)
    h, m = dt.hour, dt.minute
    now_min = h * 60 + m
    # Наступне вікно: London 08:00, NY 13:00, Asia 00:00 наступної доби.
    starts = [("LONDON", 8 * 60), ("NY", 13 * 60), ("ASIA", 24 * 60)]
    nxt_name = None
    nxt_in = None
    for name, start in starts:
        if start > now_min:
            nxt_name, nxt_in = name, start - now_min
            break
    if nxt_name is None:
        nxt_name, nxt_in = "ASIA", (24 * 60 - now_min)
    return {
        "active": label,
        "next": nxt_name,
        "next_in_min": int(nxt_in) if nxt_in is not None else None,
        "code": active,
    }


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x


def m1_confirmation(candles_m1: List[Dict[str, Any]], *, direction: str, level: float) -> bool:
    return m15_confirmation(candles_m1, direction=direction, level=level)


def detect_breakout_retest(candles: List[Dict[str, Any]], level: float, *, direction: str) -> bool:
    if not isinstance(candles, list) or len(candles) < 2:
        return False
    prev, last = candles[-2], candles[-1]
    if not isinstance(prev, dict) or not isinstance(last, dict):
        return False
    pc, lc = _f(prev.get("close")), _f(last.get("close"))
    ll, lh = _f(last.get("low")), _f(last.get("high"))
    lv = _f(level)
    if None in (pc, lc, ll, lh, lv):
        return False
    side = str(direction or "").upper()
    if side == "LONG":
        return bool(pc > lv and ll <= lv * 1.002 and lc > lv)
    if side == "SHORT":
        return bool(pc < lv and lh >= lv * 0.998 and lc < lv)
    return False


def detect_continuation(candles: List[Dict[str, Any]], *, direction: str) -> bool:
    if not isinstance(candles, list) or len(candles) < 2:
        return False
    a, b = candles[-2], candles[-1]
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    ao, ac = _f(a.get("open")), _f(a.get("close"))
    bo, bc = _f(b.get("open")), _f(b.get("close"))
    if None in (ao, ac, bo, bc):
        return False
    side = str(direction or "").upper()
    if side == "LONG":
        return bool(ac > ao and bc > bo and bc > ac)
    if side == "SHORT":
        return bool(ac < ao and bc < bo and bc < ac)
    return False


def independent_flip_ok(
    *,
    previous_direction: str,
    new_direction: str,
    sweep: Dict[str, Any],
    m5_ok: bool,
    m1_ok: bool,
    stop_hit: bool,
) -> bool:
    prev = str(previous_direction or "").upper()
    nxt = str(new_direction or "").upper()
    if not prev or prev == nxt:
        return True
    if stop_hit and not (m5_ok or m1_ok):
        return False
    if nxt == "LONG" and not sweep.get("ssl_sweep"):
        return False
    if nxt == "SHORT" and not sweep.get("bsl_sweep"):
        return False
    return bool(m5_ok or m1_ok)


@dataclass
class SessionRadarResult:
    symbol: str
    status: str
    session: str = ""
    setup_type: str = ""
    direction: str = ""
    level_price: Optional[float] = None
    reason: str = ""
    card: Optional[Dict[str, Any]] = None
    opens_position: bool = False
    kind: str = KIND_SIGNAL
    entry_blocked: bool = False
    search_continues: bool = True
    extras: Dict[str, Any] = field(default_factory=dict)


def classify_setup(
    *,
    sweep: Dict[str, Any],
    m15_ok: bool,
    m5_ok: bool,
    breakout_retest: bool,
    continuation: bool,
    direction: str,
) -> str:
    if sweep.get("ssl_sweep") or sweep.get("bsl_sweep"):
        if m15_ok or m5_ok:
            return "sweep_reclaim"
        return "sweep_reclaim"
    if breakout_retest:
        return "breakout_retest"
    if continuation:
        return "continuation"
    if str(direction or "").upper() in ("LONG", "SHORT"):
        return "reversal"
    return ""


def evaluate_session_radar(
    *,
    symbol: str,
    price: float,
    level_price: Optional[float],
    sweep_candles: List[Dict[str, Any]],
    m15_candles: List[Dict[str, Any]],
    m5_candles: Optional[List[Dict[str, Any]]] = None,
    m1_candles: Optional[List[Dict[str, Any]]] = None,
    day_used_pct: Optional[float] = None,
    utc_now: Optional[datetime] = None,
    previous_direction: str = "",
    stop_hit: bool = False,
) -> SessionRadarResult:
    """Офлайн сесійне рішення. SIGNAL лише картка; opens_position завжди False."""
    sym = str(symbol or "").upper().strip() or "BTCUSDT"
    sess = session_at_utc(utc_now)
    atr = classify_atr_day_used(day_used_pct)
    px = _f(price)
    lv = _f(level_price)
    sweep = detect_sweep_from_candles(sweep_candles)
    direction = str(sweep.get("direction_hint") or "")
    if not direction and lv and px:
        direction = "LONG" if px >= lv else "SHORT"

    empty = SessionRadarResult(
        symbol=sym,
        status="NONE",
        session=sess,
        search_continues=True,
        extras={"atr": atr, "sweep": sweep},
    )
    if px is None:
        empty.reason = "немає ціни"
        return empty

    sweep_lv = _f(sweep.get("sweep_level")) or lv or px
    m15_ok = False
    m5_ok = False
    m1_ok = False
    if direction == "LONG" and sweep.get("ssl_sweep"):
        m15_ok = m15_confirmation(m15_candles, direction="LONG", level=float(sweep_lv))
        m5_ok = m15_confirmation(m5_candles or [], direction="LONG", level=float(sweep_lv))
        m1_ok = m1_confirmation(m1_candles or [], direction="LONG", level=float(sweep_lv))
    elif direction == "SHORT" and sweep.get("bsl_sweep"):
        m15_ok = m15_confirmation(m15_candles, direction="SHORT", level=float(sweep_lv))
        m5_ok = m15_confirmation(m5_candles or [], direction="SHORT", level=float(sweep_lv))
        m1_ok = m1_confirmation(m1_candles or [], direction="SHORT", level=float(sweep_lv))

    br = detect_breakout_retest(m15_candles, float(lv or sweep_lv), direction=direction) if direction else False
    cont = detect_continuation(m15_candles, direction=direction) if direction else False
    setup = classify_setup(
        sweep=sweep,
        m15_ok=m15_ok,
        m5_ok=m5_ok,
        breakout_retest=br,
        continuation=cont,
        direction=direction,
    )
    prox = classify_proximity(px, float(lv or sweep_lv))

    if not independent_flip_ok(
        previous_direction=previous_direction,
        new_direction=direction,
        sweep=sweep,
        m5_ok=m5_ok or m15_ok,
        m1_ok=m1_ok,
        stop_hit=stop_hit,
    ):
        return SessionRadarResult(
            symbol=sym,
            status="WATCHING",
            session=sess,
            setup_type=setup or "reversal",
            direction=previous_direction,
            level_price=lv,
            reason="переворот без незалежного підтвердження — лишаємо WATCHING",
            kind=KIND_WATCHING,
            entry_blocked=True,
            extras={"atr": atr, "sweep": sweep},
        )

    confirmed = bool(m15_ok or m5_ok or m1_ok or br)
    watching = SessionRadarResult(
        symbol=sym,
        status="WATCHING",
        session=sess,
        setup_type=setup,
        direction=direction,
        level_price=lv or sweep_lv,
        reason="сесія є, підтвердження M15/M5/M1 немає",
        kind=KIND_WATCHING,
        entry_blocked=bool(atr.get("gerchik_entry_blocked") or atr.get("t0_entry_blocked")),
        extras={"atr": atr, "sweep": sweep, "proximity": prox},
    )
    has_interest = bool(
        sweep.get("ssl_sweep") or sweep.get("bsl_sweep") or prox in ("approaching", "reached") or br or cont
    )
    if not has_interest:
        empty.reason = "немає сесійного сетапу"
        return empty
    if not confirmed:
        watching.reason = "sweep/рівень без підтвердження малого ТФ — WATCHING, не ENTER"
        return watching

    card = card_levels(direction=direction, entry=px, structure_sl=float(sweep_lv), rr=DEFAULT_RR)
    if float(card.get("rr") or 0) < MIN_RR:
        watching.reason = f"RR {card.get('rr')} < {MIN_RR} — WATCHING"
        watching.card = card
        return watching
    if atr.get("t0_entry_blocked") or atr.get("gerchik_entry_blocked"):
        watching.reason = str(atr.get("label") or "ATR блок входу") + " — пошук триває, SIGNAL немає"
        watching.card = card
        watching.entry_blocked = True
        return watching

    return SessionRadarResult(
        symbol=sym,
        status="SIGNAL",
        session=sess,
        setup_type=setup or "sweep_reclaim",
        direction=direction,
        level_price=lv or sweep_lv,
        reason="підтвердження малого ТФ є; це картка, не позиція",
        card=card,
        opens_position=False,
        kind=KIND_SIGNAL,
        extras={"atr": atr, "sweep": sweep, "m15": m15_ok, "m5": m5_ok, "m1": m1_ok},
    )
