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


LABEL = "ОЗНАКА (кандидат), не доведена причина"


def evidence_digest(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Підсумок модулів доказів зі знімка READY (існуючий office2.evidence): що підтримувало, що суперечило, чого не було. Wyckoff/Bulkowski/Gerchik — вже в знімку, нічого не перераховуємо."""
    out = {"for": [], "against": [], "neutral": [], "not_connected": []}
    for e in snap.get("evidence") or []:
        item = {"module": e.get("module"), "finding": str(e.get("finding", ""))[:160]}
        if e.get("status") == "NOT_CONNECTED":
            out["not_connected"].append(e.get("module"))
        elif e.get("supports") == 1:
            out["for"].append(item)
        elif e.get("supports") == -1:
            out["against"].append(item)
        else:
            out["neutral"].append(item)
    return out


def classify(snap: Dict[str, Any], pos: Dict[str, Any], pm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Класи помилок (кандидати) з доказами. Не доведені причини: один SL нічого не доводить; VALID_LOSS — якщо жодна ознака не спрацювала."""
    th = snap.get("thesis") or {}
    seq = th.get("sequence") or []
    ev = pm.get("events") or {}
    fl = set(pm.get("flags") or [])
    dg = evidence_digest(snap)
    codes: List[Dict[str, Any]] = []

    def add(code: str, proof: str) -> None:
        codes.append({"code": code, "proof": proof, "status": LABEL})

    for e in (snap.get("evidence") or []):
        if str(e.get("module", "")).startswith("M5/M1") and e.get("supports") == 0 and "— ні" in str(e.get("finding", "")):
            add("EARLY_ENTRY", f"M5-тригер не підтверджений на момент READY: {e.get('finding')}")
    rt = _step(seq, "ретрейс у зону")
    if seq and not (rt and rt.get("ok")):
        add("NO_RETEST", "у послідовності немає виконаного кроку «ретрейс у зону»")
    bos = _step(seq, "зсув структури")
    if seq and not (bos and bos.get("ok")):
        add("NO_BOS", "крок «зсув структури (MSS/BOS)» не підтверджений")
    if "EVENT_IS_RETEST_NOT_FRESH_SWEEP" in fl:
        add("WEAK_LEVEL", f"подія — повторний тест прийнятого рівня, не свіжий sweep: {ev.get('event')}")
    lvl = th.get("level") or {}
    if lvl and (lvl.get("strength") or 1) < 2 and not any("Gerchik mirror" in str(x.get("module")) for x in dg["for"]):
        add("WEAK_LEVEL", f"strength={lvl.get('strength')} і дзеркального підтвердження Gerchik немає")
    if fl & {"BTC_DAILY_REGIME_CONFLICT"}:
        add("BTC_CONFLICT", f"напрям {pos['direction']} проти денного режиму BTC ({(ev.get('btc') or {}).get('regime_daily')})")
    if fl & {"HTF_CONFLICT_H4"}:
        add("HTF_CONFLICT", f"проти H4 ({(ev.get('htf_structure') or {}).get('h4')})")
    if fl & {"WEEKEND", "OFF_HOURS"}:
        add("SESSION_RISK", f"сесія {(ev.get('session') or {}).get('session')}, weekend={(ev.get('session') or {}).get('weekend')}")
    for a in dg["against"]:
        if "premium-discount" in str(a["module"]):
            add("BAD_PREMIUM_DISCOUNT", a["finding"])
    if "TP1_REACHED_AFTER_SL" in fl:
        add("SL_HUNT_CANDIDATE", f"після SL ціна дійшла до TP1 (через {(ev.get('after_sl') or {}).get('hours_to_tp1')} год)")
    if "SL_WICK_ONLY_M15_CLOSED_INSIDE" in fl:
        add("SL_WICK_ONLY", "M15-свічка SL закрилась всередині: прокол, не закріплення за SL")
    if "COST_HEAVY" in fl:
        add("COST_HEAVY", f"витрати {(ev.get('cost') or {}).get('cost_r')} R")
    lag = None
    try:
        lag = float(pos.get("delivered_ts")) - float(pos.get("generated_ts"))
    except (TypeError, ValueError):
        pass
    if lag is not None and lag > 120:
        add("DELIVERY_DELAY", f"доставка через {int(lag)} с після рішення")
    if pm.get("missing") and len(pm["missing"]) >= 3:
        add("INSUFFICIENT_DATA", "відсутні: " + ", ".join(pm["missing"]))
    if not codes:
        add("VALID_LOSS", "жодна з перевірених ознак не спрацювала: угода відповідала правилам, збиток у межах очікуваного")
    return codes


def alternatives(snap: Dict[str, Any], pos: Dict[str, Any], bars: List[Tuple[float, ...]]) -> Dict[str, Any]:
    """Формалізовані альтернативи (office2.learning.counterfactual V1–V8) на ЦІЙ угоді. Це ілюстрація, не доказ: перевага підтверджується лише на вибірці (population)."""
    import numpy as np

    from office2.learning import counterfactual as CF

    th = snap.get("thesis") or {}
    tg = th.get("targets") or []
    decided = snap.get("decided_ts")
    if not (decided and tg and th.get("entry") and th.get("sl") and bars):
        return {"status": ND, "note": "немає decided_ts/цілей/свічок"}
    t = np.array([b[0] for b in bars], dtype=float)
    idx = int(np.searchsorted(t, float(decided) - 900.0, side="left"))      # бар, що закрився в decided_ts
    if idx >= len(t) - 1 or abs(t[idx] - (float(decided) - 900.0)) > 1:
        return {"status": ND, "note": "бар рішення поза доступними свічками (угода надто стара для 15m-вікна 50 год)"}
    m15 = {"t": t, "o": np.array([b[1] for b in bars]), "h": np.array([b[2] for b in bars]), "l": np.array([b[3] for b in bars]), "c": np.array([b[4] for b in bars]),
           "v": np.ones(len(t)), "tbv": np.ones(len(t))}
    entry, sl, tp1 = float(th["entry"]), float(th["sl"]), float(tg[0]["p"])
    risk = abs(entry - sl)
    if risk <= 0:
        return {"status": ND, "note": "нульовий ризик"}
    ev = {"dir": pos["direction"], "entry": entry, "sl": sl, "tp1": tp1, "i": idx, "r_tp1": abs(tp1 - entry) / risk, "risk_pct": risk / entry * 100.0, "source": "PAPER", "ts_bar": float(t[idx]), "symbol": pos["symbol"]}
    rows = CF.per_event([ev], m15)
    if not rows:
        return {"status": ND, "note": "per_event порожній"}
    v = rows[0]["variants"]
    out = {"status": "OK", "variants": {k: {"outcome": x["outcome"], "r_net": x["r_net"], "usd_at_10": (round(x["r_net"] * 10.0, 2) if x["r_net"] is not None else None)} for k, x in v.items()},
           "no_trade": {"outcome": "NO_TRADE", "r_net": 0.0, "usd_at_10": 0.0},
           "note": "ілюстрація на одній угоді: альтернатива не вважається покращенням, поки не підтверджена на вибірці (див. population)"}
    out["population"] = population_evidence()
    return out


def population_evidence() -> Dict[str, Any]:
    """Підсумок replay на вибірці (fixtures/learning/replay_paired_*.json): як кожна альтернатива поводилась на сотнях подій, а не на цій угоді."""
    import json
    import os

    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "learning", "replay_paired_2026-10.json")
    try:
        return json.load(open(p))
    except Exception:  # noqa: BLE001
        return {"status": ND, "note": "файл вибірки відсутній"}


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
    ev["evidence"] = evidence_digest(snap)
    if any("Wyckoff" in str(e.get("module")) and "не визначена" in str(e.get("finding", "")) for e in (snap.get("evidence") or [])):
        ev["wyckoff"] = "UNKNOWN (фаза не визначена модулем office_wyckoff)"
    pm = {"version": "pm-2", "analyzed_at": now, "closed_utc": _kyiv(pos.get("close_ts")), "events": ev, "flags": flags, "missing": missing,
          "note": "Прапори — ознаки для накопичення статистики, не доказ помилки і не правило. Висновки — лише з ≥30 угод та незалежного replay."}
    pm["error_classes"] = classify(snap, pos, pm)
    pm["alternatives"] = alternatives(snap, pos, bars) if bars else {"status": ND, "note": "немає свічок"}
    return pm
