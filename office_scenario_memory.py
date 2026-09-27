"""Пам'ять сценаріїв Лева: попередній LONG/SHORT, ТФ, статус, співіснування.

Недосягнутий TP сам не скасовує сценарій.
Протилежні сигнали одного горизонту — не два одночасні дозволи на вхід.
Різні ТФ тієї самої монети можуть співіснувати.
BTC-контекст лише коли є підтверджені дані.
Не ордер.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SCENARIO_LIVE = (
    "WATCHING",
    "ACTIVE",
    "HIT_ENTRY",
    "HIT_TP1",
    "HIT_TP2",
    "CONFIRMED",
    "CONFIRMATION_PENDING",
    "ZONE_REACHED",
)


def normalize_tf(tf: Any) -> str:
    u = str(tf or "").strip().upper().replace(" ", "")
    aliases = {
        "1H": "H1",
        "60": "H1",
        "60M": "H1",
        "1M": "M1",
        "5M": "M5",
        "15M": "M15",
        "4H": "H4",
        "240": "H4",
        "1D": "D1",
        "D": "D1",
        "1W": "W",
    }
    if u in aliases:
        return aliases[u]
    if u.endswith("USDT"):
        return ""
    return u


def parse_note_meta(note: Any) -> Dict[str, str]:
    raw = str(note or "")
    out = {"origin": "", "timeframe": "", "okey": "", "ckey": ""}
    m_o = re.search(r"origin=([^\s]+)", raw, flags=re.I)
    m_t = re.search(r"(?:tf|timeframe)=([^\s]+)", raw, flags=re.I)
    m_k = re.search(r"okey=([^\s]+)", raw, flags=re.I)
    m_c = re.search(r"ckey=([^\s]+)", raw, flags=re.I)
    if m_o:
        out["origin"] = str(m_o.group(1) or "").strip().lower()
    if m_t:
        out["timeframe"] = normalize_tf(m_t.group(1))
    if m_k:
        out["okey"] = m_k.group(1)
    if m_c:
        out["ckey"] = m_c.group(1)
    if not out["origin"] and out["okey"]:
        parts = out["okey"].split("|")
        if len(parts) >= 5:
            out["origin"] = str(parts[4] or "").strip().lower()
        if len(parts) >= 6 and not out["timeframe"]:
            out["timeframe"] = normalize_tf(parts[5])
    return out


def stamp_scenario_note(
    note: Any,
    *,
    origin: str = "",
    timeframe: str = "",
    origin_key: str = "",
) -> str:
    raw = str(note or "").strip()
    meta = parse_note_meta(raw)
    extra: List[str] = []
    if origin and not meta.get("origin"):
        extra.append(f"origin={str(origin).strip().lower()}")
    if timeframe and not meta.get("timeframe"):
        extra.append(f"tf={normalize_tf(timeframe)}")
    if origin_key and not meta.get("okey"):
        extra.append(f"okey={origin_key}")
    if not extra:
        return raw
    return (raw + (" " if raw else "") + " ".join(extra)).strip()[:2000]


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _zone_close(a: Any, b: Any, tol: float = 1e-8) -> bool:
    x, y = _f(a), _f(b)
    if x is None or y is None:
        return True
    if x == 0 and y == 0:
        return True
    return abs(x - y) <= max(tol, abs(x) * 1e-8)


def row_matches_scenario(
    row: Dict[str, Any],
    *,
    symbol: str,
    direction: str,
    timeframe: str = "",
    origin: str = "",
    zone_lo: Any = None,
    zone_hi: Any = None,
    signal_id: str = "",
) -> bool:
    """Не всі ACTIVE символу — лише цей напрям/ТФ/origin/зона або signal_id."""
    if not isinstance(row, dict):
        return False
    if str(row.get("symbol") or "").upper() != str(symbol or "").upper():
        return False
    sid = str(signal_id or "").strip()
    if sid and str(row.get("signal_id") or "") == sid:
        return True
    if str(row.get("direction") or "").upper() != str(direction or "").upper():
        return False
    meta = parse_note_meta(row.get("analysis_note"))
    want_tf = normalize_tf(timeframe)
    got_tf = meta.get("timeframe") or normalize_tf(row.get("timeframe"))
    if want_tf and got_tf and want_tf != got_tf:
        return False
    want_o = str(origin or "").strip().lower()
    got_o = str(meta.get("origin") or "").strip().lower()
    if want_o and got_o and want_o != got_o:
        return False
    if zone_lo is not None and not _zone_close(row.get("entry_low"), zone_lo):
        return False
    if zone_hi is not None and not _zone_close(row.get("entry_high"), zone_hi):
        return False
    return True


def memory_for_symbol(rows: List[Dict[str, Any]], symbol: str) -> Dict[str, Any]:
    """Попередні LONG/SHORT тієї самої монети: ТФ, статус, причина."""
    want = str(symbol or "").upper()
    items: List[Dict[str, Any]] = []
    for r in rows or []:
        if str(r.get("symbol") or "").upper() != want:
            continue
        meta = parse_note_meta(r.get("analysis_note"))
        items.append(
            {
                "signal_id": r.get("signal_id"),
                "direction": str(r.get("direction") or "").upper(),
                "status": str(r.get("status") or "").upper(),
                "timeframe": meta.get("timeframe") or normalize_tf(r.get("timeframe")) or "",
                "origin": meta.get("origin") or "",
                "outcome": r.get("outcome") or "",
                "note": str(r.get("analysis_note") or "")[:240],
            }
        )
    return {"symbol": want, "rows": items}


def missed_tp_cancels_scenario() -> bool:
    """Недосягнутий TP сам по собі сценарій не скасовує."""
    return False


def btc_context_usable(ctx: Any) -> bool:
    if not isinstance(ctx, dict):
        return False
    if str(ctx.get("data_status") or "").upper() in ("DATA_UNAVAILABLE", "UNAVAILABLE", ""):
        if ctx.get("change_pct") is None and ctx.get("price") is None:
            return False
    if ctx.get("change_pct") is None and not ctx.get("use_in_narrative"):
        st = str(ctx.get("data_status") or "").upper()
        return st in ("DATA_OK", "OK")
    return bool(ctx.get("use_in_narrative") or ctx.get("change_pct") is not None or ctx.get("price") is not None)


def gate_entry_vs_memory(
    rows: List[Dict[str, Any]],
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    missed_tp: bool = False,
) -> Dict[str, Any]:
    """Один горизонт — не два протилежні дозволи. missed_tp ігнорується як скасування."""
    _ = missed_tp
    if missed_tp_cancels_scenario():
        return {"allow_entry": False, "reason": "unreachable"}
    side = str(direction or "").upper()
    tf = normalize_tf(timeframe)
    opposite = "SHORT" if side == "LONG" else "LONG"
    coexist: List[Dict[str, Any]] = []
    conflict: List[Dict[str, Any]] = []
    for r in rows or []:
        if str(r.get("symbol") or "").upper() != str(symbol or "").upper():
            continue
        st = str(r.get("status") or "").upper()
        if st not in SCENARIO_LIVE:
            continue
        d = str(r.get("direction") or "").upper()
        meta = parse_note_meta(r.get("analysis_note"))
        rtf = meta.get("timeframe") or normalize_tf(r.get("timeframe"))
        item = {
            "signal_id": r.get("signal_id"),
            "direction": d,
            "status": st,
            "timeframe": rtf,
            "coexist": bool(rtf and tf and rtf != tf),
        }
        if d == opposite and tf and rtf == tf:
            conflict.append(item)
        elif d == opposite and (not tf or not rtf or rtf != tf):
            coexist.append(item)
    if conflict:
        return {
            "allow_entry": False,
            "coexist": False,
            "reason": "протилежний сценарій того самого горизонту вже живий — не два входи",
            "conflict": conflict,
            "memory": memory_for_symbol(rows, symbol),
        }
    return {
        "allow_entry": True,
        "coexist": bool(coexist),
        "reason": "співіснування різних ТФ" if coexist else "немає конфлікту горизонту",
        "conflict": [],
        "peers": coexist,
        "memory": memory_for_symbol(rows, symbol),
    }


def apply_confirmed_status(
    db_path: str,
    *,
    symbol: str,
    direction: str,
    timeframe: str = "",
    origin: str = "desk",
    zone_lo: Any = None,
    zone_hi: Any = None,
    signal_id: str = "",
    price: Any = None,
) -> List[str]:
    """CONFIRMED лише для рядків цього сценарію."""
    from office_bridge import signal_get_active, signal_update

    updated: List[str] = []
    for row in signal_get_active(db_path) or []:
        if not row_matches_scenario(
            row,
            symbol=symbol,
            direction=direction,
            timeframe=timeframe,
            origin=origin,
            zone_lo=zone_lo,
            zone_hi=zone_hi,
            signal_id=signal_id,
        ):
            continue
        sid = str(row.get("signal_id") or "")
        if not sid:
            continue
        note = stamp_scenario_note(
            str(row.get("analysis_note") or "")
            + " confirm_sent=1"
            + (f" confirmed_px={price}" if price is not None else ""),
            origin=origin,
            timeframe=timeframe,
        )
        signal_update(db_path, signal_id=sid, status="CONFIRMED", analysis_note=note[:2000])
        updated.append(sid)
    return updated
