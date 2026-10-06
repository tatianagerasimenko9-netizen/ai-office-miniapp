"""Єдине представлення рівнів Office2 для Telegram і Mini App (одна математика, одні назви).

READY-ціна (th.entry) — ціна підтвердження сигналу; lifecycle (ENTRY/TP/SL) і R рахуються від неї.
Зона входу — від READY-ціни до рівня тригера (рівень пробою/sweep): вхід можливий де завгодно в зоні.
Ризик у %, TP у % та в R залежать від ціни входу, тому для зони показуємо діапазон по обох її краях, а не одне число від одного краю.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _rng(vals: List[float]) -> List[float]:
    return [min(vals), max(vals)]


def zone_of(th: Dict[str, Any]) -> List[float]:
    """Зона входу тези: brain v2 — entry_zone (OTE ∪ OB/FVG); brain v1 — від READY-ціни до рівня тригера."""
    entry = float(th["entry"])
    ez = th.get("entry_zone")
    if ez and len(ez) == 2:
        return [min(float(ez[0]), float(ez[1]), entry), max(float(ez[0]), float(ez[1]), entry)]
    trig = float(th["trigger_level"]) if th.get("trigger_level") is not None else entry
    return [min(entry, trig), max(entry, trig)]


def level_view(entry: float, trigger: Optional[float], sl: float, targets: List[Dict[str, Any]], zone: Optional[List[float]] = None) -> Dict[str, Any]:
    entry, sl = float(entry), float(sl)
    trig = float(trigger) if trigger is not None else entry
    lo, hi = (min(zone), max(zone)) if zone else (min(entry, trig), max(entry, trig))
    ends = [entry] if lo == hi else [lo, hi]
    ends = [e for e in ends if e > 0 and abs(e - sl) > 0]
    out_t = []
    for t in targets or []:
        p = float(t["p"])
        out_t.append({"p": p, "kind": t.get("kind"), "pct": _rng([abs(p - e) / e * 100.0 for e in ends]), "r": _rng([abs(p - e) / abs(e - sl) for e in ends])})
    return {"ready_price": entry, "zone": [lo, hi] if lo != hi else None, "sl": sl, "sl_pct": _rng([abs(e - sl) / e * 100.0 for e in ends]), "targets": out_t,
            "note": "R і lifecycle рахуються від READY-ціни; для інших цін у зоні ризик і R інші (діапазон)"}


def view_from_thesis(th: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        return level_view(th["entry"], th.get("trigger_level"), th["sl"], th.get("targets") or [], zone_of(th) if th.get("entry_zone") else None)
    except (KeyError, TypeError, ValueError):
        return None


def pct_txt(r: List[float], sign: str) -> str:
    """«(−0,40…−0,85%)» для діапазону, «(−0,85%)» якщо краї збігаються."""
    f = lambda v: (f"{v:.2f}" if v < 10 else f"{v:.1f}").replace(".", ",")  # noqa: E731
    a, b = f(r[0]), f(r[1])
    return f" ({sign}{a}%)" if a == b else f" ({sign}{a}…{sign}{b}%)"


def range_txt(r: List[float]) -> str:
    """«0,40–0,85» (діапазон) або «0,85» (краї збігаються)."""
    f = lambda v: (f"{v:.2f}" if v < 10 else f"{v:.1f}").replace(".", ",")  # noqa: E731
    a, b = f(r[0]), f(r[1])
    return a if a == b else f"{a}–{b}"
