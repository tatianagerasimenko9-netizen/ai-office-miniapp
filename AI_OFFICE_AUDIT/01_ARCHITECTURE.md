# 01. Фактична архітектура

## Процеси

| Вхід | Роль | Окремий процес? |
|------|------|-----------------|
| `office_multibot_bootstrap.py` | Лаунчер: токени, потім subprocess `office_relay_wizard.py` | Так |
| `office_relay_wizard.py` | Ядро: Telethon, хендлери, усі `asyncio` монітори | Так |
| `office_bridge.py` | Бібліотека: БД, `office_handle_signal`, промпти `LEV_RULE` / `DESK_BASE_RULE` | Ні |
| `office_llm_agent.py` | `ask_agent()` + спільний список tools | Ні |
| `office_market_data.py` | REST Binance / макро | Ні |
| `office_gerchik_kernel.py` | Текст ядра + `compute_gerchik_ops()` | Ні |
| `office_bulkowski_kernel.py` | Текст для Марічки, без скорера | Ні |
| `office_mini_app.py` | HTML+JSON на `:8790` | Так, окремо |
| `office_dashboard.py` | Таблиці на `:8787` | Так, окремо |

**CONFIRMED:** Mini App і Dashboard **не керують** relay. Спільний стан можливий лише через ту саму БД.

## Що за чим запускається (користувач написав тікер)

```
USER "Ake" / "Btc"
  → office_relay_wizard.full_auto_analysis()
  → REST знімок (1h/4h, ATR 1d, OI, proxy liq, L/S, levels, OTE, funding)
  → LLM Лев (LEV_RULE + tools, до 5 tool-calls)
  → парсинг Entry/SL/TP з тексту
  → якщо ПРОПУСК і є зона → office_signals WATCHING (новий рядок)
  → якщо ПРОПУСК і вже був watching_signal_id → EXPIRED / SKIP_WATCH
  → Олеся пише «зона в WATCHING»
```

**CONFIRMED** кодом `full_auto_analysis` (`office_relay_wizard.py` ~1672–1847). Telegram 19–20.09.2026: кожне `Ake` → `🔍 Аналізую AKEUSDT...`.

## Фонові цикли (між повідомленнями користувача)

| Цикл | Інтервал | Що робить |
|------|----------|-----------|
| `monitor_active_signals` | 120 с в London/NY KZ UTC, інакше **900 с** | Ціна WATCHING/ACTIVE через `fetch_liquidations_proxy` |
| `monitor_proactive_scanner` | **3600 с** (докстрінґ каже 15 хв — **розбіжність**) | Скан альтів, **без BTC/ETH** |
| `monitor_positions` | 30 с | In-memory позиції desk |
| `session_announcer` | 55 с | Банери Asia/London/NY + playbook |
| `marichka_morning/evening` | за розкладом | Домашка / ранок |
| `meta_intelligence_weekly` | тиждень 20:00 | LLM «МЕТ АНАЛІЗ ТИЖНЯ» |
| `monitor_news` | 120 с | NewsAPI якщо ключ |
| `monitor_funding_atr_alerts` | 180 с default | Алерти BTC funding/ATR |
| `monitor_tradingview_signals` | 15 с | Таблиця `tv_signals` |

**WebSocket Binance: ABSENT.**

## Детермінований шар vs LLM

Є детерміновані фільтри: `fetch_edge_score`, `fetch_probability_score`, `compute_gerchik_ops`, kill zone, circuit breaker, ATR_DEAD на WATCHING.

Фінальне «ПРОПУСК / Чекаю зону» для ручного тікера все одно **пише Лев (LLM)**. Сканер теж викликає ланцюг агентів для **одного** `best` символу, не на кожну монету.

## Чого немає як FSM

Немає статусів `ZONE_REACHED`, `SWEEP_DETECTED`, `CONFIRMATION_PENDING`, `CONFIRMED`, `SIGNAL`.  
Є лише рядки `office_signals`: `WATCHING` → `ACTIVE` → `HIT_ENTRY` → `HIT_TP*` / `HIT_SL` / `EXPIRED` (+ outcome `ATR_DEAD`, `SKIP_WATCH`).
