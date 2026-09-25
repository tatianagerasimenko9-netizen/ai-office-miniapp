"""T8: діагностика T7 connected=false без очікування forceOrder.

Не створює ENTER. Пояснює холодний знімок vs обрив vs connecting.
"""
from __future__ import annotations

import socket
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from office_btc_liquidations import FORCE_ORDER_WS_URL, WS_FRESH_SEC


def classify_book_state(snap: Dict[str, Any]) -> str:
    connected = bool(snap.get("connected"))
    loop = bool(snap.get("loop_started"))
    rec = int(snap.get("reconnects") or 0)
    err = str(snap.get("last_error") or "")
    if connected:
        return "connected"
    if rec > 0 or err:
        return "disconnected"
    if loop:
        return "connecting"
    return "idle_cold"


def diagnose_force_order_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Чому Mini App бачить connected=false — без припущення про ліквідації."""
    state = classify_book_state(snap)
    rec = int(snap.get("reconnects") or 0)
    err = str(snap.get("last_error") or "")
    if state == "idle_cold":
        why = (
            "Знімок холодний: цикл WS у цьому процесі не стартував "
            "(reconnects=0, немає last_error). Це НЕ означає, що на ринку не було ліквідацій — "
            "книга просто не підключена. Часто лог пишеться з порожньої книги до create_task."
        )
    elif state == "connecting":
        why = "Цикл стартував, сокет ще не mark_connected (handshake). forceOrder не потрібен."
    elif state == "disconnected":
        why = (
            f"Сокет відпав (reconnects={rec}). last_error={err or 'н/д'}. "
            "Механізм reconnect окремий від наявності ліквідацій."
        )
    else:
        why = "Потік підключений. Відсутність подій = немає forceOrder, не обрив."
    return {
        "state": state,
        "why_connected_false": why if state != "connected" else "",
        "ws_fresh_sec": WS_FRESH_SEC,
        "reconnects": rec,
        "last_error": err,
        "creates_enter": False,
        "needs_force_order_to_prove_ws": False,
        "idle_cold_means_no_liquidations": False,
    }


def probe_fstream_tcp(url: str = FORCE_ORDER_WS_URL, timeout_sec: float = 5.0) -> Dict[str, Any]:
    """TCP до хоста forceOrder. Не чекає ліквідацію, ордерів немає."""
    parsed = urlparse(url)
    host = parsed.hostname or "fstream.binance.com"
    port = int(parsed.port or 443)
    ok = False
    err = ""
    try:
        with socket.create_connection((host, port), timeout=float(timeout_sec)):
            ok = True
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    return {
        "host": host,
        "port": port,
        "tcp_ok": ok,
        "error": err,
        "creates_enter": False,
        "proves_force_order_stream": False,
        "note": "TCP OK ≠ є ліквідації; TCP fail пояснює connected=false/reconnect.",
    }
