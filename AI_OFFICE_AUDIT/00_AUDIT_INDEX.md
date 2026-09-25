# AI Office — індекс аудиту (етап 1)

**Статус:** тільки розтин. Код, промпти, CONFIG, торгові правила **не змінювались**.  
**Дата:** 2026-09-25.  
**Гілка документів:** `cursor/office-full-audit-5134`.  
**Команда на зміни:** немає. Чекаємо `МОЖНА ВНОСИТИ ЗМІНИ`.

## Короткий висновок

Офіс зараз — **Telegram-relay + LLM-персонажі + REST-фільтри Binance**, а не event-машина «зона → sweep → підтвердження → короткий сигнал».

Він **багато відповідає на ручні тікери** (`full_auto_analysis` після `Ake` / `Btc`) і **мало сам ловить події**. Проактивний сканер **виключає BTCUSDT і ETHUSDT**, крутиться раз на годину і лише в London/NY kill zone. Порогу edge **85/100** на боковику BTC часто **математично неможливо** набрати.

Тижневий звіт «39 сигналів / 0 TP / 3/10» — це **текст Лева з `meta_intelligence_weekly` по таблиці `office_signals`**, не незалежний брокерський PnL. У цьому середовищі прод-БД **не надана**, тож 39 рядків **не верифіковані**. Повтор AKEUSDT у звіті як «система сама крутиться» — **спростовано**: 11× це було `USER_REQUEST` «Ake».

## Джерела

| Джерело | Статус |
|---------|--------|
| Код `main` у цьому репо | Прочитано |
| Telegram `result.json` чат **AI Office** (05.05.2026–25.09.2026, 6438 текстів) | Прочитано; **не комітиться** |
| Render Postgres / `office_signals` live | **НЕ ВСТАНОВЛЕНО** |
| Логи relay | **НЕ ВСТАНОВЛЕНО** |
| Ціна після SKIP (бектест) | **НЕ ВСТАНОВЛЕНО** (немає історичних свічок у VM) |

## Файли

| # | Файл |
|---|------|
| 01 | `01_ARCHITECTURE.md` |
| 02 | `02_TELEGRAM_AUDIT.md` |
| 03 | `03_AGENTS.md` |
| 04 | `04_SIGNALS.md` |
| 05 | `05_SKIP_ANALYSIS.md` |
| 06 | `06_EVENTS_SWEEPS.md` |
| 07 | `07_ATR_DEAD.md` |
| 08 | `08_SESSIONS.md` |
| 09 | `09_SCALP_INTRADAY_SWING.md` |
| 10 | `10_MARKET_CONTEXT.md` |
| 11 | `11_GEX_OPTIONS.md` |
| 12 | `12_WHALES.md` |
| 13 | `13_LIQUIDATIONS.md` |
| 14 | `14_PATTERNS.md` |
| 15 | `15_STATISTICS.md` |
| 16 | `16_RISK_ENGINE.md` |
| 17 | `17_TOKEN_USAGE.md` |
| 18 | `18_INTENT_STATE_BUGS.md` |
| 19 | `19_MISSED_OPPORTUNITIES.md` |
| 20 | `20_ROOT_CAUSES.md` |
| 21 | `21_CURRENT_VS_REQUIRED.md` |
| 22 | `22_OFFICE_2_ARCHITECTURE.md` |
| — | `telegram_audit_stats.json` |

Детальний roadmap — у `22_OFFICE_2_ARCHITECTURE.md`.
