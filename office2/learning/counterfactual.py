"""Контрфактуальні правила входу/стопа на ТИХ САМИХ READY-подіях replay. Лише дані, доступні на момент рішення (ATR — по барах ≤ рішення);
наслідок рахується по наступних барах M15 з витратами. Бар із SL і TP одночасно → SL. Не підбираємо «найкращу точку заднім числом»: усі варіанти формалізовані наперед.

V0 — як зараз (вхід за ціною плану одразу).
V1–V3 — відкладений вхід на 15/30/60 хв (open першого доступного бару; якщо за цей час уже SL/TP — MISSED).
V4/V5 — SL ширший на 0,5/1,0 ATR15; розмір позиції перераховано (ризик $ той самий), цілі в ціні ті самі.
V6 — лімітний вхід на ціні плану (retest): fill лише якщо ціна торкнулася її за ≤ 8 барів; якщо TP досягнуто раніше fill — MISSED (рух пішов без нас)."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from office2.learning import sessions as SS
from office2.smc import core as K
from office2.smc import replay as RP

LIMIT_TTL_BARS = 8
FEE_RT_PCT = RP.DEFAULT_FEE_RT_PCT
SLIP_BPS = RP.DEFAULT_SLIPPAGE_RT_BPS
VARIANTS = ["V0_current", "V1_delay_15m", "V2_delay_30m", "V3_delay_60m", "V4_sl_plus_0.5atr", "V5_sl_plus_1.0atr", "V6_limit_retest"]


def _compact(s: Dict[str, Any]) -> Dict[str, Any]:
    return {"outcome": s["outcome"], "r_net": s["r_net"], "bars": s.get("bars")}


def _sim(m15, i, ev, *, sl=None, delay=0.0):
    sl = ev["sl"] if sl is None else sl
    risk = abs(ev["entry"] - sl)
    if risk <= 0:
        return {"outcome": "NO_DATA", "r_net": None, "bars": 0}
    rr = abs(ev["tp1"] - ev["entry"]) / risk
    return _compact(RP.simulate(m15, i, ev["dir"], ev["entry"], sl, ev["tp1"], rr, risk / ev["entry"] * 100.0,
                                fee_rt_pct=FEE_RT_PCT, slippage_rt_bps=SLIP_BPS, entry_delay_sec=delay, entry_ttl_sec=4 * 3600))


def _limit(m15, i, ev):
    sg = 1.0 if ev["dir"] == "LONG" else -1.0
    n = len(m15["t"])
    for j in range(i + 1, min(n, i + 1 + LIMIT_TTL_BARS)):
        touched = (m15["l"][j] <= ev["entry"]) if sg > 0 else (m15["h"][j] >= ev["entry"])
        tp_first = (m15["h"][j] >= ev["tp1"]) if sg > 0 else (m15["l"][j] <= ev["tp1"])
        if tp_first and not touched:
            return {"outcome": "MISSED_TP_BEFORE_ENTRY", "r_net": None, "bars": 0}
        if touched:
            sub = RP.simulate(m15, j - 1, ev["dir"], ev["entry"], ev["sl"], ev["tp1"], ev["r_tp1"], ev["risk_pct"], fee_rt_pct=FEE_RT_PCT, slippage_rt_bps=SLIP_BPS)
            return _compact(sub)
    return {"outcome": "MISSED_NO_RETEST", "r_net": None, "bars": 0}


def per_event(events: List[Dict[str, Any]], m15) -> List[Dict[str, Any]]:
    atr = K.atr_arr(m15)
    out = []
    for ev in events:
        if "error" in ev or ev.get("tp1") is None or not ev.get("risk_pct"):
            continue
        i = int(ev["i"])
        a = K.atr_at(atr, i)
        sg = 1.0 if ev["dir"] == "LONG" else -1.0
        v = {"V0_current": _compact(RP.simulate(m15, i, ev["dir"], ev["entry"], ev["sl"], ev["tp1"], ev["r_tp1"], ev["risk_pct"], fee_rt_pct=FEE_RT_PCT, slippage_rt_bps=SLIP_BPS)),
             "V1_delay_15m": _sim(m15, i, ev, delay=900.0), "V2_delay_30m": _sim(m15, i, ev, delay=1800.0), "V3_delay_60m": _sim(m15, i, ev, delay=3600.0),
             "V4_sl_plus_0.5atr": _sim(m15, i, ev, sl=ev["sl"] - sg * 0.5 * a), "V5_sl_plus_1.0atr": _sim(m15, i, ev, sl=ev["sl"] - sg * 1.0 * a),
             "V6_limit_retest": _limit(m15, i, ev)}
        out.append({"symbol": ev.get("symbol"), "source": ev["source"], "dir": ev["dir"], "ts_bar": ev["ts_bar"], "model": ev.get("model"),
                    "late": bool(ev.get("late")), "atr_pct": round(a / max(ev["entry"], 1e-9) * 100, 3), "risk_pct": ev["risk_pct"], "r_tp1": ev["r_tp1"],
                    **SS.session_of(float(ev["ts_bar"])), "variants": v})
    return out


def _stats(sims: List[Dict[str, Any]], n_events: int) -> Dict[str, Any]:
    sc = [s for s in sims if s["r_net"] is not None]
    rs = [s["r_net"] for s in sc]
    oc = {k: sum(1 for s in sc if s["outcome"] == k) for k in ("TP1", "SL", "OPEN")}
    return {"events": n_events, "scored": len(sc), "missed": sum(1 for s in sims if str(s["outcome"]).startswith("MISSED")), **oc,
            "mean_r_net": round(float(np.mean(rs)), 3) if rs else None, "r_net_ci95": RP.bootstrap_ci(rs), "sum_r_net": round(float(np.sum(rs)), 2) if rs else 0.0,
            "usd_at_10": round(float(np.sum(rs)) * 10.0, 1) if rs else 0.0}


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """По рушію й варіанту: скільки угод, пропущених входів, TP1/SL, середній R та $ при ризику $10. Плюс розріз по сесіях (варіант V0)."""
    out: Dict[str, Any] = {"n_events": len(rows), "by_source": {}, "sessions": {}}
    for src in sorted({r["source"] for r in rows}):
        rs = [r for r in rows if r["source"] == src]
        out["by_source"][src] = {v: _stats([r["variants"][v] for r in rs], len(rs)) for v in VARIANTS}
        out["sessions"][src] = {s: _stats([r["variants"]["V0_current"] for r in rs if r.get("session") == s], sum(1 for r in rs if r.get("session") == s)) for s in sorted({r.get("session") for r in rs})}
        out["sessions"][src]["_direction"] = {d: _stats([r["variants"]["V0_current"] for r in rs if r["dir"] == d], sum(1 for r in rs if r["dir"] == d)) for d in ("LONG", "SHORT")}
    return out
