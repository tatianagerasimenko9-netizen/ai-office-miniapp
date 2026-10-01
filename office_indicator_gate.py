"""Вимикач впливу двох Pine-портів на рішення Лева.

ICT SMC HUNTER і PUMP & DUMP HUNTER тимчасово НЕ додають бали й НЕ підтверджують/блокують готовий сигнал,
поки їхня відповідність Pine не доведена (docs/pine-python-parity.md). Код, тести й parity-звірка лишаються.
Регресійний канал і вся інша аналітика Офісу працюють як раніше.
Повернути вплив після доведення: OFFICE_PINE_INFLUENCE=1 (або прибрати ключі з PINE_PORTS)."""
from __future__ import annotations

import os
from typing import Iterable, Tuple

PINE_PORTS: Tuple[str, ...] = ("pump_dump", "ict_hunter")
DISABLED_REASON = "ВИМКНЕНО: не впливає на рішення, доки відповідність Pine не доведена"


def pine_influence_enabled() -> bool:
    return os.getenv("OFFICE_PINE_INFLUENCE", "0").strip() == "1"


def is_active(key: str) -> bool:
    """True — індикатор має право впливати на рішення Лева."""
    return pine_influence_enabled() or str(key) not in PINE_PORTS


def active_keys(keys: Iterable[str]) -> Tuple[str, ...]:
    return tuple(k for k in keys if is_active(k))
