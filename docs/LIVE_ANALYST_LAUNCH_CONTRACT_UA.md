# Issue #169 — LIVE Analyst Office: обов'язковий контракт повного запуску
Дата: 2026-10-12. Це **специфікація для реалізації**, не звіт про виконаний код. Не позначати критерії DONE без доказів.

## Мета й режим
- Природні ринкові сигнали у Telegram для **самостійного рішення користувачки**. Немає навчальних/вигаданих рекомендацій, немає автозаявок, немає підвищення ризику.
- Розрізняти LIVE_ANALYSIS (аналіз реального ринку), MANUAL_POSITION (підтверджена користувачкою позиція), PAPER (внутрішній симулятор), WATCH, READY, INVALIDATED, EXPIRED, CLOSED. LIVE_ANALYSIS **не означає**, що реальну угоду відкрито.
- Жодних PnL/R «зароблено» без підтвердженого MANUAL_POSITION; для PAPER завжди явна позначка «симуляція». Якщо користувачка не підтвердила вхід — супровід тільки як сценарій із рекомендаціями/умовами, без заяв про виконання угоди.

## 1. Повна інвентаризація першоджерел і реалізації
- Зібрати книгу Герчика, повний SM Trader, методику Дарії, всі надані зображення/скріншоти, раніше погоджені вимоги до карток і графіків. Визначити, які матеріали доступні в репозиторії, які лише у вкладеннях користувачки, які відсутні. Не вигадувати недоступні сторінки/зображення.
- Згенерувати `docs/methodology/TRACEABILITY.md` з **окремим рядком на КОЖНЕ правило**: метод/розділ/сторінка або image ID, формулювання, потрібні OHLC/volume/context, таймфрейм, файл+функція детектора, тест, live-поле доказу, статус IMPLEMENTED/PARTIAL/MISSING/UNVERIFIED. Не підміняти назву методу доказом реалізації.
- Для Дарії відновити оригінальні 1→2→3→4→5→6 кроків і всі критерії входу з джерела. Якщо M5/M1 чи конкретний крок не підтверджений — UNVERIFIED, не вигадувати.

## 2. Єдина causal ринкова база
- Всі рішення READY/entry/SL/TP/invalidation тільки на перевірених **Binance USDⓈ-M Futures** свічках; зберігати symbol, exchange, market=futures, source endpoint/WS, TF, candle open/close UTC, last_closed, OHLCV, fetched_at, latency, version.
- Fail-closed при 418/429, stale/missing bars, непідтвердженому source: WATCH/NO SIGNAL + одна зрозуміла технічна діагностика; **spot/Bybit не використовувати для підтвердження LIVE-сигналу**.
- Виправити WebSocket hits=0 за наявних WS events; порівняти контрольні OHLC для TIA d37a production 21:30 UTC vs futures replay 21:15 UTC; без причинної відповідності не знімати блокування.
- Тільки закриті бари й as-of cutoffs, жодного lookahead. DST-aware сесії Kyiv з UTC у БД.

## 3. Ринкова структура від старшого до молодшого
- D1: режим, основні тренди/межі, weekly/monthly highs/lows, PDH/PDL, контекст BTC.
- H4: підтвердження структури, значущі сильні рівні й зони, база, кількість тестів, дзеркальні рівні (support↔resistance), HTF ліквідність.
- H1: якість рівня, обсяг, ATR, підхід ціни, імпульс, хибний пробій, ретест, OB/FVG/BPR, premium/discount, перешкоди до TP.
- M15: структура HH/HL/LH/LL, BOS/MSS/CHoCH тільки за визначеннями джерела, sweep, displacement, підтвердження сценарію та invalidation.
- M5/M1: лише якщо це випливає з методики — причинне підтвердження, точка входу, стоп за структурою, час/TTL. Не робити входу лише через торкання широкої зони.
- Герчик: рівні/дзеркала, breakout/retest, false break (1/2/3+ барів), якість бази, відбій, запас ходу, трендова і контртрендова лінії; формалізувати кожну умову за джерелом.
- SMC: HTF/ITF/LTF, external/internal liquidity, BSL/SSL, sweep, BOS/MSS, OB, FVG, BPR, OTE, premium/discount, session high/low, PO3 тільки за підтвердженим описом.
- Дарія: її авторська послідовність 1–6 — окремий `daria_evidence` у картці з pass/fail/unknown на кожному кроці і посиланням на source.

## 4. Єдиний lifecycle без фальшивого PnL
- Immutable events + state machine: CANDIDATE→WATCH→READY→INVALIDATED/EXPIRED або CONFIRMED_ENTRY→TP1→TP2→TP3/SL/BE→CLOSED. INVALIDATED до ENTRY не може породити TP/PnL. Ціль до входу = `TARGET_TOUCHED_WITHOUT_ENTRY`, без прибутку.
- Ключі card_id, thesis_id, symbol, strategy_version, scenario_revision; дедуп TG/outbox і CAS/transactional transitions.
- Розібрати TIA: TP1 05:16, TP2 05:30, INVALIDATED 13:47 — зіставити IDs, timestamps, source, версії, entry. JUP TP2 і TP3 обидва +2.35R — підтвердити partial accounting або виправити.
- Ретроспективні виправлення тільки через audit correction events, не видаляти стару історію; синхронізувати Telegram/Mini App/journal.
- Реальну ручну позицію супроводжувати як реальну **лише після явного підтвердження входу користувачкою** (ціна/час/розмір/часткові закриття). Без цього давати аналітичний супровід сценарію, не заявляти про фактичні угоди.

## 5. Telegram: коротко й дієво
- WATCH: лише коли змінилось суттєве; коротко symbol/direction/рівень/чого бракує/TTL/посилання; без TP/PnL.
- READY: SYMBOL LONG/SHORT, TF, вхідна зона, підтвердження, SL, TP1/TP2/TP3, R/RR, час чинності, коротка причина (до 2 рядків), кнопка **Відкрити сценарій** з точним card ID.
- Ведення: ENTRY CONFIRMED (якщо є підтвердження), зміна структури, TP, перенос SL, тримати/скорочувати/закрити з підставою, «немає руху/низький ATR» лише за вимірюваними умовами; без спаму на кожній свічці.
- Жодних обіцянок прибутку; окремо аналітична рекомендація та виконана користувачкою дія.

## 6. Графік і Mini App
- Читабельні справжні OHLCV candles, достатній лівий контекст (видимі попередні swings/база/підхід до рівня), zoom/pan, HTF overview + entry detail; не обрізати до 3–5 свічок.
- На графіку: сильні рівні D1/H4/H1, дзеркальні зони, PDH/PDL, liquidity, трендова і контртрендова, BOS/MSS, regression channel (лінійний регресійний канал з описаними lookback і deviation, не підміняти трендом), зона входу, invalidation, SL, TP1–3, price scale, timestamps і source.
- Кожен шар можна вимкнути; mobile typography/contrast/labels без накладок; за замовчуванням мінімум важливих шарів, деталі в розгортанні. Deep link /v2?tab=radar&card=<ID> відкриває саме цей сценарій.
- Розгорнута картка: top-down кроки 1–6, Герчик/SMC evidence, за/проти, ліквідність, risk, BTC context, candle provenance, lifecycle timeline, журнал, помилки/unknown.

## 7. Перевірка перед запуском та запуск
- Не надсилати фальшиві сигнали у робочий Telegram. Unit/integration/replay/contract тести всередині CI **обов'язкові**; перевірити state transitions, source guard, as-of, deep links, idempotency, R accounting, screenshots mobile.
- Один узгоджений набір PR без дрібних латок; CI green; обидва Render Worker/Web LIVE на однаковому SHA, міграції Postgres, health/logs, rollback.
- Тільки **природний READY** з реальними перевіреними futures свічками; Telegram delivery ID, Mini App exact card, lifecycle update, журнал та provenance підтверджені. Якщо природного READY ще не було — звітувати NOT YET VERIFIED, не називати повним запуском.
- Після старту вимірювати latency, stale data, delivery p95, частоту READY, помилки, PnL тільки підтверджених угод; реальні ордери залишити OFF.

## Формат фінального звіту
Окремі таблиці по **кожному** пункту Герчика, Дарії 1–6, SM Trader і кожному графічному елементу: SOURCE | IMPLEMENTATION FILE/FUNCTION | TEST | LIVE EVIDENCE | STATUS. Окремо: PR, commit SHA, CI, Render Worker/Web SHA, futures source proof, останні 5 природних сигналів та message IDs, коректність журналу, відкриті блокери. Тільки після доказів — DONE; інакше PARTIAL/MISSING/UNVERIFIED.
