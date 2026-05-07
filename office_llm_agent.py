from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import httpx

from office_market_data import (
    fetch_candles,
    fetch_funding_rate,
    fetch_liquidations_proxy,
    fetch_open_interest,
)


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_candles",
        "description": "Отримати OHLCV свічки для будь-якого символу на Binance Futures",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Символ наприклад BTCUSDT ETHUSDT AIAUSDT",
                },
                "timeframe": {
                    "type": "string",
                    "description": "Таймфрейм: 1d 4h 1h 15m 5m",
                },
                "limit": {
                    "type": "integer",
                    "description": "Кількість свічок, default 5",
                },
            },
            "required": ["symbol", "timeframe"],
        },
    },
    {
        "name": "get_open_interest",
        "description": "Отримати відкритий інтерес і тренд OI для символу",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Символ наприклад BTCUSDT",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_liquidations",
        "description": "Отримати зони ліквідацій і поточну ціну",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_funding_rate",
        "description": "Отримати funding rate для символу",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
]


def _run_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    sym = str((tool_input or {}).get("symbol") or "").upper().strip()
    if tool_name == "get_candles":
        tf = str((tool_input or {}).get("timeframe") or "").strip().lower() or "4h"
        limit = int((tool_input or {}).get("limit") or 5)
        limit = max(1, min(limit, 50))
        return {
            "symbol": sym,
            "timeframe": tf,
            "candles": fetch_candles(sym, tf, limit),
        }
    if tool_name == "get_open_interest":
        return fetch_open_interest(sym)
    if tool_name == "get_liquidations":
        return fetch_liquidations_proxy(sym)
    if tool_name == "get_funding_rate":
        return fetch_funding_rate(sym)
    return {"error": f"unknown_tool:{tool_name}"}


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
        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"agent_key: {agent_key}\n"
                    f"context:\n{user_context}"
                ),
            }
        ]
        max_loops = 5

        with httpx.Client(timeout=20.0) as client:
            for _ in range(max_loops):
                payload: Dict[str, Any] = {
                    "model": "claude-sonnet-4-6",
                    "max_tokens": max(int(max_tokens), 1000),
                    "system": str(system_prompt or ""),
                    "tools": TOOLS,
                    "messages": messages,
                }
                resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

                content = data.get("content")
                if not isinstance(content, list):
                    return ""
                messages.append({"role": "assistant", "content": content})

                tool_uses: List[Dict[str, Any]] = []
                text_parts: List[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    itype = item.get("type")
                    if itype == "tool_use":
                        tool_uses.append(item)
                    elif itype == "text":
                        txt = item.get("text")
                        if isinstance(txt, str) and txt.strip():
                            text_parts.append(txt.strip())

                if not tool_uses:
                    return "\n".join(text_parts).strip()

                tool_results: List[Dict[str, Any]] = []
                for tu in tool_uses:
                    tname = str(tu.get("name") or "")
                    tinput = tu.get("input") if isinstance(tu.get("input"), dict) else {}
                    tid = str(tu.get("id") or "")
                    result = _run_tool(tname, tinput) if tid else {"error": "missing_tool_use_id"}
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                messages.append({"role": "user", "content": tool_results})
            return ""
    except Exception:
        return ""
