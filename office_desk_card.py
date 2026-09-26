"""Єдина картка входу і фільтри стрічки (Лев / PUMP / Радар).

Стоп ≥ 1× ATR(H1). Позиція > 3× депо → не слати.
TP1: альти ≥3%, BTC/ETH/XAU ≥1.2%.
Переворот: скасування або бал ≥ поріг+1; інакше конфлікт модулів.
Не змінює ATR 80/90, Edge 85. Не ордер.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from office_position_size import depo_usdt, plan_position_size

MIN_SL_ATR_H1 = 1.0
MAX_POS_MULT_DEPO = 3.0
REV_SCORE_EXTRA = 1
MAJORS = ("BTCUSDT", "ETHUSDT", "XAUUSDT", "XAUUSD", "PAXGUSDT")
MAJORS_TP1_PCT = 1.2
ALTS_TP1_PCT = 3.0
OPEN_STATUSES = ("ACTIVE", "HIT_ENTRY", "HIT_TP1", "HIT_TP2")
_NEAR_STOP_ONCE: Set[str] = set()
BANNED_CARD_FRAGMENTS = (
    "Балі",
    "Бали",
    "Модель рівнів",
    "Картка сетапу, не ордер",
    "не ордер",
    "away",
    "resistance",
    "Entry:",
    "SL:",
    "forceOrder",
    "RR 1:",
)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _px(v: Any) -> str:
    """Ціна як у картці: 84 069, без Entry/SL англійською."""
    from office_telegram_filter import format_px

    s = format_px(v)
    if not s:
        return s
    if "." in s:
        whole, frac = s.split(".", 1)
    else:
        whole, frac = s, ""
    try:
        n = int(whole)
    except ValueError:
        return s
    if abs(n) >= 1000:
        grouped = f"{n:,}".replace(",", " ")
        return f"{grouped}.{frac}" if frac else grouped
    return s


def parse_cancel_level(note: Any) -> Optional[float]:
    """Рівень скасування з analysis_note (`cancel=84000`)."""
    import re

    m = re.search(r"cancel\s*=\s*([0-9]+(?:[.,][0-9]+)?)", str(note or ""), flags=re.I)
    if not m:
        return None
    raw = str(m.group(1) or "").replace(",", ".")
    return _f(raw)


def is_major_symbol(symbol: str) -> bool:
    s = str(symbol or "").upper()
    if s in MAJORS:
        return True
    if s.startswith("BTC") or s.startswith("ETH"):
        return True
    if "XAU" in s or s.startswith("PAXG"):
        return True
    return False


def min_tp1_pct(symbol: str) -> float:
    return MAJORS_TP1_PCT if is_major_symbol(symbol) else ALTS_TP1_PCT


def style_ua(timeframe: str) -> str:
    tf = str(timeframe or "M15").upper()
    if tf in ("M1", "1M", "M5", "5M", "M15", "15M"):
        return "скальп"
    if tf in ("H4", "4H", "D1", "1D"):
        return "свінг"
    return "інтрадей"


def _pct_signed_risk(entry: float, sl: float) -> float:
    return -abs(sl - entry) / abs(entry) * 100.0


def _pct_signed_reward(entry: float, tp: float) -> float:
    return abs(tp - entry) / abs(entry) * 100.0


def widen_sl_to_atr_h1(
    *,
    entry: Any,
    sl: Any,
    direction: str,
    atr_h1: Any,
) -> Dict[str, Any]:
    e, s, atr = _f(entry), _f(sl), _f(atr_h1)
    if e is None or s is None:
        return {"ok": False, "sl": s, "reason": "немає entry/SL"}
    if atr is None or atr <= 0:
        return {"ok": False, "sl": s, "reason": "ATR(H1) DATA_UNAVAILABLE"}
    need = float(atr) * MIN_SL_ATR_H1
    dist = abs(e - s)
    side = str(direction or "").upper()
    if dist + 1e-12 >= need:
        return {"ok": True, "sl": s, "widened": False, "atr_h1": atr}
    if side == "SHORT":
        ns = e + need
    else:
        ns = e - need
    return {"ok": True, "sl": ns, "widened": True, "atr_h1": atr}


def size_over_leverage(*, entry: Any, sl: Any, score: Any = None, min_score: Any = 10) -> Dict[str, Any]:
    sized = plan_position_size(entry=entry, sl=sl, score=score, min_score=min_score)
    dep = _f(sized.get("depo")) or depo_usdt()
    sz = _f(sized.get("size_usdt"))
    if dep is None or sz is None:
        return {**sized, "over_lev": False, "max_usdt": None}
    cap = dep * MAX_POS_MULT_DEPO
    over = sz > cap + 1e-9
    return {**sized, "over_lev": over, "max_usdt": cap, "depo": dep}


def prev_cancelled(
    *,
    direction: str,
    sl: Any,
    cancel_level: Any,
    m15_close: Any,
    candle: Any = None,
) -> Dict[str, Any]:
    """Скасування: стоп або закриття M15 за рівнем скасування."""
    side = str(direction or "").upper()
    slv, lv, cl = _f(sl), _f(cancel_level), _f(m15_close)
    if cl is None and isinstance(candle, dict):
        cl = _f(candle.get("close"))
    hit_sl = False
    if slv is not None and cl is not None:
        hit_sl = (side == "LONG" and cl <= slv) or (side == "SHORT" and cl >= slv)
    if isinstance(candle, dict) and slv is not None:
        lo, hi = _f(candle.get("low")), _f(candle.get("high"))
        if side == "LONG" and lo is not None and lo <= slv:
            hit_sl = True
        if side == "SHORT" and hi is not None and hi >= slv:
            hit_sl = True
    hit_cancel = False
    reason = ""
    px = lv if lv is not None else slv
    if cl is not None and px is not None:
        if side == "LONG" and cl < px:
            hit_cancel = True
            reason = f"M15 закрилась нижче {_px(px)}, структура зламана"
        if side == "SHORT" and cl > px:
            hit_cancel = True
            reason = f"M15 закрилась вище {_px(px)}, структура зламана"
    if hit_sl:
        return {"ok": True, "how": "SL", "reason": f"стоп {_px(slv)} зачеплено"}
    if hit_cancel:
        return {"ok": True, "how": "CANCEL", "reason": reason}
    return {"ok": False, "how": "", "reason": ""}


def reversal_allowed(
    *,
    prev: Optional[Dict[str, Any]],
    new_direction: str,
    new_score: Any,
    min_score: Any,
    m15_close: Any = None,
    candle: Any = None,
) -> Dict[str, Any]:
    """Протилежний сигнал: лише скасування або бал ≥ поріг+1."""
    if not prev:
        return {"ok": True, "reversal": False, "reason": ""}
    pst = str(prev.get("status") or "").upper()
    if pst not in OPEN_STATUSES and pst not in ("OPEN",):
        return {"ok": True, "reversal": False, "reason": ""}
    pdir = str(prev.get("direction") or "").upper()
    ndir = str(new_direction or "").upper()
    if not pdir or pdir == ndir:
        return {"ok": True, "reversal": False, "reason": ""}
    sc, mn = _f(new_score), _f(min_score)
    score_ok = sc is not None and mn is not None and sc + 1e-12 >= mn + REV_SCORE_EXTRA
    cancel_lv = prev.get("cancel_level")
    if cancel_lv is None:
        el, eh = _f(prev.get("entry_low")), _f(prev.get("entry_high"))
        e = _f(prev.get("entry") or prev.get("entry_price"))
        # Широка зона — край як скасування. Точковий вхід — лише стоп або бал.
        if el is not None and eh is not None and e is not None:
            if abs(eh - el) / max(abs(e), 1e-9) > 0.0008:
                cancel_lv = el if pdir == "LONG" else eh
        elif el is not None and eh is None:
            cancel_lv = el
    canc = prev_cancelled(
        direction=pdir,
        sl=prev.get("sl") or prev.get("stop_loss"),
        cancel_level=cancel_lv,
        m15_close=m15_close,
        candle=candle,
    )
    if canc.get("ok") or score_ok:
        why = str(canc.get("reason") or "")
        if score_ok and not canc.get("ok"):
            why = f"бал {int(sc)} ≥ поріг {int(mn)}+{REV_SCORE_EXTRA}"
        return {"ok": True, "reversal": True, "reason": why, "prev": prev}
    return {
        "ok": False,
        "reversal": False,
        "reason": "конфлікт модулів",
        "prev": prev,
    }


def desk_entry_gate(
    *,
    symbol: str,
    direction: str,
    entry: Any,
    sl: Any,
    tp1: Any,
    atr_h1: Any,
    score: Any = None,
    min_score: Any = 10,
    prev: Optional[Dict[str, Any]] = None,
    m15_close: Any = None,
    candle: Any = None,
) -> Dict[str, Any]:
    """Фільтр стрічки. Не вигадує TP, щоб натягнути %."""
    from office_telegram_filter import move_pct_to_tp

    e, s, t = _f(entry), _f(sl), _f(tp1)
    empty = {"send": False, "sl": s, "size": None, "reversal": False, "reason": "", "message": ""}
    if e is None or s is None or t is None:
        return {**empty, "reason": "немає entry/SL/TP1"}
    wide = widen_sl_to_atr_h1(entry=e, sl=s, direction=direction, atr_h1=atr_h1)
    if not wide.get("ok"):
        return {**empty, "reason": str(wide.get("reason") or "стоп/ATR")}
    s2 = float(wide["sl"])
    need = min_tp1_pct(symbol)
    move = move_pct_to_tp(entry=e, tp=t)
    if move is None or move + 1e-12 < need:
        return {
            **empty,
            "sl": s2,
            "reason": f"TP1 {move if move is not None else 'н/д'}% < {need:g}%",
        }
    sized = size_over_leverage(entry=e, sl=s2, score=score, min_score=min_score)
    if sized.get("over_lev"):
        return {
            **empty,
            "sl": s2,
            "size": sized,
            "reason": f"позиція {sized.get('size_usdt'):.0f} USDT > 3× депо",
        }
    rev = reversal_allowed(
        prev=prev,
        new_direction=direction,
        new_score=score,
        min_score=min_score,
        m15_close=m15_close,
        candle=candle,
    )
    if not rev.get("ok"):
        return {**empty, "sl": s2, "size": sized, "reason": "конфлікт модулів"}
    return {
        "send": True,
        "sl": s2,
        "size": sized,
        "reversal": bool(rev.get("reversal")),
        "rev_reason": rev.get("reason") or "",
        "prev": rev.get("prev"),
        "reason": "ok",
        "widened": bool(wide.get("widened")),
    }


def _kind_line(setup_type: str, *, reentry: bool = False) -> str:
    if reentry:
        return "Повторний вхід"
    raw = str(setup_type or "").strip()
    ul = raw.upper()
    if "ПОВТОРНИЙ" in ul:
        return "Повторний вхід"
    if "СИЛЬН" in raw or "HUNTER" in ul:
        return "Відкат у сильну свічку"
    if ul in ("DUMP", "PUMP"):
        return ul
    if "РАДАР" in ul or ul == "RADAR":
        return "Радар"
    if ul == "BOUNCE":
        return "Відскік"
    if raw:
        return raw.replace("_", " ")[:40]
    return "Сетап"


def _pct_txt(pct: float) -> str:
    sign = "−" if pct < 0 else "+"
    return f"({sign}{abs(pct):.1f}%)"


def _lvl(prefix: str, px: Any, pct: Optional[float] = None) -> str:
    if pct is None:
        return f"{prefix} · {_px(px)}"
    return f"{prefix} · {_px(px)}  {_pct_txt(pct)}"


def format_desk_card(
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    entry: Any,
    sl: Any,
    tp1: Any,
    tp2: Any = None,
    tp3: Any = None,
    add_px: Any = None,
    setup_type: str = "",
    score: Any = None,
    min_score: Any = 10,
    size: Optional[Dict[str, Any]] = None,
    reversal: bool = False,
    prev: Optional[Dict[str, Any]] = None,
    rev_reason: str = "",
    reentry: bool = False,
) -> str:
    """Картка: кожне значення окремим рядком. Без RR, балів, моделей."""
    side = str(direction or "").upper()
    mark = "🟢" if side == "LONG" else "🔴"
    e, s, t1 = _f(entry), _f(sl), _f(tp1)
    tf = str(timeframe or "M15").upper()
    kind = _kind_line(setup_type, reentry=reentry)
    lines: List[str] = []
    if reversal and prev:
        pdir = str(prev.get("direction") or "").upper()
        pe = _px(prev.get("entry") or prev.get("entry_low") or prev.get("entry_high") or prev.get("entry_price"))
        why = str(rev_reason or "").strip()
        if why.lower().startswith("причина:"):
            why = why.split(":", 1)[-1].strip()
        if why:
            lines.append(f"🔄 {pdir} від {pe or '—'} скасовано — {why}")
        else:
            lines.append(f"🔄 {pdir} від {pe or '—'} скасовано")
    lines.append(f"{mark} {side} · {str(symbol).upper()} · {tf}")
    lines.append(kind)
    lines.append("")
    addv = _f(add_px)
    if addv is not None and e is not None:
        lines.append(_lvl("🎯 Вхід 60%", e))
        lines.append(_lvl("➕ Добір 40%", addv))
    else:
        lines.append(_lvl("🎯 Вхід", e))
    if e is not None and s is not None:
        lines.append(_lvl("❌ Стоп", s, _pct_signed_risk(e, s)))
    else:
        lines.append(_lvl("❌ Стоп", s))
    if t1 is not None:
        lines.append(_lvl("✅ TP1", t1, _pct_signed_reward(e, t1) if e else None))
    if tp2 is not None:
        lines.append(_lvl("✅ TP2", tp2, _pct_signed_reward(e, _f(tp2)) if e and _f(tp2) else None))
    if tp3 is not None:
        lines.append(_lvl("✅ TP3", tp3, _pct_signed_reward(e, _f(tp3)) if e and _f(tp3) else None))
    lines.append("")
    below = "нижче" if side == "SHORT" else "вище"
    lines.append(f"Вхід після закриття {tf} {below} {_px(e)}")
    sz = size if isinstance(size, dict) else plan_position_size(
        entry=e, sl=s, score=score, min_score=min_score
    )
    usdt = _f(sz.get("size_usdt"))
    dep = _f(sz.get("depo")) or depo_usdt()
    rp = _f(sz.get("risk_pct")) or 0.01
    if usdt is not None and dep is not None:
        risk_usd = dep * rp
        lines.append(f"Позиція {int(round(usdt)):,} USDT · ризик {risk_usd:.0f}$".replace(",", " "))
    else:
        lines.append(f"Ризик {rp * 100:.0f}% депо")
    return "\n".join(lines)


def card_has_banned(text: str) -> List[str]:
    hit = []
    src = str(text or "")
    for frag in BANNED_CARD_FRAGMENTS:
        if frag in src:
            hit.append(frag)
    return hit


def may_send_near_stop(*, trade_id: str, confirmed_position: bool) -> bool:
    """Лише /position, один раз на угоду."""
    tid = str(trade_id or "").strip()
    if not confirmed_position or not tid:
        return False
    if tid in _NEAR_STOP_ONCE:
        return False
    _NEAR_STOP_ONCE.add(tid)
    return True


def format_near_stop(*, symbol: str, price: Any, sl: Any) -> str:
    return (
        f"⚠️ Тетяно, {str(symbol).upper()}: ціна близько до стопу.\n"
        f"Зараз {_px(price)}, стоп {_px(sl)}."
    )


def reset_near_stop_once() -> None:
    _NEAR_STOP_ONCE.clear()


def _row_entry(row: Dict[str, Any]) -> Any:
    return row.get("entry") or row.get("entry_price") or row.get("entry_low") or row.get("entry_high")


def latest_open_desk_signal(db_path: str, symbol: str) -> Optional[Dict[str, Any]]:
    from office_bridge import _fetchall, is_confirmed_position_row, signal_get_active

    sym = str(symbol or "").upper()
    try:
        rows = signal_get_active(db_path) or []
    except Exception:
        rows = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("symbol") or "").upper() != sym:
            continue
        if str(r.get("status") or "").upper() in OPEN_STATUSES:
            out = dict(r)
            out["entry"] = _row_entry(out)
            clv = parse_cancel_level(out.get("analysis_note"))
            if clv is not None and out.get("cancel_level") is None:
                out["cancel_level"] = clv
            return out
    try:
        jrows = _fetchall(
            db_path,
            """
            SELECT trade_id, symbol, direction, status, entry_price, stop_loss,
                   take_profit, entry_reason, setup_name
            FROM trade_journal
            WHERE status = 'OPEN'
            ORDER BY ts_open_utc DESC
            """,
            (),
        )
    except Exception:
        jrows = []
    for tid, jsym, direction, status, entry, sl, tp, reason, setup in jrows:
        if str(jsym or "").upper() != sym:
            continue
        # І офісний сигнал, і /position — попередній напрямок для перевороту.
        _ = is_confirmed_position_row(reason, setup, tid)
        return {
            "signal_id": "",
            "trade_id": str(tid or ""),
            "symbol": sym,
            "direction": str(direction or ""),
            "status": str(status or "OPEN"),
            "entry": entry,
            "entry_low": entry,
            "entry_high": entry,
            "sl": sl,
            "tp1": tp,
        }
    return None


def confirmed_open_trade_id(db_path: str, symbol: str) -> str:
    from office_bridge import _fetchall, is_confirmed_position_row

    sym = str(symbol or "").upper()
    try:
        rows = _fetchall(
            db_path,
            """
            SELECT trade_id, entry_reason, setup_name, status, symbol
            FROM trade_journal
            WHERE status = 'OPEN'
            """,
            (),
        )
    except Exception:
        return ""
    for tid, reason, setup, status, row_sym in rows:
        if str(row_sym or "").upper() != sym:
            continue
        if is_confirmed_position_row(reason, setup, tid):
            return str(tid or "")
    return ""


def list_confirmed_open_positions(db_path: str) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall, is_confirmed_position_row

    try:
        rows = _fetchall(
            db_path,
            """
            SELECT trade_id, symbol, direction, entry_price, stop_loss,
                   entry_reason, setup_name
            FROM trade_journal
            WHERE status = 'OPEN'
            """,
            (),
        )
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for tid, symbol, direction, entry, sl, reason, setup in rows:
        if not is_confirmed_position_row(reason, setup, tid):
            continue
        out.append(
            {
                "trade_id": str(tid or ""),
                "symbol": str(symbol or ""),
                "direction": str(direction or ""),
                "entry": entry,
                "sl": sl,
            }
        )
    return out


def close_desk_reversal(
    db_path: str,
    prev: Optional[Dict[str, Any]],
    *,
    exit_price: Any = None,
) -> None:
    """Попередній сигнал у журналі — «переворот»."""
    from office_bridge import journal_close_trade, office_signal_trade_id, signal_update

    if not prev:
        return
    sid = str(prev.get("signal_id") or "").strip()
    tid = str(prev.get("trade_id") or "").strip()
    if sid:
        try:
            signal_update(
                db_path,
                signal_id=sid,
                status="CANCELLED",
                outcome="REVERSAL",
                analysis_note="переворот",
            )
        except Exception:
            pass
        if not tid:
            tid = office_signal_trade_id(sid)
    if not tid:
        return
    px = _f(exit_price) or _f(_row_entry(prev))
    try:
        journal_close_trade(
            db_path,
            trade_id=tid,
            outcome="BE",
            exit_price=px,
            pnl_pct=0.0,
            exit_reason="переворот",
            context_patch={"result": "переворот"},
        )
    except Exception:
        pass


def prepare_desk_send(
    *,
    db_path: str = "",
    symbol: str,
    direction: str,
    timeframe: str,
    entry: Any,
    sl: Any,
    tp1: Any,
    tp2: Any = None,
    tp3: Any = None,
    add_px: Any = None,
    atr_h1: Any,
    score: Any = None,
    min_score: Any = 10,
    setup_type: str = "",
    m15_close: Any = None,
    candle: Any = None,
    prev: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Gate + текст картки. Закриває попередній сигнал лише якщо send і reversal."""
    if prev is None and db_path:
        prev = latest_open_desk_signal(db_path, symbol)
    gate = desk_entry_gate(
        symbol=symbol,
        direction=direction,
        entry=entry,
        sl=sl,
        tp1=tp1,
        atr_h1=atr_h1,
        score=score,
        min_score=min_score,
        prev=prev,
        m15_close=m15_close,
        candle=candle,
    )
    if not gate.get("send"):
        return gate
    if gate.get("reversal") and db_path:
        close_desk_reversal(db_path, gate.get("prev") or prev, exit_price=entry)
    text = format_desk_card(
        symbol=symbol,
        direction=direction,
        timeframe=timeframe,
        entry=entry,
        sl=gate.get("sl"),
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        add_px=add_px,
        setup_type=setup_type,
        score=score,
        min_score=min_score,
        size=gate.get("size") if isinstance(gate.get("size"), dict) else None,
        reversal=bool(gate.get("reversal")),
        prev=gate.get("prev") or prev,
        rev_reason=str(gate.get("rev_reason") or ""),
    )
    return {**gate, "text": text}
