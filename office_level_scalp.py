"""T8: торгівля від рівнів — скальп M1/M5 і внутрішній день M15/H1.

Окремий режим, не коментар «по BTC». Дотик рівня ≠ сигнал.
Два сценарії в боковику: LONG від підтримки і SHORT від опору.
Комісії/спред/прослизання ті самі що T6/T8 бектест; для скальпу RR рахуємо після витрат.
Картка після реакції й підтвердження, не ордер.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from office_atr_policy import classify_atr_day_used
from office_level_parse import _extract_line_value
from office_market_data import SIGNAL_THRESHOLD
from office_radar import (
    MIN_RR,
    classify_proximity,
    cluster_sr_levels,
    detect_sweep_from_candles,
    m15_confirmation,
    sl_with_buffer,
)
from office_range_radar import detect_range_bounds
from office_session_radar import detect_breakout_retest

KIND_LEVEL = "level_scalp"
# Ті самі витрати що office_t6_backtest / office_t8_backtest, не нові пороги ATR/Edge.
COMMISSION = 0.0004
SLIPPAGE = 0.0005


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x


def infer_trade_mode(timeframe: Any, style_hint: Any = "") -> str:
    raw = f"{timeframe or ''} {style_hint or ''}".lower()
    if any(x in raw for x in ("1m", "m1", "5m", "m5", "scalp", "скальп")):
        return "scalp"
    return "intraday"


def rr_after_costs(
    *,
    entry: Any,
    sl: Any,
    tp: Any,
    commission: float = COMMISSION,
    slippage: float = SLIPPAGE,
) -> Optional[float]:
    """Чистий RR після круглого комісійного кола. Для скальпу обов'язково."""
    e, s, t = _f(entry), _f(sl), _f(tp)
    if e is None or s is None or t is None:
        return None
    risk = abs(e - s)
    if risk <= 0:
        return None
    reward = abs(t - e)
    cost = e * (float(commission) + float(slippage)) * 2.0
    return (reward - cost) / risk


def parse_bot_card_overlay(text: str) -> Dict[str, Any]:
    """Картка зовнішнього бота (Вхід/Добір/SL/TP, PENGUUSDT · 5m, СКАЛЬП)."""
    src = str(text or "")
    up = src.upper()
    out: Dict[str, Any] = {
        "symbol": "",
        "direction": "",
        "timeframe": "",
        "style": "",
        "entry": None,
        "add_on": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "opens_position": False,
    }
    m_sym = re.search(r"\b[A-Z0-9]{2,15}USDT\b", up)
    if m_sym:
        out["symbol"] = m_sym.group(0)
    if any(t in up for t in ("SHORT", "SELL", "ШОРТ", "🔴")):
        out["direction"] = "SHORT"
    elif any(t in up for t in ("LONG", "BUY", "ЛОНГ", "🟢")):
        out["direction"] = "LONG"
    m_tf = re.search(r"·\s*(\d+[mhd])\s*·", src, flags=re.IGNORECASE)
    if m_tf:
        out["timeframe"] = m_tf.group(1).lower()
    if "SCALP" in up or "СКАЛЬП" in up:
        out["style"] = "scalp"
    elif "TREND" in up:
        out["style"] = "intraday"
    entry = _extract_line_value("Вхід", src) or _extract_line_value("Entry", src)
    add_on = _extract_line_value("Добір", src)
    sl = _extract_line_value("SL", src, hint=entry)
    tp1 = _extract_line_value("TP1", src, hint=entry)
    tp2 = _extract_line_value("TP2", src, hint=entry)
    tp3 = _extract_line_value("TP3", src, hint=entry)
    out["entry"] = entry
    out["add_on"] = add_on
    out["sl"] = sl
    out["tp1"] = tp1
    out["tp2"] = tp2
    out["tp3"] = tp3
    out["mode"] = infer_trade_mode(out["timeframe"], out["style"])
    return out


def _c(bar: Any) -> Optional[Dict[str, float]]:
    if not isinstance(bar, dict):
        return None
    o, h, l, cl = _f(bar.get("open")), _f(bar.get("high")), _f(bar.get("low")), _f(bar.get("close"))
    if None in (o, h, l, cl):
        return None
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(cl)}


def collect_levels(
    candles: List[Dict[str, Any]],
    *,
    extra_bounds: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Підтримка / опір / межі боковика з конкретними цінами."""
    clustered = cluster_sr_levels(candles, min_touches=2, limit=8)
    out: List[Dict[str, Any]] = []
    for cl in clustered:
        kind = "support" if str(cl.get("type")) == "support" else "resistance"
        px = float(cl["price"])
        out.append(
            {
                "kind": kind,
                "side": "bid" if kind == "support" else "ask",
                "low": px,
                "high": px,
                "label": "підтримка" if kind == "support" else "опір",
            }
        )
    bounds = extra_bounds or detect_range_bounds(candles)
    if bounds:
        out.append(
            {
                "kind": "support",
                "side": "liquidity",
                "low": float(bounds["low"]),
                "high": float(bounds["low"]),
                "label": "низ боковика / стопи знизу",
            }
        )
        out.append(
            {
                "kind": "resistance",
                "side": "liquidity",
                "low": float(bounds["high"]),
                "high": float(bounds["high"]),
                "label": "верх боковика / стопи зверху",
            }
        )
        mid = float(bounds["mid"])
        out.append(
            {
                "kind": "equilibrium",
                "side": "mid",
                "low": mid,
                "high": mid,
                "label": "рівновага",
            }
        )
    # Унікальні за ціною.
    uniq: List[Dict[str, Any]] = []
    seen = set()
    for lv in out:
        key = round(float(lv["low"]), 8)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(lv)
    uniq.sort(key=lambda x: float(x["low"]))
    return uniq


def nearest_target(levels: List[Dict[str, Any]], *, direction: str, entry: float) -> Optional[float]:
    side = str(direction or "").upper()
    prices = [float(lv["low"]) for lv in levels]
    if side == "LONG":
        above = [p for p in prices if p > entry * 1.0005]
        return min(above) if above else None
    below = [p for p in prices if p < entry * 0.9995]
    return max(below) if below else None


def _reaction_long(last: Dict[str, float], level: float, sweep: Dict[str, Any], confirm: bool) -> bool:
    if not confirm:
        return False
    wick = last["low"] < level and last["close"] > level
    return bool(sweep.get("ssl_sweep") or wick)


def _reaction_short(last: Dict[str, float], level: float, sweep: Dict[str, Any], confirm: bool) -> bool:
    if not confirm:
        return False
    wick = last["high"] > level and last["close"] < level
    return bool(sweep.get("bsl_sweep") or wick)


@dataclass
class LevelScenario:
    direction: str
    setup: str
    level: Dict[str, Any]
    status: str
    confirmation: str
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    rr_gross: Optional[float] = None
    rr_net: Optional[float] = None
    cancel: str = ""
    mode: str = "intraday"
    opens_position: bool = False


@dataclass
class LevelBook:
    symbol: str
    mode: str
    levels: List[Dict[str, Any]]
    scenarios: List[LevelScenario] = field(default_factory=list)
    should_notify: bool = False
    opens_position: bool = False
    kind: str = KIND_LEVEL
    extras: Dict[str, Any] = field(default_factory=dict)


def evaluate_level_book(
    *,
    symbol: str,
    candles: List[Dict[str, Any]],
    confirm_candles: Optional[List[Dict[str, Any]]] = None,
    price: Any = None,
    day_used_pct: Any = None,
    edge_score: Any = None,
    mode: str = "intraday",
    prev_fingerprint: str = "",
) -> LevelBook:
    """Два сценарії від рівнів. Дотик без реакції — WATCHING."""
    sym = str(symbol or "").upper()
    md = "scalp" if str(mode).lower() == "scalp" else "intraday"
    atr = classify_atr_day_used(day_used_pct)
    levels = collect_levels(candles)
    rows = [_c(x) for x in (candles or [])]
    rows = [x for x in rows if x]
    confirm = list(confirm_candles or candles or [])
    px = _f(price) or (rows[-1]["close"] if rows else None)
    sweep = detect_sweep_from_candles(confirm if md == "scalp" else candles)
    extras = {
        "atr": atr,
        "edge_threshold": SIGNAL_THRESHOLD,
        "mode": md,
        "costs": {"commission": COMMISSION, "slippage": SLIPPAGE},
    }
    book = LevelBook(symbol=sym, mode=md, levels=levels, extras=extras)
    if px is None or not levels or not rows:
        book.extras["reason"] = "немає ціни або рівнів"
        return book
    last = rows[-1]
    supports = [lv for lv in levels if lv["kind"] == "support"]
    resists = [lv for lv in levels if lv["kind"] == "resistance"]

    def _edge_ok() -> bool:
        try:
            e = float(edge_score) if edge_score is not None and edge_score != "" else None
        except (TypeError, ValueError):
            e = None
        if e is None:
            return True
        return e >= SIGNAL_THRESHOLD

    blocked = bool(atr.get("t0_entry_blocked") or atr.get("gerchik_entry_blocked") or not _edge_ok())

    if supports:
        lv = min(supports, key=lambda x: abs(float(x["low"]) - px))
        lvl_px = float(lv["low"])
        prox = classify_proximity(px, lvl_px)
        confirm_ok = m15_confirmation(confirm, direction="LONG", level=lvl_px)
        reacted = _reaction_long(last, lvl_px, sweep, confirm_ok)
        sc = LevelScenario(
            direction="LONG",
            setup="bounce",
            level=lv,
            status="WATCHING",
            confirmation="немає — дотик не достатній",
            cancel="закриття нижче структурного мінімуму рівня",
            mode=md,
        )
        if prox in ("approaching", "reached") or reacted:
            sc.confirmation = "ціна біля підтримки, чекаємо свіп/закриття вище"
        if reacted and not blocked:
            entry = px
            sl = sl_with_buffer(entry, direction="LONG", structure_sl=lvl_px)
            tp1 = nearest_target(levels, direction="LONG", entry=entry)
            if tp1:
                net = rr_after_costs(entry=entry, sl=sl, tp=tp1)
                gross = abs(tp1 - entry) / abs(entry - sl) if abs(entry - sl) else None
                sc.entry, sc.sl, sc.tp1 = entry, sl, tp1
                sc.tp2 = nearest_target(
                    [x for x in levels if float(x["low"]) > tp1],
                    direction="LONG",
                    entry=tp1,
                )
                sc.rr_gross, sc.rr_net = gross, net
                if net is not None and net >= MIN_RR:
                    sc.status = "CONFIRMED"
                    sc.setup = "sweep_reclaim" if sweep.get("ssl_sweep") else "bounce"
                    sc.confirmation = "реакція + закриття вище рівня"
                else:
                    sc.confirmation = "після комісій/прослизання RR недостатній для цього режиму"
        if blocked:
            sc.confirmation = str(atr.get("label") or "ATR/Edge блок")
            sc.status = "WATCHING"
        book.scenarios.append(sc)

    if resists:
        lv = min(resists, key=lambda x: abs(float(x["low"]) - px))
        lvl_px = float(lv["low"])
        prox = classify_proximity(px, lvl_px)
        confirm_ok = m15_confirmation(confirm, direction="SHORT", level=lvl_px)
        reacted = _reaction_short(last, lvl_px, sweep, confirm_ok)
        retest = detect_breakout_retest(confirm, lvl_px, direction="SHORT")
        sc = LevelScenario(
            direction="SHORT",
            setup="bounce",
            level=lv,
            status="WATCHING",
            confirmation="немає — дотик не достатній",
            cancel="закриття вище структурного максимуму рівня",
            mode=md,
        )
        if prox in ("approaching", "reached") or reacted or retest:
            sc.confirmation = "ціна біля опору, чекаємо свіп/закриття нижче"
        if (reacted or retest) and not blocked:
            entry = px
            sl = sl_with_buffer(entry, direction="SHORT", structure_sl=lvl_px)
            tp1 = nearest_target(levels, direction="SHORT", entry=entry)
            if tp1:
                net = rr_after_costs(entry=entry, sl=sl, tp=tp1)
                gross = abs(entry - tp1) / abs(sl - entry) if abs(sl - entry) else None
                sc.entry, sc.sl, sc.tp1 = entry, sl, tp1
                sc.rr_gross, sc.rr_net = gross, net
                if net is not None and net >= MIN_RR:
                    sc.status = "CONFIRMED"
                    sc.setup = "break_retest" if retest else ("sweep_reclaim" if sweep.get("bsl_sweep") else "bounce")
                    sc.confirmation = "реакція + закриття нижче рівня"
                else:
                    sc.confirmation = "після комісій/прослизання RR недостатній для цього режиму"
        if blocked:
            sc.confirmation = str(atr.get("label") or "ATR/Edge блок")
            sc.status = "WATCHING"
        book.scenarios.append(sc)

    fp = "|".join(
        f"{s.direction}:{s.status}:{s.setup}" for s in book.scenarios
    )
    extras["fingerprint"] = fp
    confirmed = [s for s in book.scenarios if s.status == "CONFIRMED"]
    book.should_notify = bool(confirmed) and fp != str(prev_fingerprint or "")
    book.opens_position = False
    return book


def format_level_book(book: LevelBook) -> str:
    """Факти карток рівнів. Не репліка Лева."""
    if not book.levels and not book.scenarios:
        return ""
    lines = [
        f"Рівні · {book.symbol} · режим {'скальп M1/M5' if book.mode == 'scalp' else 'внутрішній день M15/H1'}",
        "Дотик рівня — не сигнал. Картка після реакції. Угода лише через /position.",
    ]
    for lv in book.levels[:8]:
        lines.append(f"Рівень: {lv.get('label')} {lv.get('low')}–{lv.get('high')}")
    for sc in book.scenarios:
        lines.append(
            f"Сценарій {sc.direction} ({sc.setup}): {sc.status}. "
            f"Підтвердження: {sc.confirmation}."
        )
        if sc.status == "CONFIRMED" and sc.entry is not None:
            lines.append(
                f"  Entry {sc.entry} | SL {sc.sl} | TP1 {sc.tp1} | TP2 {sc.tp2} | "
                f"RR брутто {sc.rr_gross} / після витрат {sc.rr_net}"
            )
            lines.append(f"  Скасування: {sc.cancel}")
        elif sc.status == "WATCHING":
            lines.append("  Спостерігаємо, не змушуємо вгадувати чи рівень витримає.")
    return "\n".join(lines)
