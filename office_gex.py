"""GEX BTC/ETH з Deribit. Не ордер. Немає даних → DATA_UNAVAILABLE.

Не змінює ATR 80/90, Edge 85, MIN_RR. У Telegram не пише.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from office_market_data import _http_get_json

DERIBIT_BOOK = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
GEX_CURRENCIES = ("BTC", "ETH")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _unavailable(currency: str, reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "DATA_UNAVAILABLE",
        "currency": str(currency or "").upper(),
        "reason": reason,
        "call_gex": None,
        "put_gex": None,
        "net_gex": None,
        "flip": None,
        "n": 0,
    }


def summarize_deribit_book(rows: Any, *, currency: str) -> Dict[str, Any]:
    """Сумарний gamma×OI (грубий GEX). Порожній список — DATA_UNAVAILABLE."""
    cur = str(currency or "").upper()
    if not isinstance(rows, list) or not rows:
        return _unavailable(cur, "порожня книга Deribit")
    call_g = 0.0
    put_g = 0.0
    n = 0
    for item in rows:
        if not isinstance(item, dict):
            continue
        inst = str(item.get("instrument_name") or "")
        if f"{cur}-" not in inst:
            continue
        gamma = _f(item.get("greeks", {}).get("gamma") if isinstance(item.get("greeks"), dict) else item.get("gamma"))
        oi = _f(item.get("open_interest"))
        if gamma is None or oi is None or oi <= 0:
            continue
        contrib = gamma * oi
        n += 1
        if inst.endswith("-C"):
            call_g += contrib
        elif inst.endswith("-P"):
            put_g += contrib
    if n <= 0:
        return _unavailable(cur, "немає gamma/OI в книзі")
    net = call_g - put_g
    return {
        "ok": True,
        "status": "OK",
        "currency": cur,
        "reason": "",
        "call_gex": call_g,
        "put_gex": put_g,
        "net_gex": net,
        "flip": "call" if net > 0 else "put",
        "n": n,
    }


def fetch_gex(currency: str = "BTC") -> Dict[str, Any]:
    """Публічний Deribit. Мережа закрита / 4xx → DATA_UNAVAILABLE, без винятку наверх."""
    cur = str(currency or "BTC").upper().replace("USDT", "")
    if cur not in GEX_CURRENCIES:
        return _unavailable(cur, "лише BTC/ETH")
    try:
        raw = _http_get_json(DERIBIT_BOOK, {"currency": cur, "kind": "option"})
    except Exception as exc:
        return _unavailable(cur, f"{type(exc).__name__}")
    result = raw.get("result") if isinstance(raw, dict) else None
    return summarize_deribit_book(result, currency=cur)


def fetch_gex_btc_eth() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for cur in GEX_CURRENCIES:
        out[cur] = fetch_gex(cur)
    return out


def gex_log_line(pack: Dict[str, Any]) -> str:
    """Один рядок у лог Worker, не в чат."""
    bits: List[str] = []
    for cur in GEX_CURRENCIES:
        row = pack.get(cur) if isinstance(pack, dict) else None
        if not isinstance(row, dict):
            bits.append(f"{cur}=DATA_UNAVAILABLE")
            continue
        if not row.get("ok"):
            bits.append(f"{cur}={row.get('status')}")
            continue
        bits.append(f"{cur} net={row.get('net_gex'):.4g} n={row.get('n')}")
    return "[gex] " + " ".join(bits)
