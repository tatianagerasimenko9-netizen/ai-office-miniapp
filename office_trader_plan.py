"""T8: один торговий план на сигнал бота — не SKIP як фінал.

Бот = кандидат. Лев перевіряє поточний вхід, LONG після відкату і SHORT після
свіпу/BOS. Рівні лише з даних. Виніс ≠ намір маркет-мейкера.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from office_external_signal import ExternalReview, VERDICT_CONFIRMED
from office_level_scalp import nearest_target, rr_after_costs
from office_radar import MIN_RR, detect_sweep_from_candles
from office_range_radar import classify_range_event, detect_range_bounds
from office_skip_plan import SkipPlan, build_skip_plan, case_key, format_skip_plan

KIND_TRADER = "trader_plan"
WICK_SWEEP_RETURN = "SWEEP_RETURN"
WICK_BREAK_HOLD = "BREAK_HOLD"
WICK_VOLATILE = "VOLATILE"
WICK_NONE = "NONE"


def classify_wick(*, candles: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Свіп із поверненням vs пробій vs звичайна волатильність. Без наміру MM."""
    empty = {
        "class": WICK_NONE,
        "mm_intent_claimed": False,
        "more_likely_short": False,
        "reason": "немає свічок для класифікації виносу",
    }
    if not candles or len(candles) < 3:
        return empty
    sweep = detect_sweep_from_candles(candles)
    bounds = detect_range_bounds(candles)
    if bounds:
        last = candles[-1] if isinstance(candles[-1], dict) else {}
        prev = candles[-2] if isinstance(candles[-2], dict) else None
        ev = classify_range_event(bounds=bounds, last={
            "open": float(last.get("open") or 0),
            "high": float(last.get("high") or 0),
            "low": float(last.get("low") or 0),
            "close": float(last.get("close") or 0),
        }, prev={
            "open": float((prev or {}).get("open") or 0),
            "high": float((prev or {}).get("high") or 0),
            "low": float((prev or {}).get("low") or 0),
            "close": float((prev or {}).get("close") or 0),
        } if prev else None, confirm_candles=candles)
        if ev.get("event") in ("SWEEP_HIGH", "SWEEP_LOW"):
            return {
                "class": WICK_SWEEP_RETURN,
                "mm_intent_claimed": False,
                "more_likely_short": False,
                "event": ev.get("event"),
                "reason": ev.get("reason"),
            }
        if ev.get("confirmed"):
            return {
                "class": WICK_BREAK_HOLD,
                "mm_intent_claimed": False,
                "more_likely_short": False,
                "event": ev.get("event"),
                "reason": ev.get("reason"),
            }
    if sweep.get("bsl_sweep") or sweep.get("ssl_sweep"):
        return {
            "class": WICK_SWEEP_RETURN,
            "mm_intent_claimed": False,
            "more_likely_short": False,
            "reason": "свіп із поверненням за рівень — гіпотеза, не сигнал",
        }
    return {
        "class": WICK_VOLATILE,
        "mm_intent_claimed": False,
        "more_likely_short": False,
        "reason": "різкий рух без свіпу/закріплення — волатильність, не маніпуляція MM",
    }


def assess_bot_entry(
    original: Dict[str, Any],
    *,
    price: Any = None,
    levels: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Чи придатний entry бота, чи запізнілий (мало простору до цілі)."""
    side = str(original.get("direction") or "").upper()
    entry = original.get("entry")
    sl = original.get("sl")
    tp = original.get("tp1")
    try:
        px = float(price) if price is not None else float(entry or 0)
        e = float(entry or 0)
        s = float(sl or 0)
    except (TypeError, ValueError):
        px, e, s = 0.0, 0.0, 0.0
    late = False
    reason = "початковий entry бота ще можна розглядати після фільтрів"
    if e > 0 and px > 0 and abs(px - e) / px > 0.012:
        late = True
        reason = "ціна вже далеко від entry бота — початковий вхід пропускаємо"
    if e > 0 and s > 0 and levels:
        tgt = nearest_target(levels, direction=side or "LONG", entry=px or e)
        if tgt is not None:
            net = rr_after_costs(entry=px or e, sl=s, tp=tgt)
            if net is not None and net < MIN_RR:
                late = True
                reason = "до найближчого перевіреного рівня замало простору після витрат"
    if tp and e and s:
        net_bot = rr_after_costs(entry=e, sl=s, tp=tp)
        if net_bot is not None and net_bot < MIN_RR and str(original.get("mode") or "") == "scalp":
            late = True
            reason = "скальп бота після комісій не проходить RR"
    return {
        "usable": not late,
        "late": late,
        "reason": reason,
        "direction_kept": side in ("LONG", "SHORT"),
        "copy_bot": False,
    }


@dataclass
class TraderPlan:
    case_key: str
    bot_verdict: str
    own_plan: str
    opposite: str
    office_action: str
    wick: Dict[str, Any]
    skip: Optional[SkipPlan]
    confirmed_card: Optional[Dict[str, Any]] = None
    asof: str = ""
    opens_position: bool = False
    mm_intent_claimed: bool = False
    kind: str = KIND_TRADER
    extras: Dict[str, Any] = field(default_factory=dict)


def compose_trader_plan(
    original: Dict[str, Any],
    review: ExternalReview,
    *,
    market: Optional[Dict[str, Any]] = None,
    t7_snap: Optional[Dict[str, Any]] = None,
    candles: Optional[List[Dict[str, Any]]] = None,
    skip: Optional[SkipPlan] = None,
    confirmed_card: Optional[Dict[str, Any]] = None,
    asof: str = "",
) -> TraderPlan:
    """Завжди план або обґрунтована відсутність плану. Не фінал на слові SKIP."""
    orig = deepcopy(original or {})
    mkt = dict(market or {})
    wick = classify_wick(candles=candles)
    entry_view = assess_bot_entry(
        orig,
        price=mkt.get("price") or orig.get("entry"),
        levels=mkt.get("levels"),
    )
    sp = skip
    if sp is None and review.verdict != VERDICT_CONFIRMED:
        sp = build_skip_plan(
            orig,
            review,
            market=mkt,
            t7_snap=t7_snap,
            candles=candles,
        )
    if entry_view["late"] or review.verdict != VERDICT_CONFIRMED:
        bot_v = (
            f"Сигнал бота: {orig.get('direction')} entry={orig.get('entry')} — "
            f"початковий вхід пропускаємо. {entry_view['reason']}. "
            f"Вердикт фільтрів: {review.verdict}."
        )
    else:
        bot_v = (
            f"Сигнал бота {orig.get('direction')} збігається з правилами як картка розбору, "
            "не як ордер."
        )
    if sp:
        a = sp.alt_a
        if a.get("zone_low") is not None:
            own = (
                f"Власний план: спостерігаю LONG-відкат у {a.get('zone_low')}–{a.get('zone_high')}. "
                "Підтвердження: свіп мінімуму, повернення над рівень, структура M5. "
                "Після цього перерахую entry/SL/TP. Сам дотик зони — не вхід."
            )
        else:
            own = (
                "Власний план: перевіреної зони попиту на свічках немає — рівні не вигадую. "
                f"{a.get('note')}. {'; '.join(a.get('wait_for') or [])}."
            )
        b = sp.alt_b
        if wick.get("class") == WICK_BREAK_HOLD and str((confirmed_card or {}).get("direction") or "") == "SHORT":
            opp = "SHORT підтверджено карткою після структури, не через RSI чи виніс."
        elif b.get("zone_low") is not None:
            opp = (
                f"Протилежний сценарій: виніс до {b.get('zone_high')} сам по собі не сигнал. "
                "SHORT лише після повернення під опір і BOS. Ймовірніший SHORT без цих даних не оголошую."
            )
        else:
            opp = (
                "Протилежний сценарій: SHORT не називаю ймовірнішим без BOS і свіпу зверху. "
                f"{b.get('note')}."
            )
        action = (
            "Обидва сценарії у WATCHING. Повідомлю після підтвердження або інвалідації. "
            "Початковий сигнал бота не дублюю. Угода лише через /position."
        )
    else:
        own = "Власний план: поточна картка офісу після підтвердження (не копія бота)."
        opp = "Протилежний сценарій лишається гіпотезою, доки немає зворотного BOS."
        action = "Картка надіслана після підтвердження. Не чекаємо повторного запиту по монеті."
    if confirmed_card and not (sp and review.verdict != VERDICT_CONFIRMED):
        action = (
            "Підтверджений сценарій уже в картці. Інший напрямок — WATCHING до інвалідації. "
            "Угода лише через /position."
        )
    return TraderPlan(
        case_key=case_key(orig),
        bot_verdict=bot_v,
        own_plan=own,
        opposite=opp,
        office_action=action,
        wick=wick,
        skip=sp,
        confirmed_card=deepcopy(confirmed_card) if confirmed_card else None,
        asof=str(asof or orig.get("received_at") or ""),
        extras={"entry_view": entry_view, "review": review.verdict},
    )


def format_trader_plan(plan: TraderPlan) -> str:
    """Одне повідомлення в Telegram: 4 блоки фактів, не репліка-шаблон."""
    lines = [
        "1) Вердикт щодо сигналу бота",
        plan.bot_verdict,
        "2) Власний торговий план",
        plan.own_plan,
        "3) Протилежний сценарій",
        plan.opposite,
        "4) Дія офісу",
        plan.office_action,
    ]
    if plan.asof:
        lines.append(f"Дані asof: {plan.asof}")
    lines.append(f"Виніс: {plan.wick.get('class')} — {plan.wick.get('reason')}")
    lines.append("Намір маркет-мейкера не стверджую.")
    lines.append("Це аналітика, не ордер.")
    if plan.skip:
        lines.append(format_skip_plan(plan.skip))
    return "\n".join(lines)
