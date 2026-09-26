"""Статистика журналу сигналів офісу (osig-). Не ордер, не /position.

Менше MIN_GROUP у групі → «мало даних». Немає рядків → DATA_UNAVAILABLE.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from office_bridge import OFFICE_SIGNAL_SETUP, _fetchall, _parse_journal_ts, is_confirmed_position_row
from office_rsi_heat import RSI_LONG_HOT

DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
MIN_GROUP = 20
RSI_PEAK_EXTREME = 92.0


def kyiv_session(ts: Any) -> str:
    dt = _parse_journal_ts(ts)
    if dt is None:
        return "UNKNOWN"
    h = dt.astimezone(ZoneInfo("Europe/Kyiv")).hour
    if 3 <= h < 11:
        return "ASIA"
    if 11 <= h < 16:
        return "LONDON"
    if 16 <= h < 24:
        return "NY"
    return "OFFHOURS"


def classify_setup(setup_note: Any, extra: Optional[Dict[str, Any]] = None) -> str:
    blob = f"{setup_note or ''} {json.dumps(extra or {}, ensure_ascii=False)}".upper()
    if "PUMP" in blob and "DUMP" not in blob:
        return "PUMP"
    if "DUMP" in blob:
        return "DUMP"
    if "REENTRY" in blob or "SWEEP_REENTRY" in blob:
        return "REENTRY"
    if "SC-OTE" in blob or "SC_OTE" in blob or "OTE" in blob:
        return "SC-OTE"
    if extra and extra.get("pattern"):
        return str(extra.get("pattern") or "PATTERN")[:24]
    if extra and extra.get("patterns"):
        pats = extra.get("patterns")
        if isinstance(pats, list) and pats:
            return str(pats[0])[:24]
    if setup_note:
        return str(setup_note)[:24]
    return "OTHER"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _is_office_signal(trade_id: Any, setup_name: Any, entry_reason: Any) -> bool:
    tid = str(trade_id or "")
    setup = str(setup_name or "").upper()
    reason = str(entry_reason or "").lower()
    if tid.startswith("osig-"):
        return True
    if setup == OFFICE_SIGNAL_SETUP:
        return True
    if "office signal card" in reason:
        return True
    return False


def load_office_signal_rows(db_path: str) -> List[Dict[str, Any]]:
    try:
        raw = _fetchall(
            db_path,
            """
            SELECT trade_id, symbol, direction, status, outcome, pnl_pct, r_multiple,
                   timeframe, setup_name, entry_reason, context_json, ts_open_utc,
                   entry_price, stop_loss, take_profit, exit_price
            FROM trade_journal
            """,
            (),
        )
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in raw:
        (
            trade_id,
            symbol,
            direction,
            status,
            outcome,
            pnl_pct,
            r_multiple,
            timeframe,
            setup_name,
            entry_reason,
            context_json,
            ts_open,
            entry_price,
            stop_loss,
            take_profit,
            exit_price,
        ) = r
        if is_confirmed_position_row(entry_reason, setup_name, trade_id):
            continue
        if not _is_office_signal(trade_id, setup_name, entry_reason):
            continue
        ctx: Dict[str, Any] = {}
        try:
            obj = json.loads(str(context_json or "{}"))
            if isinstance(obj, dict):
                ctx = obj
        except Exception:
            ctx = {}
        out.append(
            {
                "trade_id": trade_id,
                "symbol": str(symbol or "").upper(),
                "direction": str(direction or "").upper(),
                "status": str(status or "").upper(),
                "outcome": str(outcome or "").upper(),
                "pnl_pct": _f(pnl_pct),
                "r_multiple": _f(r_multiple),
                "timeframe": str(timeframe or ctx.get("timeframe") or "").upper() or "?",
                "setup": classify_setup(ctx.get("setup") or setup_name, ctx),
                "session": str(ctx.get("session") or kyiv_session(ts_open)),
                "mfe": _f(ctx.get("mfe_pct")),
                "mae": _f(ctx.get("mae_pct")),
                "rsi_entry": _f(ctx.get("rsi_at_signal") or ctx.get("rsi_h1")),
                "rsi_peak": _f(ctx.get("rsi_peak")),
                "sweep_then_tp": bool(ctx.get("sweep_then_tp")),
                "entry": _f(entry_price),
                "sl": _f(stop_loss),
                "tp": _f(take_profit),
                "exit": _f(exit_price),
                "ts_open": ts_open,
            }
        )
    return out


def _infer_sweep_then_tp(row: Dict[str, Any]) -> bool:
    if row.get("sweep_then_tp"):
        return True
    e, sl, tp, mae, mfe = row.get("entry"), row.get("sl"), row.get("tp"), row.get("mae"), row.get("mfe")
    if None in (e, sl) or e == 0:
        return False
    stop_pct = abs(float(e) - float(sl)) / abs(float(e)) * 100.0
    if mae is None or stop_pct <= 0:
        return False
    swept = abs(float(mae)) + 1e-9 >= stop_pct
    if not swept:
        return False
    if str(row.get("outcome") or "") in ("WIN", "TP", "TP1", "TP2"):
        return True
    if tp is not None and mfe is not None:
        tp_pct = abs(float(tp) - float(e)) / abs(float(e)) * 100.0
        if abs(float(mfe)) + 1e-9 >= tp_pct * 0.9:
            return True
    return False


def _group_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if n < MIN_GROUP:
        return {"n": n, "ok": False, "line": f"n={n} мало даних"}
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    if len(closed) < MIN_GROUP:
        return {"n": n, "closed": len(closed), "ok": False, "line": f"n={n} закр.{len(closed)} мало даних"}
    wins = sum(1 for r in closed if r.get("outcome") in ("WIN", "TP", "TP1", "TP2"))
    losses = sum(1 for r in closed if r.get("outcome") in ("LOSS", "SL"))
    rs = [float(r["r_multiple"]) for r in closed if r.get("r_multiple") is not None]
    mfes = [float(r["mfe"]) for r in closed if r.get("mfe") is not None]
    maes = [float(r["mae"]) for r in closed if r.get("mae") is not None]
    wr = wins / len(closed) * 100.0
    avg_r = sum(rs) / len(rs) if rs else None
    exp = sum(rs) / len(rs) if rs else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    avg_mae = sum(maes) / len(maes) if maes else None
    parts = [f"n={len(closed)}", f"WR {wr:.0f}%"]
    parts.append(f"R {avg_r:+.2f}" if avg_r is not None else "R DATA_UNAVAILABLE")
    parts.append(f"E {exp:+.2f}" if exp is not None else "E DATA_UNAVAILABLE")
    parts.append(f"MFE {avg_mfe:.2f}%" if avg_mfe is not None else "MFE DATA_UNAVAILABLE")
    parts.append(f"MAE {avg_mae:.2f}%" if avg_mae is not None else "MAE DATA_UNAVAILABLE")
    return {
        "n": n,
        "closed": len(closed),
        "ok": True,
        "wr": wr,
        "avg_r": avg_r,
        "expectancy": exp,
        "mfe": avg_mfe,
        "mae": avg_mae,
        "line": " · ".join(parts),
    }


def _bucket(rows: List[Dict[str, Any]], key: str) -> List[str]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(key) or "?")].append(r)
    lines = []
    for name in sorted(groups):
        m = _group_metrics(groups[name])
        lines.append(f"{name}: {m['line']}")
    return lines


def rsi_threshold_line(rows: List[Dict[str, Any]]) -> str:
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    if len(closed) < MIN_GROUP:
        return f"RSI 85/92: мало даних (n={len(closed)})"
    entries = [float(r["rsi_entry"]) for r in closed if r.get("rsi_entry") is not None]
    peaks = [float(r["rsi_peak"]) for r in closed if r.get("rsi_peak") is not None]
    if len(entries) < MIN_GROUP:
        return f"RSI 85/92: мало даних (rsi n={len(entries)})"
    hot = sum(1 for x in entries if x >= RSI_LONG_HOT)
    ext = sum(1 for x in peaks if x >= RSI_PEAK_EXTREME)
    avg_e = sum(entries) / len(entries)
    avg_p = sum(peaks) / len(peaks) if peaks else None
    peak_txt = f"{avg_p:.1f}" if avg_p is not None else DATA_UNAVAILABLE
    return (
        f"RSI вхід середнє {avg_e:.1f} (≥{RSI_LONG_HOT:.0f}: {hot}/{len(entries)}) · "
        f"пік середнє {peak_txt} (≥{RSI_PEAK_EXTREME:.0f}: {ext}/{len(peaks) or 0})"
    )


def sweep_calibration_line(rows: List[Dict[str, Any]]) -> str:
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    if len(closed) < MIN_GROUP:
        return f"Свіп→TP: мало даних (n={len(closed)})"
    n = sum(1 for r in closed if _infer_sweep_then_tp(r))
    return f"Свіп стопа, потім TP: {n}/{len(closed)}"


def build_stats_report(db_path: str) -> Dict[str, Any]:
    rows = load_office_signal_rows(db_path)
    if not rows:
        return {
            "ok": False,
            "data_status": DATA_UNAVAILABLE,
            "message": "📊 /stats\nDATA_UNAVAILABLE — у журналі немає сигналів офісу.",
            "one_liner": "Сигнали: DATA_UNAVAILABLE",
            "n": 0,
        }
    overall = _group_metrics(rows)
    lines = [
        "📊 /stats — журнал сигналів (не /position)",
        f"Усього карток: {len(rows)} · {overall['line']}",
        "Сетап:",
        *("  " + x for x in _bucket(rows, "setup")),
        "Сесія:",
        *("  " + x for x in _bucket(rows, "session")),
        "ТФ:",
        *("  " + x for x in _bucket(rows, "timeframe")),
        "Напрямок:",
        *("  " + x for x in _bucket(rows, "direction")),
        sweep_calibration_line(rows),
        rsi_threshold_line(rows),
    ]
    one = f"Сигнали: {overall['line']}"
    return {
        "ok": True,
        "data_status": "DATA_OK" if overall.get("ok") else "THIN",
        "message": "\n".join(lines),
        "one_liner": one,
        "n": len(rows),
        "rows": rows,
    }


def format_stats_one_liner(db_path: str) -> str:
    return str(build_stats_report(db_path).get("one_liner") or "Сигнали: DATA_UNAVAILABLE")
