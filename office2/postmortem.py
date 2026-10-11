"""Автоматичний розбір закритої paper-угоди з даних знімка READY і свічок. Лише факти: чого немає — «NO_DATA» (причини не вигадуються).

Прапори (flags) — ознаки для накопичення статистики, НЕ доказ помилки й НЕ правило блокування: один збиток нічого не доводить.
Перевірка гіпотез — лише через learning-звіт на ≥ 30 угод та незалежний replay."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ND = "NO_DATA"
AFTER_SL_HOURS = 24


def _step(seq: List[Dict[str, Any]], prefix: str) -> Optional[Dict[str, Any]]:
    for x in seq or []:
        if str(x.get("step", "")).startswith(prefix):
            return x
    return None


def _kyiv(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    from datetime import timedelta

    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{(d + timedelta(hours=3)):%d.%m %H:%M} Київ ({d:%H:%M} UTC)"


def after_sl(direction: str, sl: float, tp1: float, sl_ts: float, bars: List[Tuple[float, ...]], now: float) -> Dict[str, Any]:
    """Що було з ціною після закриття за SL: чи дійшла до TP1 (і чи раніше нового мінімуму за SL), скільки годин спостерігали."""
    long_ = direction == "LONG"
    after = [b for b in bars if b[0] >= sl_ts - 1]
    if not after:
        return {"status": ND, "note": "немає свічок після SL"}
    observed_h = round((min(after[-1][0] + 900, now) - sl_ts) / 3600.0, 1)
    hit_ts = None
    extreme = None
    for t, o, h, l, c in after:
        if hit_ts is None and ((h >= tp1) if long_ else (l <= tp1)):
            hit_ts = t
        extreme = max(extreme or h, h) if long_ else min(extreme or l, l)
        if hit_ts is not None:
            break
    done = hit_ts is not None or observed_h >= AFTER_SL_HOURS
    return {"status": "FINAL" if done else "PENDING", "observed_h": observed_h, "reached_tp1_after_sl": hit_ts is not None,
            "hours_to_tp1": round((hit_ts - sl_ts) / 3600.0, 1) if hit_ts else None, "extreme_after": extreme}


def analyze(snap: Dict[str, Any], pos: Dict[str, Any], bars: Optional[List[Tuple[float, ...]]] = None, now: Optional[float] = None) -> Dict[str, Any]:
    import time

    now = time.time() if now is None else now
    th = snap.get("thesis") or {}
    seq = th.get("sequence") or []
    lvl = th.get("level") or {}
    inv = th.get("invalidation") or {}
    q = th.get("quality") or {}
    d = pos["direction"]
    long_ = d == "LONG"
    mk = snap.get("market_at_signal") or {}
    mkt = mk.get("market") or {}
    smc = snap.get("smc") or {}
    ev: Dict[str, Any] = {}
    flags: List[str] = []
    missing: List[str] = []

    ev["level"] = {"kind": lvl.get("kind"), "price": lvl.get("p"), "strength": lvl.get("strength")} if lvl else ND
    if not lvl:
        missing.append("level")
    ev0 = _step(seq, "подія")
    ev["event"] = ev0.get("value") if ev0 else ND
    fresh_sweep = bool(ev0 and "SWEEP" in str(ev0.get("value", "")).upper() and "ПОВТОРНИЙ" not in str(ev0.get("value", "")).upper())
    retest_old = bool(ev0 and "ПОВТОРНИЙ ТЕСТ" in str(ev0.get("value", "")).upper())
    ev["sweep"] = "FRESH_SWEEP" if fresh_sweep else ("RETEST_OF_ACCEPTED_LEVEL (не свіжий sweep)" if retest_old else (ND if not ev0 else "NO_SWEEP"))
    if retest_old:
        flags.append("EVENT_IS_RETEST_NOT_FRESH_SWEEP")
    bos = _step(seq, "зсув структури")
    ev["bos_choch"] = (bos.get("value") if bos and bos.get("ok") else ("не підтверджено" if bos else ND))
    rt = _step(seq, "ретрейс у зону")
    ev["retest"] = (rt.get("value") if rt and rt.get("ok") else ("немає" if rt else ND))
    ev["why_direction"] = th.get("reason") or ND
    ev["sequence_ok"] = [x.get("step") for x in seq if x.get("ok")] or ND

    sess = snap.get("session_tag") or {}
    ev["session"] = {"session": sess.get("session"), "weekend": sess.get("weekend"), "min_to_london_open": sess.get("min_to_london_open"), "min_to_ny_open": sess.get("min_to_ny_open")} if sess else ND
    if sess.get("weekend"):
        flags.append("WEEKEND")
    if sess.get("session") == "OFF_HOURS":
        flags.append("OFF_HOURS")

    # HTF / BTC / SMC
    h4 = ((smc.get("structure") or {}).get("h4") or {}).get("trend")
    h1 = ((smc.get("structure") or {}).get("h1") or {}).get("trend")
    ev["htf_structure"] = {"h4": h4, "h1": h1} if (h4 or h1) else ND
    if h4 in ("UP", "DOWN") and ((long_ and h4 == "DOWN") or ((not long_) and h4 == "UP")):
        flags.append("HTF_CONFLICT_H4")
    regd = mkt.get("btc_regd")
    ev["btc"] = {"regime_daily": regd, "ret_1h": mkt.get("btc_ret_1h"), "ret_4h": mkt.get("btc_ret_4h"), "ret_24h": mkt.get("btc_ret_24h")} if mkt else ND
    if regd in (-1, 1) and ((long_ and regd == -1) or ((not long_) and regd == 1)):
        flags.append("BTC_DAILY_REGIME_CONFLICT")
    al = snap.get("alignment_summary") or {}
    ev["alignment"] = {"against": al.get("against"), "for": al.get("for"), "neutral": al.get("neutral")} if al else ND
    if (al.get("against") or 0) >= 2 and (al.get("against") or 0) >= (al.get("for") or 0):
        flags.append("ALIGNMENT_AGAINST_GE_FOR")
    ev["smc_shadow"] = {"agrees_ready": smc.get("agrees_ready"), "state": smc.get("state"), "reason": smc.get("reason")} if smc else ND
    if smc and smc.get("agrees_ready") is False:
        flags.append("SMC_SHADOW_DISAGREES")

    # вхід: чи був передчасним (ознаки: відхилення fill від плану, змішана екскурсія)
    plan, fill = pos.get("plan_entry"), pos.get("fill_price")
    risk = abs(plan - pos["sl"]) if plan and pos.get("sl") else None
    ev["entry"] = {"plan": plan, "fill": fill, "slip_r": round(((fill - plan) if long_ else (plan - fill)) / risk, 3) if (plan and fill and risk) else ND,
                   "mfe_r": pos.get("mfe_r"), "mae_r": pos.get("mae_r")}
    # SL
    stop_pct = (th.get("sizing") or {}).get("stop_pct")
    ev["sl"] = {"price": pos.get("sl"), "invalidation": inv.get("price"), "buffer": inv.get("buffer"), "buffer_basis": inv.get("buffer_basis"), "why": inv.get("why"),
                "risk_atr15": q.get("risk_atr15"), "stop_pct": stop_pct}
    if q.get("risk_atr15") is not None and q["risk_atr15"] < 1.0:
        flags.append("SL_INSIDE_M15_NOISE")
    if stop_pct:
        from office2.learning import costs as C

        cr = C.cost_r(stop_pct)
        ev["cost"] = {"cost_r": round(cr, 3), "cost_usd": pos.get("cost_usd"), "share_of_loss_pct": round(abs(pos["cost_usd"]) / abs(pos["pnl_a"]) * 100, 1) if pos.get("pnl_a") and pos.get("cost_usd") else ND}
        if cr >= 0.25:
            flags.append("COST_HEAVY")
    else:
        ev["cost"] = ND

    # SL: прокол чи закріплення; що було потім
    ev["sl_candle"] = ND
    ev["after_sl"] = ND
    if bars is not None and pos.get("sl_ts") and pos.get("sl"):
        sb = [b for b in bars if b[0] <= pos["sl_ts"] <= b[0] + 900 + 1]
        if sb:
            t, o, h, l, c = sb[-1]
            closed_beyond = (c <= pos["sl"]) if long_ else (c >= pos["sl"])
            ev["sl_candle"] = {"close": c, "closed_beyond_sl": closed_beyond, "note": "M15-свічка, у якій спрацював SL" + ("" if closed_beyond else "; закрилась НЕ за SL (прокол)")}
            if not closed_beyond:
                flags.append("SL_WICK_ONLY_M15_CLOSED_INSIDE")
        if pos.get("tp1"):
            a = after_sl(d, pos["sl"], pos["tp1"], pos["sl_ts"], bars, now)
            ev["after_sl"] = a
            if a.get("reached_tp1_after_sl"):
                flags.append("TP1_REACHED_AFTER_SL")
    for k in ("sl_candle", "after_sl"):
        if ev[k] == ND:
            missing.append(k)
    return {"version": "pm-1", "analyzed_at": now, "closed_utc": _kyiv(pos.get("close_ts")), "events": ev, "flags": flags, "missing": missing,
            "note": "Прапори — ознаки для накопичення статистики, не доказ помилки і не правило. Висновки — лише з ≥30 угод та незалежного replay."}
