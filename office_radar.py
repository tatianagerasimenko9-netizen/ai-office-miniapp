"""T6: практичний радар рівнів / sweep / підтвердження.

Без підтвердження на малому ТФ — WATCHING, не сигнал.
SIGNAL лише картка розбору (T1: не відкриває позицію).
Ризик-фільтри чинні: RR, ATR T0, Kill Zone, bot_action BLOCKED (T5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from office_bridge import is_kill_zone
from office_market_state import scanner_signal_blocked
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT

# Люфт стопа — частка ціни; не CONFIG торгового ядра.
SL_BUFFER_PCT = 0.0015
NEAR_PCT = 0.0035
REACHED_PCT = 0.0012
MIN_RR = 1.5
DEFAULT_RR = 2.0
RADAR_SYMBOLS = ("BTCUSDT",)


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x


def cluster_sr_levels(candles: List[Dict[str, Any]], *, min_touches: int = 2, limit: int = 6) -> List[Dict[str, Any]]:
    """Підтримка/опір з хаїв/лоїв. Той самий кластер, що fetch_key_levels, але офлайн."""
    points: List[Dict[str, Any]] = []
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        h = _f(c.get("high"))
        l = _f(c.get("low"))
        if h:
            points.append({"price": h, "type": "resistance"})
        if l:
            points.append({"price": l, "type": "support"})
    clusters: List[Dict[str, Any]] = []
    for p in points:
        price = float(p["price"])
        ptype = str(p["type"])
        matched = False
        for cl in clusters:
            if str(cl["type"]) != ptype:
                continue
            center = float(cl["price"])
            tol = max(center * 0.005, 1e-9)
            if abs(price - center) <= tol:
                touches = int(cl["touches"]) + 1
                cl["touches"] = touches
                cl["price"] = ((center * (touches - 1)) + price) / touches
                matched = True
                break
        if not matched:
            clusters.append({"price": price, "type": ptype, "touches": 1})
    clusters = [c for c in clusters if int(c["touches"]) >= int(min_touches)]
    clusters.sort(key=lambda x: int(x["touches"]), reverse=True)
    out: List[Dict[str, Any]] = []
    for cl in clusters[: max(1, int(limit))]:
        touches = int(cl["touches"])
        out.append(
            {
                "price": float(cl["price"]),
                "type": str(cl["type"]),
                "touches": touches,
                "strength": "strong" if touches >= 4 else "medium",
            }
        )
    return out


def classify_proximity(price: float, level: float) -> str:
    """away | approaching | reached."""
    p = _f(price)
    lv = _f(level)
    if p is None or lv is None:
        return "away"
    dist = abs(p - lv) / p
    if dist <= REACHED_PCT:
        return "reached"
    if dist <= NEAR_PCT:
        return "approaching"
    return "away"


def detect_sweep_from_candles(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """BSL/SSL як у fetch_liquidity_sweep, без мережі."""
    result = {"bsl_sweep": False, "ssl_sweep": False, "sweep_level": None, "direction_hint": ""}
    if not isinstance(candles, list) or len(candles) < 3:
        return result
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    if not all(isinstance(c, dict) for c in (c1, c2, c3)):
        return result
    h1, h2 = _f(c1.get("high")), _f(c2.get("high"))
    l1, l2 = _f(c1.get("low")), _f(c2.get("low"))
    hi, lo, cl = _f(c3.get("high")), _f(c3.get("low")), _f(c3.get("close"))
    if None in (h1, h2, l1, l2, hi, lo, cl):
        return result
    prev_high = max(h1, h2)  # type: ignore[arg-type]
    prev_low = min(l1, l2)  # type: ignore[arg-type]
    if hi > prev_high and cl < prev_high:
        result["bsl_sweep"] = True
        result["sweep_level"] = prev_high
        result["direction_hint"] = "SHORT"
    if lo < prev_low and cl > prev_low:
        result["ssl_sweep"] = True
        result["sweep_level"] = prev_low if not result["bsl_sweep"] else result["sweep_level"]
        result["direction_hint"] = "LONG" if not result["bsl_sweep"] else result["direction_hint"]
    return result


def m15_confirmation(candles_m15: List[Dict[str, Any]], *, direction: str, level: float) -> bool:
    """Підтвердження: остання M15 закрилась назад за рівень у бік сетапу."""
    if not isinstance(candles_m15, list) or len(candles_m15) < 1:
        return False
    last = candles_m15[-1]
    if not isinstance(last, dict):
        return False
    cl = _f(last.get("close"))
    op = _f(last.get("open"))
    lv = _f(level)
    if cl is None or op is None or lv is None:
        return False
    side = str(direction or "").upper()
    if side == "LONG":
        return cl > lv and cl >= op
    if side == "SHORT":
        return cl < lv and cl <= op
    return False


def sl_with_buffer(entry: float, *, direction: str, structure_sl: float) -> float:
    """Стоп за структуру + люфт."""
    e = float(entry)
    sl = float(structure_sl)
    buf = e * SL_BUFFER_PCT
    side = str(direction or "").upper()
    if side == "LONG":
        return min(sl, e) - buf
    return max(sl, e) + buf


def card_levels(*, direction: str, entry: float, structure_sl: float, rr: float = DEFAULT_RR) -> Dict[str, Any]:
    sl = sl_with_buffer(entry, direction=direction, structure_sl=structure_sl)
    risk = abs(entry - sl)
    side = str(direction or "").upper()
    if risk <= 0:
        return {"entry": entry, "sl": sl, "tp": None, "rr": 0.0}
    if side == "LONG":
        tp = entry + risk * float(rr)
    else:
        tp = entry - risk * float(rr)
    return {"entry": entry, "sl": sl, "tp": tp, "rr": float(rr)}


def format_radar_card(result: "RadarResult") -> str:
    if result.status == "SIGNAL" and result.card:
        c = result.card
        return (
            f"Радар · {result.symbol} {result.direction}\n"
            f"Рівень: {result.level_price} ({result.level_type}) · {result.proximity}\n"
            f"Sweep: так · M15: підтверджено\n"
            f"Entry: {c['entry']:.6g} | SL: {c['sl']:.6g} (з люфтом) | TP: {c['tp']:.6g} | RR: {c['rr']:.1f}\n"
            "Це картка сетапу, не відкрита позиція. Угода лише через /position."
        )
    return (
        f"Радар · {result.symbol} WATCHING\n"
        f"Рівень: {result.level_price} ({result.level_type}) · {result.proximity}\n"
        f"Причина: {result.reason}\n"
        "Без підтвердження на M15 — не сигнал."
    )


@dataclass
class RadarResult:
    symbol: str
    status: str  # NONE | WATCHING | SIGNAL
    direction: str = ""
    level_price: Optional[float] = None
    level_type: str = ""
    proximity: str = "away"
    reason: str = ""
    card: Optional[Dict[str, Any]] = None
    opens_position: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)


def evaluate_radar(
    *,
    symbol: str,
    price: float,
    daily_candles: List[Dict[str, Any]],
    sweep_candles: List[Dict[str, Any]],
    m15_candles: List[Dict[str, Any]],
    day_used_pct: Optional[float] = None,
    bot_action: Any = None,
    utc_now: Optional[datetime] = None,
    in_kill_zone: Optional[bool] = None,
) -> RadarResult:
    """Рішення радара. SIGNAL лише при sweep + M15 + ризик ок."""
    sym = str(symbol or "").upper().strip() or "BTCUSDT"
    px = _f(price)
    levels = cluster_sr_levels(daily_candles)
    if px is None or not levels:
        return RadarResult(symbol=sym, status="NONE", reason="немає ціни або рівнів")

    nearest = min(levels, key=lambda lv: abs(float(lv["price"]) - px))
    level_px = float(nearest["price"])
    prox = classify_proximity(px, level_px)
    sweep = detect_sweep_from_candles(sweep_candles)
    direction = str(sweep.get("direction_hint") or "")
    if not direction:
        if str(nearest["type"]) == "support":
            direction = "LONG"
        elif str(nearest["type"]) == "resistance":
            direction = "SHORT"

    base = RadarResult(
        symbol=sym,
        status="WATCHING",
        direction=direction,
        level_price=level_px,
        level_type=str(nearest["type"]),
        proximity=prox,
        reason="рівень є, підтвердження немає",
        extras={"sweep": sweep, "touches": nearest.get("touches")},
    )
    if prox == "away" and not (sweep.get("bsl_sweep") or sweep.get("ssl_sweep")):
        base.status = "NONE"
        base.reason = "ціна далеко від рівня"
        return base

    confirmed = False
    sweep_lv = _f(sweep.get("sweep_level")) or level_px
    if sweep.get("ssl_sweep") and direction == "LONG":
        confirmed = m15_confirmation(m15_candles, direction="LONG", level=float(sweep_lv))
    elif sweep.get("bsl_sweep") and direction == "SHORT":
        confirmed = m15_confirmation(m15_candles, direction="SHORT", level=float(sweep_lv))

    if not confirmed:
        base.reason = "sweep/наближення без підтвердження M15"
        return base

    structure_sl = float(sweep_lv)
    card = card_levels(direction=direction, entry=px, structure_sl=structure_sl, rr=DEFAULT_RR)
    base.card = card
    if float(card.get("rr") or 0) < MIN_RR:
        base.reason = f"RR {card.get('rr')} < {MIN_RR} — не сигнал"
        return base
    if day_used_pct is not None and float(day_used_pct) > ATR_DAY_USED_ENTRY_BLOCK_PCT:
        base.reason = "ATR day_used>90 — T0 блок входу, лишаємо WATCHING"
        return base
    if scanner_signal_blocked(bot_action):
        base.reason = "bot_action=BLOCKED — T5, не сигнал"
        return base
    kz = in_kill_zone
    if kz is None:
        kz = is_kill_zone(utc_now or datetime.now(timezone.utc))
    if not kz:
        base.reason = "поза Kill Zone — WATCHING, не сигнал"
        return base

    base.status = "SIGNAL"
    base.reason = "sweep + M15 + ризик ок"
    base.opens_position = False
    return base
