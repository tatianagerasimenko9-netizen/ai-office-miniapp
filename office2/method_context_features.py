"""Method-rule inputs from market context: calendar/sessions, top-down, SMC, D1 base (SHADOW only).

Every input carries `_provenance` {source, basis, asof_closed_bar_ts}: basis is SOURCE when the
condition is the one written in the provided materials, HYPOTHESIS when our implementation
had to choose a form (e.g. which timeframe confirms). HYPOTHESIS rows must never be read as
source-confirmed PASS. Closed bars only; no orders, no READY/risk/LIVE-gate changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Dict, List, Mapping, Optional


def _prov(source: str, basis: str, asof: Optional[float]) -> Dict[str, Any]:
    return {"source": source, "basis": basis, "asof_closed_bar_ts": asof}


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


def msk_session(now: float) -> str:
    """Source windows are Moscow time (fixed UTC+3): Europe 10:00-13:00, US 15:30-18:00, else off-hours."""
    msk = datetime.fromtimestamp(now, timezone.utc).hour * 60 + datetime.fromtimestamp(now, timezone.utc).minute + 180
    minutes = msk % 1440
    if 600 <= minutes < 780:
        return "EUROPE"
    if 930 <= minutes < 1080:
        return "US"
    return "OFF_HOURS"


def session_news(now: float, news_state: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """D-SESSIONS-NEWS from the office calendar (office_calendar.news_check state OK|FAIL|UNAVAILABLE)."""
    if news_state not in ("OK", "FAIL"):
        return {}      # calendar unavailable/disabled -> UNKNOWN, never a silent PASS
    return {"D-SESSIONS-NEWS": {"high_impact_news_soon": news_state == "FAIL", "session_label": msk_session(now),
                                "_provenance": _prov("office_calendar.news_check + MSK windows of the source", "SOURCE", now)}}


def from_topdown(td: Optional[Mapping[str, Any]], asof: Optional[float]) -> Dict[str, Dict[str, Any]]:
    """D-HTF-LTF-CONFIRM / D-NO-CONFIRMATION-NO-TRADE from office2.topdown stages (already closed-bar based)."""
    out: Dict[str, Dict[str, Any]] = {}
    if not td:
        return out
    st = {s.get("tf"): s.get("state") for s in td.get("stages") or [] if isinstance(s, Mapping)}

    def verdict(tfs):
        have = [st.get(t) for t in tfs if st.get(t) in ("CONFIRMS", "NEUTRAL", "CONFLICTS")]
        if not have:
            return None
        return "CONFLICTS" not in have and "CONFIRMS" in have

    htf, ltf = verdict(("D1", "H4")), verdict(("H1", "M15"))
    if htf is not None and ltf is not None:
        out["D-HTF-LTF-CONFIRM"] = {"htf_agrees": htf, "ltf_confirms": ltf, "_provenance": _prov(
            "office2.topdown stages D1/H4 vs H1/M15; entry TF of the source is NOT CONFIRMED", "HYPOTHESIS", asof)}
    m15 = st.get("M15")
    if m15 in ("CONFIRMS", "NEUTRAL", "CONFLICTS"):
        out["D-NO-CONFIRMATION-NO-TRADE"] = {"confirmed": m15 == "CONFIRMS", "_provenance": _prov(
            "office2.topdown M15 stage (Brain sequence event->shift->retrace->trigger); form of confirmation NOT CONFIRMED in source",
            "HYPOTHESIS", asof)}
    return out


def from_smc(smc_res: Optional[Mapping[str, Any]], direction: str, asof: Optional[float]) -> Dict[str, Dict[str, Any]]:
    """S-REVERSAL-CONT, S-OB (mean threshold) and S-PO3 from office2.smc.engine.analyze output."""
    out: Dict[str, Dict[str, Any]] = {}
    if not smc_res or smc_res.get("error") or direction not in ("LONG", "SHORT"):
        return out
    model = ((smc_res.get("models") or {}).get(direction) or {}).get("REVERSAL")
    if isinstance(model, Mapping):
        steps = model.get("steps") or []
        shift = any(isinstance(s, Mapping) and str(s.get("step", "")).startswith("MS") and s.get("ok") for s in steps)
        poi = bool((model.get("htf_context") or {}).get("htf_poi"))
        out["S-REVERSAL-CONT"] = {"htf_poi": poi, "liquidity_raid": bool(model.get("sweep")), "market_structure_shift": shift,
                                  "_provenance": _prov("office2.smc REVERSAL model (detector thresholds are OUR_IMPLEMENTATION)", "HYPOTHESIS", asof)}
        ob = next((p for p in model.get("pois") or [] if isinstance(p, Mapping) and p.get("kind") == "OB"), None)
        price = _num(smc_res.get("price"))
        if ob and price is not None and _num(ob.get("open")) is not None and _num(ob.get("mt")) is not None:
            op, mt = _num(ob["open"]), _num(ob["mt"])
            out["S-OB"] = {"body_open": op, "body_close": 2 * mt - op, "latest_body_close": price, "direction": direction,
                           "_provenance": _prov("office2.smc OB; Mean Threshold rule is from the source, OB detection is OUR_IMPLEMENTATION",
                                                "HYPOTHESIS", asof)}
    amd = smc_res.get("amd")
    if isinstance(amd, Mapping) and amd.get("stage") not in (None, "NO_RANGE"):
        stage = amd["stage"]
        out["S-PO3"] = {"accumulation": True, "manipulation": stage in ("M", "D"), "distribution": stage == "D",
                        "_provenance": _prov("office2.smc.sessions.amd; Asia window is the canonical ICT proxy, not the source clock (D-02)",
                                             "HYPOTHESIS", asof)}
    return out


def d1_base_after_impulse(d1: Optional[Mapping[str, Any]], asof: Optional[float], lookback: int = 20) -> Dict[str, Dict[str, Any]]:
    """D-POST-IMPULSE-BASE from closed D1 bars (arrays o,h,l,c; last element = last CLOSED day).

    Impulse = latest paranormal D1 bar (range >= 2x mean range of the 20 prior bars, as G-LVL-PARANORMAL)
    within the last `lookback` (=20, source: base older than 20 days is stale) days. Base = bars after it.
    Expected third: lower third after a fall, upper third after a rise. Retracement complete: >= 50% of impulse.
    """
    try:
        o, h, l, c = ([float(x) for x in d1[k]] for k in ("o", "h", "l", "c"))
    except (TypeError, KeyError, ValueError):
        return {}
    n = len(c)
    if n < 22 or not all(isfinite(x) for x in o + h + l + c):
        return {}
    for j in range(n - 2, max(n - 2 - lookback, 20), -1):     # needs at least one base bar after j
        prior = [h[i] - l[i] for i in range(j - 20, j)]
        avg = sum(prior) / 20
        rng = h[j] - l[j]
        if avg <= 0 or rng < 2 * avg:
            continue
        down = c[j] < o[j]
        base_h, base_l = max(h[j + 1:]), min(l[j + 1:])
        third = rng / 3.0
        if down:
            in_third = base_h <= l[j] + third
            retraced = (base_h - l[j]) / rng >= 0.5
        else:
            in_third = base_l >= h[j] - third
            retraced = (h[j] - base_l) / rng >= 0.5
        return {"D-POST-IMPULSE-BASE": {"base_in_expected_third": bool(in_third), "retracement_complete": bool(retraced),
                                        # context for hypotheses (predicate ignores): impulse geometry and base range
                                        "impulse_dir": "DOWN" if down else "UP", "impulse_hi": h[j], "impulse_lo": l[j],
                                        "base_hi": base_h, "base_lo": base_l, "base_days": n - 1 - j,
                                        "_provenance": _prov(f"closed D1 bars; impulse day index {j}, base {n - 1 - j} days", "SOURCE", asof)}}
    return {}


NOT_APPLICABLE_CLASSES = {"STUDENT_EXAMPLE_NOT_RULE", "UX_EXAMPLE_NOT_RULE", "PRODUCT_QA_NOT_RULE"}


def scope_resolution(rules: List[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """NOT_APPLICABLE only where the registry itself says the entry is not a trading rule or is superseded for crypto."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in rules:
        rid, cls = r["rule_id"], r.get("evidence_class")
        if cls in NOT_APPLICABLE_CLASSES:
            out[rid] = {"_not_applicable": f"registry class {cls}: example/QA, not a trading rule"}
        elif rid == "G-STOP-CALC":
            out[rid] = {"_not_applicable": "stock-market stop (0.1-0.2%); for crypto the source gives G-STOP-CRYPTO"}
    return out
