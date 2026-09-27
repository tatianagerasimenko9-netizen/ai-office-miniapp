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


def _card_decimals(ref: Any) -> int:
    """Одна точність для всіх цін картки — за масштабом ціни входу."""
    import math

    x = _f(ref)
    if x is None or x <= 0:
        return 4
    if x >= 1000:
        return 1
    if x >= 10:
        return 2
    if x >= 1:
        return 3
    return 3 - int(math.floor(math.log10(x)))


def _px_txt(v: Any) -> str:
    """Ціна в реченні (переворот): без зайвих нулів — 84 069, 0.922."""
    out = _px(v)
    if "." in out:
        out = out.rstrip("0").rstrip(".")
    return out


def _px(v: Any, dec: Optional[int] = None) -> str:
    """Ціна як у картці: 84 069.5; усі ціни картки — однакова точність."""
    x = _f(v)
    if x is None:
        return ""
    d = _card_decimals(x) if dec is None else int(dec)
    s = f"{x:.{d}f}"
    whole, _, frac = s.partition(".")
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
            reason = f"M15 закрилась нижче {_px_txt(px)}, структура зламана"
        if side == "SHORT" and cl > px:
            hit_cancel = True
            reason = f"M15 закрилась вище {_px_txt(px)}, структура зламана"
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
    side_u = str(direction or "").upper()
    if side_u == "SHORT":
        side_ok = s > e > t
    else:
        side_ok = s < e < t
    if not side_ok:
        return {**empty, "reason": "стоп/TP1 не з того боку від входу"}
    wide = widen_sl_to_atr_h1(entry=e, sl=s, direction=direction, atr_h1=atr_h1)
    if not wide.get("ok"):
        return {**empty, "reason": str(wide.get("reason") or "стоп/ATR")}
    s2 = float(wide["sl"])
    from office_radar import MIN_RR

    rr = abs(t - e) / abs(e - s2) if abs(e - s2) > 1e-12 else 0.0
    if rr + 1e-12 < float(MIN_RR):
        return {**empty, "sl": s2, "reason": f"RR {rr:.2f} < {MIN_RR}"}
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


def _kind_line(setup_type: str, *, reentry: bool = False, direction: str = "", grade: str = "") -> str:
    from office_confluence import kind_ua

    if reentry:
        base = "Повторний вхід"
    else:
        base = kind_ua(setup_type, direction)
    g = str(grade or "").strip().upper()
    if g in ("A", "B"):
        return f"{base} · сила {g}"
    return base


def _pct_txt(pct: float) -> str:
    sign = "−" if pct < 0 else "+"
    return f"({sign}{abs(pct):.1f}%)"


def _lvl(prefix: str, px: Any, pct: Optional[float] = None, dec: Optional[int] = None) -> str:
    if pct is None:
        return f"{prefix} · {_px(px, dec)}"
    return f"{prefix} · {_px(px, dec)}  {_pct_txt(pct)}"


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
    entry_low: Any = None,
    entry_high: Any = None,
    grade: str = "",
    zone_line: str = "",
    confirm_wait: str = "",
    now_line: str = "",
) -> str:
    """Універсальна картка LONG/SHORT. Без RR, range, балів."""
    from office_telegram_filter import format_level_span

    side = str(direction or "").upper()
    mark = "🟢" if side == "LONG" else "🔴"
    e, s, t1 = _f(entry), _f(sl), _f(tp1)
    elo, ehi = _f(entry_low), _f(entry_high)
    if elo is None:
        elo = e
    if ehi is None:
        ehi = _f(add_px) or e
    mid = e
    if mid is None and elo is not None and ehi is not None:
        mid = (elo + ehi) / 2.0
    tf = str(timeframe or "M15").upper()
    kind = _kind_line(setup_type, reentry=reentry, direction=side, grade=grade)
    lines: List[str] = []
    if reversal and prev:
        pdir = str(prev.get("direction") or "").upper()
        pe = _px_txt(prev.get("entry") or prev.get("entry_low") or prev.get("entry_high") or prev.get("entry_price"))
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
    dec = _card_decimals(mid if mid is not None else elo)
    # Прибрати спільні хвостові нулі: 0.9220/0.9400 → 0.922/0.940, але однаково для всіх.
    _all = [x for x in (elo, ehi, s, t1, _f(tp2), _f(tp3)) if x is not None]
    while dec > 0 and _all and all(round(abs(x) * 10 ** dec) % 10 == 0 for x in _all):
        dec -= 1
    if elo is not None and ehi is not None and abs(elo - ehi) > 1e-12:
        a, b = sorted((elo, ehi))
        span = f"{_px(a, dec)}–{_px(b, dec)}"
    else:
        span = _px(mid if mid is not None else elo, dec)
    lines.append(f"🎯 Вхід · {span}")
    s_show = s
    if s is not None:
        import math

        q = 10 ** dec
        s_show = (math.ceil(s * q - 1e-9) / q) if side == "SHORT" else (math.floor(s * q + 1e-9) / q)
    if mid is not None and s_show is not None:
        lines.append(_lvl("❌ Стоп", s_show, _pct_signed_risk(mid, s_show), dec))
    else:
        lines.append(_lvl("❌ Стоп", s_show, None, dec))
    if t1 is not None:
        lines.append(_lvl("✅ TP1", t1, _pct_signed_reward(mid, t1) if mid else None, dec))
    if tp2 is not None:
        lines.append(_lvl("✅ TP2", tp2, _pct_signed_reward(mid, _f(tp2)) if mid and _f(tp2) else None, dec))
    if tp3 is not None:
        lines.append(_lvl("✅ TP3", tp3, _pct_signed_reward(mid, _f(tp3)) if mid and _f(tp3) else None, dec))
    lines.append("")
    z = str(zone_line or "").strip()
    if z:
        lines.append(f"Зона: {z}")
    w = str(confirm_wait or "").strip()
    if w:
        lines.append(w if w.lower().startswith("чекаю") else f"Чекаю на {tf}: {w}")
    trig_tf = str((confirm_wait and w.split(":")[0].replace("Чекаю на", "").strip()) or tf).upper() or tf
    if elo is not None and ehi is not None:
        z_lo, z_hi = sorted((elo, ehi))
    else:
        z_lo = z_hi = mid
    if z_lo is not None:
        if side == "SHORT":
            lines.append(f"Вхід після закриття {trig_tf} нижче {_px(z_lo, dec)}")
        else:
            lines.append(f"Вхід після закриття {trig_tf} вище {_px(z_hi, dec)}")
    lines.append(str(now_line or "Зараз: поза угодою, чекаю відкат"))
    lines.append("При TP1 — частина + стоп у беззбиток")
    sz = size if isinstance(size, dict) else plan_position_size(
        entry=mid, sl=s, score=score, min_score=min_score
    )
    usdt = _f(sz.get("size_usdt"))
    dep = _f(sz.get("depo")) or depo_usdt()
    rp = _f(sz.get("risk_pct")) or 0.01
    if usdt is not None and dep is not None:
        risk_usd = dep * rp
        lines.append(f"Позиція {int(round(usdt)):,} USDT · ризик {risk_usd:.0f}$".replace(",", " "))
    else:
        lines.append(f"Ризик {rp * 100:.0f}% депо")
    text = "\n".join(lines)
    if "range" in text.lower():
        text = text.replace("range", "межа").replace("Range", "Межа").replace("RANGE", "межа")
    return text


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


def anchor_sl_beyond_zone(
    *,
    direction: str,
    sl: Any,
    zone_lo: Any,
    zone_hi: Any,
    atr_h1: Any,
    buffer_atr: float = 0.25,
) -> Any:
    """Стоп модуля рахувався під його вхід. Коли рушій переносить вхід у зону,
    стоп має стояти за дальнім краєм зони + буфер, інакше вхід опиняється за стопом."""
    s, lo, hi, atr = _f(sl), _f(zone_lo), _f(zone_hi), _f(atr_h1)
    if s is None or lo is None or hi is None:
        return sl
    if lo > hi:
        lo, hi = hi, lo
    buf = float(atr) * buffer_atr if atr and atr > 0 else (hi - lo) * 0.5
    if str(direction or "").upper() == "SHORT":
        need = hi + buf
        return max(s, need)
    need = lo - buf
    return min(s, need)


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
    candles_m15: Any = None,
    candles_h1: Any = None,
    candles_h4: Any = None,
    candles_d1: Any = None,
    candles_w: Any = None,
    candles_ltf: Any = None,
    price: Any = None,
    require_confluence: bool = True,
    confluence: Optional[Dict[str, Any]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    now_ts: Any = None,
) -> Dict[str, Any]:
    """Gate + збіги + текст картки. Закриває попередній сигнал лише якщо send і reversal."""
    from office_confluence import evaluate_confluence, mark_live

    if prev is None and db_path:
        prev = latest_open_desk_signal(db_path, symbol)
    conf = confluence
    if conf is None and require_confluence:
        has_px = any(
            x is not None
            for x in (candles_m15, candles_h1, candles_h4, candles_d1, candles_ltf)
        )
        if not has_px and not candidates:
            return {
                "send": False,
                "sl": sl,
                "size": None,
                "reversal": False,
                "reason": "DATA_UNAVAILABLE збіги",
                "message": "",
            }
        conf = evaluate_confluence(
            symbol=symbol,
            direction=direction,
            timeframe=timeframe,
            candles_m15=candles_m15,
            candles_h1=candles_h1,
            candles_h4=candles_h4,
            candles_d1=candles_d1,
            candles_w=candles_w,
            candles_ltf=candles_ltf,
            price=price if price is not None else entry,
            now_ts=now_ts,
            candidates=candidates,
        )
    if require_confluence and conf is not None and not conf.get("send_card"):
        return {
            "send": False,
            "sl": sl,
            "size": None,
            "reversal": False,
            "reason": str(conf.get("reason") or "збіги"),
            "confluence": conf,
            "message": "",
        }
    zone_lo = (conf or {}).get("zone_lo")
    zone_hi = (conf or {}).get("zone_hi")
    entry_use = (conf or {}).get("entry") if conf and conf.get("entry") is not None else entry
    sl_use = anchor_sl_beyond_zone(
        direction=direction, sl=sl, zone_lo=zone_lo, zone_hi=zone_hi, atr_h1=atr_h1
    )
    gate = desk_entry_gate(
        symbol=symbol,
        direction=direction,
        entry=entry_use,
        sl=sl_use,
        tp1=tp1,
        atr_h1=atr_h1,
        score=score,
        min_score=min_score,
        prev=prev,
        m15_close=m15_close,
        candle=candle,
    )
    if not gate.get("send"):
        return {**gate, "confluence": conf}
    if gate.get("reversal") and db_path:
        close_desk_reversal(db_path, gate.get("prev") or prev, exit_price=entry_use)
    text = format_desk_card(
        symbol=symbol,
        direction=direction,
        timeframe=timeframe,
        entry=entry_use,
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
        entry_low=zone_lo if zone_lo is not None else entry_use,
        entry_high=zone_hi if zone_hi is not None else (add_px if add_px is not None else entry_use),
        grade=str((conf or {}).get("grade") or ""),
        zone_line=str((conf or {}).get("zone_line") or ""),
        confirm_wait=str((conf or {}).get("confirm_wait") or ""),
        now_line=str((conf or {}).get("now_line") or ""),
    )
    key = str((conf or {}).get("setup_key") or "")
    if key:
        mark_live(
            key,
            {
                "symbol": symbol,
                "direction": direction,
                "timeframe": timeframe,
                "sl": gate.get("sl"),
                "zone_lo": zone_lo,
                "zone_hi": zone_hi,
                "grade": (conf or {}).get("grade"),
                "ts": now_ts,
            },
        )
    return {**gate, "text": text, "confluence": conf, "setup_key": key, "entry": entry_use}
