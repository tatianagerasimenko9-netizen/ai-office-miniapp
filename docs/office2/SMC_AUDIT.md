# SMC: звірка Masterplan із Brain v2.1 (після PR #162–#163)

Дата: 09.10.2026. Це внутрішній етап роботи, а не зупинка. Джерела: Masterplan «AI Office × Smart Money Concept» (методичка SM Trader від 20.03.2026, 40 схем), PDF «Strong Candle Probability Levels Tester [SYNC & TRADE]», код `office2/*` на `main` = `70394ba`.

## Матеріали й що з ними зроблено

| Матеріал | Що є | Висновок |
|---|---|---|
| Методичка SM Trader (Додаток A) | Повний текст (Додаток A, ~96 тис. символів), зміст (Додаток B), посилання | Прочитано повністю; кожен підрозділ має `source_section_id` (`office2/smc/sources.py`). Відео й статті за посиланнями **недоступні** й не вважаються прочитаними |
| Навчальні схеми (Додаток C) | **40** зображень (запит згадував 41) | Усі 40 переглянуто, прив'язано до розділів, зменшені копії + sha256 у `fixtures/smc/sm_trader/`. 41-ї схеми немає — зафіксовано (D-07) |
| PDF Strong Candle Tester | 3 сторінки (прочитано через pypdf) | Опис індикатора/стратегії TradingView: Volume Delta, Supertrend (ATR 5, mult 2,62), Fibonacci-сітка входів 0–78,6% і цілей 127,2–462%, сильна свічка = z-score ≥2. **Формули «сильної свічки» автор не розкриває** → у код не переносимо; Strong Candle лишається EVIDENCE (D-08) |
| Telegram-експорт (result1.json) | 2 208 повідомлень | Контекст розмови; не джерело правил |

## Що вже було в Brain v2.1

| Блок Masterplan | Brain v2.1 | Стан |
|---|---|---|
| A. Data health (закриті бари, 429/backoff, staleness) | `Feed`, `wait_bar_closed`, priority/backoff (#162–#163), `UNVERIFIED` у вікні даних | **є** |
| B. HTF narrative / карта TF | `brain.htf_context`, `brain2.build_map`, counter-trend gate з HTF-локацією й доказом H1 | **є** |
| C. Подія → зсув → POI → тригер | `brain2._sweep_events → _shift → _entry_zone → _evaluate` | **частково** (див. нижче) |
| D. Confluence (BTC, CVD, OI, funding, Wyckoff, Bulkowski, Gerchik, Strong Candle) | `evidence.collect`, `align` — ЗА/ПРОТИ у знімку | **є** (OI/funding — RESEARCH; DOM/GEX — NOT_CONNECTED) |
| E. Ризик: SL+люфт, шум ≥1 ATR, TP від реальних рівнів, простір ≥1R, $-ризик, portfolio gate | `_finalize`, `brain.targets_for`, `engine.portfolio_gate` | **є** |
| F. Вивід: READY/WAIT, Telegram коротко, Mini App повністю | `delivery`, `webview`, `mini_v2.html` | **є**, але графік показує лише зону/SL/TP, не «що побачив Office» |
| Заморожені знімки, життєвий цикл, STALE/MISSED, затримка | #161–#163 | **є** |

## Що працювало частково

- **Swing**: Brain — 5-свічкові фрактали (`features.swings(n=2)`), методичка — 3 свічки (D-05).
- **Зсув структури**: «перше закриття за останнім swing після події + displacement ≥1,2 ATR» — спрощення; методичка не вимагає displacement для MSS, але вимагає, щоб ламався **захищений** мінімум (початок останньої ноги).
- **Свіжий sweep vs прийнятий рівень**: Brain лише *пояснює* (`prior.closes_beyond ≥ 3` → текст «повторний тест після прийняття»), READY не блокує (за правилом «без failed-research gates»). Методичка (кейс ONDO 0,4882) — прийнятий рівень не дає свіжого raid. SMC позначає `LATE_SWEEP`; чи робити це воротами Brain — рішення власниці (не змінювалось).
- **OB/FVG**: у Brain — склад зони входу (остання ведмежа свічка перед displacement; FVG у нозі), без перевірки поглинання, MT, тестів, «поваги» FVG.
- **Сесії**: власні вікна `office_sessions`; DST враховано, але killzones джерела («UTC+3/KZ») неоднозначні (D-02).
- **PD/OTE**: є OTE 62–79%; «застарілих якорів» немає.

## Чого не було

Стан структури BMS/MSS/CONFIRM із захищеним мінімумом і розпізнаванням корекції; Range/Deviation/Expansion; життєвий цикл рівнів і класи проколу; Breaker/Mitigation (2 профілі)/Rejection/Sponsored/StB-BtS; VI/Void/Gap/BPR; External/Internal; HRLR/LRLR; окремі графи Reversal і Continuation (2 MS); NYM/Judas/PO3/AMD з DST; overlay «що побачив Office» на реальному графіку; матриця відповідності.

## Що суперечить методичці

1. Swing 5 свічок замість 3 (D-05) — **не змінюємо** в Brain, SMC працює за методичкою.
2. READY на прийнятому рівні (LATE_SWEEP) — Brain допускає (навмисно), методичка — ні. Питання до власниці.
3. Displacement як обов'язкова частина «зсуву» — вимога Brain, якої немає в методичці.
4. Текст методички суперечить схемам у BOS/BMS/MSB і Mitigation Block (D-01, D-03); killzones (D-02); Sponsored Candle (D-04) — зафіксовано, обидва варіанти збережено.

## Що зроблено в цьому пакеті

Пакет `office2/smc/` (чисті детектори без lookahead, SHORT = дзеркало LONG), SMC-вердикти Reversal/Continuation як події-графи, фоновий shadow (`office2_smc_shadow`), display-поле `smc` у знімку READY, шар SMC і панель у Mini App, time-frozen replay Brain vs SMC, реєстр джерел і матриця. Живі READY, пороги Brain, ризик, Telegram — **без змін**.
