"""T8: після SKIP — один кейс, версії аналізу, альтернативи без вигаданих рівнів.

Не новий поріг ATR/Edge. ПРЕМІУМ 16/20 ≠ дозвіл входу.
T7 forceOrder — уже відбуті ліквідації, не карта майбутніх рівнів.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from office_atr_policy import explain_atr_day_used, new_daily_bar_resets_atr
from office_bridge import log_event, signal_get_active, signal_upsert
from office_btc_liquidations import CREATES_ENTER
from office_external_signal import ExternalReview, VERDICT_CONFIRMED
from office_level_scalp import collect_levels
from office_market_data import SIGNAL_THRESHOLD
from office_range_radar import detect_range_bounds
from office_t7_health import diagnose_force_order_snapshot
from office_watching_dedup import apply_skip_watching_gate

KIND_SKIP_PLAN = "skip_plan"
SKIP_CASE_EVENT = "T8_SKIP_CASE"


def premium_score_allows_entry(_score: Any = None, _max: Any = None) -> bool:
    """Рейтинг бота не є дозволом входу."""
    return False


def case_key(original: Dict[str, Any]) -> str:
    """Один зовнішній сигнал — один кейс, незалежно від повторного LLM."""
    sym = str(original.get("symbol") or "").upper()
    side = str(original.get("direction") or "").upper()
    entry = original.get("entry")
    sl = original.get("sl")
    raw = f"{sym}|{side}|{entry}|{sl}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x


def liquidation_context(t7_snap: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """forceOrder ≠ heatmap майбутніх ліквідацій; idle_cold — не висновок про ринок."""
    snap = dict(t7_snap or {})
    diag = diagnose_force_order_snapshot(snap)
    usable = diag.get("state") == "connected"
    return {
        "kind": "forceOrder_actual_not_map",
        "usable_now": bool(usable),
        "state": diag.get("state"),
        "idle_cold_means_no_liquidations": False,
        "creates_enter": bool(CREATES_ENTER),
        "mm_hunting_claimed": False,
        "note": (
            "T7 показує вже здійснені forceOrder, не майбутні рівні CoinGlass/Hyblock. "
            "Поки connected=false / idle_cold — не робимо висновків про актуальні ліквідації."
            if not usable
            else "Потік підключений: події = уже відбуті ліквідації, не гарантована ціль MM."
        ),
    }


def _alt_from_candles(
    *,
    direction: str,
    candles: Optional[List[Dict[str, Any]]],
    setup: str,
) -> Dict[str, Any]:
    """Зона лише зі свічок. Немає свічок — не вигадуємо ціну з чату."""
    if not candles:
        return {
            "direction": direction,
            "setup": setup,
            "zone_low": None,
            "zone_high": None,
            "invented": False,
            "ready": False,
            "wait_for": [
                "актуальні H1/M15 свічки й реакція на рівень",
                "підтвердження (свіп + закриття), не дотик",
            ],
            "note": "немає перевірених свічок — рівні з тексту Лева/бота не підставляємо",
        }
    bounds = detect_range_bounds(candles)
    levels = collect_levels(candles, extra_bounds=bounds)
    if direction == "LONG":
        supports = [lv for lv in levels if lv.get("kind") == "support"]
        if not supports:
            return {
                "direction": "LONG",
                "setup": setup,
                "zone_low": None,
                "zone_high": None,
                "invented": False,
                "ready": False,
                "wait_for": ["поява перевіреної підтримки / FVG / OB на свічках"],
                "note": "структурної зони лонга ще немає",
            }
        lo = min(float(x["low"]) for x in supports)
        hi = max(float(x["high"]) for x in supports[-2:] or supports)
        return {
            "direction": "LONG",
            "setup": setup,
            "zone_low": lo,
            "zone_high": hi,
            "invented": False,
            "ready": False,
            "wait_for": [
                "відкат у перевірену зону",
                "SSL sweep або реакція + закриття вище",
                "нова D1 лише перерахунок day_used, не вхід",
            ],
            "note": "альтернативний LONG після відкату — WATCHING, не картка входу",
        }
    resists = [lv for lv in levels if lv.get("kind") == "resistance"]
    if not resists:
        return {
            "direction": "SHORT",
            "setup": setup,
            "zone_low": None,
            "zone_high": None,
            "invented": False,
            "ready": False,
            "wait_for": ["зміна структури (BOS) і свіп ліквідності зверху, не RSI сам по собі"],
            "note": "SHORT лише після підтвердженого розвороту",
        }
    lo = min(float(x["low"]) for x in resists[:2] or resists)
    hi = max(float(x["high"]) for x in resists)
    return {
        "direction": "SHORT",
        "setup": setup,
        "zone_low": lo,
        "zone_high": hi,
        "invented": False,
        "ready": False,
        "wait_for": [
            "свіп стопів над опором і закриття назад",
            "BOS вниз на малому ТФ",
            "не відкривати SHORT лише через RSI/великий денний хід",
        ],
        "note": "альтернативний SHORT — гіпотеза, доки немає розвороту",
    }


@dataclass
class SkipPlan:
    case_key: str
    current: str
    why: List[str]
    original: Dict[str, Any]
    atr: Dict[str, Any]
    alt_a: Dict[str, Any]
    alt_b: Dict[str, Any]
    liquidations: Dict[str, Any]
    retrigger: List[str]
    version: int = 1
    watching_id: str = ""
    invented_levels: bool = False
    premium_allows_entry: bool = False
    opens_position: bool = False
    kind: str = KIND_SKIP_PLAN
    extras: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "case_key": self.case_key,
            "current": self.current,
            "why": list(self.why),
            "original": deepcopy(self.original),
            "atr": dict(self.atr),
            "alt_a": dict(self.alt_a),
            "alt_b": dict(self.alt_b),
            "liquidations": dict(self.liquidations),
            "retrigger": list(self.retrigger),
            "version": self.version,
            "watching_id": self.watching_id,
            "invented_levels": False,
            "premium_allows_entry": False,
            "opens_position": False,
            "kind": self.kind,
            "new_d1_is_entry": False,
            "extras": dict(self.extras),
        }


def build_skip_plan(
    original: Dict[str, Any],
    review: ExternalReview,
    *,
    market: Optional[Dict[str, Any]] = None,
    t7_snap: Optional[Dict[str, Any]] = None,
    candles: Optional[List[Dict[str, Any]]] = None,
    premium_score: Any = None,
    version: int = 1,
) -> SkipPlan:
    orig = deepcopy(original or {})
    mkt = dict(market or {})
    atr = explain_atr_day_used(mkt.get("day_used_pct"))
    why: List[str] = []
    if review.verdict != VERDICT_CONFIRMED:
        why.append(f"поточний сигнал бота: SKIP / {review.verdict}")
    why.extend(list(review.reasons or []))
    if atr.get("plain"):
        why.append(str(atr["plain"]))
    if mkt.get("edge_score") is not None:
        why.append(
            f"Edge {mkt.get('edge_score')} (поріг {SIGNAL_THRESHOLD}) — рейтинг бота не замінює Edge"
        )
    why.append("ПРЕМІУМ 16/20 не є дозволом входу")
    if not review.reasons:
        why.append("немає sweep/BOS підтвердження для поточного entry бота")
    retrigger = [
        "перерахунок day_used (нова D1 не вхід)",
        "відкат у перевірену зону + SSL sweep + закриття (альтернатива LONG)",
        "свіп ліквідності зверху + BOS вниз (альтернатива SHORT)",
    ]
    if new_daily_bar_resets_atr():
        retrigger.append("помилка: D1 не має бути входом")
    return SkipPlan(
        case_key=case_key(orig),
        current="SKIP",
        why=why,
        original=orig,
        atr=atr,
        alt_a=_alt_from_candles(direction="LONG", candles=candles, setup="pullback_long"),
        alt_b=_alt_from_candles(direction="SHORT", candles=candles, setup="reversal_short"),
        liquidations=liquidation_context(t7_snap),
        retrigger=retrigger,
        version=int(version or 1),
        extras={
            "premium_score": premium_score,
            "premium_allows_entry": premium_score_allows_entry(premium_score),
        },
    )


def format_skip_plan(plan: SkipPlan) -> str:
    """Факти після SKIP. Не шаблон особистості Лева."""
    o = plan.original
    a, b = plan.alt_a, plan.alt_b
    watch_bits = []
    if a.get("zone_low") is not None:
        watch_bits.append(f"LONG-відкат {a.get('zone_low')}–{a.get('zone_high')}")
    else:
        watch_bits.append("LONG-відкат: чекаємо свічки, зону не вигадуємо")
    if b.get("zone_low") is not None:
        watch_bits.append(f"SHORT-гіпотеза {b.get('zone_low')}–{b.get('zone_high')}")
    else:
        watch_bits.append("SHORT: чекаємо BOS, не RSI")
    lines = [
        f"Цей вхід пропускаємо · {o.get('symbol')} {o.get('direction')} entry={o.get('entry')}",
        "Ось що відстежуємо: " + "; ".join(watch_bits),
        "Ось за якої події повідомимо: " + "; ".join(plan.retrigger),
        "Чому зараз не копіюємо бота:",
    ]
    for w in plan.why:
        lines.append(f"— {w}")
    lines.append("Альтернатива A · LONG після відкату:")
    if a.get("zone_low") is not None:
        lines.append(f"  зона {a.get('zone_low')}–{a.get('zone_high')} (зі свічок, не з чату)")
    else:
        lines.append(f"  {a.get('note')}")
    lines.append("  чекаємо: " + "; ".join(a.get("wait_for") or []))
    lines.append("Альтернатива B · SHORT після зміни структури:")
    if b.get("zone_low") is not None:
        lines.append(f"  зона {b.get('zone_low')}–{b.get('zone_high')} (гіпотеза до BOS)")
    else:
        lines.append(f"  {b.get('note')}")
    lines.append("  чекаємо: " + "; ".join(b.get("wait_for") or []))
    liq = plan.liquidations
    lines.append(f"Ліквідації T7: {liq.get('note')}")
    lines.append("Далі: " + "; ".join(plan.retrigger))
    lines.append("Картка після підтвердження. Угода лише через /position.")
    return "\n".join(lines)


def persist_skip_case(
    db_path: str,
    plan: SkipPlan,
    *,
    now_ts: float,
) -> Dict[str, Any]:
    """Один WATCHING на кейс. Повторний LLM додає версію, не другу зону."""
    payload = plan.as_dict()
    log_event(db_path, SKIP_CASE_EVENT, payload, signal_id=plan.case_key)
    watching_id = f"skip-{plan.case_key}"
    existing = [
        r
        for r in (signal_get_active(db_path) or [])
        if str(r.get("signal_id") or "") == watching_id
    ]
    zone = None
    for alt in (plan.alt_a, plan.alt_b):
        if alt.get("zone_low") is not None and alt.get("zone_high") is not None:
            zone = alt
            break
    if existing:
        return {
            "created": False,
            "version_bump": True,
            "watching_id": watching_id,
            "opens_position": False,
        }
    if zone is None:
        return {
            "created": False,
            "version_bump": False,
            "watching_id": "",
            "opens_position": False,
            "reason": "немає перевіреної зони — WATCHING без вигаданих цін",
        }
    gate = apply_skip_watching_gate(
        db_path,
        symbol=str(plan.original.get("symbol") or ""),
        direction=str(zone.get("direction") or "LONG"),
        entry_low=zone.get("zone_low"),
        entry_high=zone.get("zone_high"),
        timeframe=str(plan.original.get("timeframe") or "5m"),
        setup_name="skip_alt",
        now_ts=now_ts,
        current_price=plan.original.get("entry"),
    )
    if not gate.get("create"):
        return {
            "created": False,
            "version_bump": False,
            "watching_id": watching_id,
            "opens_position": False,
            "gate": gate,
        }
    signal_upsert(
        db_path,
        signal_id=watching_id,
        symbol=str(plan.original.get("symbol") or ""),
        direction=str(zone.get("direction") or "LONG"),
        entry_low=zone.get("zone_low"),
        entry_high=zone.get("zone_high"),
        sl=None,
        tp1=None,
        tp2=None,
        rr=None,
        status="WATCHING",
        analysis_note=json.dumps(
            {"case_key": plan.case_key, "version": plan.version, "kind": KIND_SKIP_PLAN},
            ensure_ascii=False,
        )[:2000],
    )
    return {
        "created": True,
        "version_bump": False,
        "watching_id": watching_id,
        "opens_position": False,
    }
