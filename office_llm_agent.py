from __future__ import annotations

import os
from typing import Any, Dict

import httpx


def ask_agent(
    agent_key: str,
    system_prompt: str,
    user_context: str,
    max_tokens: int = 150,
) -> str:
    """
    Lightweight Anthropic adapter for agent-style replies.
    Returns empty string on any failure (graceful fallback).
    """
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return ""

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": "claude-sonnet-4-6",
            "max_tokens": int(max_tokens),
            "system": str(system_prompt or ""),
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"agent_key: {agent_key}\n"
                        f"context:\n{user_context}"
                    ),
                }
            ],
        }

        with httpx.Client(timeout=20.0) as client:
            resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("content")
        if not isinstance(content, list):
            return ""
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                txt = item.get("text")
                if isinstance(txt, str) and txt.strip():
                    parts.append(txt.strip())
        return "\n".join(parts).strip()
    except Exception:
        return ""
