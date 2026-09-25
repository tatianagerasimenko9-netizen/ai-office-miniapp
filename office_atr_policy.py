"""Єдина політика ATR: два чинні пороги, різні ролі.

Числа 80% і 90% НЕ змінюємо без бектесту.
NO_TRADE 100% — спрацювання правила входу, не прогноз що ціна не рухається.
Нова D1-свічка лише перераховує day_used = day_range/ATR; ATR(14) не reset і не авто-вхід.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT

# Герчик / Лев / Probability Engine / проактивний сканер ENTER — чинне вето по тренду.
GERCHIK_TREND_ENTRY_BLOCK_PCT = 80.0
# T0 монітор ZONE_REACHED / evaluate_radar — блок SIGNAL, зона лишається.
T0_ENTRY_BLOCK_PCT = float(ATR_DAY_USED_ENTRY_BLOCK_PCT)

ATR_POLICY_DOC = (
    "80% (Герчик/Лев/Probability): вето конкретного входу по тренду. "
    "90% (T0/радар): блок SIGNAL, WATCHING і ZONE_REACHED лишаються. "
    "Пошук нових сценаріїв на M5/M15 триває в обох випадках. "
    "Пороги не змінювати без історичного бектесту."
)


def new_daily_bar_resets_atr() -> bool:
    """Новий денний бар не обнуляє ATR і не дозволяє вхід сам по собі."""
    return False


def no_trade_means_price_wont_move() -> bool:
    """NO_TRADE 100% ≠ ймовірність відсутності руху."""
    return False


def classify_atr_day_used(day_used_pct: Any) -> Dict[str, Any]:
    """Розділяє блок конкретного входу і дозвіл шукати далі."""
    try:
        used = float(day_used_pct) if day_used_pct is not None and day_used_pct != "" else None
    except (TypeError, ValueError):
        used = None
    if used is None:
        return {
            "day_used_pct": None,
            "t0_entry_blocked": False,
            "gerchik_entry_blocked": False,
            "search_continues": True,
            "new_d1_resets_atr": False,
            "rule_id": "ATR_UNKNOWN",
            "label": "ATR day_used невідомий — пошук триває, вхід без цифри не відкриваємо",
        }
    t0 = used > T0_ENTRY_BLOCK_PCT
    gerchik = used > GERCHIK_TREND_ENTRY_BLOCK_PCT
    if t0:
        rule = "ATR_USED_GT_90_T0"
        label = (
            f"ATR day_used {used:.1f}% > {T0_ENTRY_BLOCK_PCT:.0f}% — "
            "T0 блок SIGNAL/входу; зона й пошук сценаріїв тривають"
        )
    elif gerchik:
        rule = "ATR_USED_GT_80_GERCHIK"
        label = (
            f"ATR day_used {used:.1f}% > {GERCHIK_TREND_ENTRY_BLOCK_PCT:.0f}% — "
            "вето конкретного входу по тренду (Герчик/Лев); "
            "це не T0-90 і не прогноз що ринок зупинився"
        )
    else:
        rule = "ATR_USED_OK"
        label = f"ATR day_used {used:.1f}% — запас ходу для розгляду входу"
    return {
        "day_used_pct": used,
        "t0_entry_blocked": t0,
        "gerchik_entry_blocked": gerchik,
        "search_continues": True,
        "new_d1_resets_atr": False,
        "rule_id": rule,
        "label": label,
    }


def explain_atr_day_used(day_used_pct: Any) -> Dict[str, Any]:
    """120.7% = денний хід на 20.7% більший за ATR, не «більш ніж удвічі»."""
    cls = classify_atr_day_used(day_used_pct)
    used = cls.get("day_used_pct")
    excess = None
    if used is not None:
        excess = round(float(used) - 100.0, 1)
    return {
        **cls,
        "excess_pct_over_atr": excess,
        "more_than_double_atr": bool(used is not None and float(used) >= 200.0),
        "new_d1_is_entry": False,
        "plain": (
            None
            if used is None
            else (
                f"ATR day_used {used:.1f}% — денний діапазон = {used:.1f}% від ATR "
                f"(на {excess:.1f}% більший за ATR, не «більш ніж удвічі»). "
                "Це правило ризику: конкретний вхід по тренду блокується. "
                "Це не бак пального і не фізична заборона ціні рухатись далі. "
                "Нова D1 лише перераховує day_used, ATR(14) не обнуляється і це не вхід."
            )
        ),
    }


def probability_no_trade_payload(day_used_pct: float) -> Dict[str, Any]:
    """Поля Probability Engine при ATR>80: правило, не forecast ціни."""
    cls = classify_atr_day_used(day_used_pct)
    return {
        "long_prob": 0,
        "short_prob": 0,
        "no_trade_prob": 100,
        "confidence": "LOW",
        "recommendation": "NO_TRADE",
        "reason": cls["label"],
        "rule_id": cls["rule_id"],
        "no_trade_is_rule": True,
        "no_trade_is_price_forecast": False,
        "search_continues": True,
        "entry_blocked": True,
        "factors_long": [],
        "factors_short": [],
    }
