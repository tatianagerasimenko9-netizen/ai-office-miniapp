"""Ознаки рішення Brain v2.1 на момент READY (лише дані ДО входу): рівень, подія, контекст, сесія, ризик. Єдиний словник для replay, production-кандидатів і розбору помилок.
Ознаки — для статистики «ознака → результат» з перевіркою на незалежному періоді; самі по собі правилами не є."""
from __future__ import annotations

from typing import Any, Dict, Optional

from office2.learning import sessions as SS

SESSION_LVL = ("ASIA_", "LONDON_", "NEW_YORK_")
LTF_SW = ("M15SW", "H1SW")
HTF_SW = ("H4SW", "D1SW", "W1SW")
DAILY = ("PDH", "PDL", "D1H", "D1L")
WEEK_MONTH = ("PWH", "PWL", "PMH", "PML", "W1H", "W1L")


def level_class(kind: Optional[str]) -> str:
    k = str(kind or "")
    if k.startswith(SESSION_LVL):
        return "SESSION"
    if k in LTF_SW:
        return "SWING_LTF"
    if k in HTF_SW:
        return "SWING_HTF"
    if k in DAILY:
        return "DAILY"
    if k in WEEK_MONTH:
        return "WEEK_MONTH"
    return "ORIGIN" if k == "ORIGIN_LOW" else "OTHER"


def _bucket(x: Optional[float], cuts) -> str:
    if x is None:
        return "NA"
    for i, c in enumerate(cuts):
        if x < c:
            return f"<{c}" if i == 0 else f"{cuts[i - 1]}–{c}"
    return f"≥{cuts[-1]}"


def extract(th: Dict[str, Any], now: float, mc: Optional[Dict[str, Any]] = None, rel: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ev = th.get("evidence") or []
    integ = th.get("integral") or {}
    lvl = th.get("level") or {}
    event = th.get("event") or {}
    q = th.get("quality") or {}
    d = th.get("dir")
    by_mod = {str(e.get("module", "")): e for e in ev}

    def mod(prefix: str) -> Optional[Dict[str, Any]]:
        for k, v in by_mod.items():
            if k.startswith(prefix):
                return v
        return None

    pd = mod("OB / FVG / OTE")
    mirror = mod("Gerchik mirror")
    bulk = mod("Bulkowski")
    wy = mod("Wyckoff")
    seq = th.get("sequence") or []
    retest_old = any("ПОВТОРНИЙ ТЕСТ" in str(s.get("value", "")).upper() for s in seq if s.get("step") == "подія")
    sess = SS.session_of(float(now))
    btc1 = (mc or {}).get("btc_ret_1h")
    rs1 = (rel or {}).get("rs_vs_btc_1h")
    sg = 1 if d == "LONG" else -1
    stop_pct = (th.get("sizing") or {}).get("stop_pct") or th.get("risk_pct")
    cost_r = (0.15 / stop_pct) if stop_pct else None
    return {
        "dir": d, "kind": th.get("kind"),
        "ev_class": event.get("class") or "NONE", "retest_not_fresh": bool(retest_old or event.get("class") == "LATE_SWEEP"),
        "lvl_kind": lvl.get("kind"), "lvl_class": level_class(lvl.get("kind")), "lvl_strength": "3+" if int(lvl.get("strength") or 1) >= 3 else str(int(lvl.get("strength") or 1)),
        "mirror_for": bool(mirror and mirror.get("supports") == 1), "bulkowski_for": bool(bulk and bulk.get("supports") == 1),
        "wyckoff_defined": bool(wy and "не визначена" not in str(wy.get("finding", ""))),
        "pd": ("FOR" if pd and pd.get("supports") == 1 else "AGAINST" if pd and pd.get("supports") == -1 else "NEUTRAL"),
        "htf_class": integ.get("classification") or "NA", "counter_trend": bool(integ.get("counter_trend")),
        "n_for": len(integ.get("for") or []), "n_against": len(integ.get("against") or []),
        "risk_atr": _bucket(q.get("risk_atr15"), (2.0, 3.0)), "tp1_r": _bucket(q.get("first_target_r"), (1.5, 3.0)),
        "cost_heavy": bool(cost_r is not None and cost_r >= 0.25), "stop_pct": round(float(stop_pct), 3) if stop_pct else None,
        "session": sess["session"], "weekend": sess["weekend"],
        "btc_1h": "NA" if btc1 is None else ("WITH" if btc1 * sg > 0.1 else "AGAINST" if btc1 * sg < -0.1 else "FLAT"),
        "rs_1h": "NA" if rs1 is None else ("WITH" if rs1 * sg > 0.1 else "AGAINST" if rs1 * sg < -0.1 else "FLAT"),
    }
