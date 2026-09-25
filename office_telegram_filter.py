"""T8: фільтр Telegram — аналітика всередині, у чат лише придатний сетап.

3% — мінімальний очікуваний рух entry→TP1 для стандартного алерту, не чистий PnL
і не ATR/Edge. Не можна малювати дальній TP, щоб натягнути 3%.
CONFIRMED у коді ≠ автоматична розсилка.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from office_radar import MIN_RR

KIND_ALERT = "telegram_opportunity"
# Стрічка Telegram, не торговий поріг ATR 80/90 і не Edge 85.
MIN_ALERT_MOVE_PCT = 3.0
ALERT_COOLDOWN_SEC = 4 * 3600


def format_px(value: Any) -> str:
    """Читабельна ціна без float-сміття і без 'None'."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return ""
    if x <= 0 or x != x:
        return ""
    if x >= 100:
        s = f"{x:.2f}"
    elif x >= 1:
        s = f"{x:.4f}"
    else:
        s = f"{x:.6f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def format_level_span(low: Any, high: Any) -> str:
    a, b = format_px(low), format_px(high)
    if not a and not b:
        return ""
    if not b or a == b:
        return a
    return f"{a}–{b}"


def move_pct_to_tp(*, entry: Any, tp: Any) -> Optional[float]:
    try:
        e = float(entry)
        t = float(tp)
    except (TypeError, ValueError):
        return None
    if e <= 0:
        return None
    return abs(t - e) / e * 100.0


def alert_decision(
    *,
    status: str,
    entry: Any,
    sl: Any,
    tp1: Any,
    rr_net: Any,
    chase: bool = False,
    quote_stale: bool = False,
    liquid_enough: bool = True,
) -> Dict[str, Any]:
    """Чи варто показувати Тетяні. Аналіз у коді може лишатися CONFIRMED."""
    st = str(status or "").upper()
    if st != "CONFIRMED":
        return {
            "send": False,
            "reason": "не CONFIRMED — у стрічку не кладемо внутрішній WATCHING/INSIDE",
            "kind": KIND_ALERT,
            "min_move_pct": MIN_ALERT_MOVE_PCT,
        }
    if chase or quote_stale or not liquid_enough:
        return {
            "send": False,
            "reason": "ціна/ліквідність не для алерту",
            "kind": KIND_ALERT,
            "min_move_pct": MIN_ALERT_MOVE_PCT,
        }
    if not format_px(entry) or not format_px(sl) or not format_px(tp1):
        return {
            "send": False,
            "reason": "немає повного плану entry/SL/TP1",
            "kind": KIND_ALERT,
            "min_move_pct": MIN_ALERT_MOVE_PCT,
        }
    move = move_pct_to_tp(entry=entry, tp=tp1)
    if move is None or move + 1e-12 < MIN_ALERT_MOVE_PCT:
        return {
            "send": False,
            "reason": (
                f"до найближчої цілі {move if move is not None else 'н/д'}% "
                f"< {MIN_ALERT_MOVE_PCT:.0f}% — не натягуємо дальній TP"
            ),
            "kind": KIND_ALERT,
            "min_move_pct": MIN_ALERT_MOVE_PCT,
            "move_pct": move,
        }
    try:
        net = float(rr_net) if rr_net is not None else None
    except (TypeError, ValueError):
        net = None
    if net is None or net < MIN_RR:
        return {
            "send": False,
            "reason": f"RR після витрат {net} < {MIN_RR}",
            "kind": KIND_ALERT,
            "min_move_pct": MIN_ALERT_MOVE_PCT,
            "move_pct": move,
        }
    return {
        "send": True,
        "reason": "придатний сетап для стрічки",
        "kind": KIND_ALERT,
        "min_move_pct": MIN_ALERT_MOVE_PCT,
        "move_pct": move,
        "rr_net": net,
        "opens_position": False,
    }


def format_opportunity_alert(
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    setup: str,
    why: str,
    entry: Any,
    sl: Any,
    tp1: Any,
    tp2: Any = None,
    rr_net: Any = None,
    cancel: str = "",
    quote_asof: str = "",
    move_pct: Any = None,
) -> str:
    """Одне повідомлення — одна угода для графіка. Без списку всіх рівнів."""
    e, s, t1 = format_px(entry), format_px(sl), format_px(tp1)
    t2 = format_px(tp2)
    tf = str(timeframe or "").strip() or "H1"
    setup_ua = {
        "bounce": "відскок від рівня",
        "sweep_reclaim": "свіп і повернення",
        "break_retest": "пробій і ретест",
    }.get(str(setup or ""), str(setup or "сетап"))
    lines = [
        f"🦁 {direction} · {symbol} · {tf} · {setup_ua}",
        f"Чому звернув увагу: {why}",
        f"План: вхід {e} · SL {s} · TP1 {t1}" + (f" · TP2 {t2}" if t2 else ""),
    ]
    if move_pct is not None:
        lines.append(
            f"Потенціал до TP1: приблизно {float(move_pct):.1f}% до витрат "
            "(не чистий прибуток). "
            + (f"RR після витрат {float(rr_net):.1f}." if rr_net is not None else "")
        )
    if cancel:
        lines.append(f"Скасування: {cancel}")
    if quote_asof:
        lines.append(f"Котирування: {quote_asof}")
    lines.append(
        "Статус: умови підтверджені всередині офісу; "
        "перевірити актуальність ціни перед рішенням. Не ордер. Угода лише через /position."
    )
    return "\n".join(lines)


def format_watch_nudge(
    *,
    symbol: str,
    direction: str,
    zone: str,
    move_pct: Any,
    wait_for: str,
) -> str:
    """Коротко лише якщо зона ключова і запас ходу вже ≥ 3%."""
    mv = f"{float(move_pct):.1f}%" if move_pct is not None else "н/д"
    return (
        f"🦁 {symbol}: наближення до ключової зони {zone} ({direction}). "
        f"Потенціал до наступної цілі {mv}. {wait_for} "
        "Картки входу ще немає."
    )


def level_book_to_alert(book: Any, *, quote_asof: str = "", chase: bool = False) -> Optional[str]:
    """З внутрішньої книги рівнів — щонайбільше один алерт, не вісім ліній."""
    scenarios = list(getattr(book, "scenarios", None) or [])
    confirmed = [s for s in scenarios if str(getattr(s, "status", "")).upper() == "CONFIRMED"]
    if not confirmed:
        return None
    # Один напрямок: той, де більший запас ходу, якщо обидва пройшли фільтр.
    picked = None
    picked_dec = None
    for sc in confirmed:
        dec = alert_decision(
            status=sc.status,
            entry=sc.entry,
            sl=sc.sl,
            tp1=sc.tp1,
            rr_net=sc.rr_net,
            chase=chase,
        )
        if not dec.get("send"):
            continue
        if picked is None or float(dec.get("move_pct") or 0) > float(picked_dec.get("move_pct") or 0):
            picked, picked_dec = sc, dec
    if picked is None:
        return None
    mode = str(getattr(book, "mode", "") or "")
    tf = "M5" if mode == "scalp" else "H1"
    why = str(getattr(picked, "confirmation", "") or "реакція на ключовому рівні")
    return format_opportunity_alert(
        symbol=str(getattr(book, "symbol", "")),
        direction=str(picked.direction),
        timeframe=tf,
        setup=str(picked.setup or ""),
        why=why,
        entry=picked.entry,
        sl=picked.sl,
        tp1=picked.tp1,
        tp2=picked.tp2,
        rr_net=picked.rr_net,
        cancel=str(picked.cancel or ""),
        quote_asof=quote_asof,
        move_pct=picked_dec.get("move_pct"),
    )


def range_result_to_alert(res: Any, *, quote_asof: str = "", chase: bool = False) -> Optional[str]:
    """INSIDE/прокол без картки — мовчання. CONFIRMED — лише якщо ≥ 3% до TP1."""
    if str(getattr(res, "status", "")).upper() != "CONFIRMED" or not getattr(res, "card", None):
        return None
    c = res.card or {}
    dec = alert_decision(
        status="CONFIRMED",
        entry=c.get("entry"),
        sl=c.get("sl"),
        tp1=c.get("tp1") or c.get("tp"),
        rr_net=c.get("rr"),
        chase=chase,
    )
    if not dec.get("send"):
        return None
    return format_opportunity_alert(
        symbol=str(getattr(res, "symbol", "")),
        direction=str(getattr(res, "direction", "")),
        timeframe="H1",
        setup=str(getattr(res, "event", "") or "breakout"),
        why=str(getattr(res, "reason", "") or "підтверджений вихід з боковика"),
        entry=c.get("entry"),
        sl=c.get("sl"),
        tp1=c.get("tp1") or c.get("tp"),
        tp2=c.get("tp2"),
        rr_net=c.get("rr"),
        cancel="повернення всередину боковика без закріплення",
        quote_asof=quote_asof,
        move_pct=dec.get("move_pct"),
    )
