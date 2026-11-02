# Розрив: вимога власниці «багато монет + золото/нафта/газ» ↔ факт (перевірено 02.11.2026)

Вимога власниці: сканувати значно більше за 12 монет, включно з ф'ючерсами на золото, нафту, природний газ та іншими інструментами з хорошим потенціалом.

## Факти
- **B&R у production**: у `br_test_signal` рівно 12 символів (ETH, NEAR, LINK, SEI, BTC, TIA, DOGE, ONDO, SOL, XRP, ADA, AVAX), жодного металу/енергії. Причина в коді: `office_br/live.py` `SYMBOLS` — жорсткий список із 12; динамічний універсум `BR_LIVE_DYNAMIC_UNIVERSE` за замовчуванням `0` (вимкнено), у логах Worker рядків `[br-live] futures_universe=` немає → не вмикався.
- Код для широкого універсуму **вже є** й не підключений: `office_br/universe.py` (усі USDT-M PERPETUAL TRADING, `PRIORITY` = XAU, XAG, CL, BZ, NATGAS, COPPER, XPT, XPD закріплені в кожній ротації) + `office_br/scheduler.py` (`BR_LIVE_DYNAMIC_BATCH`, перевірка ваги/бану Binance).
- **Office2 Brain**: `office2/live.py` `DEFAULT_UNIVERSE` — короткий CORE (BTC, ETH, BNB, SOL, XRP, DOGE, ADA, AVAX, LINK, DOT, LTC …); `OFFICE2_DYNAMIC_UNIVERSE` вимкнено / `watch` (лише спостереження, без READY/Telegram); `live` не вмикався (рішення власниці було відкладено, `docs/office2/HANDOFF.md`).
- **Scout/сканер контексту** (логи `[scout]`/`[funnel]`): бачить ≈237 ф'ючерсів (є COPPER, XPD, акції-перпи), але XAUUSDT там лише «контекст ринку», сигнали по ньому не генеруються.
- На Binance USDT-M існують ТрадФі-перпи (XAU, XAG, CL, BZ, NATGAS, COPPER, XPT, XPD — ті, що в PRIORITY; наявність і назви перевіряти по живому `exchangeInfo`, у цій пісочниці binance недоступний).

## Що робити (кроки, без зміни ризику/ордерів)
1. Після Resume Worker і стабілізації пам'яті: `BR_LIVE_DYNAMIC_UNIVERSE=1` + малий `BR_LIVE_DYNAMIC_BATCH` (напр. 12–20 за цикл) → B&R сканує всі PERPETUAL з ротацією, метали/енергія закріплені. Це збільшує навантаження на Binance (ліміт 2400 вага/хв, раніше були 418-бани) — стежити за `used_weight_1m`.
2. Нові символи позначити в БД (колонка/тег `universe_tier`: core12 / extended / tradfi), щоб порівнювати результативність окремо; виводити в звіт ChatGPT: чи метали/енергія дають кращий net R, чи в інші сесії.
3. Office2 Brain: `OFFICE2_DYNAMIC_UNIVERSE=watch` → оцінити WATCH-якість по тредфі-інструментах → лише потім окремим рішенням власниці `live`.
4. Специфіка ТрадФі: торгові години/перерви, інша вартість (spread/funding) — витрати 0.15% для них НЕ ПІДТВЕРДЖЕНІ; виміряти окремо.
Все — тільки shadow/paper; LIVE-гейти, ризик, ордери не чіпати.
