# PR-X — Пачка 3 (канал) і Пачка 4 (календар із блоком входу)

**Регресійний канал як підтвердження** (`office_regression_channel.tags_for`, тег `channel_edge`, «межа регресійного каналу»):
LONG — нижня межа каналу (на кінці) у зоні сценарію (допуск 0,25 σ), остання закрита свічка закрилась не нижче межі, нахил ≥ 0; SHORT — дзеркально. Лише закриті свічки, ≥31 свічка. Підключено в `office_confluence.detect_ltf_confirms` через `FORMAL_TAGS`. Тест: `scripts/test_channel_tag.py`.

**Макрокалендар** (`office_calendar.py`, вмикається `OFFICE_CALENDAR_BLOCK=1`, за замовчуванням вимкнено): безкоштовний тижневий JSON (faireconomy/ForexFactory), лише `impact=High` і країни `OFFICE_CALENDAR_COUNTRIES` (USD). Вікно блоку −30/+15 хв від виходу новини (те саме, що в NEWS_CHAOS). Блок стоїть у `office_lev_watch.check_plan` — тобто діє і на Telegram-підтвердження, і на «Готово/Не готово» у Mini App (причина людською мовою, план відстежується мовчки як відхилений). Немає даних → `DATA_UNAVAILABLE`, вхід не блокуємо, Mini App чесно пише «календар недоступний». У Mini App — блок «Новини». Тест: `scripts/test_calendar.py`.

**Не підключено (чесно):** карта ліквідацій — безкоштовного надійного джерела немає; платне (Coinglass тощо) — лише за рішенням власниці з ціною. OI / funding / long-short — показ у Mini App (`office_market_context`), пороги інформаційні й нічого не блокують.

**Не змінено:** ATR 80/90, Edge 85, RR ≥ 1,5, TP1, Risk Officer, ризик 1%, Telegram-правила.
