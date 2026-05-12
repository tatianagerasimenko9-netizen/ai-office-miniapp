from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx

from office_market_data import (
    fetch_atr_context,
    fetch_candles,
    fetch_funding_rate,
    fetch_fvg,
    fetch_key_levels,
    fetch_long_short_ratio,
    fetch_liquidity_sweep,
    fetch_liquidations_proxy,
    fetch_macro_context,
    fetch_open_interest,
    fetch_order_blocks,
    fetch_ote_levels,
    fetch_pd_array,
    fetch_market_structure,
    fetch_recent_liquidations,
    fetch_session_levels,
    fetch_top_movers,
    fetch_top_traders_ratio,
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
        "name": "get_atr_context",
        "description": "ATR і запас ходу. Показує скільки монета пройшла за день і чи вигідно зараз входити.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_long_short_ratio",
        "description": "Співвідношення лонгів і шортів на ринку. Якщо >70% лонги — небезпека розвороту вниз.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_top_traders",
        "description": "Позиції топ трейдерів біржі — що роблять великі гравці.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_liquidations_real",
        "description": "Реальні ліквідації на ринку — де вибивали позиції.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_key_levels",
        "description": "Ключові горизонтальні рівні де ціна реагувала кілька разів. Метод Герчика — торгівля від рівнів.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_ote_levels",
        "description": "OTE зона для снайперського входу. Fibonacci 61.8-78.6% після імпульсу — мінімальний стоп.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "description": "1h або 4h"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_session_levels",
        "description": (
            "Отримати сесійні рівні Asia/London/NY (high/low за UTC-вікнами на 15m за ~24 год) "
            "та PDH/PDL/PDC попереднього дня для символу. База для ICT і снайперських зон."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Символ, наприклад BTCUSDT, ETHUSDT",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_liquidity_sweep",
        "description": (
            "Визначити чи був sweep ліквідності BSL або SSL на останніх свічках. "
            "BSL sweep = можливий SHORT. SSL sweep = можливий LONG."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Наприклад BTCUSDT"},
                "timeframe": {
                    "type": "string",
                    "description": "Таймфрейм klines, за замовчуванням 1h (1h 4h 15m)",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_pd_array",
        "description": (
            "ICT Premium/Discount Array. Визначає чи ціна в Premium (шорт) "
            "або Discount (лонг) зоні відносно останнього імпульсу. "
            "Equilibrium = 50% від імпульсу. OTE зона = 61.8-78.6% Fibonacci."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Наприклад BTCUSDT"},
                "timeframe": {
                    "type": "string",
                    "description": "Таймфрейм klines, за замовчуванням 4h (4h 1h 15m)",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_market_structure",
        "description": (
            "ICT Market Structure — BOS і CHOCH. "
            "BOS (Break of Structure) = тренд продовжується. "
            "CHOCH (Change of Character) = тренд міняється. "
            "Визначає swing highs/lows і поточний тренд."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Наприклад BTCUSDT"},
                "timeframe": {
                    "type": "string",
                    "description": "Таймфрейм klines, за замовчуванням 1h (1h 4h 15m)",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_order_blocks",
        "description": (
            "ICT Order Blocks — зони де інституції відкривали позиції. "
            "Bullish OB = зона для LONG входу. "
            "Bearish OB = зона для SHORT входу. "
            "Ціна часто повертається до OB."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Наприклад BTCUSDT"},
                "timeframe": {
                    "type": "string",
                    "description": "Таймфрейм klines, за замовчуванням 1h (1h 4h 15m)",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_fvg",
        "description": (
            "Fair Value Gap — незаповнені цінові гапи. "
            "Bullish FVG = зона підтримки знизу. "
            "Bearish FVG = зона опору зверху. "
            "Ціна часто повертається щоб заповнити FVG."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Наприклад BTCUSDT"},
                "timeframe": {
                    "type": "string",
                    "description": "Таймфрейм klines, за замовчуванням 1h (1h 4h 15m)",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_top_movers",
        "description": "Топ монети які найбільше ростуть або падають сьогодні на Binance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "gainers або losers"},
                "limit": {"type": "integer"},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "get_macro_context",
        "description": "Макро контекст: BTC, Gold, S&P 500, DXY. Кореляції і загальний настрій ринку.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
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
    if tool_name == "get_atr_context":
        return fetch_atr_context(sym)
    if tool_name == "get_long_short_ratio":
        return fetch_long_short_ratio(sym)
    if tool_name == "get_top_traders":
        return fetch_top_traders_ratio(sym)
    if tool_name == "get_liquidations_real":
        return {"symbol": sym, "items": fetch_recent_liquidations(sym)}
    if tool_name == "get_key_levels":
        return {"symbol": sym, "levels": fetch_key_levels(sym)}
    if tool_name == "get_ote_levels":
        tf = str((tool_input or {}).get("timeframe") or "4h").strip().lower()
        return {"symbol": sym, "timeframe": tf, "ote": fetch_ote_levels(sym, tf)}
    if tool_name == "get_session_levels":
        return fetch_session_levels(sym)
    if tool_name == "get_liquidity_sweep":
        tf_sw = str((tool_input or {}).get("timeframe") or "1h").strip().lower() or "1h"
        return fetch_liquidity_sweep(sym, tf_sw)
    if tool_name == "get_pd_array":
        tf_pd = str((tool_input or {}).get("timeframe") or "4h").strip().lower() or "4h"
        return fetch_pd_array(sym, tf_pd)
    if tool_name == "get_market_structure":
        tf_ms = str((tool_input or {}).get("timeframe") or "1h").strip().lower() or "1h"
        return fetch_market_structure(sym, tf_ms)
    if tool_name == "get_order_blocks":
        tf_ob = str((tool_input or {}).get("timeframe") or "1h").strip().lower() or "1h"
        return fetch_order_blocks(sym, tf_ob)
    if tool_name == "get_fvg":
        tf_fvg = str((tool_input or {}).get("timeframe") or "1h").strip().lower() or "1h"
        return fetch_fvg(sym, tf_fvg)
    if tool_name == "get_top_movers":
        direction = str((tool_input or {}).get("direction") or "").strip().lower() or "gainers"
        limit = int((tool_input or {}).get("limit") or 5)
        return {"direction": direction, "items": fetch_top_movers(direction, limit)}
    if tool_name == "get_macro_context":
        return fetch_macro_context()
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


def get_model_for_agent(agent_key: str) -> str:
    """
    Всі агенти — Sonnet (економний режим)
    """
    opus_agents = set()
    if str(agent_key or "").strip().lower() in opus_agents:
        return "claude-opus-4-6"
    return "claude-sonnet-4-6"


def ask_agent(
    agent_key: str,
    system_prompt: str,
    user_context: str,
    max_tokens: int = 150,
    messages_history: Optional[List[Dict[str, str]]] = None,
    db_path: Optional[str] = None,
) -> str:
    """
    Lightweight Anthropic adapter for agent-style replies.
    Returns empty string on any failure (graceful fallback).
    """
    try:
        agent_norm = str(agent_key or "").strip().lower()
        token_cap = 1200 if agent_norm == "lev" else 1000
        safe_max_tokens = max(64, min(int(max_tokens), token_cap))
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return ""
        context_text = str(user_context or "")
        if agent_norm == "lev":
            recent_db_path = str(db_path or "").strip() or os.getenv("DATABASE_URL", "").strip() or os.getenv("OFFICE_DB_PATH", "office_bridge.db").strip() or "office_bridge.db"
            try:
                from office_bridge import signal_get_recent  # local import to avoid import cycle at module load

                recent = signal_get_recent(recent_db_path, limit=5)
                if recent:
                    memory_lines: List[str] = ["Останні угоди:"]
                    for s in recent:
                        symbol = str(s.get("symbol") or "").strip().upper()
                        direction = str(s.get("direction") or "").strip().upper()
                        outcome = str(s.get("outcome") or "").strip().upper() or "UNKNOWN"
                        note = str(s.get("analysis_note") or "").strip().replace("\n", " ")
                        memory_lines.append(f"{symbol} {direction} -> {outcome} {note[:50]}")
                    context_text = "\n".join(memory_lines) + "\n\n" + context_text
            except Exception:
                pass

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "managed-agents-2026-04-01",
            "content-type": "application/json",
        }
        messages: List[Dict[str, Any]] = []
        for item in (messages_history or []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content_txt = str(item.get("content") or "").strip()
            if role not in ("user", "assistant") or not content_txt:
                continue
            messages.append({"role": role, "content": content_txt[:5000]})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"agent_key: {agent_key}\n"
                    f"context:\n{context_text}"
                ),
            }
        )
        max_loops = 5

        with httpx.Client(timeout=20.0) as client:
            for _ in range(max_loops):
                model_name = get_model_for_agent(agent_key)
                timeout_sec = 60.0 if "opus" in model_name else 25.0
                payload: Dict[str, Any] = {
                    "model": model_name,
                    "max_tokens": safe_max_tokens,
                    "system": str(system_prompt or ""),
                    "tools": TOOLS,
                    "messages": messages,
                }
                sofia_memory_store_id = os.getenv("SOFIA_MEMORY_STORE_ID", "").strip()
                if agent_norm == "memory" and sofia_memory_store_id:
                    payload["resources"] = [
                        {
                            "type": "memory_store",
                            "memory_store_id": sofia_memory_store_id,
                            "access": "read_write",
                        }
                    ]
                resp = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=timeout_sec,
                )
                resp.raise_for_status()
                data = resp.json()
                stop_reason = data.get("stop_reason", "unknown")
                if stop_reason == "max_tokens":
                    print(f"[llm] {agent_key} hit max_tokens limit!")

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
