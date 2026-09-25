"""Єдиний знімок стану офісу для Mini App.

Шари не змішуються: signal / watching / paper / live (/position).
T7 — фактичні forceOrder з office_events, не heatmap.
Не змінює journal і WATCHING.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from office_atr_policy import ATR_POLICY_DOC, GERCHIK_TREND_ENTRY_BLOCK_PCT, T0_ENTRY_BLOCK_PCT
from office_bridge import is_confirmed_position_row, signal_get_active
from office_session_radar import KIND_LIVE, KIND_PAPER, KIND_SIGNAL, KIND_WATCHING


def _payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        obj = json.loads(str(raw or "{}"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def build_desk_state(
    db_path: str,
    *,
    watching_rows: List[Dict[str, Any]] | None = None,
    journal_rows: List[Dict[str, Any]] | None = None,
    force_order_events: List[Dict[str, Any]] | None = None,
    paper_trades: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    watching: List[Dict[str, Any]] = []
    rows = watching_rows
    if rows is None:
        try:
            rows = [r for r in signal_get_active(db_path) if str(r.get("status") or "").upper() == "WATCHING"]
        except Exception:
            rows = []
    for r in rows or []:
        watching.append(
            {
                "kind": KIND_WATCHING,
                "signal_id": r.get("signal_id"),
                "symbol": r.get("symbol"),
                "direction": r.get("direction"),
                "entry_low": r.get("entry_low"),
                "entry_high": r.get("entry_high"),
                "note": str(r.get("analysis_note") or "")[:240],
            }
        )

    live: List[Dict[str, Any]] = []
    signals: List[Dict[str, Any]] = []
    for r in journal_rows or []:
        item = {
            "trade_id": r.get("trade_id"),
            "symbol": r.get("symbol"),
            "direction": r.get("direction"),
            "status": r.get("status"),
        }
        if is_confirmed_position_row(r.get("entry_reason"), r.get("setup_name"), r.get("trade_id")):
            item["kind"] = KIND_LIVE
            live.append(item)
        else:
            item["kind"] = KIND_SIGNAL
            signals.append(item)

    liqs: List[Dict[str, Any]] = []
    for ev in force_order_events or []:
        p = _payload(ev.get("payload_json") if isinstance(ev, dict) else ev)
        liqs.append(
            {
                "kind": "t7_force_order",
                "creates_enter": False,
                "connected": p.get("connected"),
                "events": p.get("events_in_window") or p.get("event_count"),
                "asof": p.get("asof_utc") or ev.get("ts_utc"),
            }
        )

    paper = []
    for t in paper_trades or []:
        row = dict(t)
        row["kind"] = KIND_PAPER
        paper.append(row)

    return {
        "atr_policy": {
            "gerchik_entry_block_pct": GERCHIK_TREND_ENTRY_BLOCK_PCT,
            "t0_entry_block_pct": T0_ENTRY_BLOCK_PCT,
            "doc": ATR_POLICY_DOC,
            "thresholds_frozen_until_backtest": True,
        },
        "layers": {
            "watching": watching,
            "scenarios_signal": signals,
            "positions_live": live,
            "paper": paper,
            "liquidations_t7": liqs[:8],
        },
        "counts": {
            "watching": len(watching),
            "signals": len(signals),
            "live_positions": len(live),
            "paper": len(paper),
            "t7": len(liqs),
        },
        "mix_forbidden": True,
    }
