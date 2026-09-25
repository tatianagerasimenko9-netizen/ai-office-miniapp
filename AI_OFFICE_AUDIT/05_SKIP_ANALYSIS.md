# 05. SKIP / NO TRADE

## Лічильники Telegram (агенти)

| Маркер | К-сть повідомлень |
|--------|------------------:|
| ПРОПУСК / SKIP | 508 |
| NO_TRADE (літерально) | 157 |
| WATCHING (часто одразу після SKIP) | 488 |

Це **не** унікальні сетапи: одне `Ake` = SKIP + WATCHING.

## Причини в тексті SKIP (перетин тегів, 508 повідомлень)

Евристика по токенах: ATR, RANGE, score/edge, PANIC, підтвердження, порожні дані, kill zone.

Найчастіше в ручних відповідях Лева: **ATR day_used**, **RANGE без sweep**, **score << 85**, **PANIC**, порожній REST (`ціна None`).

## Де відсікає КОД (сканер / desk), не чат

Порядок у `proactive_market_scan` / `office_handle_signal` (CONFIRMED):

1. Поза London/NY UTC → сканер мовчить.  
2. Circuit / drawdown.  
3. Об’єм / виключені BTC+ETH.  
4. ATR ≥ 80% або gerchik ≤ 4.  
5. Режими BTC NEWS_CHAOS / PANIC / LOW_LIQUIDITY → альти skip.  
6. `fetch_probability_score` → NO_TRADE (ATR>80, RANGE, chaos…).  
7. `fetch_edge_score` `has_edge=False` (<85 або напрямок не LONG/SHORT).  
8. Текст Лева з словами пропуск/чекаю → тихий WATCHING.  
9. Дарина REJECTED у desk-chain.

## Чи система «занадто сувора»?

**CONFIRMED (арифметика score):** при BTC RANGE і високому ATR максимум edge часто **≤80 < 85** → снайперський вхід закритий. Див. `04`/`12` score file.

**НЕ ВСТАНОВЛЕНО:** чи SKIP потім давав +2R. Немає свічок після події в цьому аудиті.

**PROBABLE з чату:** суворість + ручний спам тікерів = багато SKIP підряд (AKE ATR 400% — SKIP був **раціональний**; помилка — повторний аналіз і новий WATCHING).

## Що не треба робити зараз

Не додавати нові фільтри «щоб менше сміття». Сміття вже є від **повторного WATCHING після SKIP** і від **85 на RANGE**.
