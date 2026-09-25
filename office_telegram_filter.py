"""T8: фільтр Telegram — аналітика всередині, у чат лише придатний сетап.

3% — мінімальний очікуваний рух entry→TP1 для стандартного алерту, не чистий PnL
і не ATR/Edge. Не можна малювати дальній TP, щоб натягнути 3%.
CONFIRMED у коді ≠ автоматична розсилка.
Скальп <3% лишається у внутрішньому WATCHING/CONFIRMED — фільтр лише стрічки.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from office_radar import MIN_RR
from office_topdown import ENTRY_WAITING_SWEEP

KIND_ALERT = "telegram_opportunity"
# Стрічка Telegram, не торговий поріг ATR 80/90 і не Edge 85.
MIN_ALERT_MOVE_PCT = 3.0
ALERT_COOLDOWN_SEC = 4 * 3600
# M5/M15: свіжіше за 20 хв. Лише H1: поточна година + буфер.
QUOTE_STALE_SEC_INTRADAY = 20 * 60
QUOTE_STALE_SEC_HOURLY = 70 * 60

# Тип угоди → ТФ входу і ТФ скасування. Не пороги ATR/Edge.
TRADE_STYLE = {
    "scalp": {"type_ua": "СКАЛЬП", "entry_tf": "M5", "cancel_tf": "M5"},
    "intraday": {"type_ua": "ІНТРАДЕЙ", "entry_tf": "M15", "cancel_tf": "H1"},
    "swing": {"type_ua": "СВІНГ", "entry_tf": "H4", "cancel_tf": "H4"},
}


def resolve_trade_style(mode: Any = "", timeframe: Any = "") -> dict:
    """СКАЛЬП/ІНТРАДЕЙ/СВІНГ для картки. Не змінює статус сценарію."""
    md = str(mode or "").strip().lower()
    if md in TRADE_STYLE:
        return dict(TRADE_STYLE[md])
    tf = str(timeframe or "").strip().lower()
    if tf in ("m1", "1m", "m5", "5m"):
        return dict(TRADE_STYLE["scalp"])
    if tf in ("h4", "4h", "d1", "1d"):
        return dict(TRADE_STYLE["swing"])
    return dict(TRADE_STYLE["intraday"])


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


def parse_quote_dt(ts: Any) -> Optional[datetime]:
    """UTC-мітка котирування зі свічки Binance (`ts`) або ISO."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def newest_quote_asof(*candle_groups: Any) -> str:
    """Найсвіжіший `ts` серед наборів свічок (M5/M15/H1)."""
    best_dt: Optional[datetime] = None
    for group in candle_groups:
        if not isinstance(group, list) or not group:
            continue
        last = group[-1] if isinstance(group[-1], dict) else None
        if not last:
            continue
        dt = parse_quote_dt(last.get("ts") or last.get("asof"))
        if dt is not None and (best_dt is None or dt > best_dt):
            best_dt = dt
    return best_dt.isoformat() if best_dt is not None else ""


def quote_is_stale(
    ts: Any,
    *,
    now: Any = None,
    has_intraday: bool = True,
) -> bool:
    """Перед алертом: без мітки або застаріле — не надсилаємо, аналіз не чіпаємо."""
    dt = parse_quote_dt(ts)
    if dt is None:
        return True
    now_dt = parse_quote_dt(now) if now is not None else datetime.now(timezone.utc)
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    else:
        now_dt = now_dt.astimezone(timezone.utc)
    age = (now_dt - dt).total_seconds()
    limit = QUOTE_STALE_SEC_INTRADAY if has_intraday else QUOTE_STALE_SEC_HOURLY
    return age > float(limit)


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
    entry_mode: str = "",
) -> Dict[str, Any]:
    """Чи варто показувати Тетяні. Аналіз у коді може лишатися CONFIRMED."""
    st = str(status or "").upper()
    mode = str(entry_mode or "").upper()
    if st != "CONFIRMED" or st == "WAITING_SWEEP" or mode == ENTRY_WAITING_SWEEP:
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
    setup: str = "",
    why: str = "",
    entry: Any,
    sl: Any,
    tp1: Any,
    tp2: Any = None,
    rr_net: Any = None,
    cancel: str = "",
    quote_asof: str = "",
    move_pct: Any = None,
    structure_line: str = "",
    sweep_line: str = "",
    asia_high: Any = None,
    asia_low: Any = None,
    sl_explain: str = "",
    entry_note: str = "",
    mode: str = "",
    live_price: Any = None,
    logic_line: str = "",
    entry_mode: str = "",
    sweep_level: Any = None,
) -> str:
    """Картка практика: тип/ТФ, цифри SL/TP, скасування цифрою. Без шаблонного статусу."""
    e, s, t1 = format_px(entry), format_px(sl), format_px(tp1)
    t2 = format_px(tp2)
    tf = str(timeframe or "").strip() or "H1"
    style = resolve_trade_style(mode, tf)
    side = str(direction or "").upper()
    mark = "🟢" if side == "LONG" else "🔴"
    lines = [
        f"{mark} {side} · {symbol} · {tf}",
        f"Тип: {style['type_ua']} · Вхід на {style['entry_tf']}",
    ]
    live = format_px(live_price) or e
    if live:
        lines.append(f"Ціна зараз: {live}")
    struct = str(structure_line or "").strip()
    why_s = str(why or "").strip()
    template_why = any(
        x in why_s.lower()
        for x in ("реакція +", "закриття нижче рівня", "закриття вище рівня", "умови підтверджен")
    )
    if struct:
        lines.append(f"Структура: {struct}")
    elif why_s and not template_why:
        lines.append(f"Структура: {why_s}")
    else:
        lines.append("Структура: DATA_UNAVAILABLE (немає свічок)")
    logic = str(logic_line or "").strip()
    if logic:
        lines.append(f"Логіка: {logic}")
    if sweep_line:
        sw = str(sweep_line).strip()
        if "знято" in sw.lower() and "✅" not in sw:
            sw = f"{sw} ✅"
        lines.append(f"Свіп: {sw}")
    else:
        lines.append("Свіп: DATA_UNAVAILABLE (немає підтверджених свічок)")
    ah, al = format_px(asia_high), format_px(asia_low)
    if ah and al:
        lines.append(f"Діапазон сесії: Asian High {ah} · Low {al}")
    else:
        lines.append("Діапазон сесії: Asian High/Low DATA_UNAVAILABLE")
    waiting = str(entry_mode or "").upper() == ENTRY_WAITING_SWEEP
    note = str(entry_note or "").strip()
    if waiting:
        slv = format_px(sweep_level)
        if side == "SHORT":
            wait_e = f"після свіпу і закриття {style['entry_tf']} нижче {slv}" if slv else "після свіпу"
        else:
            wait_e = f"після свіпу і закриття {style['entry_tf']} вище {slv}" if slv else "після свіпу"
        lines.append(f"Вхід: {wait_e}")
        lines.append("Спостереження: якщо ціна дійде до рівня свіпу і відскочить")
        lines.append("Нічого не робити поки свіп не підтверджено")
        blob = "\n".join(lines)
        return blob
    if note:
        lines.append(f"Вхід: {note}" if not note.lower().startswith("вхід:") else note)
    elif live and e and live == e:
        lines.append(f"Вхід: по ринку {e} (зона вже досягнута)")
    elif e:
        lines.append(f"Вхід: {e} ({style['entry_tf']} закрита {'нижче' if side == 'SHORT' else 'вище'})")
    else:
        lines.append("Вхід: DATA_UNAVAILABLE")
    lines.append(f"SL: {s}")
    lines.append(f"TP1: {t1}")
    if move_pct is not None:
        lines.append(f"Потенціал до TP1: {float(move_pct):.1f}%")
    if t2 and move_pct is not None and entry:
        try:
            m2 = abs(float(tp2) - float(entry)) / float(entry) * 100.0
            lines.append(f"TP2: {t2}  (+{m2:.1f}%)")
        except (TypeError, ValueError):
            lines.append(f"TP2: {t2}")
    elif t2:
        lines.append(f"TP2: {t2}")
    if rr_net is not None:
        lines.append(f"RR: 1:{float(rr_net):.1f}")
    if t2:
        lines.append(
            "Ведення: при TP1 — закрий 50–70%, перестав SL у беззбиток на рівень входу, "
            "тримай решту до TP2"
        )
    else:
        lines.append("Ведення: при TP1 — закрий 50–70% і перестав SL у беззбиток на рівень входу")
    if s:
        above = "вище" if side == "SHORT" else "нижче"
        lines.append(
            f"Скасування: {style['cancel_tf']} свічка закривається {above} {s}"
        )
    elif cancel and format_px(cancel):
        above = "вище" if side == "SHORT" else "нижче"
        lines.append(
            f"Скасування: {style['cancel_tf']} свічка закривається {above} {format_px(cancel)}"
        )
    lines.append("→ Олеся фіксує в журнал")
    blob = "\n".join(lines)
    return blob


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


def level_book_to_alert(
    book: Any,
    *,
    quote_asof: str = "",
    chase: bool = False,
    quote_stale: bool = False,
) -> Optional[str]:
    """З внутрішньої книги рівнів — щонайбільше один алерт, не вісім ліній.

    send=False не змінює status сценаріїв: WATCHING/CONFIRMED лишаються всередині.
    """
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
            quote_stale=quote_stale,
        )
        if not dec.get("send"):
            continue
        if picked is None or float(dec.get("move_pct") or 0) > float(picked_dec.get("move_pct") or 0):
            picked, picked_dec = sc, dec
    if picked is None:
        return None
    mode = str(getattr(book, "mode", "") or "")
    if mode == "scalp":
        tf = "M5"
    elif mode == "swing":
        tf = "H4"
    else:
        tf = "H1"
    extras = getattr(book, "extras", None) or {}
    td = extras.get("topdown") if isinstance(extras, dict) else None
    td = td if isinstance(td, dict) else {}
    sweep = td.get("sweep") if isinstance(td.get("sweep"), dict) else {}
    if str(td.get("entry_mode") or sweep.get("entry_mode") or "") == ENTRY_WAITING_SWEEP or sweep.get("ahead"):
        return None
    asia = td.get("asia") if isinstance(td.get("asia"), dict) else {}
    extras_px = extras.get("price") if isinstance(extras, dict) else None
    return format_opportunity_alert(
        symbol=str(getattr(book, "symbol", "")),
        direction=str(picked.direction),
        timeframe=tf,
        setup=str(picked.setup or ""),
        why=str(td.get("structure_line") or ""),
        entry=picked.entry,
        sl=picked.sl,
        tp1=picked.tp1,
        tp2=picked.tp2,
        rr_net=picked.rr_net,
        cancel=str(picked.cancel or ""),
        quote_asof=quote_asof,
        move_pct=picked_dec.get("move_pct"),
        structure_line=str(td.get("structure_line") or ""),
        sweep_line=str(sweep.get("line") or ""),
        asia_high=asia.get("high"),
        asia_low=asia.get("low"),
        sl_explain="",
        entry_note=str(getattr(picked, "entry_note", "") or ""),
        mode=mode,
        live_price=extras_px if extras_px is not None else picked.entry,
        logic_line=str(td.get("logic_line") or ""),
        entry_mode=str(td.get("entry_mode") or sweep.get("entry_mode") or getattr(picked, "entry_mode", "") or ""),
        sweep_level=sweep.get("level"),
    )


def range_result_to_alert(
    res: Any,
    *,
    quote_asof: str = "",
    chase: bool = False,
    quote_stale: bool = False,
) -> Optional[str]:
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
        quote_stale=quote_stale,
    )
    if not dec.get("send"):
        return None
    extras = getattr(res, "extras", None) or {}
    td = extras.get("topdown") if isinstance(extras, dict) else {}
    td = td if isinstance(td, dict) else {}
    asia = td.get("asia") if isinstance(td.get("asia"), dict) else {}
    sweep = td.get("sweep") if isinstance(td.get("sweep"), dict) else {}
    if str(td.get("entry_mode") or sweep.get("entry_mode") or "") == ENTRY_WAITING_SWEEP or sweep.get("ahead"):
        return None
    return format_opportunity_alert(
        symbol=str(getattr(res, "symbol", "")),
        direction=str(getattr(res, "direction", "")),
        timeframe="H1",
        setup=str(getattr(res, "event", "") or "breakout"),
        why=str(td.get("structure_line") or getattr(res, "reason", "") or ""),
        entry=c.get("entry"),
        sl=c.get("sl"),
        tp1=c.get("tp1") or c.get("tp"),
        tp2=c.get("tp2"),
        rr_net=c.get("rr"),
        cancel="",
        quote_asof=quote_asof,
        move_pct=dec.get("move_pct"),
        structure_line=str(td.get("structure_line") or ""),
        sweep_line=str(sweep.get("line") or ""),
        asia_high=asia.get("high"),
        asia_low=asia.get("low"),
        sl_explain="",
        entry_note="",
        mode="intraday",
        live_price=c.get("entry"),
        logic_line=str(td.get("logic_line") or ""),
        entry_mode=str(td.get("entry_mode") or sweep.get("entry_mode") or ""),
        sweep_level=sweep.get("level"),
    )


def _book_tf(book: Any) -> str:
    mode = str(getattr(book, "mode", "") or "")
    if mode == "scalp":
        return "M5"
    if mode == "swing":
        return "H4"
    return "H1"


def level_book_to_watching(book: Any) -> Optional[str]:
    """WATCHING-картка очікування свіпу. Не сигнал у стрічку."""
    from office_lifecycle import format_waiting_sweep_watch

    extras = getattr(book, "extras", None) or {}
    td = extras.get("topdown") if isinstance(extras, dict) else {}
    td = td if isinstance(td, dict) else {}
    sweep = td.get("sweep") if isinstance(td.get("sweep"), dict) else {}
    waiting = False
    for sc in list(getattr(book, "scenarios", None) or []):
        if str(getattr(sc, "entry_mode", "") or "").upper() == ENTRY_WAITING_SWEEP:
            waiting = True
            break
    if not waiting and str(td.get("entry_mode") or "") == ENTRY_WAITING_SWEEP:
        waiting = True
    if not waiting:
        return None
    direction = ""
    for sc in list(getattr(book, "scenarios", None) or []):
        if str(getattr(sc, "direction", "")):
            direction = str(sc.direction)
            if str(getattr(sc, "entry_mode", "") or "").upper() == ENTRY_WAITING_SWEEP:
                break
    if not direction:
        direction = "LONG" if str(sweep.get("kind") or "") == "SSL" else "SHORT"
    return format_waiting_sweep_watch(
        symbol=str(getattr(book, "symbol", "")),
        timeframe=_book_tf(book),
        direction=direction,
        sweep_level=sweep.get("level"),
        sweep_kind=str(sweep.get("kind") or "SSL"),
    )


def level_book_to_sweep_approach(book: Any, *, price: Any = None) -> Optional[str]:
    """Алерт ±0.3% до рівня свіпу. Не картка входу."""
    from office_lifecycle import format_sweep_approach_alert, sweep_approach_due

    extras = getattr(book, "extras", None) or {}
    td = extras.get("topdown") if isinstance(extras, dict) else {}
    td = td if isinstance(td, dict) else {}
    sweep = td.get("sweep") if isinstance(td.get("sweep"), dict) else {}
    waiting_sc = any(
        str(getattr(sc, "entry_mode", "") or "").upper() == ENTRY_WAITING_SWEEP
        for sc in list(getattr(book, "scenarios", None) or [])
    )
    if not waiting_sc and str(td.get("entry_mode") or extras.get("entry_mode") or "") != ENTRY_WAITING_SWEEP:
        return None
    if not (sweep.get("ahead") or str(sweep.get("entry_mode") or "") == ENTRY_WAITING_SWEEP):
        return None
    px = price if price is not None else (extras.get("price") if isinstance(extras, dict) else None)
    if not sweep_approach_due(price=px, level=sweep.get("level"), already_happened=bool(sweep.get("happened"))):
        return None
    direction = "LONG" if str(sweep.get("kind") or "") == "SSL" else "SHORT"
    for sc in list(getattr(book, "scenarios", None) or []):
        if str(getattr(sc, "direction", "")):
            direction = str(sc.direction)
            break
    return format_sweep_approach_alert(
        symbol=str(getattr(book, "symbol", "")),
        level=sweep.get("level"),
        price=px,
        direction=direction,
        sweep_kind=str(sweep.get("kind") or "SSL"),
    )
