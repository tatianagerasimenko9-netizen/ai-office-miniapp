"""Лев — аналітик спочатку, індикатори лише аргумент.

Порядок: контекст → discovery → структура → здійсненність → власний сценарій
→ Pump/Hunter/канал як CONFIRM | CONTRADICT | NEUTRAL | NOT_CONNECTED.
Жоден індикатор не створює ENTER. Відсутність Pine не зупиняє сканер.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5, TP1-фільтри. Не ордер.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office_atr_policy import classify_atr_day_used
from office_risk_officer import review_plan
from office_confluence import TAG_UA, evaluate_confluence
from office_desk_card import _f, widen_sl_to_atr_h1
from office_ict_hunter import evaluate_ict_hunter
from office_pump_dump import evaluate_pump_dump
from office_radar import MIN_RR, detect_sweep_from_candles
from office_regression_channel import regression_channel
from office_topdown import calc_sl_with_buffer
from office_trade_steer import _bars

STANCE_CONFIRM = "CONFIRM"
STANCE_CONTRADICT = "CONTRADICT"
STANCE_NEUTRAL = "NEUTRAL"
STANCE_NOT_CONNECTED = "NOT_CONNECTED"

ACTION_SEND = "SEND"
ACTION_WAIT = "WAIT"
ACTION_SKIP = "SKIP"
ACTION_WATCHING = "WATCHING"

INDICATOR_KEYS = ("pump_dump", "ict_hunter", "channel")


def indicator_stance(
    *,
    lev_direction: str,
    indicator_direction: Any = None,
    connected: bool,
    signal: Any = False,
    reason: str = "",
    source: str = "ohlcv_port",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Індикатор — аргумент. Ніколи не створює ENTER."""
    out: Dict[str, Any] = {
        "stance": STANCE_NOT_CONNECTED,
        "creates_enter": False,
        "connected": bool(connected),
        "signal": bool(signal) if not isinstance(signal, str) else bool(signal),
        "direction": str(indicator_direction or "").upper(),
        "reason": reason or "",
        "source": source,
    }
    if extra:
        out["extra"] = extra
    if not connected:
        out["stance"] = STANCE_NOT_CONNECTED
        out["reason"] = reason or "NOT_CONNECTED"
        return out
    lev = str(lev_direction or "").upper()
    ind = str(indicator_direction or "").upper()
    fired = bool(signal) if not isinstance(signal, str) else True
    if isinstance(signal, str) and signal.strip():
        fired = True
        if not ind:
            ind = "LONG" if signal.upper() == "PUMP" else ("SHORT" if signal.upper() == "DUMP" else "")
            out["direction"] = ind
    if not fired or not ind:
        out["stance"] = STANCE_NEUTRAL
        out["reason"] = reason or "немає сигналу індикатора"
        return out
    if lev and ind == lev:
        out["stance"] = STANCE_CONFIRM
        out["reason"] = reason or "збігається з сценарієм Лева"
        return out
    out["stance"] = STANCE_CONTRADICT
    out["reason"] = reason or f"індикатор {ind} проти сценарію {lev or '—'}"
    return out


def _grade_rank(grade: Any, n: Any) -> tuple:
    g = str(grade or "").upper()
    gi = {"A": 3, "B": 2}.get(g, 0)
    try:
        ni = int(n or 0)
    except (TypeError, ValueError):
        ni = 0
    return (1 if gi or ni else 0, gi, ni)


def _structural_sl(*, direction: str, zone_lo: Any, zone_hi: Any, price: Any) -> Optional[float]:
    side = str(direction or "").upper()
    lo, hi = _f(zone_lo), _f(zone_hi)
    px = _f(price)
    if side == "LONG":
        packed = calc_sl_with_buffer(lo if lo is not None else hi, "LONG", price=px or lo)
    else:
        packed = calc_sl_with_buffer(hi if hi is not None else lo, "SHORT", price=px or hi)
    return _f(packed.get("sl"))


def _tp_from_rr(*, direction: str, entry: float, sl: float, rr: float = MIN_RR) -> Optional[float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    side = str(direction or "").upper()
    if side == "LONG":
        return entry + risk * float(rr)
    if side == "SHORT":
        return entry - risk * float(rr)
    return None


def sl_in_liquidity_pool(
    *,
    direction: str,
    sl: Any,
    candles: Any,
) -> Dict[str, Any]:
    """Стоп у очевидному пулі рівних лоїв/хайів або на свіпі. Стоп не розширюємо."""
    s = _f(sl)
    rows = _bars(candles)
    empty = {"in_pool": False, "need_sweep_reclaim": False, "level": None, "reason": ""}
    if s is None or len(rows) < 3:
        return empty
    sweep = detect_sweep_from_candles(rows)
    side = str(direction or "").upper()
    lv = _f(sweep.get("sweep_level"))
    if lv is not None:
        tol = abs(lv) * 0.0025
        if abs(s - lv) <= tol:
            return {
                "in_pool": True,
                "need_sweep_reclaim": True,
                "level": lv,
                "reason": "стоп біля рівня свіпу — потрібен sweep/reclaim, стоп не розширюємо",
            }
    recent = rows[-20:] if len(rows) >= 20 else rows
    if side == "LONG":
        lows = [_f(r.get("low")) for r in recent]
        pts = [x for x in lows if x is not None]
        if pts:
            eq = min(pts)
            cluster = sum(1 for x in pts if abs(x - eq) / eq <= 0.0025)
            if cluster >= 3 and abs(s - eq) / eq <= 0.003:
                return {
                    "in_pool": True,
                    "need_sweep_reclaim": True,
                    "level": eq,
                    "reason": "стоп у пулі рівних лоїв — чекаю свіп/reclaim, стоп не розширюю",
                }
    else:
        highs = [_f(r.get("high")) for r in recent]
        pts = [x for x in highs if x is not None]
        if pts:
            eq = max(pts)
            cluster = sum(1 for x in pts if abs(x - eq) / eq <= 0.0025)
            if cluster >= 3 and abs(s - eq) / eq <= 0.003:
                return {
                    "in_pool": True,
                    "need_sweep_reclaim": True,
                    "level": eq,
                    "reason": "стоп у пулі рівних хаїв — чекаю свіп/reclaim, стоп не розширюю",
                }
    return empty


def draft_lev_scenario(
    *,
    symbol: str,
    timeframe: str = "H1",
    candles_m15: Any = None,
    candles_h1: Any = None,
    candles_h4: Any = None,
    candles_d1: Any = None,
    candles_w: Any = None,
    candles_ltf: Any = None,
    price: Any = None,
    atr_h1: Any = None,
    day_used_pct: Any = None,
    now_ts: Any = None,
    candidates_long: Any = None,
    candidates_short: Any = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Власний сценарій Лева ДО індикаторів. Обидва напрямки, не підганяти під LONG."""
    ctx = dict(market_context or {})
    if not ctx:
        ctx = {
            "data_status": "DATA_UNAVAILABLE",
            "note": "макро/новини/Nasdaq/DXY/золото/нафта не підставлені — не вигадую кореляцій",
        }
    long_c = evaluate_confluence(
        symbol=symbol,
        direction="LONG",
        timeframe=timeframe,
        candles_m15=candles_m15,
        candles_h1=candles_h1,
        candles_h4=candles_h4,
        candles_d1=candles_d1,
        candles_w=candles_w,
        candles_ltf=candles_ltf,
        price=price,
        now_ts=now_ts,
        candidates=candidates_long,
    )
    short_c = evaluate_confluence(
        symbol=symbol,
        direction="SHORT",
        timeframe=timeframe,
        candles_m15=candles_m15,
        candles_h1=candles_h1,
        candles_h4=candles_h4,
        candles_d1=candles_d1,
        candles_w=candles_w,
        candles_ltf=candles_ltf,
        price=price,
        now_ts=now_ts,
        candidates=candidates_short,
    )
    lr = _grade_rank(long_c.get("grade"), long_c.get("n"))
    sr = _grade_rank(short_c.get("grade"), short_c.get("n"))
    # Не віддавати перевагу LONG: сильніший кластер, при рівності — той, хто send_card.
    if lr > sr:
        primary, alt, side = long_c, short_c, "LONG"
    elif sr > lr:
        primary, alt, side = short_c, long_c, "SHORT"
    elif long_c.get("send_card") and not short_c.get("send_card"):
        primary, alt, side = long_c, short_c, "LONG"
    elif short_c.get("send_card") and not long_c.get("send_card"):
        primary, alt, side = short_c, long_c, "SHORT"
    else:
        primary, alt, side = long_c, short_c, "LONG" if long_c.get("n") else "SHORT"

    entry = _f(primary.get("entry"))
    sl = _structural_sl(
        direction=side,
        zone_lo=primary.get("zone_lo"),
        zone_hi=primary.get("zone_hi"),
        price=price,
    )
    wide = widen_sl_to_atr_h1(entry=entry, sl=sl, direction=side, atr_h1=atr_h1) if entry and sl else {}
    if wide.get("ok"):
        sl = _f(wide.get("sl"))
    tp1 = _tp_from_rr(direction=side, entry=entry, sl=sl) if entry is not None and sl is not None else None
    rr = None
    if entry is not None and sl is not None and tp1 is not None and abs(entry - sl) > 0:
        rr = abs(tp1 - entry) / abs(entry - sl)

    atr_cls = classify_atr_day_used(day_used_pct)
    liq = sl_in_liquidity_pool(direction=side, sl=sl, candles=candles_h1 or candles_m15)
    alt_side = "SHORT" if side == "LONG" else "LONG"
    alt_ok = bool(alt.get("send_card") or (alt.get("n") or 0) >= 2)
    draft = {
        "symbol": str(symbol or "").upper(),
        "direction": side,
        "timeframe": timeframe,
        "send_card": bool(primary.get("send_card")),
        "confluence": primary,
        "alt_confluence": alt,
        "alternative": {
            "direction": alt_side,
            "send_card": bool(alt.get("send_card")),
            "n": alt.get("n") or 0,
            "grade": alt.get("grade") or "",
            "zone_lo": alt.get("zone_lo"),
            "zone_hi": alt.get("zone_hi"),
            "reason": alt.get("reason") or "",
            "eligible": alt_ok,
        },
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "rr": rr,
        "zone_lo": primary.get("zone_lo"),
        "zone_hi": primary.get("zone_hi"),
        "confirmation": primary.get("confirm_wait") or primary.get("confirms") or [],
        "invalidation": sl,
        "widened_to_atr": bool(wide.get("widened")),
        "atr": atr_cls,
        "liquidity": liq,
        "market_context": ctx,
        "reason": str(primary.get("reason") or ""),
    }
    return draft


def stance_pump_dump(pd: Any, *, lev_direction: str) -> Dict[str, Any]:
    ev = pd if isinstance(pd, dict) else {}
    connected = str(ev.get("reason") or "") != "DATA_UNAVAILABLE" and (
        "total_l" in ev or "total_s" in ev
    )
    return indicator_stance(
        lev_direction=lev_direction,
        indicator_direction=ev.get("direction"),
        connected=connected,
        signal=ev.get("signal"),
        reason="" if connected else str(ev.get("reason") or "NOT_CONNECTED"),
        source="ohlcv_port",
        extra={
            "total_l": ev.get("total_l"),
            "total_s": ev.get("total_s"),
            "signal": ev.get("signal"),
            "creates_enter": False,
        },
    )


def stance_ict_hunter(hunt: Any, *, lev_direction: str) -> Dict[str, Any]:
    ev = hunt if isinstance(hunt, dict) else {}
    connected = bool(ev.get("ok"))
    return indicator_stance(
        lev_direction=lev_direction,
        indicator_direction=ev.get("direction"),
        connected=connected,
        signal=bool(ev.get("signal")),
        reason="" if connected else str(ev.get("reason") or "NOT_CONNECTED"),
        source="ohlcv_port",
        extra={
            "score": ev.get("score"),
            "min_score": ev.get("min_score"),
            "patterns": ev.get("patterns") or [],
            "creates_enter": False,
        },
    )


def stance_channel(ch: Any, *, lev_direction: str, price: Any = None) -> Dict[str, Any]:
    ev = ch if isinstance(ch, dict) else {}
    connected = bool(ev.get("ok"))
    if not connected:
        return indicator_stance(
            lev_direction=lev_direction,
            connected=False,
            signal=False,
            reason=str(ev.get("data_status") or "NOT_CONNECTED"),
            source="ohlcv_port",
        )
    px = _f(price)
    lo, hi, mid = _f(ev.get("lower_end")), _f(ev.get("upper_end")), _f(ev.get("mid_end"))
    ind = ""
    fired = False
    why = "канал нейтральний — шар, не вхід"
    if px is not None and lo is not None and hi is not None and hi > lo:
        span = hi - lo
        if abs(px - lo) <= span * 0.08:
            ind, fired, why = "LONG", True, "ціна біля нижньої межі каналу"
        elif abs(px - hi) <= span * 0.08:
            ind, fired, why = "SHORT", True, "ціна біля верхньої межі каналу"
        elif mid is not None:
            why = "ціна всередині каналу"
    st = indicator_stance(
        lev_direction=lev_direction,
        indicator_direction=ind,
        connected=True,
        signal=fired,
        reason=why,
        source="ohlcv_port",
        extra={"slope": ev.get("slope"), "creates_enter": False, "signal": False},
    )
    # Канал ніколи не є сигналом входу, навіть як CONFIRM.
    st["signal"] = False
    st["extra"] = {**(st.get("extra") or {}), "creates_enter": False, "channel_signal": False}
    return st


def collect_indicator_stances(
    *,
    lev_direction: str,
    price: Any = None,
    candles_m5: Any = None,
    candles_m15: Any = None,
    candles_h1: Any = None,
    candles_d1: Any = None,
    pine_alerts: Any = None,
) -> Dict[str, Any]:
    m15 = candles_m15 if isinstance(candles_m15, list) else []
    m5 = candles_m5 if isinstance(candles_m5, list) else []
    h1 = candles_h1 if isinstance(candles_h1, list) else []
    d1 = candles_d1 if isinstance(candles_d1, list) else []
    pd_src = m15 if len(m15) >= 22 else (m5 if len(m5) >= 22 else m15)
    pd = evaluate_pump_dump(candles=pd_src, daily=d1)
    hunt_src = m15 if len(m15) >= 8 else h1
    hunt = evaluate_ict_hunter(candles=hunt_src, timeframe="M15", daily=d1)
    ch = regression_channel(h1 if len(h1) >= 12 else m15)
    alerts = pine_alerts if isinstance(pine_alerts, list) else []
    return {
        "pump_dump": stance_pump_dump(pd, lev_direction=lev_direction),
        "ict_hunter": stance_ict_hunter(hunt, lev_direction=lev_direction),
        "channel": stance_channel(ch, lev_direction=lev_direction, price=price),
        "raw": {"pump_dump": pd, "ict_hunter": hunt, "channel": ch},
        "pine_alerts": {
            "stance": STANCE_NOT_CONNECTED if not alerts else STANCE_NEUTRAL,
            "connected": bool(alerts),
            "creates_enter": False,
            "reason": "немає історичних TradingView alerts" if not alerts else f"alerts={len(alerts)}",
        },
    }


def _contradict_keys(stances: Dict[str, Any]) -> List[str]:
    hit = []
    for k in INDICATOR_KEYS:
        st = stances.get(k) if isinstance(stances.get(k), dict) else {}
        if st.get("stance") == STANCE_CONTRADICT:
            hit.append(k)
    return hit


def lev_conclusion_text(draft: Dict[str, Any], stances: Dict[str, Any], action: str) -> str:
    """Висновок Лева для картки — без переліку міток індикаторів."""
    side = str(draft.get("direction") or "")
    lo, hi = draft.get("zone_lo"), draft.get("zone_hi")
    z = ""
    if _f(lo) is not None and _f(hi) is not None:
        z = f"зона {_f(lo):.6g}–{_f(hi):.6g}"
    alt = draft.get("alternative") if isinstance(draft.get("alternative"), dict) else {}
    parts = [f"Лев: {side} {z}".strip()]
    conf = draft.get("confluence") if isinstance(draft.get("confluence"), dict) else {}
    tags = conf.get("tags") or []
    if tags:
        names = [TAG_UA.get(str(t), str(t)) for t in tags[:4]]
        parts.append("структура: " + ", ".join(names))
    contra = _contradict_keys(stances)
    missing = [
        k
        for k in INDICATOR_KEYS
        if (stances.get(k) or {}).get("stance") == STANCE_NOT_CONNECTED
    ]
    confirms = [
        k
        for k in INDICATOR_KEYS
        if (stances.get(k) or {}).get("stance") == STANCE_CONFIRM
    ]
    if action == ACTION_WAIT and contra:
        parts.append("розбіжність з індикатором — не підганяю сценарій, чекаю умову")
    elif confirms:
        parts.append("індикатори підсилюють висновок, не керують ним")
    elif missing == list(INDICATOR_KEYS):
        parts.append("індикатори не підключені — рішення Лева без них")
    else:
        parts.append("індикатори нейтральні або неповні")
    if alt.get("eligible"):
        parts.append(f"альтернатива: {alt.get('direction')}")
    liq = draft.get("liquidity") if isinstance(draft.get("liquidity"), dict) else {}
    if liq.get("in_pool"):
        parts.append("стоп у пулі ліквідності — без довільного розширення")
    return ". ".join(p for p in parts if p).strip()


_HTF_MARKS = ("H1", "H4", "D1", "1H", "4H", "1D", "W1", "HTF", "FIB_H4", "РІВЕНЬ D")


def has_htf_grounds(confluence: Any) -> bool:
    """HTF-підстави лише з тегів/зони збігів, не з порожнього макро."""
    conf = confluence if isinstance(confluence, dict) else {}
    parts = [str(conf.get("zone_line") or ""), " ".join(str(t) for t in (conf.get("tags") or []))]
    cluster = conf.get("cluster") if isinstance(conf.get("cluster"), dict) else {}
    for m in cluster.get("members") or conf.get("zones") or []:
        if isinstance(m, dict):
            parts.append(str(m.get("tf") or ""))
            parts.append(str(m.get("tag") or m.get("label") or ""))
    blob = " ".join(parts).upper()
    return any(mark in blob for mark in _HTF_MARKS)


def invalidation_defined(*, sl: Any = None, cancel_level: Any = None, invalidate_line: str = "") -> bool:
    inv = str(invalidate_line or "").lower()
    if "не визначено" in inv or "заблокован" in inv:
        return False
    return _f(sl) is not None or _f(cancel_level) is not None


def scenario_ready_to_present(
    *,
    confluence: Any = None,
    sl: Any = None,
    cancel_level: Any = None,
    invalidate_line: str = "",
    lev_note: str = "",
    why_line: str = "",
) -> Dict[str, Any]:
    """Готовий до виконання ≠ WATCHING з тестовими рівнями."""
    note = f"{lev_note} {why_line}".upper()
    demo = "DEMO" in note or "OFFLINE" in note
    htf = has_htf_grounds(confluence)
    inv = invalidation_defined(sl=sl, cancel_level=cancel_level, invalidate_line=invalidate_line)
    why_una = "DATA_UNAVAILABLE" in note
    if demo:
        return {
            "ready": False,
            "demo": True,
            "reason": "DEMO/OFFLINE — приклад розрахунку, не Live",
        }
    if why_una or not htf:
        return {"ready": False, "demo": False, "reason": "немає HTF-підстав — не формую готову рекомендацію"}
    if not inv:
        return {"ready": False, "demo": False, "reason": "немає інвалідації — сценарій не готовий до виконання"}
    return {"ready": True, "demo": False, "reason": "ok"}


def finalize_lev(
    draft: Dict[str, Any],
    stances: Optional[Dict[str, Any]] = None,
    *,
    hunter_only_enter: bool = False,
    risk_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """ENTER лише якщо є власний сетап Лева. Індикатор не відкриває угоду."""
    st = stances or {}
    send_lev = bool(draft.get("send_card"))
    action = ACTION_SKIP
    recheck = ""
    reason = str(draft.get("reason") or "")
    atr = draft.get("atr") if isinstance(draft.get("atr"), dict) else {}
    liq = draft.get("liquidity") if isinstance(draft.get("liquidity"), dict) else {}
    rr = _f(draft.get("rr"))
    sl = _f(draft.get("sl"))
    entry = _f(draft.get("entry"))
    tp1 = _f(draft.get("tp1"))

    # Індикатор ніколи не створює ENTER, навіть якщо hunter_only_enter спробували.
    if hunter_only_enter and not send_lev:
        action = ACTION_SKIP
        reason = "Hunter не має права самостійно створити ENTER"
    elif not send_lev:
        n = int((draft.get("confluence") or {}).get("n") or 0)
        action = ACTION_WATCHING if n >= 1 else ACTION_SKIP
        reason = reason or "немає власного сетапу Лева"
    elif atr.get("gerchik_entry_blocked") or atr.get("t0_entry_blocked"):
        action = ACTION_SKIP
        reason = str(atr.get("label") or "ATR veto")
        recheck = "після зниження day_used або нової D1 — перерахунок, не авто-вхід"
    elif entry is None or sl is None or tp1 is None:
        action = ACTION_SKIP
        reason = "немає entry/SL/TP1 зі структури"
    elif rr is not None and rr + 1e-12 < MIN_RR:
        action = ACTION_SKIP
        reason = f"RR {rr:.2f} < {MIN_RR} — структурний стоп не розширюємо"
    elif liq.get("in_pool"):
        action = ACTION_WAIT
        reason = str(liq.get("reason") or "ліквідність біля стопа")
        recheck = "після sweep/reclaim або ретесту зони, той самий стоп"
    else:
        contra = _contradict_keys(st)
        if contra:
            action = ACTION_WAIT
            reason = "суперечність з індикатором — не підганяю аналіз"
            recheck = (
                "перевірити ТФ, час сигналу, близьку ліквідність і простір до TP; "
                "повтор після підтвердження на LTF або зникнення розбіжності"
            )
        else:
            ready = scenario_ready_to_present(
                confluence=draft.get("confluence"),
                sl=sl,
                cancel_level=draft.get("invalidation") if draft.get("invalidation") != sl else sl,
                lev_note=str(draft.get("lev_note") or ""),
            )
            if not ready.get("ready"):
                action = ACTION_WATCHING
                reason = str(ready.get("reason") or "сценарій не готовий до виконання")
            else:
                action = ACTION_SEND
                reason = "власний сетап Лева придатний; індикатори аргумент"

    # Opt-in integration: the independent officer may veto, never promote.
    # Existing callers retain their historical analyst-only behavior until
    # portfolio exposure, verified feed health and execution quality are wired.
    risk_review = None
    if risk_context is not None:
        rc = dict(risk_context)
        risk_review = review_plan(
            {"direction": draft.get("direction"), "entry": entry, "sl": sl,
             "tp1": tp1, "quantity": rc.get("quantity")},
            equity_usdt=rc.get("equity_usdt"),
            max_risk_pct=rc.get("max_risk_pct"),
            existing_risk_usdt=rc.get("existing_risk_usdt", 0),
            max_portfolio_risk_pct=rc.get("max_portfolio_risk_pct", 2),
            data_quality=rc.get("data_quality", "UNAVAILABLE"),
            context_quality=rc.get("context_quality", "UNAVAILABLE"),
            execution_quality=rc.get("execution_quality", "UNAVAILABLE"),
        )
        if action == ACTION_SEND and not risk_review["approved_for_review"]:
            action = ACTION_WAIT
            reason = "незалежний ризик-контроль: " + ", ".join(risk_review["reasons"])
            recheck = "оновити дані, експозицію та план; не відкривати ордер"
    note = lev_conclusion_text(draft, st, action)
    return {
        "action": action,
        "send": action == ACTION_SEND,
        "continue_scan": True,
        "reason": reason,
        "recheck": recheck,
        "lev_note": note,
        "draft": draft,
        "stances": st,
        "direction": draft.get("direction"),
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "confluence": draft.get("confluence"),
        "alternative": draft.get("alternative"),
        "db_status": (
            "NEAR"
            if action in (ACTION_WAIT, ACTION_WATCHING)
            else ("ACTIVE" if action == ACTION_SEND else "")
        ),
        "creates_enter_from_indicator": False,
        "risk_review": risk_review,
    }


def lev_cycle(
    *,
    symbol: str,
    price: Any = None,
    timeframe: str = "H1",
    candles_m5: Any = None,
    candles_m15: Any = None,
    candles_h1: Any = None,
    candles_h4: Any = None,
    candles_d1: Any = None,
    candles_w: Any = None,
    candles_ltf: Any = None,
    atr_h1: Any = None,
    day_used_pct: Any = None,
    now_ts: Any = None,
    candidates_long: Any = None,
    candidates_short: Any = None,
    market_context: Optional[Dict[str, Any]] = None,
    pine_alerts: Any = None,
    stances: Optional[Dict[str, Any]] = None,
    risk_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Повний цикл: сценарій Лева, потім індикатори, потім рішення."""
    draft = draft_lev_scenario(
        symbol=symbol,
        timeframe=timeframe,
        candles_m15=candles_m15,
        candles_h1=candles_h1,
        candles_h4=candles_h4,
        candles_d1=candles_d1,
        candles_w=candles_w,
        candles_ltf=candles_ltf if candles_ltf is not None else candles_m5,
        price=price,
        atr_h1=atr_h1,
        day_used_pct=day_used_pct,
        now_ts=now_ts,
        candidates_long=candidates_long,
        candidates_short=candidates_short,
        market_context=market_context,
    )
    st = stances
    if st is None:
        st = collect_indicator_stances(
            lev_direction=str(draft.get("direction") or ""),
            price=price,
            candles_m5=candles_m5,
            candles_m15=candles_m15,
            candles_h1=candles_h1,
            candles_d1=candles_d1,
            pine_alerts=pine_alerts,
        )
    return finalize_lev(draft, st, risk_context=risk_context)
