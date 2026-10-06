"""Risk Manager (shadow): не «$10 на угоду», а портфельний ризик. Розмір позиції — ЛИШЕ після структурного SL.

Правила (усі пороги — параметри конфігу, не підбираються на test):
  * розмір: qty = risk_usd / (|entry − SL| + fee_rt·entry) — збиток на SL разом із комісіями дорівнює risk_usd;
  * одночасний відкритий ризик ≤ max_open_risk_usd;
  * кластер корельованості: BTC / ETH / ALT (альти високо корельовані з BTC); ≤ max_cluster_open_risk_usd за кластером і ≤ max_same_direction_alts однонапрямлених альтів;
  * один символ+напрям: не більше max_same_symbol відкритих; повторна ідея після SL — не раніше repeat_after_sl_sec (0 = вимкнено, shadow-експеримент);
  * пов'язані сценарії (той самий рівень ліквідності): ≤ max_related;
  * денний збиток ≤ daily_loss_r (R), просадка від піку ≥ dd_halt_r (R) → пауза до наступної доби UTC.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class RiskConfig:
    risk_usd: float = 10.0
    max_open_risk_usd: float = 40.0
    max_cluster_open_risk_usd: float = 30.0
    max_same_direction_alts: int = 3
    max_same_symbol: int = 1
    repeat_after_sl_sec: int = 0
    max_related: int = 1
    daily_loss_r: float = 3.0
    dd_halt_r: float = 8.0


def cluster_of(symbol: str) -> str:
    s = symbol.upper()
    return "BTC" if s == "BTCUSDT" else "ETH" if s == "ETHUSDT" else "ALT"


def position_size(risk_usd: float, entry: float, sl: float, fee_rt_pct: float = 0.10) -> Dict[str, float]:
    """Кількість і номінал так, щоб збиток на SL РАЗОМ із комісіями кола дорівнював risk_usd. Без SL (структурного) розмір не рахується."""
    dist = abs(entry - sl)
    if dist <= 0 or entry <= 0:
        return {"qty": 0.0, "notional": 0.0, "risk_usd": 0.0}
    qty = risk_usd / (dist + fee_rt_pct / 100.0 * entry)
    return {"qty": qty, "notional": qty * entry, "risk_usd": risk_usd}


def _day(t: float) -> int:
    return int(t // 86400)


def simulate_portfolio(trades: List[Dict[str, Any]], cfg: RiskConfig = RiskConfig()) -> Dict[str, Any]:
    """trades: словники з t_entry, t_exit, symbol, dir, r_net (результат у R), lvl_key (опційно). Обробка в порядку t_entry.
    Просадка рахується від піку ПІСЛЯ останнього скидання: коли спрацював dd_halt, торгівля зупиняється до наступної доби UTC і база просадки
    скидається (нова доба = новий відлік), інакше після першої великої просадки система ніколи б не поверталась.
    Повертає accepted, rejected{reason: n}, equity, total_r, max_dd_r, worst_day_r."""
    accepted: List[Dict[str, Any]] = []
    rejected: Dict[str, int] = {}
    last_sl: Dict[Tuple[str, str], float] = {}
    halt_day: Optional[int] = None
    base_t = -1e18          # закриті угоди ДО цього моменту не враховуються у просадці (скидання після halt)
    for tr in sorted(trades, key=lambda x: x["t_entry"]):
        t0 = tr["t_entry"]
        d = _day(t0)
        if halt_day is not None and d > halt_day and base_t < d * 86400:
            base_t = d * 86400.0   # нова доба після зупинки: база просадки скинута
        closed = [a for a in accepted if a["t_exit"] <= t0 and a["t_exit"] > base_t]
        eq = sum(a["r_net"] for a in closed)
        peak = max([0.0] + list(_run_peak(closed)))
        dd = peak - eq
        day_loss = sum(a["r_net"] for a in accepted if a["t_exit"] <= t0 and _day(a["t_exit"]) == d)
        reason = None
        open_ = [a for a in accepted if a["t_exit"] > t0]
        cl = cluster_of(tr["symbol"])
        if halt_day == d:
            reason = "halt_day"
        elif dd >= cfg.dd_halt_r:
            halt_day = d
            reason = "drawdown_halt"
        elif day_loss <= -cfg.daily_loss_r:
            reason = "daily_loss"
        elif (len(open_) + 1) * cfg.risk_usd > cfg.max_open_risk_usd:
            reason = "open_risk"
        elif (sum(1 for a in open_ if cluster_of(a["symbol"]) == cl) + 1) * cfg.risk_usd > cfg.max_cluster_open_risk_usd:
            reason = "cluster_risk"
        elif cl == "ALT" and sum(1 for a in open_ if cluster_of(a["symbol"]) == "ALT" and a["dir"] == tr["dir"]) >= cfg.max_same_direction_alts:
            reason = "same_direction_alts"
        elif sum(1 for a in open_ if a["symbol"] == tr["symbol"] and a["dir"] == tr["dir"]) >= cfg.max_same_symbol:
            reason = "same_symbol"
        elif cfg.repeat_after_sl_sec and t0 - last_sl.get((tr["symbol"], tr["dir"]), -1e18) < cfg.repeat_after_sl_sec:
            reason = "repeat_after_sl"
        elif tr.get("lvl_key") is not None and sum(1 for a in open_ if a.get("lvl_key") == tr["lvl_key"]) >= cfg.max_related:
            reason = "related_scenarios"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        accepted.append(tr)
        if tr["r_net"] < 0:
            last_sl[(tr["symbol"], tr["dir"])] = tr["t_exit"]
    run = 0.0
    pk = 0.0
    worst_dd = 0.0
    eq_curve = []
    for a in sorted(accepted, key=lambda x: x["t_exit"]):
        run += a["r_net"]
        pk = max(pk, run)
        worst_dd = max(worst_dd, pk - run)
        eq_curve.append((a["t_exit"], run))
    days: Dict[int, float] = {}
    for a in accepted:
        days[_day(a["t_exit"])] = days.get(_day(a["t_exit"]), 0.0) + a["r_net"]
    return {"accepted": accepted, "rejected": rejected, "equity": eq_curve, "total_r": run, "max_dd_r": worst_dd, "worst_day_r": min(days.values()) if days else 0.0,
            "n_days": len(days)}


def _run_peak(closed: List[Dict[str, Any]]):
    run = 0.0
    for a in sorted(closed, key=lambda x: x["t_exit"]):
        run += a["r_net"]
        yield run
