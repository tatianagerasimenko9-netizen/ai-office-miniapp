"""Єдина модель витрат. Комісія кола і прослизання — у відсотках ціни; у R витрати = cost_pct / stop_pct (стоп малий → витрати великі)."""
FEE_RT_PCT = 0.10        # taker × 2 (як office2.sim.FEE_RT_DEFAULT)
SLIP_RT_PCT = 0.05       # припущення Office2 (sizing.fee_slip_note: комісія+slippage ≈ 0,15% кола)


def cost_pct(fee_rt: float = FEE_RT_PCT, slip_rt: float = SLIP_RT_PCT) -> float:
    return fee_rt + slip_rt


def cost_r(stop_pct, fee_rt: float = FEE_RT_PCT, slip_rt: float = SLIP_RT_PCT):
    """None, якщо відстань стопа невідома (не вигадуємо)."""
    if not stop_pct or stop_pct <= 0:
        return None
    return cost_pct(fee_rt, slip_rt) / stop_pct


# Розкладка витрат кола. ПРИПУЩЕННЯ (не виміряні на рахунку власниці): тариф Binance USDT-M VIP0 за публічною сіткою — maker 0.02 %, taker 0.05 % за сторону
# (знижка BNB та VIP-рівні не враховані); slippage+spread 0.05 % кола — припущення Office2; funding НЕ входить у PnL (див. docs/office2/COST_MODEL.md).
TAKER_SIDE_PCT = 0.05
MAKER_SIDE_PCT = 0.02
SLIPPAGE_RT_ASSUMED_PCT = SLIP_RT_PCT


def breakdown(notional: float) -> dict:
    """Скільки $ витрат на позицію за сценаріями виконання: модель Office2 (taker+taker+slippage) і чутливість (maker TP)."""
    f = lambda pct: round(notional * pct / 100.0, 4)  # noqa: E731
    return {
        "model_taker_taker_usd": f(2 * TAKER_SIDE_PCT), "slippage_spread_assumed_usd": f(SLIPPAGE_RT_ASSUMED_PCT), "model_total_usd": f(cost_pct()),
        "sensitivity_taker_entry_maker_tp_usd": f(TAKER_SIDE_PCT + MAKER_SIDE_PCT + SLIPPAGE_RT_ASSUMED_PCT / 2),
        "funding_usd": None, "funding_note": "не моделюється: залежить від ставки на момент і від перетину 00/08/16 UTC",
        "basis": {"fees": "ПРИПУЩЕННЯ: публічна сітка Binance USDT-M, VIP0, без знижки BNB; не перевірено в цьому середовищі", "slippage": "ПРИПУЩЕННЯ Office2", "funding": "не враховано"},
    }
