"""Каталог команд офісу. Лише опис, без ордерів і без спаму в Telegram."""
from __future__ import annotations

from typing import List, Tuple

# Команда → що робить. Не шаблон відповіді агента.
COMMANDS: List[Tuple[str, str]] = [
    ("/chart SYMBOL", "PNG графіка на запит; немає свічок → DATA_UNAVAILABLE"),
    ("/stats", "журнал сигналів osig-; n<20 → «мало даних»"),
    ("/review", "розбір без позиції; не /position"),
    ("/position", "підтверджена угода Тетяни (entry+SL+status)"),
]


def catalog_log_line() -> str:
    bits = [name for name, _ in COMMANDS]
    return "[commands] " + " ".join(bits)
