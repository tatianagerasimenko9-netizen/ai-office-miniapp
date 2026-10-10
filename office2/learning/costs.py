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
