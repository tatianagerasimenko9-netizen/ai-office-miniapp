# 15. Статистика

## Таблиці (CONFIRMED код)

- `trade_journal` — desk-угоди open/close/pnl/tags.  
- `trade_journal_knowledge` — бібліотека Олесі.  
- `office_signals` — FSM сигналів.  
- Mini App KPI з журналу.

## Чого немає

MFE, MAE, time-to-TP, session-tagged expectancy, auto-підбір buffer.  
Навчання **не змінює** пороги: лише `learning_note` у промпт.

## Що видно в Telegram

Часто `Щоденний журнал: Угод: 0`.  
Мета-тиждень: LLM переказує агрегації `office_signals` (expired ≈ «не відпрацювали»).

Без прод-БД **немає** правдивої wr/avg R офісу.  
Експорт **My Crypto Scanner** (інший канал, квітень–серпень) — це **не** цей офіс; його PnL не змішувати.

## Висновок

Statistics engine як продукт **не готовий**. Журнал є схемою, наповнення ручними угодами Тетяни — слабке.
