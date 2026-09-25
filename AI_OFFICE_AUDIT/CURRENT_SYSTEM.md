# CURRENT_SYSTEM.md — що реально існує

Мітки: ПІДТВЕРДЖЕНО кодом/чатом. Немає джерела → НЕ ПЕРЕВІРЕНО.

## Процеси (ПІДТВЕРДЖЕНО)

| Процес | Файл | Роль |
|--------|------|------|
| Лаунчер | `office_multibot_bootstrap.py` | Токени → subprocess wizard |
| Ядро | `office_relay_wizard.py` | Telethon, хендлери, asyncio-цикли |
| Бібліотека | `office_bridge.py` | БД, `office_handle_signal`, промпти |
| LLM | `office_llm_agent.py` | спільні tools, усі агенти |
| Дані | `office_market_data.py` | REST Binance / макро |
| Gerchik | `office_gerchik_kernel.py` | текст + `compute_gerchik_ops` |
| Bulkowski | `office_bulkowski_kernel.py` | текст Марічки, без скорера |
| Mini App | `office_mini_app.py` | HTTP `:8790` |
| Dashboard | `office_dashboard.py` | HTTP `:8787` |

**Немає в репо:** `file-1.py.py`, `2scanner_bot_1.py` (шляхи лише в snapshot-доках на ПК Тетяни). ПІДТВЕРДЖЕНО відсутність файлу; живий процес сканера на Render — **НЕ ПЕРЕВІРЕНО**.

## Хто що робить зараз (ПІДТВЕРДЖЕНО)

| Функція | Хто |
|---------|-----|
| Ринкові дані | `office_market_data` REST; LLM tools за запитом |
| Виявлення подій | Майже немає. Sweep = 3 свічки 1h на виклик. Watch poll ціни vs entry |
| Сетап | LLM Лев (`full_auto_analysis`) або desk-chain сканера альтів |
| Підтвердження сигналу | Текст LLM, не FSM |
| NO TRADE / SKIP | Лев-текст; edge 85; gerchik; ATR; kill zone; Дарина в `office_handle_signal` |
| Дозвіл торгівлі | Офіс: verdict ENTER лише для обробленого сигналу MAIN. Сканер file-1: сам собі |
| Позиція | In-memory `active_positions` + журнал; Олеся WATCHING-текст |
| Результат | HIT_TP/SL у `office_signals` якщо рядок вівся; інакше часто 0 угод |

## Цикли (ПІДТВЕРДЖЕНО)

- `monitor_active_signals`: 120 с у UTC KZ, інакше **900 с**
- `monitor_proactive_scanner`: **3600 с**, London/NY UTC, **без BTC/ETH**
- сесійні банери, debrief, weekly meta-LLM, news poll, TV webhook 15 с
- **WebSocket: немає**

## БД (ПІДТВЕРДЖЕНО схема; прод-вміст НЕ ПЕРЕВІРЕНО)

SQLite `office_bridge.db` або Postgres `DATABASE_URL`.  
Таблиці: `office_signals`, `trade_journal`, `trade_journal_knowledge`, events, tv_signals.

## Telegram (ПІДТВЕРДЖЕНО експорт групи AI Office)

05.05–25.09.2026: 6458 записів, 6438 текстів.  
Лев 3849, Олеся 580, Марічка 419, Дарина 302, Макс 159, Марко 154, Віктор 129, Назар 45, Тетяна 801.

## Інтеграції

- Binance futures REST — у коді є; з audit-VM **HTTP 451** (НЕ ПЕРЕВІРЕНО live прод)
- NewsAPI — опційно; деградація
- Anthropic — LLM; downtime був, не головна якість
- Біржові ордери з офісу: **немає**
- GEX: **немає**
