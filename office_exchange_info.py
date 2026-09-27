"""Binance Futures exchangeInfo: tickSize / stepSize на символ.

Кеш. Немає метаданих — fail-closed (без розміру і без « round як на біржі»).
Не змінює ATR/Edge/MIN_RR. Не ордер.
"""
from __future__ import annotations

import json
import os
import sys
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen

FAPI_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
CACHE_TTL_SEC = 3600.0

# Лише для офлайн-тестів (OFFICE_EXINFO_SEED=1 або scripts/test_*).
# Не є Live-біржею і не підставляється в прод без явного seed.
_SEED: Dict[str, Dict[str, str]] = {
    "BTCUSDT": {"tickSize": "0.10", "stepSize": "0.001"},
    "ETHUSDT": {"tickSize": "0.01", "stepSize": "0.001"},
    "XAUUSDT": {"tickSize": "0.01", "stepSize": "0.001"},
    "MANTAUSDT": {"tickSize": "0.000001", "stepSize": "0.1"},
}

_CACHE: Dict[str, Any] = {"ts": 0.0, "by_sym": {}, "fetched": False, "ok": False}


def reset_exchange_info() -> None:
    _CACHE["ts"] = 0.0
    _CACHE["by_sym"] = {}
    _CACHE["fetched"] = False
    _CACHE["ok"] = False


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        x = v if isinstance(v, Decimal) else Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if x.is_nan() or x <= 0:
        return None
    return x


def seed_allowed() -> bool:
    if str(os.getenv("OFFICE_EXINFO_FORCE_EMPTY") or "").strip() in ("1", "true", "YES"):
        return False
    if str(os.getenv("OFFICE_EXINFO_SEED") or "").strip() in ("1", "true", "YES"):
        return True
    argv = " ".join(sys.argv)
    return "test_" in argv or "/scripts/test" in argv


def _force_empty() -> bool:
    return str(os.getenv("OFFICE_EXINFO_FORCE_EMPTY") or "").strip() in ("1", "true", "YES")


def _apply_seed() -> Dict[str, Dict[str, Decimal]]:
    out: Dict[str, Dict[str, Decimal]] = {}
    for sym, row in _SEED.items():
        t, s = _dec(row.get("tickSize")), _dec(row.get("stepSize"))
        if t is None or s is None:
            continue
        out[sym] = {"tickSize": t, "stepSize": s}
    return out


def _parse_info(payload: Any) -> Dict[str, Dict[str, Decimal]]:
    out: Dict[str, Dict[str, Decimal]] = {}
    if not isinstance(payload, dict):
        return out
    for item in payload.get("symbols") or []:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").upper()
        if not sym:
            continue
        tick = step = None
        for flt in item.get("filters") or []:
            if not isinstance(flt, dict):
                continue
            ft = str(flt.get("filterType") or "")
            if ft == "PRICE_FILTER":
                tick = _dec(flt.get("tickSize"))
            elif ft == "LOT_SIZE":
                step = _dec(flt.get("stepSize"))
        if tick is not None and step is not None:
            out[sym] = {"tickSize": tick, "stepSize": step}
    return out


def _fetch_raw() -> Any:
    req = Request(
        FAPI_EXCHANGE_INFO,
        headers={
            "User-Agent": "Mozilla/5.0 (AI-Office exchangeInfo)",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def refresh_exchange_info(*, force: bool = False) -> Dict[str, Any]:
    """Оновлення кешу. Порожній fetch — fail-closed, без тихого seed у прод."""
    now = time.time()
    if not force and _CACHE.get("fetched") and (now - float(_CACHE.get("ts") or 0)) < CACHE_TTL_SEC:
        return {"ok": bool(_CACHE.get("ok")), "cached": True, "n": len(_CACHE.get("by_sym") or {})}
    if _force_empty():
        reset_exchange_info()
        _CACHE["fetched"] = True
        _CACHE["ts"] = now
        _CACHE["ok"] = False
        return {"ok": False, "reason": "EXCHANGE_INFO_UNAVAILABLE", "forced": True}
    if seed_allowed():
        parsed = _apply_seed()
        _CACHE["by_sym"] = parsed
        _CACHE["fetched"] = True
        _CACHE["ts"] = now
        _CACHE["ok"] = bool(parsed)
        _CACHE["seeded"] = True
        return {"ok": bool(parsed), "n": len(parsed), "seeded": True, "reason": None}
    parsed: Dict[str, Dict[str, Decimal]] = {}
    fetched_ok = False
    try:
        parsed = _parse_info(_fetch_raw())
        fetched_ok = bool(parsed)
    except Exception as exc:
        parsed = {}
        fetched_ok = False
        _CACHE["error"] = f"{type(exc).__name__}"
    if not fetched_ok and seed_allowed():
        parsed = _apply_seed()
        _CACHE["seeded"] = True
    else:
        _CACHE["seeded"] = False
    _CACHE["by_sym"] = parsed
    _CACHE["fetched"] = True
    _CACHE["ts"] = now
    _CACHE["ok"] = bool(parsed)
    return {
        "ok": bool(parsed),
        "n": len(parsed),
        "seeded": bool(_CACHE.get("seeded")),
        "reason": None if parsed else "EXCHANGE_INFO_UNAVAILABLE",
    }


def get_symbol_filters(symbol: str) -> Dict[str, Any]:
    """Фактичні PRICE_FILTER.tickSize і LOT_SIZE.stepSize. Інакше ok=False."""
    deny = {
        "ok": False,
        "tickSize": None,
        "stepSize": None,
        "reason": "EXCHANGE_INFO_UNAVAILABLE",
        "symbol": str(symbol or "").upper(),
    }
    sym = str(symbol or "").upper().strip()
    if not sym:
        return deny
    refresh_exchange_info()
    row = (_CACHE.get("by_sym") or {}).get(sym)
    if not row and seed_allowed() and not _force_empty():
        if "BTC" in sym:
            t = Decimal("0.10")
        elif "ETH" in sym or "XAU" in sym or "PAXG" in sym:
            t = Decimal("0.01")
        else:
            t = Decimal("0.000001")
        return {
            "ok": True,
            "tickSize": t,
            "stepSize": Decimal("0.001"),
            "reason": "test_seed_generic",
            "symbol": sym,
            "seeded": True,
        }
    if not row:
        return deny
    tick, step = row.get("tickSize"), row.get("stepSize")
    if tick is None or step is None:
        return deny
    return {
        "ok": True,
        "tickSize": tick,
        "stepSize": step,
        "reason": "ok",
        "symbol": sym,
        "seeded": bool(_CACHE.get("seeded")),
    }
