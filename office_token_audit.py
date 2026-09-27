"""Аудит наявності секретів: set/missing, без значень."""
from __future__ import annotations

import os
from typing import Dict, List

FLAG_KEYS = (
    "TG_BOT_TOKEN",
    "TG_API_ID",
    "TG_API_HASH",
    "MAIN_CHAT_ID",
    "OFFICE_CHAT_ID",
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "NEWS_API_KEY",
    "OFFICE_DEPO_USDT",
    "RENDER_API_KEY",
)
AGENT_TOKEN_KEYS = (
    "AGENT_BOT_TOKEN_LEV",
    "AGENT_BOT_TOKEN_MAKS",
    "AGENT_BOT_TOKEN_NEWS",
    "AGENT_BOT_TOKEN_DARYNA",
    "AGENT_BOT_TOKEN_MARKO",
    "AGENT_BOT_TOKEN_OLESYA",
    "AGENT_BOT_TOKEN_MEMORY",
    "AGENT_BOT_TOKEN_PSYCH",
    "AGENT_BOT_TOKEN_DEV",
    "AGENT_BOT_TOKEN_MARICHKA",
)


def _present(name: str) -> bool:
    return bool(str(os.getenv(name) or "").strip())


def audit_flags() -> Dict[str, List[str]]:
    set_keys = [k for k in FLAG_KEYS if _present(k)]
    missing = [k for k in FLAG_KEYS if not _present(k)]
    agents_set = [k for k in AGENT_TOKEN_KEYS if _present(k)]
    agents_missing = [k for k in AGENT_TOKEN_KEYS if not _present(k)]
    return {
        "set": set_keys,
        "missing": missing,
        "agents_set": agents_set,
        "agents_missing": agents_missing,
    }


def audit_log_line() -> str:
    a = audit_flags()
    return (
        "[tokens] set="
        + ",".join(a["set"] or ["none"])
        + " missing="
        + ",".join(a["missing"] or ["none"])
        + " agents_set="
        + str(len(a["agents_set"]))
        + "/"
        + str(len(AGENT_TOKEN_KEYS))
    )
