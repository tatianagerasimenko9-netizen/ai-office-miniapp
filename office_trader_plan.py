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
from office_skip_plan import SkipPlan, build_skip_plan, case_key
from office_telegram_filter import format_px
from office_topdown import clock_pair_ua

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
    extras_stale = bool((review.extras or {}).get("signal_stale"))
    clock = str((review.extras or {}).get("clock_line") or "")
    if extras_stale and not clock:
        clock = clock_pair_ua(
            orig.get("source_at") or orig.get("received_at"),
            mkt.get("review_at") or (review.extras or {}).get("review_at"),
            scalp=True,
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
    if entry_view["late"] or review.verdict != VERDICT_CONFIRMED or extras_stale:
        stale_bit = f"{clock} " if clock else "Первинний сигнал застарів. "
        bot_v = (
            f"{stale_bit}Сигнал бота: {orig.get('direction')} entry={format_px(orig.get('entry'))} "
            f"(картка {orig.get('source_at') or orig.get('received_at') or 'н/д'}). "
            f"Початковий вхід не копіюємо. {entry_view['reason']}. "
            f"Вердикт: {review.verdict}."
        )
    else:
        bot_v = (
            f"Сигнал бота {orig.get('direction')} збігається з правилами як картка розбору, "
            "не як ордер."
        )
    confirmed_ok = (
        review.verdict == VERDICT_CONFIRMED
        and not extras_stale
        and not entry_view["late"]
    )
    if confirmed_ok:
        p = dict(confirmed_card or review.office_plan or {})
        e, s, t1 = format_px(p.get("entry")), format_px(p.get("sl")), format_px(p.get("tp1") or p.get("tp"))
        own = (
            "Підтверджений план офісу (не ордер): "
            f"вхід {e or 'н/д'} · SL {s or 'н/д'} · TP1 {t1 or 'н/д'}."
            if (e and s and t1)
            else "Власний план: поточна картка офісу після підтвердження (не копія бота)."
        )
        try:
            from office_trade_steer import format_entry_trigger

            trig = format_entry_trigger(
                direction=str(p.get("direction") or orig.get("direction") or ""),
                tf=str(p.get("tf") or orig.get("timeframe") or "M15"),
                level=p.get("trigger_level") or p.get("entry") or orig.get("entry"),
                entry=p.get("entry"),
                already_done=bool(p.get("trigger_done")),
            )
            own = own + " " + trig
        except Exception:
            pass
        opp = "Протилежний сценарій лишається гіпотезою, доки немає зворотного BOS."
        action = "Картка після підтвердження. Угода лише через /position."
    else:
        own = (
            "Зараз: УГОДИ НЕМАЄ. Підтвердженого альтернативного плану на свічках немає. "
            "Добір/азійський рендж бота не підставляємо як зону офісу. "
            "Нова денна свічка не є входом."
        )
        opp = (
            "LONG після відкату і SHORT після BOS лишаються внутрішніми гіпотезами, "
            "поки немає реакції на рівні зі свічок. Не оголошую SHORT через RSI і не вигадую wait-зону."
        )
        action = (
            "Офіс спостерігає всередині, без голої картки WATCHING у Telegram. "
            "Повторна пересилка дає нову версію розбору того самого кейса, не другу угоду. "
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
        asof=str(asof or mkt.get("quote_asof") or orig.get("received_at") or ""),
        extras={
            "entry_view": entry_view,
            "review": review.verdict,
            "reasons": list(review.reasons or []),
            "signal_stale": extras_stale,
            "clock_line": clock,
            "quote_asof": mkt.get("quote_asof") or asof,
            "review_at": (review.extras or {}).get("review_at") or mkt.get("review_at") or "",
            "source_at": orig.get("source_at") or "",
            "version": int(getattr(sp, "version", 1) or 1),
            "liq_state": (getattr(sp, "liquidations", None) or {}).get("state") if sp else None,
        },
    )


def format_trader_plan(plan: TraderPlan) -> str:
    """Короткий /review: статус первинного, причина, що змінилось, висновок. Не ордер."""
    o = (plan.skip.original if plan.skip else {}) or {}
    sym = str(o.get("symbol") or "")
    lines = [
        f"🦁 {sym or 'розбір'} · зовнішній сигнал",
    ]
    clock = str((plan.extras or {}).get("clock_line") or "")
    if clock:
        lines.append(clock)
    lines.extend(
        [
            "1) Статус первинного сигналу",
            plan.bot_verdict,
            "2) Чому так",
        ]
    )
    reasons = list((plan.extras or {}).get("reasons") or [])
    if reasons:
        for r in reasons[:6]:
            lines.append(f"— {r}")
    else:
        lines.append("— див. вердикт вище")
    ver = (plan.extras or {}).get("version") or 1
    lines.append("3) Що змінилось")
    lines.append(
        f"Версія розбору {ver}. Повторна пересилка не копіює попередню відповідь "
        "і не відкриває другу угоду."
    )
    lines.append("4) Зараз")
    lines.append(plan.own_plan)
    lines.append(plan.opposite)
    lines.append(plan.office_action)
    liq = (plan.extras or {}).get("liq_state")
    if liq and liq != "connected":
        lines.append(
            f"Ліквідації T7: стан {liq} — не використовуємо як підтвердження входу "
            "(forceOrder ≠ heatmap)."
        )
    lines.append("Намір маркет-мейкера не стверджую.")
    lines.append("Це аналітика, не ордер.")
    blob = "\n".join(lines)
    return blob
