"""Legacy-шляхи створення сценаріїв підпорядковані висновку Лева.

Старий проактивний сканер парсить LLM-текст («entry:/sl:») і раніше одразу писав
ACTIVE. Тепер ACTIVE лише якщо lev_cycle повернув SEND у тому самому напрямку;
інакше сценарій зберігається як WATCHING (не план, без Telegram-вердикту).
OFFICE_LEGACY_ACTIVE_REQUIRES_LEV=0 повертає стару поведінку (для відкату).
"""
from __future__ import annotations

import os
from typing import Any, Dict

ENV = "OFFICE_LEGACY_ACTIVE_REQUIRES_LEV"


def legacy_requires_lev() -> bool:
    return os.getenv(ENV, "1").strip() != "0"


def legacy_scenario_status(cycle: Dict[str, Any], *, direction: str, enforce: bool = True) -> Dict[str, str]:
    if not enforce:
        return {"status": "ACTIVE", "reason": f"{ENV}=0 — стара поведінка", "note_prefix": ""}
    side = str(direction or "").upper()
    lev_side = str((cycle or {}).get("direction") or "").upper()
    if (cycle or {}).get("send") and lev_side == side:
        return {"status": "ACTIVE", "reason": "Лев підтвердив SEND", "note_prefix": ""}
    why = str((cycle or {}).get("reason") or "немає висновку Лева")
    if (cycle or {}).get("send") and lev_side != side:
        why = f"Лев бачить {lev_side}, LLM — {side}"
    action = str((cycle or {}).get("action") or "SKIP")
    return {
        "status": "WATCHING",
        "reason": f"{action}: {why}",
        "note_prefix": f"legacy proactive: Лев не підтвердив ({action}: {why})\n",
    }


def lev_cycle_for_symbol(db_path: str, symbol: str, price: Any = None) -> Dict[str, Any]:
    """Повний lev_cycle + shadow Risk Officer + журнал тези для legacy-шляхів (sync).

    Помилка або відсутність даних ніколи не дає SEND.
    """
    from office_lev_verdict import lev_cycle
    from office_market_data import fetch_candles

    ctx = {"data_status": "DATA_UNAVAILABLE"}
    try:
        bars = {}
        for tf, iv, n in (("H1", "1h", 48), ("H4", "4h", 48), ("M15", "15m", 96), ("D1", "1d", 30)):
            v = fetch_candles(symbol, iv, n)
            bars[tf] = v if isinstance(v, list) and v else None
        px = price
        if px is None and bars.get("M15"):
            px = (bars["M15"][-1] or {}).get("close")
        cyc = lev_cycle(
            symbol=symbol, price=px, timeframe="H1",
            candles_m15=bars["M15"], candles_h1=bars["H1"], candles_h4=bars["H4"],
            candles_d1=bars["D1"], candles_ltf=bars["M15"], candles_m5=bars["M15"],
            market_context=ctx,
        )
    except Exception as exc:
        return {"action": "SKIP", "send": False, "reason": f"lev_cycle error: {type(exc).__name__}"}
    from office_feed_quality import gate_send_on_fresh_data

    cyc = gate_send_on_fresh_data(cyc, bars["M15"], interval="15m")
    if db_path:
        try:
            from office_risk_context import apply_risk_officer

            cyc = apply_risk_officer(cyc, db_path=db_path, symbol=symbol, candles_ltf=bars["M15"], market_context=ctx)
        except Exception as exc:
            print(f"[risk] legacy review error {symbol}: {type(exc).__name__}: {exc}")
            from office_risk_context import enforce_enabled

            if enforce_enabled() and cyc.get("send"):
                cyc = {**cyc, "action": "WAIT", "send": False, "reason": "ризик-контроль недоступний"}
        try:
            from office_thesis_journal import record_thesis

            record_thesis(db_path, cyc, candles_by_tf=bars)
        except Exception as exc:
            print(f"[thesis] legacy journal error {symbol}: {type(exc).__name__}: {exc}")
    return cyc
