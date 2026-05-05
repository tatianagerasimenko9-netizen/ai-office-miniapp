===01.05.2026 ===

ВИПРАВЛЕНО:
✅ FILTER повідомлення тепер показує причину:
   🚫 ALLOUSDT · score 13 · CHOP
   замість: 🚫 ALLOUSDT · FILTER · score 13

ОНОВЛЕНО (дисципліна):
✅ Додано дисциплінарні фільтри без рефакторингу ядра:
   - session discipline для SCALP (clean-zone; Asia опційно);
   - hard cap по позиціях в один бік через DISCIPLINE_MAX_SAME_DIR;
   - сесійний контекст у AI-тегах тепер рахується через дисциплінарне правило.

НОВИЙ ФАЙЛ СТРАТЕГІЇ:
✅ Створено `СТРАТЕГІЯ_ЦІЛЬ_ДНЯ_01.05.2026.md`
   - покроковий план: стабілізація -> P0 тест -> TARGET MODE -> звітність.

ОНОВЛЕНО (TARGET MODE):
✅ Додано блок "Ціль дня" в код:
   - `TARGET_MODE_ENABLED`, `TARGET_DAILY_USD`, `TARGET_PER_TRADE_USD` у CONFIG;
   - додано `TARGET_BLOCK_ALL_SIGNALS` (за замовч. `False`);
   - при `TARGET_BLOCK_ALL_SIGNALS=False` ICT/SMC/PREPUMP/PREDUMP не блокуються;
   - глобальна зупинка всіх входів працює лише якщо явно увімкнути `TARGET_BLOCK_ALL_SIGNALS=True`;
   - у `daily_report(...)` додано блок прогресу до цілі:
     - Ціль дня / Зароблено / Залишилось / Угод до цілі;
     - при виконанні: "✅ Ціль досягнута!".

ОНОВЛЕНО (PREPUMP/PREDUMP):
✅ PREPUMP/PREDUMP тепер не "тільки ніч":
   - додано `PREPUMP_REQUIRE_NIGHT_ONLY=False` (за замовч.);
   - сигнал може формуватись у будь-який час доби, якщо виконане ядро якості.
✅ Нічні guard-и ізольовано:
   - додано `PREPUMP_GUARDS_ONLY_IN_NIGHT_WINDOW=True`;
   - killswitch/нічні ліміти застосовуються тільки у нічному вікні.
✅ Створено окремий файл стратегії:
   - `СТРАТЕГІЯ_PREPUMP_PREDUMP_01.05.2026.md`
   - детально: ролі, правила, кроки, чек-лист 3 дні.

ОНОВЛЕНО (стратегічні бонуси score):
✅ Додано 3 бонуси як окремий шар:
   - `BTC_MSB_CONFIRM +2` (по імпульсу BTC за 30 хв у бік сигналу),
   - `ASIAN_SWEEP_QUALITY +2` (якісний Asian range + sweep),
   - `POSITIONAL_TF +1` (для `1h` / `4h`).
✅ У повідомленні сигналу додано рядок:
   - `⚡ Бонуси: ...` (якщо є активні бонуси).

ОНОВЛЕНО (звітність бонусів):
✅ Бонуси збережено в угоді і в історії фіксацій:
   - `bonus_tags` пишеться в `active_trades` та `closed_trades_log`.
✅ У `daily_report(...)` додано окремий блок:
   - "⚡ Бонуси (по закритих угодах)"
   - Всього з бонусами + WR + USD
   - окремо для `BTC_MSB_CONFIRM`, `ASIAN_SWEEP_QUALITY`, `POSITIONAL_TF`.

ОНОВЛЕНО (анти-тиша PREPUMP/PREDUMP):
✅ Послаблено занадто жорсткі фільтри, які душили частоту:
   - `NIGHT_PREPUMP_ONLY_MOVERS: True -> False`
   - `NIGHT_PREPUMP_VOL_EXPAND_X: 1.30 -> 1.15`
   - `NIGHT_PREPUMP_LEVEL_TOL_PCT: 1.20 -> 1.80`
✅ Логіка безпеки та ядро setup НЕ зламані:
   - `PREPUMP_REQUIRE_NIGHT_ONLY=False` лишається;
   - `PREPUMP_GUARDS_ONLY_IN_NIGHT_WINDOW=True` лишається;
   - mandatory core (compression + volume + level) лишається.
