"""Мова AI Office для користувача: коротко, просто, українською, кожен висновок — з цифрою. Перевірка (лінт) для текстів повідомлень і карток.

Заборонено у тексті для людини: англійський жаргон там, де є українська (COUNTER-MARKET, liquidity sweep, bullish regime...), і «воду» без цифр
(«біля хорошої зони», «сильний рівень», «BTC слабшає», «є підтвердження», «можливий ведмежий сценарій»). Складні розрахунки лишаються всередині."""
from __future__ import annotations

import re
from typing import List

JARGON = ("counter-market", "with market", "liquidity", "sweep", "bullish", "bearish", "regime", "risk-off", "risk-on", "displacement", "order block",
          "breaker", "fvg", "ote", "choch", "bos", "sfp", "atr", "funding", "open interest", "heatmap", "gex", "squeeze", "no trade", "setup", "confluence")
WATER = ("біля хорошої зони", "біля важливого рівня", "сильний рівень", "btc слабшає", "btc росте", "є підтвердження", "можливий ведмежий сценарій",
         "можливий бичачий сценарій", "виглядає слабким", "виглядає сильним", "велика ліквідність", "великий обсяг", "близько стопа", "біля підтримки", "біля опору")
ALLOW = ("USDT", "USD", "TP1", "TP2", "TP3", "SL", "LONG", "SHORT", "BTC", "ETH", "RR", "M1", "M5", "M15", "H1", "H4", "D1")   # прийнятні скорочення (тікери, позначки цілей)


def problems(text: str) -> List[str]:
    """Список порушень мови: жаргон і вода. Порожній — текст відповідає стандарту."""
    low = str(text or "").lower()
    out: List[str] = []
    for j in JARGON:
        if re.search(r"(?<![a-zа-я])" + re.escape(j) + r"(?![a-zа-я])", low):
            out.append(f"жаргон: {j}")
    for w in WATER:
        if w in low:
            out.append(f"вода без цифри: «{w}»")
    return out


def max_lines_ok(text: str, limit: int = 12) -> bool:
    return len([ln for ln in str(text or "").splitlines() if ln.strip()]) <= limit
