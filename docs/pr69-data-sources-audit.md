# Джерела даних АІ офісу — фактичний аудит за кодом (гілка `claude/eager-pascal-t9e1ac`)

Складено 2026-09-29 з коду репозиторію. Позначки: **CODE** — так реалізовано в коді;
**UNVERIFIED** — не перевірялось у цій сесії (потрібен запуск з Render або з ключем);
**BLOCKED** — перевірено й недоступне з певного середовища.
Нічого тут не підтверджує якість даних на production: це карта того, що код *намагається* читати.

## Що підключено

| Дані | Джерело / ендпоінт (CODE) | Використання | Обмеження |
|---|---|---|---|
| Свічки OHLCV (1m…1w) | Binance USD-M `fapi/v1/klines` (`office_market_data.fetch_candles`) | Лев, радар, Mini App графік | Без ключа. З GitHub-runner Binance USD-M повертав **HTTP 451** (**BLOCKED** з CI); із цього sandbox — 403 проксі. Доступність із Render — **UNVERIFIED** |
| Ціна/24h, top movers | `fapi/v1/ticker/24hr` | Радар, Mini App | те саме |
| OI, історія OI | `fapi/v1/openInterest`, `futures/data/openInterestHist` | Edge-скор Макса, лог | Лише у тексті/скорі; **не** доказ Лева |
| Funding | `fapi/v1/premiumIndex` (`fetch_funding_rate`) | Edge, алерти | те саме |
| Long/short ratio | `futures/data/globalLongShortAccountRatio`, `topLongShortPositionRatio` | Edge, контекст | Історичний ліміт Binance |
| Стакан (стіни) | `fapi/v1/depth?limit=100` **одним знімком** (`fetch_order_book_walls`) | Текстові «стіни» для агентів | Знімок ≠ потік: без відновлення книги, змін ліквідності, поглинання. **Не** використовується як доказ; у Risk/Execution — `UNAVAILABLE` |
| Спред | — | — | **Немає джерела.** Перевірка «спред/ліквідність» завжди `UNAVAILABLE` |
| Ліквідації (факт) | WebSocket `btcusdt@forceOrder`, лише **BTCUSDT** (`office_btc_liquidations`) | T7, радар (BTC) | Лише BTC; це потік *фактичних* ліквідацій, не карта |
| Ліквідації REST | `fapi/v1/forceOrders` (`fetch_recent_liquidations`) | Контекст агентів | Публічний вигляд цього ендпоінта Binance обмежений/може вимагати автентифікації; на production **UNVERIFIED** — не спиратися як на доказ |
| «Ліквідації» (proxy) | `fetch_liquidations_proxy`: зони з 24h high/low і ціни | Радар/агенти | **Модельна оцінка**, не карта ліквідацій. `office_feed_quality` забороняє видавати її за перевірену |
| Економічний календар | `financialmodelingprep.com/stable/economic-calendar`, потребує `NEWS_API_KEY` | Назар (новини) | Ключ опційний і на production **UNVERIFIED**; без ключа → порожньо (`DATA_EMPTY`). Не використовується в Execution Planner |
| Ринковий контекст | Yahoo (`GC=F` тощо), Stooq | Контекст макро | Неофіційні ендпоінти, без SLA/ліцензії для перепродажу — **UNVERIFIED** |
| GEX Deribit | лише в окремих PR (#59/#60), **не** в цій гілці | — | Mini App пише `GEX не в main` |
| LLM | Anthropic API (`ANTHROPIC_API_KEY`, опційно) | Репліки агентів | Без ключа — евристики |
| BTC/ETH контекст | `market_state` (Worker) + `btc_context_only` | Теза/радар | Якщо не підтверджено даними → `DATA_UNAVAILABLE` |

## Чого немає (і як це відображається)
- **Стакан як потік (depth + trades), спред, глибина на відстані** → Execution Planner: `Спред і ліквідність = UNAVAILABLE`; Risk Officer: `EXECUTION_NOT_VERIFIED` (це і є причина, чому enforce поки заблокував би кожен SEND).
- **Карта ліквідацій (кластери)** → немає. Показуємо лише факт-стрім BTC і явно позначену proxy.
- **Календар подій / токен-анлоки / лістинги** → немає перевіреного джерела; новинний ризик у Execution Planner = `UNAVAILABLE`.
- **Funding/OI як точки перевірки в тезі** → не в тезі Лева (лише в тексті агентів).

## Кандидати на закриття прогалин (без підписок; нічого не підключено)
| Потреба | Безкоштовний кандидат | Що треба перевірити перед підключенням |
|---|---|---|
| Depth + trades потік | Binance USD-M WebSocket `@depth@100ms`, `@aggTrade` | Ліміти з’єднань, відновлення книги за `lastUpdateId`, доступність з Render, обсяг трафіку/CPU worker |
| Спред | `@bookTicker` (той самий WS) | Затримка; тільки як показник, не як «доказ наміру» |
| Ліквідації по багатьох парах | Binance `!forceOrder@arr`, публічні потоки інших бірж | Повнота (Binance віддає зріз, не всі події), ліцензія на використання даних |
| Календар | Офіційні календарі ФРС/BLS (публічні сторінки/ICS) | Ліцензія, стабільність формату; ручне підтвердження власницею |
| Історія для replay | Binance Vision (вже використовується, публічно, без ключа) | Лише свічки; OI/стакан/ліквідації історично **не** відтворюються |

Платні варіанти (наприклад, агрегатори карт ліквідацій) — **не оформлювати без погодження**;
оцінку вартості складу лише після того, як власниця вкаже, чи потрібна карта, а не потік фактичних ліквідацій.

## Обов’язкові перевірки з боку Render (потребують доступу, у цій сесії Render-інструментів немає)
1. З worker/web: `curl -sS -o /dev/null -w "%{http_code}" https://fapi.binance.com/fapi/v1/ping` — чи не 451/403 із регіону Render.
2. Наявність `NEWS_API_KEY`, `ANTHROPIC_API_KEY` (лише факт «задано/ні», без значень).
3. Розмір диска `/var/data` і що на ньому лежить (`office_relay_config.json`, сесія Telethon).
4. Одна Postgres для web і worker (`office_db_identity` fingerprint збігається).
