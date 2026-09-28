"""Risk Officer у робочому циклі Лева: shadow за замовчуванням, veto лише за прапорцем.

Контекст ризику збирається тільки з перевірюваних джерел; невідоме лишається
невідомим (None / UNAVAILABLE), і review_plan() тоді fail-closed.

- equity: OFFICE_DEPO_USDT — це налаштування, а не підтверджений баланс біржі;
  позначається source="config".
- існуючий ризик: лише підтверджені /position з trade_journal, у яких є
  entry, SL і кількість. Якщо хоч одна відкрита позиція без кількості або БД
  недоступна — ризик невідомий.
- дані: свіжість останньої LTF-свічки через office_feed_quality.
- виконання: стакану/спреду в офісі немає → UNAVAILABLE.

Ордерів не створює. Telegram не надсилає.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from office_feed_quality import assess_feed
from office_position_size import RISK_PCT_BASE, depo_usdt, plan_position_size

ENFORCE_ENV = "OFFICE_RISK_OFFICER_ENFORCE"
SHADOW_EVENT = "RISK_SHADOW_REVIEW"
VETO_EVENT = "RISK_VETO"
MAX_PORTFOLIO_RISK_PCT = 2.0
LTF_MAX_AGE_SECONDS = 900


def enforce_enabled() -> bool:
    return os.getenv(ENFORCE_ENV, "").strip() == "1"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def existing_risk_usdt(db_path: str) -> Dict[str, Any]:
    """Сума |entry−SL|×qty підтверджених OPEN /position. Невідоме ≠ 0."""
    from office_bridge import _fetchall, is_confirmed_position_row

    try:
        rows = _fetchall(
            db_path,
            """
            SELECT trade_id, entry_price, stop_loss, position_qty, entry_reason, setup_name
            FROM trade_journal
            WHERE status = 'OPEN'
            """,
            (),
        )
    except Exception as exc:
        return {"value": None, "status": "UNAVAILABLE", "reason": f"trade_journal: {type(exc).__name__}"}
    total = 0.0
    unknown: List[str] = []
    n = 0
    for tid, entry, sl, qty, reason, setup in rows or []:
        if not is_confirmed_position_row(reason, setup, tid):
            continue
        n += 1
        e, s, q = _f(entry), _f(sl), _f(qty)
        if e is None or s is None or q is None:
            unknown.append(str(tid))
            continue
        total += abs(e - s) * q
    if unknown:
        return {"value": None, "status": "UNAVAILABLE", "reason": "позиції без entry/SL/qty: " + ", ".join(unknown[:5]), "open": n}
    return {"value": total, "status": "OK", "reason": "підтверджені /position", "open": n}


def _last_ts(candles: Any) -> Optional[str]:
    if not isinstance(candles, list) or not candles:
        return None
    last = candles[-1] or {}
    ts = last.get("ts") if isinstance(last, dict) else None
    return str(ts) if ts else None


def build_risk_context(
    *,
    db_path: str,
    symbol: str,
    direction: str,
    entry: Any,
    sl: Any,
    candles_ltf: Any = None,
    market_context: Optional[Dict[str, Any]] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now_utc or datetime.now(timezone.utc)
    equity = depo_usdt()
    size = plan_position_size(entry=entry, sl=sl, depo=equity, direction=direction, symbol=symbol)
    qty = None
    e = _f(entry)
    if size.get("size_usdt") and e:
        qty = float(size["size_usdt"]) / e
    feed = assess_feed(
        {"kind": "ohlcv", "source": "binance_futures", "observed_at": _last_ts(candles_ltf), "complete": bool(_last_ts(candles_ltf))},
        now_utc=now,
        max_age_seconds=LTF_MAX_AGE_SECONDS,
    )
    mc = market_context or {}
    ctx_ok = bool(mc) and str(mc.get("data_status") or "").upper() not in ("DATA_UNAVAILABLE", "UNAVAILABLE", "")
    ex = existing_risk_usdt(db_path)
    return {
        "equity_usdt": equity,
        "equity_source": "config:OFFICE_DEPO_USDT" if equity is not None else None,
        "max_risk_pct": RISK_PCT_BASE * 100.0,
        "quantity": qty,
        "existing_risk_usdt": ex["value"] if ex["value"] is not None else float("nan"),
        "existing_risk": ex,
        "max_portfolio_risk_pct": MAX_PORTFOLIO_RISK_PCT,
        "data_quality": feed["quality"],
        "data_reasons": feed["reasons"],
        "context_quality": "OK" if ctx_ok else "UNAVAILABLE",
        "execution_quality": "UNAVAILABLE",
        "execution_reason": "немає перевіреного стакану/спреду",
    }


def apply_risk_officer(
    cycle: Dict[str, Any],
    *,
    db_path: str,
    symbol: str,
    candles_ltf: Any = None,
    market_context: Optional[Dict[str, Any]] = None,
    enforce: Optional[bool] = None,
    now_utc: Optional[datetime] = None,
    log: bool = True,
) -> Dict[str, Any]:
    """Перевіряє лише потенційний SEND. Shadow: рішення не змінюється, review у журнал.

    Enforce: той самий finalize_lev(risk_context=…) — veto переводить SEND у WAIT,
    ніколи не підвищує WAIT/SKIP до SEND.
    """
    if not cycle.get("send"):
        return cycle
    enf = enforce_enabled() if enforce is None else bool(enforce)
    ctx = build_risk_context(
        db_path=db_path,
        symbol=symbol,
        direction=str(cycle.get("direction") or ""),
        entry=cycle.get("entry"),
        sl=cycle.get("sl"),
        candles_ltf=candles_ltf,
        market_context=market_context,
        now_utc=now_utc,
    )
    from office_lev_verdict import finalize_lev

    reviewed = finalize_lev(cycle.get("draft") or {}, cycle.get("stances") or {}, risk_context=ctx)
    review = reviewed.get("risk_review") or {}
    approved = bool(review.get("approved_for_review"))
    out = reviewed if enf else {**cycle, "risk_review": review}
    out = {**out, "risk_mode": "enforce" if enf else "shadow", "risk_context": _public_ctx(ctx)}
    if log and db_path:
        try:
            from office_bridge import log_event

            log_event(
                db_path,
                VETO_EVENT if (enf and not approved) else SHADOW_EVENT,
                {
                    "symbol": str(symbol or "").upper(),
                    "direction": cycle.get("direction"),
                    "mode": out["risk_mode"],
                    "approved_for_review": approved,
                    "would_veto": not approved,
                    "reasons": review.get("reasons"),
                    "estimated_risk_usdt": review.get("estimated_risk_usdt"),
                    "context": _public_ctx(ctx),
                    "order_authorized": False,
                },
                signal_id=str(cycle.get("scenario_id") or ""),
            )
        except Exception as exc:
            print(f"[risk] journal write failed: {type(exc).__name__}: {exc}")
    return out


def _public_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ex = ctx.get("existing_risk") or {}
    return json.loads(json.dumps({
        "equity_source": ctx.get("equity_source"),
        "max_risk_pct": ctx.get("max_risk_pct"),
        "quantity_known": ctx.get("quantity") is not None,
        "existing_risk_status": ex.get("status"),
        "existing_risk_reason": ex.get("reason"),
        "data_quality": ctx.get("data_quality"),
        "data_reasons": ctx.get("data_reasons"),
        "context_quality": ctx.get("context_quality"),
        "execution_quality": ctx.get("execution_quality"),
    }, default=str))
