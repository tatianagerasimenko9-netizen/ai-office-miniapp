# AI Office — MASTER

Єдиний збірник. Деталі: `AI_OFFICE_AUDIT/`.  
Код **не змінювати** без `МОЖНА ВНОСИТИ ЗМІНИ`.  
Оновлено: 2026-09-25 (уточнення Тетяни + GGShot guide + план keep/change/remove).

## Одна фраза

Офіс навчився казати NO TRADE, але не навчився **сам** сказати 👀 зона → 🚨 sweep → 🟢 сигнал. Паралельно сканер може торгувати **всупереч** цьому NO TRADE.

## Мета 2.0

Радар: scalp / intraday / swing. Короткі події й картки Entry/SL/TP/RR.  
`/review` ≠ `/position`. Один стан OFFICE ↔ BOT. Статистика SIGNAL→RESULT.  
Апка: Home, Scanner, Signals, My Positions, Statistics, пуші.  
GEX — характер ринку, не напрямок. Мінімум токенів. Українською, просто.

## Доведено

Коментатор, не радар. Скан без BTC/ETH, 1h. Sweep = 3 свічки 1h.  
AKE = ручний. BTC 23.09 07:35 — немає timely alert.  
804 ≠ сигнали (472 токени, ~4 картки).  
Scanner `file-1` автономний; офісний SKIP його не глушить (`23`).  
Назар: **22/45** «Новинний фон чистий. Входити можна.»  
Debrief ~**128** — лишити, з’єднати з RESULT.  
Binance з audit-VM: HTTP 451.  
Mini App зараз — таблиці журналу, не GGShot.

## Не встановлено

Прод «39 рядків», біржовий факт 87247, +2R після SKIP, GEX API, DM ботів.

## Keep / change / remove

Покроково: `AI_OFFICE_AUDIT/24_KEEP_CHANGE_REMOVE_PLAN.md`.  
Апка vs GGShot: `25_MINIAPP_GGSHOT.md`.  
Промпт далі: `PROMPT_NEXT_CLOUD.md`.

## P0–P4

0. **Спільний MarketState + BLOCK сканера при OFFICE NO.** Intent. Назар fail-closed. Антиспам WATCHING.  
1. Радар BTC (APPROACH/SWEEP/CONFIRM/SIGNAL). GEX-картка зі знімка.  
2. Статистика етапів + debrief→RESULT.  
3. Mini App екрани.  
4. ENTER як у GGShot (пресет, тап, біржа) — **не зараз**.

Не робити більше сигналів і не різати Лева як KPI.

## Промпт у Cloud

Скопіюй текст з `AI_OFFICE_AUDIT/PROMPT_NEXT_CLOUD.md`.

## Від Тетяни

`МОЖНА ВНОСИТИ ЗМІНИ` + який P0 шматок першим. Опційно: dump Render `office_signals`. ChatGPT-проєкт «AI Office» — у **її** акаунті ChatGPT (я не можу натиснути «перенести чат» там). Тут у git уже лежить увесь аудит.
