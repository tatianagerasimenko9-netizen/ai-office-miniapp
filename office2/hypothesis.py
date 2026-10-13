"""Hypothesis engine: explainable market-model hypotheses with scenarios A/B/C and active observation (SHADOW).

A hypothesis is NOT a READY and NOT a trade permission. It says: "this looks like model X, at stage Y, because
(supports), despite (contradicts), still missing (missing), check next (next_checks)". It is built from the same
closed-bar method inputs as the 82-rule trace (office2.method_inputs) plus SMC, top-down structure and market context.
Entry/SL/TP exist only if a real READY plan of the same direction exists; otherwise `plan` is None.
Never sends Telegram messages, never creates READY/orders/lifecycle events, never changes risk or gates.

Parameters that are OUR convention (not from the sources) are marked HYPOTHESIS: TTL, CONFIRM_R, minimal observation R.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

VERSION = "hyp-1"
M15 = 900.0
TTL_BARS = {"FALSE_BREAK_RECLAIM": 96, "BREAKOUT_RETEST": 96, "POST_IMPULSE_BASE": 96 * 20, "SMC_REVERSAL": 96, "SMC_CONTINUATION": 96}   # HYPOTHESIS: 24 h; D1 base: 20 days (source: older base is stale)
CONFIRM_R = 1.0            # HYPOTHESIS: "hypothesis came true" = reached 1 observation-R in its direction before invalidation
DDL = """CREATE TABLE IF NOT EXISTS office2_hypothesis (
    hyp_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, family TEXT NOT NULL, direction TEXT NOT NULL, state TEXT NOT NULL, stage TEXT,
    first_ts DOUBLE PRECISION NOT NULL, last_ts DOUBLE PRECISION NOT NULL, bar_ts DOUBLE PRECISION NOT NULL, level DOUBLE PRECISION,
    invalidation DOUBLE PRECISION, ref_price DOUBLE PRECISION, risk_ref DOUBLE PRECISION, closed_ts DOUBLE PRECISION,
    payload_json TEXT NOT NULL, outcome_json TEXT, version TEXT)"""
WIDTH = {"d1": 86400.0, "h4": 14400.0, "h1": 3600.0, "m15": 900.0}
UNAVAILABLE_CONTEXT = ["домінування BTC", "OI/funding/ліквідації (якщо flow недоступний)", "золото", "S&P 500", "нафта"]


def _f(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m %H:%M UTC")


def _px(x: Any) -> str:
    v = _f(x)
    return "—" if v is None else f"{v:.6g}"


def tf_view(ctx: Mapping[str, Any], now: float, direction: str) -> Dict[str, Any]:
    """Short-term structure per timeframe from CLOSED bars: UP/DOWN/RANGE (same windows as rule S-STRUCTURE) and relation to the hypothesis."""
    from office2.method_inputs import _closed

    view: Dict[str, Any] = {}
    conflicts: List[str] = []
    for tf in ("d1", "h4", "h1", "m15"):
        a = _closed(ctx.get(tf), WIDTH[tf], now)
        if not a or len(a.get("h", [])) < 8:
            view[tf.upper()] = {"trend": "UNKNOWN", "relation": "UNKNOWN", "note": "немає достатньо закритих барів"}
            continue
        h, l = [float(x) for x in a["h"]], [float(x) for x in a["l"]]
        old_h, new_h, old_l, new_l = max(h[-8:-4]), max(h[-4:]), min(l[-8:-4]), min(l[-4:])
        trend = "UP" if new_h > old_h and new_l > old_l else "DOWN" if new_h < old_h and new_l < old_l else "RANGE"
        rel = "NEUTRAL" if trend == "RANGE" else ("WITH" if (trend == "UP") == (direction == "LONG") else "AGAINST")
        view[tf.upper()] = {"trend": trend, "relation": rel, "closed_ts": float(a["t"][-1]) + WIDTH[tf]}
        if rel == "AGAINST" and tf in ("d1", "h4"):
            conflicts.append(f"{tf.upper()} {('вгору' if trend == 'UP' else 'вниз')} — проти напрямку гіпотези ({direction})")
    return {"tfs": view, "conflicts": conflicts}


def _context(ctx_in: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    c = dict(ctx_in or {})
    mc = c.get("mc") or {}
    have = {k: mc.get(k) for k in ("btc_ret_1h", "btc_ret_4h", "btc_ret_24h", "btc_reg4", "btc_regd", "breadth_up_4h") if mc.get(k) is not None}
    missing = list(UNAVAILABLE_CONTEXT)
    if c.get("flow"):
        missing = [m for m in missing if "OI" not in m]
    if c.get("news_state") not in ("OK", "FAIL"):
        missing.append("календар новин")
    return {"btc": have or None, "session": c.get("session"), "news": c.get("news_state"), "flow": c.get("flow"), "unavailable": missing}


def _scenarios(h: Mapping[str, Any], now: float) -> Dict[str, Any]:
    d, lvl, inv, ref = h["direction"], h.get("level"), h.get("invalidation"), h.get("ref_price")
    long_ = d == "LONG"
    nxt = f"на закритті наступної M15 ({_utc(now + M15)})"
    fam = h["family"]
    if fam == "POST_IMPULSE_BASE":
        a_t = f"Основний: база {'тримається' if True else ''} і ціна виходить з неї {'вниз' if not long_ else 'вгору'} за напрямом імпульсу ({d})."
        a_c = [f"закриття D1 {'нижче' if not long_ else 'вище'} межі бази {_px(lvl)}", "на H4/H1 реакція за напрямом після виходу"]
        b_t = "Альтернативний: ціна відкочується в базу і глибше — база стає розворотною, гіпотеза продовження слабшає."
        b_c = [f"закриття {'вище' if not long_ else 'нижче'} межі бази без продовження", "відкат наближається до 50% імпульсу"]
        c_t = f"Скасування: відкат імпульсу ≥50% (ціна закріпилась {'вище' if not long_ else 'нижче'} {_px(inv)})."
    else:
        a_t = f"Основний: ціна утримується {'вище' if long_ else 'нижче'} рівня {_px(lvl)} і рухається за гіпотезою ({d})."
        a_c = [f"закриття M15 {'вище' if long_ else 'нижче'} {_px(lvl)} після кожного повернення до рівня", "реакція на M5/M1 у зоні рівня (перевірка не підключена в цьому модулі)"]
        b_t = f"Альтернативний: ціна повертається до рівня {_px(lvl)} і боротьба триває (діапазон / повторний тест)."
        b_c = [f"повторний тест {_px(lvl)} з закриттям назад {'вище' if long_ else 'нижче'} — гіпотеза зберігається", "відсутність імпульсу після тесту — слабка реакція"]
        c_t = f"Скасування: закриття M15 {'нижче' if long_ else 'вище'} {_px(inv)} — модель не спрацювала."
    return {
        "A": {"title": a_t, "conditions": a_c, "next_action": "спостерігати; ENTRY/SL/TP лише якщо з'явиться READY", "review": nxt},
        "B": {"title": b_t, "conditions": b_c, "next_action": "очікувати повторного тесту, не входити від дотику", "review": nxt},
        "C": {"title": c_t, "conditions": [f"закриття за {_px(inv)}"], "next_action": "закрити гіпотезу як REFUTED, записати результат", "review": nxt},
    }


def _base(sym, family, direction, stage, what, why, level, inv, ref, risk_ref, rules, now, asof, supports, contradicts, missing, next_checks, ctx, ctx_in, plan_th):
    plan = None
    if plan_th and plan_th.get("state") == "READY" and plan_th.get("dir") == direction:
        tg = plan_th.get("targets") or []
        e, s = _f(plan_th.get("entry")), _f(plan_th.get("sl"))
        t1 = _f(tg[0].get("p")) if tg and isinstance(tg[0], Mapping) else None
        if e and s and t1 and e != s:
            plan = {"entry": e, "sl": s, "tp1": t1, "rr_tp1": round(abs(t1 - e) / abs(e - s), 2), "source": "READY thesis (office2.brain)"}
    tv = tf_view(ctx, now, direction)
    if tv["conflicts"]:
        contradicts = list(contradicts) + tv["conflicts"]
    key = f"{sym}|{family}|{direction}|{round(level, 10) if level is not None else 'na'}"
    h = {"id": key, "version": VERSION, "symbol": sym, "family": family, "direction": direction, "stage": stage, "state": "ACTIVE",
         "what_seen": what, "why_this_model": why, "supports": supports, "contradicts": contradicts, "missing": missing, "next_checks": next_checks,
         "level": level, "invalidation": inv, "ref_price": ref, "risk_ref": risk_ref, "rule_ids": rules,
         "tf": tv["tfs"], "context": _context(ctx_in), "plan": plan, "created_bar_ts": asof, "decided_ts": now,
         "role": "SHADOW", "is_ready": False,
         "note": "Гіпотеза ≠ READY: ENTRY/SL/TP/R:R розраховуються лише для READY-плану." if plan is None else "READY-план цього напрямку існує окремо; гіпотеза не змінює його."}
    h["scenarios"] = _scenarios(h, now)
    return h


def build(sym: str, ctx: Mapping[str, Any], now: float, inputs: Mapping[str, Mapping[str, Any]], *, smc_res: Optional[Mapping[str, Any]] = None,
          plan_th: Optional[Mapping[str, Any]] = None, context: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Hypotheses visible at closed-bar time `now`. `inputs` = office2.method_inputs.build_inputs(...) output (already causal)."""
    from office2.method_predicates import evaluate

    def ev(rid):
        v = inputs.get(rid)
        return evaluate(rid, {k: x for k, x in v.items() if not str(k).startswith("_")})["status"] if v else "ABSENT"

    asof = (inputs.get("G-ATR-CALC") or {}).get("_provenance", {}).get("asof_closed_bar_ts") or _f((ctx.get("m15") or {}).get("t", [None])[-1] if len(ctx.get("m15", {}).get("t", [])) else None)
    avg_rng = _f((inputs.get("G-PROGNOSTIC") or {}).get("average_range"))
    out: List[Dict[str, Any]] = []
    # F1 — false break / liquidity raid with return (Gerchik D-FALSE-BREAK, SMC raid)
    fb = inputs.get("D-FALSE-BREAK")
    if fb and ev("D-FALSE-BREAK") == "PASS":
        d, lvl, close = fb["direction"], float(fb["level"]), float(fb["close"])
        ext = float(fb["low"]) if d == "LONG" else float(fb["high"])
        sup = [f"ціна проколола рівень {_px(lvl)} (екстремум {_px(ext)}) і закрила бар {'вище' if d == 'LONG' else 'нижче'} рівня"]
        con, miss = [], ["реакція на M5/M1 після повернення", "новини/календар" if (context or {}).get("news_state") not in ("OK", "FAIL") else "підтвердження наступною свічкою"]
        for rid, ok_t, bad_t in (("G-FB-DEPTH", "глибина проколу ≤30% ATR(D1) (джерело)", "глибина проколу >30% ATR(D1) — глибокий хибний пробій"),
                                 ("G-LVL-CONFIRM-SIGNS", "рівень має ознаки підтвердження (дотики/хвіст/хибний пробій)", "ознак підтвердження рівня немає"),
                                 ("G-LVL-FLOATING", "рівень фіксований", "рівень плаваючий (немає підтвердження) — «радіоактивна зона»")):
            st = ev(rid)
            (sup if st == "PASS" else con if st == "FAIL" else miss).append(ok_t if st == "PASS" else bad_t if st == "FAIL" else f"{rid}: немає даних")
        if ev("G-FB-2BAR") == "PASS":
            sup.append("повернення за 2 свічки (G-FB-2BAR)")
        elif ev("G-FB-1BAR") == "PASS":
            sup.append("повернення за 1 свічку (G-FB-1BAR)")
        rng = inputs.get("S-RANGE")
        tgt = _f(rng.get("range_high" if d == "LONG" else "range_low")) if rng else None
        if tgt is not None:
            sup.append(f"межа діапазону {_px(tgt)} — орієнтир для спостереження (не TP)")
        risk = max(abs(close - ext), avg_rng or 0.0) or None   # HYPOTHESIS: observation-R floor = mean M15 range
        out.append(_base(sym, "FALSE_BREAK_RECLAIM", d, "RETURNED", f"прокол і повернення за рівень {_px(lvl)} ({d})",
                         "хибний пробій: винос стопів за рівень, закриття назад (Герчик D-FALSE-BREAK; SMC liquidity raid)", lvl, ext, close, risk,
                         ["D-FALSE-BREAK", "G-FALSE-BREAK-DEF", "S-LIQUIDITY-RAID", "G-FB-1BAR", "G-FB-DEPTH", "G-LVL-CONFIRM-SIGNS", "G-LVL-FLOATING"], now, asof,
                         sup, con, miss, ["наступна закрита M15: чи утримується закриття за рівнем", "H1/H4: чи рівень значущий і чи немає конфлікту", "M5/M1: реакція у зоні рівня"],
                         ctx, context, plan_th))
    # F2 — breakout of a prior resistance and retest (mirror level)
    bo = inputs.get("G-BREAKOUT")
    if bo and bo.get("closed_beyond") is True and _f(bo.get("level")) is not None:
        lvl = float(bo["level"])
        held = bo.get("held_retest") is True
        close = float((inputs.get("S-KAVYA-CONCEPTS") or {}).get("close") or lvl)
        risk = max(abs(close - lvl), avg_rng or 0.0) or None
        out.append(_base(sym, "BREAKOUT_RETEST", "LONG", "RETEST_HELD" if held else "BROKEN_WAIT_RETEST",
                         f"закриття вище колишнього опору {_px(lvl)}" + (" і утримання ретесту" if held else ", ретесту ще не було"),
                         "пробій з дзеркальним рівнем: опір стає підтримкою (Герчик G-BREAKOUT / G-LVL-MIRROR)", lvl, lvl, close, risk,
                         ["G-BREAKOUT", "G-LVL-MIRROR"], now, asof,
                         [f"попередня свічка закрилась вище {_px(lvl)}"] + (["ретест рівня утримано"] if held else []), [],
                         ([] if held else ["ретест рівня"]) + ["імпульс після пробою (G-IMPULSE: у джерелі немає вікна часу — не оцінюється)"],
                         ["чи буде ретест без закриття нижче рівня", "H1/H4: чи пробій не проти старшої структури"], ctx, context, plan_th))
    # F3 — post-impulse base on D1 (Gerchik D-POST-IMPULSE-BASE)
    pb = inputs.get("D-POST-IMPULSE-BASE")
    if pb and ev("D-POST-IMPULSE-BASE") == "PASS" and _f(pb.get("impulse_hi")) is not None:
        down = pb.get("impulse_dir") == "DOWN"
        d = "SHORT" if down else "LONG"
        hi, lo, bh, bl = (float(pb[k]) for k in ("impulse_hi", "impulse_lo", "base_hi", "base_lo"))
        days = int(pb.get("base_days") or 0)
        stage = "BASE_FORMING" if days < 2 else "BASE_MATURE" if days <= 7 else "BASE_DEEP"
        lvl = bl if down else bh
        inv = (hi + lo) / 2.0            # retracement ≥50% of the impulse refutes (source)
        close = float((inputs.get("S-KAVYA-CONCEPTS") or {}).get("close") or lvl)
        out.append(_base(sym, "POST_IMPULSE_BASE", d, stage, f"база {days} дн. після {'падіння' if down else 'зростання'} D1 в {'нижній' if down else 'верхній'} третині імпульсу",
                         "після паранормального руху без нормального відкату формується база; очікуємо продовження (Герчик D-POST-IMPULSE-BASE)", lvl, inv, close, abs(inv - lvl) or None,
                         ["D-POST-IMPULSE-BASE", "D-PARANORMAL-IMPULSE", "G-LVL-PARANORMAL"], now, asof,
                         [f"імпульс {_px(lo)}–{_px(hi)}", f"база {_px(bl)}–{_px(bh)} у {'нижній' if down else 'верхній'} третині", f"відкат <50% імпульсу; база {days} дн. ({'оптимум 2–7' if 2 <= days <= 7 else 'поза оптимумом 2–7 днів'})"],
                         [], ["волатильність у базі (джерело: якісно)", "реакція на H4/H1 біля межі бази"], ["вихід з бази закриттям D1", "чи немає відкату ≥50%"], ctx, context, plan_th))
    # F4 — SMC models in WAIT/ARMED/CANDIDATE (reversal / continuation): steps, what is missing
    if smc_res and not smc_res.get("error"):
        for d in ("LONG", "SHORT"):
            for model in ("REVERSAL", "CONTINUATION"):
                m = ((smc_res.get("models") or {}).get(d) or {}).get(model)
                if not isinstance(m, Mapping) or m.get("state") not in ("WAIT", "ARMED", "CANDIDATE", "READY") or not m.get("sweep"):
                    continue
                sw = m["sweep"]
                lvl = _f((sw.get("level") or {}).get("p")) if isinstance(sw.get("level"), Mapping) else None
                ext = _f(sw.get("extreme"))
                if lvl is None or ext is None:
                    continue
                done = [str(s.get("step")) + (f": {s.get('detail')}" if s.get("detail") else "") for s in m.get("steps") or [] if isinstance(s, Mapping) and s.get("ok")]
                bad = [str(s.get("step")) for s in m.get("steps") or [] if isinstance(s, Mapping) and not s.get("ok")]
                need = (m.get("need") or {}).get("text") if isinstance(m.get("need"), Mapping) else None
                px = _f(smc_res.get("price")) or lvl
                out.append(_base(sym, f"SMC_{model}", d, f"{m.get('state')}·крок {m.get('stage')}", f"SMC {model}: raid {_px(lvl)} → {m.get('state')}",
                                 str(m.get("reason") or "модель SMC (Smart Money/ICT)"), lvl, ext, px, abs(px - ext) or None,
                                 ["S-REVERSAL-CONT", "S-LIQUIDITY-RAID", "S-OB", "S-OTE-PD"], now, asof, done, list(m.get("evidence_against") or []) + [f"не виконано: {b}" for b in bad],
                                 [need] if need else [], [need] if need else ["наступний крок моделі"], ctx, context, plan_th))
    return out


def compact(h: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: h.get(k) for k in ("id", "family", "direction", "stage", "state", "what_seen", "level", "invalidation", "is_ready")}


# ---- active observation ------------------------------------------------------------------------------------------------------------

_INIT: set = set()


def init_db(db: str) -> None:
    from office_bridge import _execute

    _execute(db, DDL)


def _insert_or_refresh(db: str, h: Mapping[str, Any], now: float) -> None:
    from office_bridge import _execute, _fetchall

    row = _fetchall(db, "SELECT state, stage, payload_json FROM office2_hypothesis WHERE hyp_id = ?", (h["id"],))
    payload = json.dumps(dict(h), ensure_ascii=False, default=str)
    if not row:
        _execute(db, "INSERT INTO office2_hypothesis (hyp_id, symbol, family, direction, state, stage, first_ts, last_ts, bar_ts, level, invalidation, ref_price, risk_ref, payload_json, version) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                 (h["id"], h["symbol"], h["family"], h["direction"], "ACTIVE", h["stage"], now, now, h["created_bar_ts"] or now, h["level"], h["invalidation"], h["ref_price"], h["risk_ref"], payload, VERSION))
        return
    state, stage, old = row[0]
    if state != "ACTIVE":
        return       # terminal hypotheses are never revived; a new structure gets a new id (new level)
    if stage != h["stage"]:
        try:
            hist = json.loads(old).get("history") or []
        except Exception:  # noqa: BLE001
            hist = []
        hist.append({"ts": now, "event": "STAGE", "from": stage, "to": h["stage"]})
        d = dict(h, history=hist[-30:])
        _execute(db, "UPDATE office2_hypothesis SET stage = ?, last_ts = ?, payload_json = ? WHERE hyp_id = ?", (h["stage"], now, json.dumps(d, ensure_ascii=False, default=str), h["id"]))
    else:
        _execute(db, "UPDATE office2_hypothesis SET last_ts = ? WHERE hyp_id = ?", (now, h["id"]))


def walk(fam: str, d: str, bar_ts: float, lvl: Optional[float], inv: Optional[float], ref: Optional[float], risk: Optional[float],
         arr: Mapping[str, Any], now: float) -> Dict[str, Any]:
    """Pure state walk over CLOSED M15 bars after the signal bar (shared by live observation and replay; no I/O)."""
    from office2.method_inputs import _closed

    a = _closed(arr, M15, now)
    out: Dict[str, Any] = {"state": "ACTIVE", "closed_ts": None, "events": [], "mfe": 0.0, "mae": 0.0, "touches": 0, "bars": 0}
    if not a:
        return out
    t = [float(x) for x in a["t"]]
    idx = [i for i, ts in enumerate(t) if ts > float(bar_ts)]
    out["bars"] = len(idx)
    long_ = d == "LONG"
    r = float(risk) if risk else None
    for i in idx:
        hi, lo, cl = float(a["h"][i]), float(a["l"][i]), float(a["c"][i])
        if inv is not None and (cl < inv if long_ else cl > inv):
            out.update(state="REFUTED", closed_ts=t[i] + M15)
            out["events"].append({"ts": out["closed_ts"], "event": "REFUTED", "close": cl})
            return out
        if lvl is not None and lo <= lvl <= hi:
            out["touches"] += 1
            held = cl >= lvl if long_ else cl <= lvl
            out["events"].append({"ts": t[i] + M15, "event": "RETEST_HELD" if held else "TOUCH_LOST", "close": cl})
        if r and ref is not None:
            fav = (hi - ref) / r if long_ else (ref - lo) / r
            adv = (ref - lo) / r if long_ else (hi - ref) / r
            out["mfe"], out["mae"] = max(out["mfe"], fav), max(out["mae"], adv)
            if out["mfe"] >= CONFIRM_R:
                out.update(state="CONFIRMED", closed_ts=t[i] + M15)
                out["events"].append({"ts": out["closed_ts"], "event": "CONFIRMED", "mfe_r": round(out["mfe"], 2)})
                return out
    if len(idx) >= TTL_BARS.get(fam, 96):
        out.update(state="EXPIRED", closed_ts=t[idx[-1]] + M15)
        out["events"].append({"ts": out["closed_ts"], "event": "EXPIRED"})
    return out


def progress(db: str, sym: str, m15: Mapping[str, Any], now: float) -> List[Dict[str, Any]]:
    """Advance ACTIVE hypotheses of the symbol using CLOSED M15 bars after the signal bar. Returns the transitions made."""
    from office_bridge import _execute, _fetchall

    rows = _fetchall(db, "SELECT hyp_id, family, direction, bar_ts, level, invalidation, ref_price, risk_ref, payload_json FROM office2_hypothesis WHERE symbol = ? AND state = 'ACTIVE'", (sym,))
    done: List[Dict[str, Any]] = []
    for hid, fam, d, bar_ts, lvl, inv, ref, risk, pj in rows:
        w = walk(fam, d, bar_ts, lvl, inv, ref, risk, m15, now)
        if w["state"] == "ACTIVE" and not w["events"]:
            continue
        try:
            payload = json.loads(pj)
        except Exception:  # noqa: BLE001
            payload = {}
        payload["history"] = ((payload.get("history") or []) + w["events"])[-30:]
        payload["state"] = w["state"]
        outcome = ({"state": w["state"], "mfe_r": round(w["mfe"], 3), "mae_r": round(w["mae"], 3), "bars_after": w["bars"], "touches": w["touches"],
                    "convention": f"CONFIRMED = {CONFIRM_R}R у напрямку до інвалідації (HYPOTHESIS); R = відстань ref→інвалідація, не ризик угоди"}
                   if w["state"] != "ACTIVE" else None)
        _execute(db, "UPDATE office2_hypothesis SET state = ?, closed_ts = ?, payload_json = ?, outcome_json = ?, last_ts = ? WHERE hyp_id = ?",
                 (w["state"], w["closed_ts"], json.dumps(payload, ensure_ascii=False, default=str), json.dumps(outcome) if outcome else None, now, hid))
        if w["state"] != "ACTIVE":
            done.append({"id": hid, "state": w["state"], "mfe_r": round(w["mfe"], 2), "mae_r": round(w["mae"], 2)})
    return done


def observe(db: str, sym: str, hyps: List[Mapping[str, Any]], m15: Mapping[str, Any], now: float) -> Dict[str, Any]:
    """One cycle: refresh/insert today's hypotheses, then advance all active ones. No messages, no READY, no orders."""
    if db not in _INIT:
        init_db(db)
        _INIT.add(db)
    for h in hyps:
        _insert_or_refresh(db, h, now)
    return {"transitions": progress(db, sym, m15, now), "formed": len(hyps)}


def cleanup(db: str, now: float, keep_days: float = 14.0) -> None:
    from office_bridge import _execute

    _execute(db, "DELETE FROM office2_hypothesis WHERE state != 'ACTIVE' AND closed_ts < ?", (now - keep_days * 86400,))


def active_for(db: str, sym: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Активні гіпотези одного символу (для розбору READY аналітиком): family, direction, stage, level, invalidation, що бачили. Лише читання."""
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT family, direction, stage, level, invalidation, first_ts, last_ts, payload_json FROM office2_hypothesis WHERE symbol = ? AND state = 'ACTIVE' ORDER BY last_ts DESC LIMIT ?", (sym, int(limit)))
    out = []
    for fam, d, stg, lvl, inv, ft, lt, pj in rows:
        try:
            what = (json.loads(pj) or {}).get("what_seen")
        except (TypeError, ValueError):
            what = None
        out.append({"family": fam, "direction": d, "stage": stg, "level": lvl, "invalidation": inv, "first_ts": ft, "last_ts": lt, "what_seen": what})
    return out


def list_hypotheses(db: str, state: str = "ACTIVE", limit: int = 50) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT payload_json, state, first_ts, last_ts, outcome_json FROM office2_hypothesis WHERE state = ? ORDER BY last_ts DESC LIMIT ?", (state, int(limit)))
    out = []
    for pj, st, ft, lt, oj in rows:
        d = json.loads(pj)
        d.update(state=st, first_ts=ft, last_ts=lt, outcome=json.loads(oj) if oj else None)
        out.append(d)
    return out
