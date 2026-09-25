# CURSOR_TASKS.md

Виконувати **лише після** `МОЖНА ВНОСИТИ ЗМІНИ`. Одна задача = один PR. Не чіпати `file-1`, книги, CONFIG торгівлі без ТЗ.

**Порядок:** T0 → T4 → T1 → T3 → T5 → T2. T6–T8 після цього, якщо немає окремої команди. Повна карта: `26_TZ_CONSISTENCY.md`.

## T0 — ZONE_REACHED ≠ SIGNAL (перша задача)
Файли: `office_relay_wizard.py` (`monitor_active_signals`, гілка `day_used_pct>90` → `EXPIRED` + `continue` без чату).  
Поведінка: ціна в WATCHING-зоні → **завжди** одне повідомлення (символ, ціна, зона, ATR, `SIGNAL=NO|YES`). «Входь!» лише якщо SIGNAL=YES.  
Заборона: не міняти edge 85, сканер, промпти.  
Тест: фікстура ATR>90 + ціна в зоні → 1 notify, 0 «входь!».  
Rollback: revert PR.

## T1 — Intent review ≠ position
Файли: `office_relay_wizard.py` (хендлер тексту), `office_bridge.py` (journal insert).  
Поведінка: `/review` або «сигнал бота» → оцінка, **не** ACTIVE position. `/position` → журнал MY_POSITION.  
Заборона: не міняти сканер, не міняти edge 85.  
Тест: фікстура тексту картки сканера → 0 рядків ENTRY.

## T2 — Назар fail-closed
Файли: news fetch + шаблон Назара (wizard/bridge).  
Поведінка: HTTP 401/402/403/429/порожньо → `NEWS DATA UNAVAILABLE`, ніколи «фон чистий».  
Тест: мок 402.

## T3 — Дедуп WATCHING після SKIP
Файли: `full_auto_analysis`.  
Поведінка: явний ПРОПУСК не створює новий `watch-*` або створює без «повідомлю» + cooldown символу.  
Тест: два `Ake` за 10 хв → один аналіз.

## T4 — Таблиця market_state
Файли: `office_bridge.py` schema.  
Поведінка: upsert по symbol полів з `OFFICE_2_ARCHITECTURE.md`. Поки read/write без зміни чату.  
Тест: insert/get.

## T5 — MAIN handler шанує bot_action
Файли: wizard ~2907–3088.  
Поведінка: якщо state.bot_action=BLOCKED — не kickoff ENTER. Повідомити «сканер BLOCKED офісом».  
Заборона: не глушити Telethon SOURCE форвард без flag (може знадобитись сировина).  
Тест: підставити BLOCKED.

## T6 — Radar stub BTC
Новий файл + loop. Watchlist hardcoded BTC BSL з `/watch` або state.  
Поведінка: ціна в 0.3% від зони → одне 👀.  
Заборона: не 6 LLM.  
Тест: replay цін.

## T7 — Mini App Home читає state
Файли: `office_mini_app.py`.  
Поведінка: блок BTC regime/watch/event або «немає стану». Без фейкового wr.

## T8 — Класифікатор історії (офлайн скрипт)
`scripts/classify_office_messages.py` по JSON експорту → counts MENTION/SETUP/WATCH/SIGNAL. Не міняти прод.  
Критерій: не називати 804 SIGNAL.

Не починати T6–T8 до **T0–T5**, якщо немає явного «можна радар першим».

## 8. GitHub → Render: обов’язкове завершення кожної задачі

Після реалізації кожного PR Cursor самостійно:

1. Запускає тести й перевіряє, що чинні функції офісу не зламані.
2. Робить commit і push у GitHub у відповідну гілку.
3. Створює або оновлює PR, перевіряє CI та після **дозволу на злиття** доводить зміни до основної гілки. Production / merge / Render deploy **без окремого дозволу заборонені**.
4. Перевіряє налаштований спосіб деплою Render: автоматичний чи ручний. Не припускає, що push означає успішний деплой.
5. Якщо деплой автоматичний — перевіряє його статус, запуск сервісу, логи й роботу зміненої функції.
6. Якщо потрібна дія Тетяни — **одне коротке повідомлення** з точною кнопкою або дією в Render. Після підтвердження перевіряє результат.
7. Якщо деплой неуспішний — причина й відкат. Не писати «готово», поки зміни не працюють на Render.

**Формат звіту після кожної задачі:**

`T0 | GitHub: pushed / PR: … | Tests: PASS/FAIL | Render: deployed / чекає ручного деплою / failed | Перевірка функції: PASS/FAIL`

Якщо потрібна дія:

```
🟡 ГОТОВО ДО ДЕПЛОЮ
Render → [назва сервісу] → Manual Deploy → Deploy latest commit
Commit: [короткий SHA]
Після деплою напиши: ЗАДЕПЛОЇЛА
```

Якщо все виконано й перевірено на запущеному сервісі:

```
🟢 T0 ПРАЦЮЄ НА RENDER
Commit: … | Тести: PASS | Деплой: LIVE | ZONE_REACHED: перевірено
```

Секрети, токени й API-ключі не світити в GitHub, PR і звітах. «Код готовий», «push зроблено» і «працює на Render» — три різні статуси.
