"""
Style QA Gate (MASTER п.27) — легке полірування видимих реплік агентів.

Не викликає LLM: евристики проти «корпоративу» й службових тегів у чаті.
"""

from __future__ import annotations

import re
from typing import List

# Максимум символів на одну репліку агента (читабельність Telegram).
MAX_AGENT_CHARS = 520

_BANNED_LEADING_PATTERNS = (
    r"^\s*RISK\s*:",
    r"^\s*FINAL\s+DECISION\s*:",
    r"^\s*STATUS\s*REPORT\s*:",
    r"^\s*EXECUTION\s+REPORT\s*:",
)

_CORPORATE_FRAGMENTS = (
    "participation rate",
    "deliverable",
    "circle back",
    "moving forward",
    "synergy",
    "low-hanging fruit",
)


def style_qa_violations(text: str) -> List[str]:
    """Список порушень до логів / дебагу (до полірування)."""
    raw = text or ""
    v: List[str] = []
    if len(raw) > MAX_AGENT_CHARS:
        v.append("over_length")
    low = raw.lower()
    for frag in _CORPORATE_FRAGMENTS:
        if frag in low:
            v.append(f"corporate:{frag}")
    for pat in _BANNED_LEADING_PATTERNS:
        if re.search(pat, raw, flags=re.I | re.MULTILINE):
            v.append("banned_label")
            break
    return v


def polish_agent_message(text: str, *, max_chars: int = MAX_AGENT_CHARS) -> str:
    """
    Прибирає заборонені префікси, «корпоратив», зайві пробіли; обрізає надто довгі репліки.
    """
    t = (text or "").strip()
    if not t:
        return t

    for pat in _BANNED_LEADING_PATTERNS:
        t = re.sub(pat, "", t, flags=re.I | re.MULTILINE).strip()

    low = t.lower()
    for frag in _CORPORATE_FRAGMENTS:
        if frag in low:
            t = re.sub(re.escape(frag), "", t, flags=re.I)
            low = t.lower()

    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    if len(t) <= max_chars:
        return t

    cut = t[: max_chars - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip() + "…"
