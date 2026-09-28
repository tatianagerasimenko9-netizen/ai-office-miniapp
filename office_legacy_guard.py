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
