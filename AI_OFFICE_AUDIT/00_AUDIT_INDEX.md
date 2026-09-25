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
| 23 | `23_OFFICE_VS_SCANNER.md` |
| 24 | `24_KEEP_CHANGE_REMOVE_PLAN.md` |
| 25 | `25_MINIAPP_GGSHOT.md` |
| 26 | `26_TZ_CONSISTENCY.md` |
| — | `CURRENT_SYSTEM.md` `AUDIT_EVIDENCE.md` `KEEP_CHANGE_REMOVE.md` |
| — | `OFFICE_2_ARCHITECTURE.md` `TRADING_RADAR_SPEC.md` `MINI_APP_SPEC.md` |
| — | `IMPLEMENTATION_ROADMAP.md` `CURSOR_TASKS.md` `OPEN_QUESTIONS.md` |
| — | `telegram_audit_stats.json` |

Корінь репо: `AI_OFFICE_MASTER.md` — єдиний збірник висновків і вимог 2.0.

Детальний roadmap — у `22_OFFICE_2_ARCHITECTURE.md`. Стик зі сканером — `23_OFFICE_VS_SCANNER.md`. MASTER — `../AI_OFFICE_MASTER.md`.

## Доповнення 2026-09-25 (GEX)

Зафіксовано в `11_GEX_OPTIONS.md` і пайплайні `22`: GEX — **окремий контекстний модуль** (характер руху, стіни, магніт, IV/RV, розріджена карта після експірації). Не копіювати довгі пости. Не визначати LONG/SHORT з гамми. Код усе ще не змінювався.

Telegram: груповий JSON чату **AI Office** уже розібраний (`02_TELEGRAM_AUDIT.md`). Повторний експорт тієї ж групи не потрібен, якщо період 05.05–25.09 повний. Окремі DM Лев/Олеся/Віктор — лише якщо спілкування йшло **поза** групою.
