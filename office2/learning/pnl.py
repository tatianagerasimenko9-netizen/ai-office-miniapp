"""Облік R і $ при фіксованому ризику. Моделі НЕ змішуються:
A — повне закриття на TP1 (SL першим → −1R).
B — 50% на TP1, стоп у беззбиток, решта 50% на TP2 (якщо досягнуто), інакше беззбиток; відкрита решта не зараховується.
Позиція без ENTRY (NOFILL) і OPEN не дають реалізованого результату. Витрати враховані у R (cost_r)."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

RISK_USD = 10.0


def r_gross_a(t: Dict[str, Any]) -> Optional[float]:
    f = t["first"]
    if f == "SL":
        return -1.0
    if f == "TP1":
        return t.get("r1")
    return None


def r_gross_b(t: Dict[str, Any]) -> Optional[float]:
    f = t["first"]
    if f == "SL":
        return -1.0
    if f != "TP1" or t.get("r1") is None:
        return None
    if t.get("eventually_tp2") and t.get("r2") is not None:
        return 0.5 * t["r1"] + 0.5 * t["r2"]
    if t.get("eventually_sl"):
        return 0.5 * t["r1"]                     # решта вийшла по беззбитку
    return None                                  # решта ще відкрита — не зараховуємо


def net(t: Dict[str, Any], model: str) -> Optional[float]:
    g = (r_gross_a if model == "A" else r_gross_b)(t)
    c = t.get("cost_r")
    if g is None or c is None:
        return None
    return g - c


def summarize(trades: Iterable[Dict[str, Any]], model: str = "A") -> Dict[str, Any]:
    ts = list(trades)
    rs, gross, costs = [], [], 0.0
    wins = 0
    for t in ts:
        n = net(t, model)
        if n is None:
            continue
        rs.append(n)
        g = (r_gross_a if model == "A" else r_gross_b)(t)
        gross.append(g)
        costs += t["cost_r"]
        wins += 1 if n > 0 else 0
    pos = sum(x for x in rs if x > 0)
    neg = -sum(x for x in rs if x < 0)
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"model": model, "trades_total": len(ts), "resolved": len(rs), "excluded_unresolved": len(ts) - len(rs),
            "wins": wins, "win_rate": round(wins / len(rs), 3) if rs else None,
            "sum_r_net": round(sum(rs), 2), "sum_r_gross": round(sum(gross), 2), "costs_r": round(costs, 2),
            "mean_r_net": round(sum(rs) / len(rs), 3) if rs else None,
            "profit_factor": round(pos / neg, 2) if neg > 0 else None,
            "usd_net": round(sum(rs) * RISK_USD, 1), "usd_gross": round(sum(gross) * RISK_USD, 1), "usd_costs": round(costs * RISK_USD, 1),
            "max_drawdown_r": round(dd, 2), "max_drawdown_usd": round(dd * RISK_USD, 1)}
