"""Method-rule inputs taken from an already-frozen Brain plan (SHADOW only).

Sources: READY thesis (entry, structural SL, trigger level, invalidation,
targets, sizing), D1 ATR from closed daily bars, OFFICE_DEPO_USDT (config, not a
verified exchange balance) and the paper journal. Nothing is guessed: a missing
source means the rule is simply absent -> UNKNOWN downstream.
Never places orders, never changes READY, risk or LIVE gates.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Dict, Iterable, List, Mapping, Optional

# Source ceilings (registry G-RISK-TRADE / G-RISK-DAY / S-RISK): 1% per trade, up to 3% per day.
RISK_TRADE_PCT_MAX = 1.0
RISK_DAY_PCT_MAX = 3.0


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


_PROVENANCE = {
    "G-TRIAL-100": ("office2_paper_position (LIVE scope, paper — not real trades)", "SOURCE"),
    "G-RISK-DAY": ("OFFICE_DEPO_USDT config x 3% (upper bound of source 1-3%) + paper journal", "SOURCE"),
    "G-STOP-ATR": ("D1 ATR (G-ATR-CALC, 3-5 closed days); source numbers are for stocks/FX", "HYPOTHESIS"),
    "G-RISK-TRADE": ("OFFICE_DEPO_USDT config x 1% (upper bound of source 0.5-1%)", "SOURCE"),
    "S-RISK": ("OFFICE_DEPO_USDT config x 1% (upper bound of source 0.5-1%)", "SOURCE"),
}


class _Stamped(dict):
    """dict that attaches _provenance (source, closed-bar time, basis) to each rule input."""

    def __init__(self, asof):
        super().__init__()
        self._asof = asof

    def __setitem__(self, rule, value):
        src, basis = _PROVENANCE.get(rule, ("frozen READY thesis (office2.brain.decide)", "SOURCE"))
        value = dict(value)
        value["_provenance"] = {"source": src, "basis": basis, "asof_closed_bar_ts": self._asof}
        super().__setitem__(rule, value)


def from_thesis(th: Optional[Mapping[str, Any]], *, daily_atr: Optional[float] = None,
                equity_usd: Optional[float] = None, closed_trades: Optional[int] = None,
                daily_loss_usd: Optional[float] = None,
                asof_bar_ts: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """Inputs for plan/risk rules. Only a READY thesis with entry, SL and TP1 qualifies."""
    out: Dict[str, Dict[str, Any]] = {}
    out = _Stamped(asof_bar_ts)
    if isinstance(closed_trades, int) and not isinstance(closed_trades, bool) and closed_trades >= 0:
        out["G-TRIAL-100"] = {"closed_trades": closed_trades}
    equity = _num(equity_usd)
    loss = _num(daily_loss_usd)
    if equity and equity > 0 and loss is not None and loss >= 0:
        out["G-RISK-DAY"] = {"daily_loss_usd": loss, "daily_limit_usd": equity * RISK_DAY_PCT_MAX / 100.0}
    if not th or th.get("state") != "READY":
        return out
    direction = th.get("dir")
    entry, sl = _num(th.get("entry")), _num(th.get("sl"))
    if direction not in ("LONG", "SHORT") or not entry or sl is None or entry <= 0:
        return out
    risk = (entry - sl) if direction == "LONG" else (sl - entry)
    if risk <= 0:
        return out
    targets = th.get("targets") or []
    tp1 = _num(targets[0].get("p")) if targets and isinstance(targets[0], Mapping) else None
    if tp1 is not None:
        reward = (tp1 - entry) if direction == "LONG" else (entry - tp1)
        if reward >= 0:
            out["G-RR-MIN3"] = {"reward": reward, "risk": risk}
    out["G-STOP-CRYPTO"] = {"stop_distance": risk, "entry_price": entry}
    level = _num(th.get("trigger_level"))
    if level is not None:
        technical = {"stop": sl, "level": level, "direction": direction}
        out["G-STOP-TECH"] = dict(technical)
        out["G-STOP-CRYPTO-TECHNICAL"] = dict(technical)
    invalidation = th.get("invalidation")
    inv_price = _num(invalidation.get("price")) if isinstance(invalidation, Mapping) else None
    if inv_price is not None:
        out["D-STOP-STRUCTURE"] = {"stop": sl, "invalidation": inv_price, "direction": direction}
    atr = _num(daily_atr)
    if atr and atr > 0:
        out["G-STOP-ATR"] = {"stop_distance": risk, "daily_atr": atr}
    risk_usd = _num((th.get("sizing") or {}).get("risk_usd")) if isinstance(th.get("sizing"), Mapping) else None
    if equity and equity > 0 and risk_usd is not None and risk_usd >= 0:
        budget = equity * RISK_TRADE_PCT_MAX / 100.0
        out["G-RISK-TRADE"] = {"risk_usd": risk_usd, "risk_budget_usd": budget}
        out["S-RISK"] = {"risk_usd": risk_usd, "risk_budget_usd": budget}
    return out


_STATS_CACHE: Dict[str, Any] = {}


def paper_journal_stats(db_path: str, now: float, ttl: float = 60.0) -> Dict[str, Any]:
    """Closed LIVE paper trades (count) and today's UTC realised loss in USD (model A).

    SQL aggregates only (the table can be large; Worker memory is tight); cached `ttl` s.
    """
    hit = _STATS_CACHE.get(db_path)
    if hit and now - hit[0] < ttl:
        return hit[1]
    from office_bridge import _fetchall

    day_start = float(int(now // 86400) * 86400)
    row = _fetchall(db_path, "SELECT COUNT(*), COALESCE(SUM(CASE WHEN close_ts >= ? AND pnl_a < 0 THEN -pnl_a ELSE 0 END), 0) "
                             "FROM office2_paper_position WHERE COALESCE(scope,'LIVE') = 'LIVE' AND pnl_a IS NOT NULL AND close_ts IS NOT NULL",
                    (day_start,))[0]
    out = {"closed_trades": int(row[0]), "daily_loss_usd": float(row[1])}
    _STATS_CACHE[db_path] = (now, out)
    return out


def daily_atr_from_ranges(ranges: Iterable[float]) -> Optional[float]:
    """Mean of 3-5 previous closed daily ranges (G-ATR-CALC); None otherwise."""
    vals: List[float] = [v for v in (_num(r) for r in ranges) if v is not None and v > 0]
    return sum(vals) / len(vals) if 3 <= len(vals) <= 5 else None
