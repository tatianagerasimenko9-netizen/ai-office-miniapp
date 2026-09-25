"""T8: боковик → спостереження за обома виходами; мультиактив.

RANGE не є спамом «не заходимо». Прокол межі ≠ підтверджений пробій.
BTC/золото — контекст, не автоматичний сигнал для іншої монети.
Картка після підтвердження — не ордер.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from office_atr_policy import classify_atr_day_used
from office_market_data import SIGNAL_THRESHOLD
from office_radar import MIN_RR, card_levels, detect_sweep_from_candles
from office_session_radar import detect_breakout_retest, m15_confirmation

# Окремо від T6 RADAR_SYMBOLS (лишається BTCUSDT).
T8_SCAN_UNIVERSE: Tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "XAUUSDT",
)
KIND_RANGE = "range_radar"
MAX_RANGE_WIDTH_PCT = 3.5
CONTEXT_ASSETS = frozenset({"BTCUSDT", "XAUUSDT"})


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x


def _c(bar: Any) -> Optional[Dict[str, float]]:
    if not isinstance(bar, dict):
        return None
    o, h, l, cl = _f(bar.get("open")), _f(bar.get("high")), _f(bar.get("low")), _f(bar.get("close"))
    if None in (o, h, l, cl):
        return None
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(cl)}


def detect_range_bounds(
    candles: List[Dict[str, Any]],
    *,
    lookback: int = 24,
    exclude_last: int = 2,
) -> Optional[Dict[str, Any]]:
    """Верх/низ/рівновага боковика. Останні свічки не розширюють межі (інакше пробій зникає)."""
    raw = list(candles or [])
    if exclude_last > 0 and len(raw) > exclude_last:
        raw = raw[:-int(exclude_last)]
    rows = [_c(x) for x in raw[-max(8, int(lookback)) :]]
    rows = [x for x in rows if x]
    if len(rows) < 8:
        return None
    hi = max(r["high"] for r in rows)
    lo = min(r["low"] for r in rows)
    mid = (hi + lo) / 2.0
    if mid <= 0:
        return None
    width_pct = (hi - lo) / mid * 100.0
    if width_pct <= 0 or width_pct > MAX_RANGE_WIDTH_PCT:
        return None
    return {
        "high": hi,
        "low": lo,
        "mid": mid,
        "width_pct": round(width_pct, 3),
        "stops_above": hi,
        "stops_below": lo,
    }


def classify_range_event(
    *,
    bounds: Dict[str, Any],
    last: Dict[str, float],
    prev: Optional[Dict[str, float]] = None,
    confirm_candles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Прокол, свіп-маніпуляція або закріплення. Обидві гіпотези живі до підтвердження."""
    rh, rl = float(bounds["high"]), float(bounds["low"])
    hi, lo, cl = last["high"], last["low"], last["close"]
    prev_cl = prev["close"] if prev else cl

    long_hyp = {
        "direction": "LONG",
        "kind": "hypothesis",
        "note": "закріплення вище межі + ретест зверху",
    }
    short_hyp = {
        "direction": "SHORT",
        "kind": "hypothesis",
        "note": "закріплення нижче межі + ретест знизу",
    }
    fake_short = {
        "direction": "SHORT",
        "kind": "hypothesis",
        "note": "хибний пробій верху боковика (свіп стопів зверху)",
    }
    fake_long = {
        "direction": "LONG",
        "kind": "hypothesis",
        "note": "хибний пробій низу боковика (свіп стопів знизу)",
    }

    # Свіп: тінь за межею, закриття всередині.
    if hi > rh and cl < rh:
        return {
            "event": "SWEEP_HIGH",
            "confirmed": False,
            "status": "PIERCE_WATCHING",
            "hypotheses": [fake_short, long_hyp],
            "active_hint": "SHORT",
            "reason": "прокол верху з поверненням у діапазон — маніпуляція, не пробій",
        }
    if lo < rl and cl > rl:
        return {
            "event": "SWEEP_LOW",
            "confirmed": False,
            "status": "PIERCE_WATCHING",
            "hypotheses": [fake_long, short_hyp],
            "active_hint": "LONG",
            "reason": "прокол низу з поверненням у діапазон — маніпуляція, не пробій",
        }

    close_above = cl > rh
    close_below = cl < rl
    prev_above = prev_cl > rh
    prev_below = prev_cl < rl
    m15 = confirm_candles or []
    retest_long = detect_breakout_retest(m15, rh, direction="LONG") if close_above else False
    retest_short = detect_breakout_retest(m15, rl, direction="SHORT") if close_below else False
    hold_long = m15_confirmation(m15, direction="LONG", level=rh) if close_above else False
    hold_short = m15_confirmation(m15, direction="SHORT", level=rl) if close_below else False

    if close_above and (prev_above or retest_long or hold_long):
        return {
            "event": "BREAK_HIGH",
            "confirmed": True,
            "status": "CONFIRMED",
            "hypotheses": [long_hyp],
            "active_hint": "LONG",
            "reason": "закріплення вище боковика — сценарій продовження LONG",
        }
    if close_below and (prev_below or retest_short or hold_short):
        return {
            "event": "BREAK_LOW",
            "confirmed": True,
            "status": "CONFIRMED",
            "hypotheses": [short_hyp],
            "active_hint": "SHORT",
            "reason": "закріплення нижче боковика — сценарій продовження SHORT",
        }
    if close_above:
        return {
            "event": "PIERCE_HIGH",
            "confirmed": False,
            "status": "PIERCE_WATCHING",
            "hypotheses": [long_hyp, fake_short],
            "active_hint": "",
            "reason": "закриття вище межі без закріплення/ретесту — обидві гіпотези живі",
        }
    if close_below:
        return {
            "event": "PIERCE_LOW",
            "confirmed": False,
            "status": "PIERCE_WATCHING",
            "hypotheses": [short_hyp, fake_long],
            "active_hint": "",
            "reason": "закриття нижче межі без закріплення/ретесту — обидві гіпотези живі",
        }
    return {
        "event": "INSIDE",
        "confirmed": False,
        "status": "RANGE_WATCHING",
        "hypotheses": [long_hyp, short_hyp],
        "active_hint": "",
        "reason": "ціна всередині боковика — стежимо за обома межами",
    }


def notify_fingerprint(symbol: str, bounds: Dict[str, Any], event: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(symbol),
            str(event.get("status") or ""),
            str(event.get("event") or ""),
            f"{float(bounds.get('high') or 0):.6g}",
            f"{float(bounds.get('low') or 0):.6g}",
            str(event.get("active_hint") or ""),
        ]
    )


@dataclass
class RangeRadarResult:
    symbol: str
    status: str  # NONE | RANGE_WATCHING | PIERCE_WATCHING | CONFIRMED | INVALIDATED
    bounds: Optional[Dict[str, Any]] = None
    event: str = ""
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    direction: str = ""
    reason: str = ""
    card: Optional[Dict[str, Any]] = None
    should_notify: bool = False
    opens_position: bool = False
    copies_btc_or_gold: bool = False
    kind: str = KIND_RANGE
    extras: Dict[str, Any] = field(default_factory=dict)


def evaluate_range_radar(
    *,
    symbol: str,
    candles: List[Dict[str, Any]],
    confirm_candles: Optional[List[Dict[str, Any]]] = None,
    price: Any = None,
    day_used_pct: Any = None,
    edge_score: Any = None,
    btc_context: Optional[Dict[str, Any]] = None,
    gold_context: Optional[Dict[str, Any]] = None,
    prev_fingerprint: str = "",
) -> RangeRadarResult:
    """Один інструмент. Контекст BTC/XAU не копіює напрямок."""
    sym = str(symbol or "").upper().strip()
    bounds = detect_range_bounds(candles)
    atr = classify_atr_day_used(day_used_pct)
    extras: Dict[str, Any] = {
        "atr": atr,
        "edge_threshold": SIGNAL_THRESHOLD,
        "btc_context": dict(btc_context or {}),
        "gold_context": dict(gold_context or {}),
        "context_only": True,
    }
    empty = RangeRadarResult(
        symbol=sym,
        status="NONE",
        reason="немає боковика — цей модуль мовчить, не пише RANGE",
        extras=extras,
    )
    if not bounds:
        return empty
    rows = [_c(x) for x in (candles or []) if _c(x)]
    if not rows:
        return empty
    last, prev = rows[-1], (rows[-2] if len(rows) > 1 else None)
    ev = classify_range_event(
        bounds=bounds,
        last=last,
        prev=prev,
        confirm_candles=confirm_candles or candles,
    )
    fp = notify_fingerprint(sym, bounds, ev)
    notify = fp != str(prev_fingerprint or "")
    # Повторний RANGE_WATCHING з тими самими межами — без спаму.
    if ev["status"] == "RANGE_WATCHING" and str(prev_fingerprint or "").startswith(f"{sym}|RANGE_WATCHING|"):
        same_bounds = str(prev_fingerprint or "").split("|")[3:5] == [
            f"{float(bounds['high']):.6g}",
            f"{float(bounds['low']):.6g}",
        ]
        if same_bounds:
            notify = False

    direction = str(ev.get("active_hint") or "")
    card = None
    status = str(ev["status"])
    px = _f(price) or last["close"]
    if ev.get("confirmed") and direction:
        structure_sl = float(bounds["low"] if direction == "LONG" else bounds["high"])
        plan = card_levels(direction=direction, entry=float(px), structure_sl=structure_sl, rr=2.0)
        try:
            edge_f = float(edge_score) if edge_score is not None and edge_score != "" else None
        except (TypeError, ValueError):
            edge_f = None
        if float(plan.get("rr") or 0) < MIN_RR:
            status = "PIERCE_WATCHING"
            ev["reason"] = f"пробій є, RR {plan.get('rr')} < {MIN_RR} — картки немає"
            ev["confirmed"] = False
        elif atr.get("t0_entry_blocked") or atr.get("gerchik_entry_blocked"):
            status = "PIERCE_WATCHING"
            ev["reason"] = str(atr.get("label") or "ATR блок входу")
            ev["confirmed"] = False
        elif edge_f is not None and edge_f < SIGNAL_THRESHOLD:
            status = "PIERCE_WATCHING"
            ev["reason"] = f"пробій без Edge>={SIGNAL_THRESHOLD}"
            ev["confirmed"] = False
        else:
            e = float(plan["entry"])
            t1 = float(plan["tp"])
            plan["tp1"] = t1
            plan["tp2"] = e + (t1 - e) * 1.6 if direction == "LONG" else e - (e - t1) * 1.6
            card = plan
            status = "CONFIRMED"

    sweep = detect_sweep_from_candles(candles)
    extras["sweep"] = sweep
    extras["fingerprint"] = fp
    return RangeRadarResult(
        symbol=sym,
        status=status,
        bounds=bounds,
        event=str(ev.get("event") or ""),
        hypotheses=list(ev.get("hypotheses") or []),
        direction=direction if status == "CONFIRMED" else "",
        reason=str(ev.get("reason") or ""),
        card=card,
        should_notify=notify,
        opens_position=False,
        copies_btc_or_gold=False,
        extras=extras,
    )


def scan_universe(
    snapshots: Dict[str, Dict[str, Any]],
    *,
    prev_fingerprints: Optional[Dict[str, str]] = None,
) -> List[RangeRadarResult]:
    """Паралельний розбір інструментів. Напрямок BTC/XAU не копіюється на альти."""
    prev = dict(prev_fingerprints or {})
    btc = snapshots.get("BTCUSDT") or {}
    gold = snapshots.get("XAUUSDT") or snapshots.get("XAUUSD") or {}
    btc_ctx = {
        "regime": btc.get("regime") or "",
        "range": bool(detect_range_bounds(btc.get("candles") or [])),
        "not_a_signal_for_alts": True,
    }
    gold_ctx = {
        "regime": gold.get("regime") or "",
        "not_a_signal_for_alts": True,
    }
    out: List[RangeRadarResult] = []
    for sym, snap in snapshots.items():
        if not isinstance(snap, dict):
            continue
        res = evaluate_range_radar(
            symbol=str(sym),
            candles=snap.get("candles") or [],
            confirm_candles=snap.get("confirm_candles") or snap.get("candles"),
            price=snap.get("price"),
            day_used_pct=snap.get("day_used_pct"),
            edge_score=snap.get("edge_score"),
            btc_context=btc_ctx if str(sym).upper() not in CONTEXT_ASSETS else None,
            gold_context=gold_ctx if str(sym).upper() != "XAUUSDT" else None,
            prev_fingerprint=prev.get(str(sym).upper(), ""),
        )
        out.append(res)
    return out


def format_range_card(res: RangeRadarResult) -> str:
    """Факти. Без «RANGE, не заходимо» щогодини."""
    if res.status == "NONE":
        return ""
    b = res.bounds or {}
    lines = [
        f"Радар боковика · {res.symbol}",
        f"Межі: {b.get('low')}–{b.get('high')} · рівновага {b.get('mid')} · ширина {b.get('width_pct')}%",
        f"Стопи: над {b.get('stops_above')} і під {b.get('stops_below')}",
        f"Подія: {res.event or 'INSIDE'} · {res.reason}",
    ]
    for h in res.hypotheses:
        lines.append(f"Гіпотеза {h.get('direction')}: {h.get('note')}")
    if res.card:
        c = res.card
        lines.append(
            f"Підтверджена картка {res.direction}: "
            f"entry={c.get('entry')} SL={c.get('sl')} "
            f"TP1={c.get('tp1') or c.get('tp')} TP2={c.get('tp2')} RR={c.get('rr')}"
        )
        lines.append("Картка сетапу, не ордер. Угода лише через /position.")
    else:
        lines.append("Підтвердженої картки ще немає — передчасний вхід відсіюємо.")
    if res.symbol not in CONTEXT_ASSETS:
        lines.append("BTC і золото — лише контекст, не копія напрямку для цієї монети.")
    return "\n".join(lines)


def radar_symbols_for_monitor(t6_symbols: Sequence[str]) -> List[str]:
    """T6 лишає BTC; T8 додає всесвіт без дублікатів."""
    seen = set()
    out: List[str] = []
    for s in list(t6_symbols) + list(T8_SCAN_UNIVERSE):
        u = str(s or "").upper()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out
