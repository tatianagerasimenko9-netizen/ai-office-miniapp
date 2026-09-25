"""T8: незалежний розбір сигналу зовнішнього бота.

Оригінал зберігається без змін. Вердикт офісу — аналітика, не ордер.
ПІДТВЕРДЖЕНО / УМОВНО ПІДТВЕРДЖЕНО / КОРЕКЦІЯ / ВІДХИЛЕНО.
Угода лише через /position.
"""
from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from office_atr_policy import classify_atr_day_used
from office_level_parse import parse_signal_levels_from_text
from office_market_data import SIGNAL_THRESHOLD
from office_market_state import scanner_signal_blocked
from office_radar import MIN_RR, card_levels, detect_sweep_from_candles, m15_confirmation
from office_session_radar import independent_flip_ok, session_at_utc
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT
from office_level_scalp import infer_trade_mode, parse_bot_card_overlay, rr_after_costs

# Вердикти — дані для Лева, не шаблон його репліки.
VERDICT_CONFIRMED = "ПІДТВЕРДЖЕНО"
VERDICT_CONDITIONAL = "УМОВНО ПІДТВЕРДЖЕНО"
VERDICT_CORRECTION = "КОРЕКЦІЯ"
VERDICT_REJECTED = "ВІДХИЛЕНО"

KIND_EXTERNAL = "external_review"
LEVEL_DRIFT_PCT = 0.0018
CHASE_PCT = 0.02


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    return x


def _now(ts: Any = None) -> datetime:
    if isinstance(ts, datetime):
        dt = ts
    elif ts:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rr(entry: Optional[float], sl: Optional[float], tp: Optional[float]) -> Optional[float]:
    e, s, t = _f(entry), _f(sl), _f(tp)
    if e is None or s is None or t is None:
        return None
    risk = abs(e - s)
    if risk <= 0:
        return None
    return abs(t - e) / risk


def _norm_symbol(raw: str) -> str:
    up = str(raw or "").upper().strip()
    if up in ("XAU", "XAUUSD", "GOLD", "XAUUSDT"):
        return "XAUUSDT"
    if up.endswith("USDT"):
        return up
    if up.isalpha() and 2 <= len(up) <= 10:
        return f"{up}USDT"
    return up


def ingest_external_signal(
    *,
    text: str,
    msg_id: Any = 0,
    received_at: Any = None,
    source: str = "external_bot",
) -> Dict[str, Any]:
    """Знімок оригіналу. Подальший аналіз цей dict не мутує."""
    src = str(text or "")
    levels = parse_signal_levels_from_text(src)
    overlay = parse_bot_card_overlay(src)
    up = src.upper()
    symbol = str(overlay.get("symbol") or "")
    m = re.search(r"\b[A-Z0-9]{2,15}USDT\b", up)
    if m:
        symbol = m.group(0)
    elif re.search(r"\bXAU(?:USD)?\b|\bGOLD\b", up):
        symbol = "XAUUSDT"
    direction = str(overlay.get("direction") or "")
    if any(t in up for t in ("SHORT", "SELL", "ШОРТ", "ПРОДАЖ", "🔴")):
        direction = "SHORT"
    elif any(t in up for t in ("LONG", "BUY", "ЛОНГ", "КУПІВЛ", "🟢")):
        direction = "LONG"
    if not direction:
        direction = str(overlay.get("direction") or "")
    entry = _f(levels.get("entry_low")) or _f(overlay.get("entry"))
    entry_high = _f(levels.get("entry_high")) or _f(overlay.get("entry"))
    if entry is not None and entry_high is not None:
        entry_mid = (entry + entry_high) / 2.0
    else:
        entry_mid = entry
    received = _now(received_at)
    return {
        "signal_id": f"ext-{int(msg_id or 0)}-{int(received.timestamp())}",
        "source": source,
        "received_at": received.isoformat(),
        "raw_text": src[:4000],
        "symbol": _norm_symbol(symbol),
        "direction": direction,
        "entry": entry_mid,
        "entry_low": _f(levels.get("entry_low")) or entry_mid,
        "entry_high": _f(levels.get("entry_high")) or entry_mid,
        "sl": _f(levels.get("sl")) or _f(overlay.get("sl")),
        "tp1": _f(levels.get("tp1")) or _f(overlay.get("tp1")),
        "tp2": _f(levels.get("tp2")) or _f(overlay.get("tp2")),
        "tp3": _f(overlay.get("tp3")),
        "add_on": _f(overlay.get("add_on")),
        "timeframe": overlay.get("timeframe") or "",
        "style": overlay.get("style") or "",
        "mode": overlay.get("mode") or infer_trade_mode(overlay.get("timeframe"), overlay.get("style")),
        "kind": KIND_EXTERNAL,
        "opens_position": False,
    }


def persist_external_original(db_path: str, original: Dict[str, Any]) -> None:
    """Лише подія. trade_journal не чіпаємо."""
    from office_bridge import log_event

    snap = deepcopy(original)
    snap["opens_position"] = False
    log_event(
        db_path,
        "EXTERNAL_SIGNAL_RECEIVED",
        snap,
        str(snap.get("signal_id") or ""),
    )


@dataclass
class ExternalReview:
    verdict: str
    original: Dict[str, Any]
    reasons: list[str] = field(default_factory=list)
    office_plan: Optional[Dict[str, Any]] = None
    watching_condition: str = ""
    lifecycle_hint: str = "WATCHING"
    opens_position: bool = False
    kind: str = KIND_EXTERNAL
    extras: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "original": deepcopy(self.original),
            "reasons": list(self.reasons),
            "office_plan": deepcopy(self.office_plan) if self.office_plan else None,
            "watching_condition": self.watching_condition,
            "lifecycle_hint": self.lifecycle_hint,
            "opens_position": False,
            "kind": self.kind,
            "extras": dict(self.extras),
        }


def _levels_drift(bot_v: Optional[float], office_v: Optional[float], px: float) -> bool:
    a, b = _f(bot_v), _f(office_v)
    if a is None or b is None or px <= 0:
        return a is None or b is None
    return abs(a - b) / px > LEVEL_DRIFT_PCT


def review_external_signal(
    original: Dict[str, Any],
    *,
    market: Optional[Dict[str, Any]] = None,
) -> ExternalReview:
    """Незалежна перевірка. Оригінал копіюється, не підганяється."""
    orig = deepcopy(original or {})
    orig["opens_position"] = False
    mkt = dict(market or {})
    reasons: list[str] = []
    extras: Dict[str, Any] = {
        "edge_threshold": SIGNAL_THRESHOLD,
        "atr_t0": ATR_DAY_USED_ENTRY_BLOCK_PCT,
        "btc_context_only": True,
    }

    symbol = str(orig.get("symbol") or "")
    direction = str(orig.get("direction") or "").upper()
    if not symbol or direction not in ("LONG", "SHORT"):
        return ExternalReview(
            verdict=VERDICT_REJECTED,
            original=orig,
            reasons=["немає символу або напрямку в оригіналі бота"],
            lifecycle_hint="INVALIDATED",
            extras=extras,
        )

    if scanner_signal_blocked(mkt.get("bot_action")):
        return ExternalReview(
            verdict=VERDICT_REJECTED,
            original=orig,
            reasons=["bot_action=BLOCKED — T5, сигнал бота не підганяємо"],
            lifecycle_hint="EXPIRED",
            extras=extras,
        )

    px = _f(mkt.get("price"))
    htf = str(mkt.get("htf_bias") or "").upper()
    edge = mkt.get("edge_score")
    try:
        edge_f = float(edge) if edge is not None and edge != "" else None
    except (TypeError, ValueError):
        edge_f = None
    atr = classify_atr_day_used(mkt.get("day_used_pct"))
    extras["atr"] = atr
    sweep = mkt.get("sweep") if isinstance(mkt.get("sweep"), dict) else detect_sweep_from_candles(
        mkt.get("sweep_candles") or []
    )
    structure_sl = _f(mkt.get("structure_sl")) or _f(sweep.get("sweep_level"))
    m15_ok = bool(mkt.get("m15_ok"))
    m5_ok = bool(mkt.get("m5_ok"))
    if not m15_ok and mkt.get("m15_candles") and structure_sl:
        m15_ok = m15_confirmation(mkt.get("m15_candles") or [], direction=direction, level=float(structure_sl))
    if not m5_ok and mkt.get("m5_candles") and structure_sl:
        m5_ok = m15_confirmation(mkt.get("m5_candles") or [], direction=direction, level=float(structure_sl))
    session = str(mkt.get("session") or session_at_utc(_now(mkt.get("utc_now"))))
    liquidity_ok = mkt.get("liquidity_ok")
    struct_ok = mkt.get("structure_ok")
    stale = bool(mkt.get("stale"))

    if htf in ("LONG", "SHORT") and htf != direction:
        if not independent_flip_ok(
            previous_direction=htf,
            new_direction=direction,
            sweep=sweep or {},
            m5_ok=m5_ok or m15_ok,
            m1_ok=bool(mkt.get("m1_ok")),
            stop_hit=bool(mkt.get("stop_hit")),
        ):
            return ExternalReview(
                verdict=VERDICT_REJECTED,
                original=orig,
                reasons=[
                    f"напрямок бота {direction} суперечить старшому ТФ {htf} без незалежного підтвердження"
                ],
                lifecycle_hint="INVALIDATED",
                extras=extras,
            )

    if struct_ok is False:
        return ExternalReview(
            verdict=VERDICT_REJECTED,
            original=orig,
            reasons=["структура інструмента зламана — старий сигнал бота не тримаємо"],
            lifecycle_hint="INVALIDATED",
            extras=extras,
        )

    bot_entry = _f(orig.get("entry"))
    bot_sl = _f(orig.get("sl"))
    bot_tp = _f(orig.get("tp1"))
    bot_rr = _rr(bot_entry, bot_sl, bot_tp)

    if stale or (px and bot_sl and bot_entry):
        if direction == "LONG" and px is not None and bot_sl is not None and px < bot_sl:
            return ExternalReview(
                verdict=VERDICT_REJECTED,
                original=orig,
                reasons=["ціна вже за стопом бота — сигнал прострочений"],
                lifecycle_hint="EXPIRED",
                extras=extras,
            )
        if direction == "SHORT" and px is not None and bot_sl is not None and px > bot_sl:
            return ExternalReview(
                verdict=VERDICT_REJECTED,
                original=orig,
                reasons=["ціна вже за стопом бота — сигнал прострочений"],
                lifecycle_hint="EXPIRED",
                extras=extras,
            )

    chase = False
    if px is not None and bot_entry is not None and px > 0:
        dist = abs(px - bot_entry) / px
        if dist > CHASE_PCT:
            chase = True
            reasons.append("ціна далеко від entry бота — не женемось")

    confirmed_tf = bool(m15_ok or m5_ok)
    need_sweep = not (sweep.get("ssl_sweep") or sweep.get("bsl_sweep"))
    session_wait = str(mkt.get("need_session") or "")
    if session_wait and session != session_wait and session != "london_ny_overlap":
        reasons.append(f"чекаємо сесію {session_wait}, зараз {session}")

    office_plan = None
    entry_px = px or bot_entry
    if entry_px and structure_sl:
        office_plan = card_levels(
            direction=direction,
            entry=float(entry_px),
            structure_sl=float(structure_sl),
            rr=max(MIN_RR, 2.0),
        )
        if bot_tp and office_plan.get("entry") and office_plan.get("sl"):
            # Другий тейк — 1.5× до TP1 офісу, не копія бота.
            e = float(office_plan["entry"])
            t1 = float(office_plan["tp"])
            office_plan["tp1"] = t1
            office_plan["tp2"] = e + (t1 - e) * 1.6 if direction == "LONG" else e - (e - t1) * 1.6
        office_plan["rr"] = float(office_plan.get("rr") or 0)
        if office_plan["rr"] < MIN_RR:
            return ExternalReview(
                verdict=VERDICT_REJECTED,
                original=orig,
                reasons=[f"RR офісу {office_plan['rr']} < {MIN_RR}"],
                office_plan=office_plan,
                lifecycle_hint="INVALIDATED",
                extras=extras,
            )
        if str(orig.get("mode") or "") == "scalp":
            net = rr_after_costs(
                entry=office_plan.get("entry"),
                sl=office_plan.get("sl"),
                tp=office_plan.get("tp1") or office_plan.get("tp"),
            )
            office_plan["rr_net"] = net
            if net is not None and net < MIN_RR:
                return ExternalReview(
                    verdict=VERDICT_CONDITIONAL,
                    original=orig,
                    reasons=["скальп: після комісій і прослизання RR нижче порогу — не копіюємо цілі бота"],
                    office_plan=office_plan,
                    watching_condition="чекаємо ширший внутрішньоденний рівень або кращий RR нетто",
                    lifecycle_hint="WATCHING",
                    extras=extras,
                )

    if atr.get("t0_entry_blocked") or atr.get("gerchik_entry_blocked"):
        reasons.append(str(atr.get("label") or "ATR блок конкретного входу"))
        return ExternalReview(
            verdict=VERDICT_CONDITIONAL,
            original=orig,
            reasons=reasons,
            office_plan=office_plan,
            watching_condition="ATR запас ходу; пошук сценарію триває, вхід бота не копіюємо",
            lifecycle_hint="WATCHING",
            extras=extras,
        )

    if edge_f is not None and edge_f < SIGNAL_THRESHOLD:
        reasons.append(f"Edge {edge_f:.0f} < {SIGNAL_THRESHOLD} — не підганяємо висновок бота")
        return ExternalReview(
            verdict=VERDICT_CONDITIONAL,
            original=orig,
            reasons=reasons,
            office_plan=office_plan,
            watching_condition="чекаємо якісніший край / підтвердження",
            lifecycle_hint="WATCHING",
            extras=extras,
        )

    waiting = bool(need_sweep or not confirmed_tf or session_wait or chase or liquidity_ok is False)
    if waiting:
        cond = mkt.get("waiting_for") or (
            "свіп ліквідності, повернення за рівень і BOS на M5/M15"
        )
        if session_wait:
            cond = f"{cond}; сесія {session_wait}"
        reasons.append("напрямок припустимий, підтвердження малого ТФ ще немає")
        return ExternalReview(
            verdict=VERDICT_CONDITIONAL,
            original=orig,
            reasons=reasons,
            office_plan=office_plan,
            watching_condition=cond,
            lifecycle_hint="WATCHING",
            extras=extras,
        )

    if office_plan and (
        _levels_drift(bot_entry, office_plan.get("entry"), float(entry_px or 1))
        or _levels_drift(bot_sl, office_plan.get("sl"), float(entry_px or 1))
        or (bot_tp is not None and _levels_drift(bot_tp, office_plan.get("tp"), float(entry_px or 1)))
        or bot_sl is None
        or bot_rr is None
        or bot_rr < MIN_RR
    ):
        reasons.append("напрямок обґрунтований; рівні бота не на структурі — офіс дає свій план")
        return ExternalReview(
            verdict=VERDICT_CORRECTION,
            original=orig,
            reasons=reasons,
            office_plan=office_plan,
            lifecycle_hint="ZONE_REACHED",
            extras=extras,
        )

    reasons.append("напрямок, структура, RR, ATR і Edge збігаються з правилами офісу")
    return ExternalReview(
        verdict=VERDICT_CONFIRMED,
        original=orig,
        reasons=reasons,
        office_plan=office_plan or {
            "entry": bot_entry,
            "sl": bot_sl,
            "tp": bot_tp,
            "tp1": bot_tp,
            "rr": bot_rr,
        },
        lifecycle_hint="CONFIRMED",
        extras=extras,
    )


def follow_up_external_review(
    previous: ExternalReview,
    *,
    market: Optional[Dict[str, Any]] = None,
) -> ExternalReview:
    """Повторний розрахунок від того самого оригіналу після свіпу/зламу."""
    orig = deepcopy(previous.original)
    mkt = dict(market or {})
    if mkt.get("scenario_broken") or mkt.get("structure_ok") is False:
        return ExternalReview(
            verdict=VERDICT_REJECTED,
            original=orig,
            reasons=["ринок зламав сценарій — старий сигнал бота скасовано"],
            lifecycle_hint="INVALIDATED",
            extras={"from_follow_up": True},
        )
    nxt = review_external_signal(orig, market=mkt)
    nxt.extras["from_follow_up"] = True
    return nxt


def format_external_review(rev: ExternalReview) -> str:
    """Факти картки. Не репліка Лева."""
    o = rev.original
    lines = [
        f"Розбір зовнішнього сигналу · {o.get('symbol') or '—'} {o.get('direction') or '—'}",
        f"Отримано: {o.get('received_at') or '—'}",
        f"Оригінал бота: entry={o.get('entry')} SL={o.get('sl')} TP1={o.get('tp1')} TP2={o.get('tp2')}",
        f"Вердикт офісу: {rev.verdict}",
        "Це аналітика, не команда купити/продати. Угода лише через /position.",
    ]
    if rev.office_plan:
        p = rev.office_plan
        lines.append(
            "План офісу: "
            f"entry={p.get('entry')} SL={p.get('sl')} "
            f"TP1={p.get('tp1') or p.get('tp')} TP2={p.get('tp2')} RR={p.get('rr')}"
        )
    if rev.watching_condition:
        lines.append(f"Умова супроводу: {rev.watching_condition}")
    for r in rev.reasons:
        lines.append(f"— {r}")
    return "\n".join(lines)
