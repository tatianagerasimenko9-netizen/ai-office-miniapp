# IMPLEMENTATION_ROADMAP.md

Код зараз не чіпати. Після дозволу — гілка `cursor/…-5134`, бэкап БД, rollback = revert PR.

Витрати API Anthropic/News/Binance у $: **НЕ ПЕРЕВІРЕНО** (немає інвойсів у репо). Радар етапу 2 має **зменшити** виклики LLM, не збільшити.

## Етап 0 — аудит і резерв (зараз)

- Карта: `CURRENT_SYSTEM.md`  
- Секрети: `.gitignore` session/json; не світити в звітах  
- Залежність: `file-1` поза репо  
- Готовність: цей пакет документів ✅  

## Етап 1 — P0 баги

Файли: `office_relay_wizard.py`, `office_bridge.py`, `office_llm_agent.py` (мінімум).  
Зміни: MarketState таблиця/JSON; SOURCE шлях читає `bot_action`; `/review` `/position`; Назар fail-closed; дедуп WATCHING.  
Міграція: нова таблиця `market_state` (Postgres+SQLite як інші).  
Тести: скрипт на parse intent; мок news 402.  
Готовність: OFFICE NO → форвард сканера не стає ENTER у офісі; review не пише trade_journal як ENTRY.  
Ризик: зламати MAIN handler. Rollback: flag `OFFICE_STATE_PROTOCOL=0`.  
**file-1 не змінювати.** Якщо BLOCK має глушити сканер фізично — окремий адаптер пізніше.

## Етап 2 — радар

Файли: новий `office_radar.py` (краще ніж роздувати wizard), monitor loop, `office_market_data` sweep 5m/15m.  
Зняти BTC з exclude **для watch**. Альти — другий контур.  
Готовність: фікстура свічок → 👀 і 🚨 без користувача.  
Ризик: спам як XAU. Cooldown + один event_id.

## Етап 3 — логіка сетапів

Не нові фільтри. Журнал SKIP + klines (не ця VM). Scalp/intraday/swing гілки.  
Готовність: звіт SKIP→MFE без look-ahead. 85 переглянути лише тоді.

## Етап 4 — журнал

Зв’язати debrief з RESULT; джерела office/scanner/manual/paper.  
Готовність: coverage debrief vs trades > зафіксованого baseline (зараз ІМОВІРНО низький: чат «Угод: 0»).

## Етап 5 — Mini App MVP

`office_mini_app.py` + API з `MINI_APP_SPEC.md`.  
Готовність: 6 вкладок на реальних полях стану, порожні стани чесні.

## Етап 6 — paper, потім live

Paper спочатку. Live ордери — **окремий дозвіл**. Ідемпотентність, kill switch.

## Порядок у Cursor

**T0 ZONE_REACHED** (окремий PR) → T4 → T1 → T3 → T5 → T2. Не пакет етапу 1 одним комітом.

план → одна зміна → `compileall` + скрипт тесту → лог → звіт → наступне. Не монолітний рерайт.
