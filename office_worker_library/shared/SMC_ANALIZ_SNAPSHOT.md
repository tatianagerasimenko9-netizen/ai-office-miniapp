# SMC — повний аналіз реалізації в боті
## Дата: 28.04.2026
## Джерело: https://smart-money.trading/smart-money-concept/

## Таблиця реалізації по пунктах

| Пункт | Що це | Є в боті | Де в коді | Якість реалізації | Що покращити |
|-------|-------|----------|-----------|-------------------|--------------|
| Структура ринку (HH/HL/LH/LL, MSB, BMS) | Визначення тренду/зміни структури через свінги | Частково | `detect_market_structure()`, `update_daily_bias()`, `scan_sym_smc()` | Середня | Додати явний поділ MSS/MSB/BMS як окремі стани, не лише `bullish/bearish/neutral`; додати confirm-рівень якості |
| Range і Expansion | Логіка накопичення -> вихід імпульсом | Частково | `detect_squeeze()`, `detect_market_regime()`, `update_asian_range()` | Середня | Додати явний state-machine `RANGE -> SWEEP -> EXPANSION` для відсікання шуму всередині range |
| Fibonacci / OTE (0.62-0.79) | Оптимальна зона відкату у dealing range | Так (частково) | `calc_smc_level()` (OTE 0.786), `scan_sym_smc()` (`ote_lo/ote_hi` 0.62-0.79) | Добра | Уніфікувати OTE між ICT і SMC (зараз різні реалізації), додати окрему статистику OTE-hit |
| FVG / Imbalance (всі види) | Неефективність ціни (FVG/VI/LV/Gap/BPR) | Частково | `find_fvg()` | Середня | Додати окремі детектори `VI`, `Liquidity Void`, `Opening Gap`, `BPR`; додати класифікацію сили зони (0.25/0.5/0.75/FF) |
| Ліквідність (BSL/SSL, PDH/PDL/PWH/PWL) | Пули ліквідності як цілі/фільтр | Частково | `get_d()/get_w()` (PDH/PDL/PWH/PWL), `detect_sfp()`, TP-логіка у `calc_entries()` | Добра | Додати явну карту liquidity-pools у сигналі (external/internal + nearest pool) |
| Order Block (бичачий/ведмежий, Breaker, Mitigation, Rejection) | POI після sweep + імпульс | Частково | `find_order_block()`, використання в `calc_smc_level()` і `scan_sym_smc()` | Середня | Додати окремі модулі `detect_breaker_block()`, `detect_mitigation_block()`, `detect_rejection_block()` (зараз breaker/mitigation/rejection не виділені як окремі сутності) |
| Wick / SFP | Ложний пробій з поверненням у діапазон | Так | `detect_sfp()`; інтеграція в `scan_sym()`/`scan_sym_smc()` | Добра | Додати геометрію wick (wick/body, ATR-нормалізація), і окремий режим входу від wick 0.5 |
| Kill Zones та сесії | Часові вікна активності + маніпуляція | Так, але у 2 різних контурах | ICT-контур: `is_london_kill_zone()`, `is_ny_kill_zone()`, `in_asia_open_manip()`, `in_asia_session()`; SMC-контур: `smc_kz_state()` | Нерівномірна (критично) | Уніфікувати KZ у єдине джерело часу: зараз ICT і SMC живуть за різними правилами |
| PO3 (Accumulation->Manipulation->Distribution) | 3-фазна модель дня/руху | Частково | `detect_amd_pattern()` (по суті PO3/AMD), `update_daily_bias()` | Середня | Додати явні PO3-теги у статистику: `po3_accum`, `po3_manip`, `po3_dist` |
| Judas Swing | Ложний рух на старті KZ перед істинним рухом | Так (у 2 місцях) | `update_daily_bias()` (через Asian sweep), `_smc_judas_confirm()` (first 30 min KZ) | Добра | Уніфікувати критерії Judas між ICT і SMC, щоб уникнути різних трактувань |
| NYM / Midnight Open (00:00 NY = 07:00 Київ) | Рівень відкриття NY дня | Так (DST-aware) | `_midnight_open_tz()`, `get_midnight_open()`, `MIDNIGHT_OPEN_TZ` | Добра | Додати в лог явний розрахований час NYM по Києву на поточний день для прозорості |
| AMD (Accumulation/Manipulation/Distribution) | Патерн маніпуляції і доставки | Так | `detect_amd_pattern()` | Добра | Додати перевірку контексту (лише в KZ + з HTF bias), бо зараз частково може працювати поза оптимальним часом |
| Чек-лист торгової системи | Дисципліна: ризик, паузи, контекст, фільтри | Частково | `MAX_DAILY_LOSS_PCT`, `LOSS_STREAK_MAX`, `corr_same_side_allowed()`, `get_min_score()`, фільтри у `scan_sym*` | Середня | Додати формальний pre-trade checklist (структура, ліквідність, POI, KZ, RR, ризик) з логом pass/fail |

## Kill Zones — порівняння еталон vs бот

### Еталон (з твого ТЗ)
- Asian KZ: `02:00-05:00` Київ  
- London KZ: `08:00-11:00` Київ  
- NY KZ: `14:00-16:00` Київ  
- NY Lunch: `16:00-17:00` (уникати входів)  
- Judas Swing: перші `15-30 хв` кожної KZ

### Що зараз у боті (фактично)

#### 1) Базовий ICT-контур (`scan_sym`)
- `is_london_kill_zone()` -> `08:30-10:00` (через `LONDON_KILL_ZONE_START/END`)
- `is_ny_kill_zone()` -> `14:30-15:00` (через `NY_KILL_ZONE_START/END`)
- `is_asia_kill_zone()` окремої функції немає; аналоги:
  - `in_asia_open_manip()` -> `03:00-04:00` (блок)
  - `in_asia_session()` -> `04:00-07:00`
- NY Lunch `16:00-17:00` у базовому ICT-контурі як жорсткий блок **не знайдено**
- Judas:
  - Є логіка через `update_daily_bias()` (wick-sweep London vs Asian range)
  - Але це не строгий універсальний "first 15-30 min кожної KZ" для всіх входів

#### 2) Окремий SMC-контур (`scan_sym_smc`)
- `smc_kz_state()`:
  - ASIA: `02:00-05:00`
  - ЛОНДОН: `08:00-11:00`
  - НЬЮ-ЙОРК: `14:00-16:00`
- NY Lunch:
  - `16:00-17:00` -> жорсткий skip (`SMC_SKIP ... NY lunch 16:00-17:00`)
- Judas:
  - `_smc_judas_confirm(... first_30=True)` -> перші 30 хв KZ реалізовані

### Висновок по KZ
- У SMC-контурі еталон із ТЗ реалізований коректно.
- У базовому ICT-контурі — інші часові вікна та інша логіка (маніп-вікна + clean-zone).

## Критичні розбіжності

1. **КРИТИЧНО P0:** Роздвоєна логіка часу між `scan_sym` і `scan_sym_smc`  
   - SMC працює по еталону, ICT — по іншій схемі (`08:30-10:00`, `14:30-15:00`, Asia `03:00-07:00`).
2. **КРИТИЧНО P0:** В базовому ICT-контурі немає явного NY Lunch hard-block `16:00-17:00`.
3. **КРИТИЧНО P1:** Немає єдиного `is_asia_kill_zone()`/уніфікованого API часу; Asia в ICT розбита на кілька ф-цій.
4. **КРИТИЧНО P1:** Judas у двох реалізаціях (daily bias vs first_30 KZ) без єдиного стандарту.
5. **КРИТИЧНО P1:** Сайт має внутрішні суперечності по KZ/NYM між різними сторінками, а в коді нема "канонічного джерела правил" для автоперевірки.

## Що реалізовано добре

- SMC-модуль має повний контур KZ по еталону + NY Lunch блок + Judas first_30.
- Є робочий AMD/PO3-патерн (`detect_amd_pattern`) із градацією сили.
- Є валідний SFP/Wick детектор, інтегрований у scoring.
- Є DST-aware підхід до NY Midnight Open через `America/New_York` (а не жорстка година).
- Є risk-обмеження системного рівня: daily loss, loss streak pause, correlation cap.

## Що відсутнє або слабке

- **P0:** Єдина часова політика KZ для всіх контурів (ICT + SMC).
- **P0:** NY Lunch hard-block у базовому ICT-контурі.
- **P1:** Повна сім'я imbalance-типів (VI, LV, Opening Gap, BPR) як окремі детектори.
- **P1:** Окремі модулі Breaker/Mitigation/Rejection, зараз лише часткова підтримка через OB/SFP/FVG.
- **P2:** Формальний checklist-движок перед входом (машиночитний pass/fail журнал).

## ТОП-5 покращень

1. Зробити єдиний модуль `kz_policy()` і підключити його одночасно в `scan_sym` та `scan_sym_smc`.
2. Додати в базовий ICT-контур hard-block `NY Lunch 16:00-17:00` (як уже зроблено в SMC).
3. Уніфікувати Judas-правило: перші 30 хв KZ + sweep + close-back, одні й ті ж критерії для всіх контурів.
4. Розширити imbalance-движок: FVG + VI + LV + Gap + BPR, з оцінкою сили та окремою статистикою.
5. Додати pre-trade checklist-лог (структура, ліквідність, POI, KZ, RR, ризик), щоб після угоди було видно, чому саме був вхід/skip.

---

Примітка по джерелу: на сайті є суперечливі години KZ/NYM між різними сторінками (наприклад, `smart-money-concept` vs `kill-zone`). Для цього аналізу еталоном взято твої задані години з ТЗ, і порівняння зроблено саме з ними.

## WICK — аналіз реалізації
## Джерело: https://smart-money.trading/wick/

### Таблиця по пунктах

| Пункт | Що це | Є в боті | Де в коді | Якість | Що покращити |
|-------|-------|----------|-----------|--------|--------------|
| Wick в трейдингу — що це | Ложний пробій/зняття ліквідності тінню з поверненням ціни | Частково (через SFP) | `detect_sfp()` | Добра | Додати окремий `detect_wick()` з метриками тіні/тіла, а не лише SFP-умови |
| Критерії формування Wick | Маленьке тіло + довга тінь + sweep + close-back | Частково | `detect_sfp()` (sweep + close-back), локальні `wick_up/wick_down` у скорингу | Середня | Додати формальні критерії: `wick/body`, мін. тінь у ATR, POI-контекст |
| Способи входу (від тіні / Wick 0.5) | Вхід від початку тіні або від середини тіні (0.5) | Ні (напряму для Wick) | Немає окремого wick-entry; OB mid є в `find_order_block()` | Слабка | Додати `wick_entry_mode`: `wick_open` і `wick_mid_0_5` |
| Стоп-лос за тінню | SL за екстремум wick | Частково/опосередковано | `calc_entries()` ставить stop від swing/ATR, не від конкретного wick | Слабка | Додати опцію `wick_stop = wick_extreme +/- buffer` |
| Wick на молодшому ТФ = ордер блок | На LTF wick може розкладатися в OB | Частково | Є окремо `find_order_block()`, але без прямого bridge "wick->ob" | Середня | Додати явну зв'язку: якщо SFP знайдено на HTF, шукати OB на LTF в межах wick-діапазону |
| Схожість Wick і Rejection Block | Rejection/wick як вузька форма OB після sweep | Частково | Логіка sweep є в `detect_sfp()`, OB є в `find_order_block()` | Середня | Додати `rejection_block` тег та окрему статистику відпрацювання |

### SFP в боті — детально

- Де рахується SFP (ядро Wick-логіки):
  - `detect_sfp()`:
    - `lo < key_low` + `close > key_low` -> bullish SFP
    - `hi > key_high` + `close < key_high` -> bearish SFP
  - Конкретні рядки: `L3044-L3063`.

- Як SFP впливає на score (ICT контур):
  - У `scan_sym`:
    - виклик `sfp_type, sfp_msgs = detect_sfp(df)`
    - якщо напрям збігається з SFP -> `score += 3`
  - Конкретні рядки: `L3603-L3610`.

- Як SFP використовується в SMC контурі:
  - `scan_sym_smc`:
    - `sfp_type = detect_sfp(df, lookback=8)`
    - входить у `liq_sweep` як тригер якості сетапу
  - Конкретні рядки: `L4494-L4498`.

- Чи є Wick 0.5 як точка входу:
  - Окремої wick 0.5 логіки **немає**.
  - Є `0.5` тільки для **Order Block mid** (`entry_price = ob_low + (ob_high-ob_low)*0.5`) — це не wick 0.5.
  - Конкретні рядки: `L3128`, `L3161`.

- Чи є вхід від початку тіні:
  - Явного wick-entry "від початку тіні" **немає**.
  - Entry уніфіковано через `level["price"]` або поточний close.
  - Конкретні рядки: `L3850`.

- Де ставиться стоп відносно тіні:
  - Прямої прив'язки до wick-екстремуму **немає**.
  - Stop ставиться від `swing +/- ATR` і обмежень `min/max stop pct`.
  - Конкретні рядки: `L3858-L3876`.
  - `hard/tech stop` далі будуються від цього stop (`L3913-L3920`), а не від wick.

### Критичні розбіжності з еталоном

1. **КРИТИЧНО P1:** Немає окремих способів входу з методички `від початку тіні` та `Wick 0.5`.
2. **КРИТИЧНО P1:** Немає стопа "за тінь" як окремого правила керування ризиком для wick-сетапів.
3. **КРИТИЧНО P1:** Wick і Rejection Block не оформлені як окремий модуль/клас сетапу (лише розкидані через SFP + OB).

### ТОП-3 покращення для Wick логіки

1. Додати `detect_wick_rejection()` з критеріями: `wick/body`, ATR-нормалізація, close-back, POI-контекст.
2. Додати `wick_entry_mode`: `wick_open` і `wick_mid_0_5` (з окремою статистикою WR/RR).
3. Додати `wick_stop_mode`: стоп за екстремум тіні + buffer, і порівняння з поточним ATR-stop (A/B метрика).
