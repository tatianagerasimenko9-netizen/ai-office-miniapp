"""Пам'ять сценаріїв Лева: попередній LONG/SHORT, ТФ, статус, співіснування.

Недосягнутий TP сам не скасовує сценарій.
Протилежні сигнали одного горизонту — не два одночасні дозволи на вхід.
Різні ТФ тієї самої монети можуть співіснувати.
BTC-контекст лише коли є підтверджені дані.
Не ордер.
"""
from __future__ import annotations

import hashlib
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
    out = {"origin": "", "timeframe": "", "okey": "", "ckey": "", "scenario_id": "", "basis": ""}
    m_o = re.search(r"origin=([^\s]+)", raw, flags=re.I)
    m_t = re.search(r"(?:tf|timeframe)=([^\s]+)", raw, flags=re.I)
    m_k = re.search(r"okey=([^\s]+)", raw, flags=re.I)
    m_c = re.search(r"ckey=([^\s]+)", raw, flags=re.I)
    m_s = re.search(r"scenario_id=([^\s]+)", raw, flags=re.I)
    m_b = re.search(r"basis=([^\s]+)", raw, flags=re.I)
    if m_o:
        out["origin"] = str(m_o.group(1) or "").strip().lower()
    if m_t:
        out["timeframe"] = normalize_tf(m_t.group(1))
    if m_k:
        out["okey"] = m_k.group(1)
    if m_c:
        out["ckey"] = m_c.group(1)
    if m_s:
        out["scenario_id"] = m_s.group(1)
    if m_b:
        out["basis"] = m_b.group(1)
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
    scenario_id: str = "",
    basis: str = "",
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
    if scenario_id and not meta.get("scenario_id"):
        extra.append(f"scenario_id={scenario_id}")
    if basis and not meta.get("basis"):
        extra.append(f"basis={basis}")
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


def market_basis_key(confluence: Any) -> str:
    """Незалежна ринкова основа: тип/ТФ/джерельна свічка кожного збігу."""
    if not isinstance(confluence, dict):
        return ""
    cluster = confluence.get("cluster") if isinstance(confluence.get("cluster"), dict) else confluence
    members = cluster.get("members") if isinstance(cluster, dict) else None
    stable_parts: List[str] = []
    transient_parts: List[str] = []
    for item in members or []:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").strip().lower()
        tf = normalize_tf(item.get("tf"))
        origin_ts = str(item.get("origin_ts") or "").strip()
        if tag:
            part = f"{tag}:{tf}:{origin_ts}"
            if tag in ("sc_ote", "sweep"):
                transient_parts.append(part)
            else:
                stable_parts.append(part)
    parts = stable_parts or transient_parts
    if not parts:
        tags = cluster.get("tags") if isinstance(cluster, dict) else confluence.get("tags")
        parts = [str(x).strip().lower() for x in tags or [] if str(x).strip()]
    if not parts:
        return ""
    raw = "|".join(sorted(set(parts)))
    basis = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return basis


def zone_overlap_ratio(a_lo: Any, a_hi: Any, b_lo: Any, b_hi: Any) -> float:
    a, b, c, d = _f(a_lo), _f(a_hi), _f(b_lo), _f(b_hi)
    if None in (a, b, c, d):
        return 0.0
    assert a is not None and b is not None and c is not None and d is not None
    if a > b:
        a, b = b, a
    if c > d:
        c, d = d, c
    union = max(b, d) - min(a, c)
    if union <= 0:
        return 1.0 if _zone_close(a, c) else 0.0
    return max(0.0, min(b, d) - max(a, c)) / union


def canonical_scenario_id(
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    basis: str,
    zone_lo: Any,
    zone_hi: Any,
) -> str:
    raw = (
        f"{str(symbol or '').upper()}|{str(direction or '').upper()}|{normalize_tf(timeframe)}|"
        f"{str(basis or '')}|{_f(zone_lo)}|{_f(zone_hi)}"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"SCN|{str(symbol or '').upper()}|{str(direction or '').upper()}|{normalize_tf(timeframe)}|{digest}"


def scenario_identity_matches(
    row: Dict[str, Any],
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    basis: str,
    zone_lo: Any,
    zone_hi: Any,
    min_overlap: float = 0.9,
) -> bool:
    if not isinstance(row, dict):
        return False
    if str(row.get("symbol") or "").upper() != str(symbol or "").upper():
        return False
    if str(row.get("direction") or "").upper() != str(direction or "").upper():
        return False
    meta = parse_note_meta(row.get("analysis_note"))
    row_tf = meta.get("timeframe") or normalize_tf(row.get("timeframe"))
    if not row_tf or row_tf != normalize_tf(timeframe):
        return False
    row_basis = str(meta.get("basis") or row.get("basis") or "")
    if not basis or not row_basis or row_basis != basis:
        return False
    return zone_overlap_ratio(
        row.get("entry_low") if row.get("entry_low") is not None else row.get("zone_lo"),
        row.get("entry_high") if row.get("entry_high") is not None else row.get("zone_hi"),
        zone_lo,
        zone_hi,
    ) >= float(min_overlap)


def find_canonical_scenario(
    rows: List[Dict[str, Any]],
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    basis: str,
    zone_lo: Any,
    zone_hi: Any,
) -> Optional[Dict[str, Any]]:
    for row in rows or []:
        if scenario_identity_matches(
            row,
            symbol=symbol,
            direction=direction,
            timeframe=timeframe,
            basis=basis,
            zone_lo=zone_lo,
            zone_hi=zone_hi,
        ):
            return row
    return None


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
