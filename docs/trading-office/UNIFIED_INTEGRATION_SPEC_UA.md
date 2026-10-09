# AI Trading Office: єдина специфікація інтеграції методик

Статус: **архітектурний контракт для shadow-реалізації; production READY не змінює**.
Базовий commit: `30d2b7e4f50522b5bdd604e7392d3cb452db08ba` (`main`, PR #162–#164).
Дата інвентаризації: 09.10.2026.

## 1. Межі достовірності

Цей документ не проголошує торгову перевагу й не дає новим методикам права створювати production READY.

### 1.1. Доступні джерела

| Джерело | Доступні байти | Що можна стверджувати |
|---|---|---|
| SM Trader, Smart Money Concept від 20.03.2026 | Реєстр розділів у `office2/smc/sources.py`, формалізація в `docs/office2/SMC_RULES.md`, 40 зменшених схем із хешами оригіналів у `fixtures/smc/sm_trader/`, код і тести | 40 схем прочитані й пов'язані з правилами; 41-ї схеми немає. Відео та зовнішні статті не вважаються прочитаними |
| О. Герчик, «Курс активного трейдера», 2019 | **Оригінального PDF/сканів у Cloud VM немає.** Є похідний конспект `office_worker_library/books/gerchik_kurs_aktyvnoho_treydera/KONSPEKT_UA.md` і операційні файли `system/*.md` | Можна специфікувати лише правила, явно позначені в конспекті як переказ книги. Не можна стверджувати, що Cursor прочитав книгу або оригінальні схеми |
| Булковскі | PDF `office_worker_library/enciklopediya_bulkovsky.pdf`, конспект і чинний `office_bulkowski.py` | Реалізовані фігури є окремим джерелом геометрії, а не «моделями Герчика» |
| Strong Candle | Pine-порт та похідна реалізація; аудит в `docs/office2/SMC_AUDIT.md` | `sc-ours-1` — власна формалізація Office, не відтворення закритої авторської формули |
| Production-дані | Публічний read-only Web/API; прямого Render/Postgres доступу немає | Web SHA і read-only стан перевіряються; Worker SHA, deploy ID та restart-логи без Render-доступу не припускаються |

Шлях користувачки `C:\Users\Admin\Desktop\AI_Office_Cursor_Gerchik_SMC_Sources` не змонтований у Cloud VM. До появи архіву твердження «повні першоджерела Герчика прочитані» має статус `SOURCE_UNAVAILABLE`.
Оригінальний файл SM Trader (Masterplan/DOCX) також не збережений у Git: доступні лише похідний реєстр, формалізація, 40 webp-схем і зафіксовані хеші. Тому джерельна атрибуція SMC відтворюється з репозиторію, але повна повторна звірка тексту з оригіналом зараз неможлива.

### 1.2. Заборонені підміни

- Схема або текстовий опис не є real-data validation.
- Синтетичний тест не є доказом торгової переваги.
- OHLC-проксі Order Flow не є DOM або стрічкою біржових ордерів.
- Taker buy volume/CVD не є повним order book.
- Розрахована ліквідаційна оцінка не є liquidation heatmap провайдера.
- MODELED/PAPER результат не є реальною угодою або PnL користувачки.
- Відсутній feed позначається `DATA_UNAVAILABLE`; значення не відновлюється «з голови».

## 2. Один Office, один життєвий цикл

Нові методики не створюють окремий Brain, outbox, Telegram-контур або таблицю бойових сигналів. Вони підключаються як версіоновані аналітичні модулі до наявного Office2.

```text
real OHLCV + verified auxiliary feeds
                │
                ▼
        canonical market snapshot
                │
     ┌──────────┼───────────┐
     ▼          ▼           ▼
 Brain v2.1   SMC shadow   Gerchik shadow
     │          │           │
     └──── unified evidence graph ────┐
                                      ▼
                              comparison / replay
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
        existing Brain READY                 shadow observations
        (unchanged authority)                (no Telegram READY)
                    │
                    ▼
 existing outbox → Telegram → lifecycle → Mini App
```

### 2.1. Канонічний стан

Використовується наявний `office2_live_scenario`/`office2_live_transition`/`office2_live_signal`; frozen snapshot не переписується. Для нових детекторів потрібне відображення на існуючу семантику:

| Універсальний стан | Office2 | Значення |
|---|---|---|
| `CANDIDATE` | `WATCH` або shadow `CANDIDATE` | Геометрія/рівень існує, але послідовність ще не сформована |
| `FORMING` | `WAIT`, етап у reason/transition | Є частина причинного ланцюга; система явно зберігає, чого бракує |
| `CONFIRMED` | `WAIT`/shadow `ARMED` | Патерн підтверджено закритим баром, але ціна/виконання ще не готові |
| `ENTRY_READY` | Brain `READY` або shadow `READY` | Entry, structural SL, targets, costs і freshness перевірено |
| `ACTIVE` | лише після verified `/position` для реальної угоди; окремо modeled lifecycle | Дотик ціни не означає реальну позицію |
| `TP/SL` | `SCENARIO_MILESTONE` | Рівень сценарію торкнуто; без `/position` не писати «угоду закрито» |
| `EXPIRED` | `EXPIRED` | TTL завершився до входу |
| `INVALIDATED` | `INVALIDATED`/`NO_TRADE`/`MISSED` | Структура зламана, дані невалідні або вхід запізнився |

Не створюється третя state machine. Методичні внутрішні кроки зберігаються у `steps`/`sequence`, а зовнішній lifecycle лишається Office2.

### 2.2. Контракт аналітичного модуля

Кожен модуль повертає один структурований observation:

```json
{
  "method": "BRAIN|SMC|GERCHIK|BULKOWSKI|WYCKOFF|STRONG_CANDLE",
  "version": "immutable-version",
  "source_rule_ids": ["..."],
  "symbol": "BTCUSDT",
  "market": "binance_usdm",
  "direction": "LONG|SHORT|NEUTRAL",
  "timeframe": "M15",
  "decision_bar_close_utc": "ISO-8601",
  "state": "CANDIDATE|FORMING|CONFIRMED|ENTRY_READY|INVALIDATED|EXPIRED",
  "lineage": {
    "candle_source": "binance_futures",
    "closed_only": true,
    "max_source_ts": "ISO-8601",
    "fixture": false
  },
  "geometry": {
    "points": [],
    "levels": [],
    "zone": null
  },
  "entry": null,
  "invalidation": null,
  "targets": [],
  "obstacles": [],
  "facts_for": [],
  "facts_against": [],
  "missing": [],
  "ambiguities": [],
  "overlay": null
}
```

Обов'язкові інваріанти:

1. `max_source_ts <= decision_bar_close_utc`.
2. Усі точки мають `bar_index`, `ts`, `price`, `confirmed_at`.
3. `ENTRY_READY` неможливий без structural invalidation, перевіреної біржової точності ціни, costs і цілі.
4. `DATA_UNAVAILABLE` не конвертується в нейтральне підтвердження.
5. LONG/SHORT мають дзеркальну математику, якщо джерело не задає асиметрію.
6. Observation не викликає Telegram і не пише `office2_live_signal`.

## 3. Спільна карта ринку

Методики використовують один time-frozen snapshot, а не незалежно завантажують свічки.

### 3.1. Мінімальні дані

| Дані | Призначення | Поточний стан |
|---|---|---|
| Binance USD-M OHLCV M1/M5/M15/H1/H4/D1/W1/MN | структура, патерни, replay | M15/H4/D1/W1/MN у Office2; M5 запитується для кандидата; M1 — delivery/lifecycle |
| `taker buy volume` | M15 delta/CVD-проксі | `office2.evidence`, EVIDENCE |
| BTC/ETH, breadth, relative strength | ринковий контекст | наявний snapshot, EVIDENCE/CONTEXT |
| PDH/PDL/PWH/PWL/PMH/PML, H4/D1 swings, session H/L | POI, перешкоди, targets | наявні частково/повністю в Brain |
| OI/funding/L:S/liquidations | research-контекст | мережевий RESEARCH; не gate |
| DOM | реальний стакан | не підключений до Office2 як надійний feed |
| GEX/options | options context | `NOT_CONNECTED` |
| macro calendar | event risk | існує legacy-шар, до Office2 не підключений |
| Volume Profile | профіль за ціною | немає підтвердженого canonical feed/алгоритму Office2 |

Перед аналізом snapshot проходить:

- пропуски й дублікати timestamp;
- очікувану ширину TF;
- тільки завершені бари;
- freshness;
- `symbol`/contract/market identity;
- futures проти spot;
- наявність OHLCV і, де потрібно, taker volume;
- provenance та fixture flag.

### 3.2. Канонічні API повторного використання

Новий інтеграційний façade має бути read-only відносно Brain і використовувати наявні обчислення замість паралельних реалізацій:

| Потреба | Канонічний API | Умова використання |
|---|---|---|
| Остання завершена свічка | `office2.features.last_closed` | єдине правило відсікання незавершених/future bars |
| Frozen multi-TF context | `office2.brain.build_full_ctx` | той самий snapshot для Brain, SMC і Gerchik |
| Рівні та їхні timestamps | `office2.brain.all_levels` | не будувати незалежний production-набір рівнів |
| Інструментний люфт | `office2.brain2.level_luft` | зберігати формулу й provenance; не підміняти фіксованим відсотком |
| Структурні цілі | `office2.brain.targets_for` | source-specific 3R зберігати окремим варіантом |
| Evidence/readiness даних | `office2.evidence.collect` | `UNAVAILABLE` не стає нейтральним фактом |
| Portfolio authority | `office2.engine.portfolio_gate` | викликається лише чинним Brain READY-контуром |

Façade може нормалізувати результати у contract з §2.2, але не викликає `brain2.assess`, `portfolio_gate`, outbox або Telegram від імені shadow-модуля.

### 3.3. Поточні ризики дублювання та semantic drift

1. `office2/smc/*` є канонічним traceable shadow-стеком; legacy `office_smc.py` досі використовується в `office_ready_evidence.py`, `office_confluence.py`, `office_scan_funnel.py` та частині UI. Їхні назви не гарантують однакових порогів або lifecycle. Legacy не можна непомітно підмінити новим SMC.
2. «Дзеркало» має щонайменше три несумісні значення: зона, яка була і support, і resistance (`office_levels.py`); штучне віддзеркалення LONG/SHORT геометрії у тестах/replay; role flip після підтвердженого пробою у методиці Герчика. У contract це окремі типи `mixed_touch_zone`, `symmetry_transform`, `role_flip_retest`.
3. Sweep/false-break і рівні будують кілька модулів (`office_smc.py`, `office2/smc`, Brain levels, market-data helpers). До уніфікації результати зіставляються через provenance та semantic group, а не взаємозамінюються.
4. Legacy Lev/Telegram і Office2 мають різні ключі dedup та різні lifecycle. Єдиний Office означає поступову adapter-міграцію з regression fixtures, а не запис shadow-подій у будь-який із бойових ledger.
5. Kill Zone/session gates не охоплюють усі legacy Lev/radar маршрути. До консолідації UI має показувати, який саме route і version сформував факт.

## 4. Єдина модель доказів

Office не підсумовує назви в непрозорий score. Він будує причинний граф:

```text
market regime
  → location / level / liquidity
  → initiating event
  → structural response
  → pattern confirmation
  → retrace / execution trigger
  → structural invalidation
  → obstacles / targets / costs
  → WAIT | shadow ENTRY_READY | Brain READY
```

### 4.1. Групи корельованих фактів

Факти в одній групі не рахуються як незалежні підтвердження:

| Група | Приклади синонімів/перетинів |
|---|---|
| Structure break | Brain BOS/CHoCH, SMC BMS/MSS/Confirm, Gerchik trend break |
| Liquidity failure | Brain sweep/reclaim, SMC SFP/FRESH_RAID, Gerchik false breakout |
| Imbalance/impulse | Brain displacement/FVG, SMC FVG/Void, Strong Candle |
| Level role change | Brain structural level, Gerchik mirror, SMC breaker/retest |
| Compression | Brain attacks/compression, Gerchik піджаття, Bulkowski triangle |
| Range | Brain regime, SMC Range, Wyckoff accumulation/distribution, Bulkowski rectangle |

Для UI зберігається `semantic_group`, `source_methods` і спільний факт. Наприклад, один wick-reclaim може мати три назви, але є одним ринковим фактом.

### 4.2. Ролі

- `GATE`: лише чинні Brain v2.1 правила.
- `EVIDENCE`: підтвердження/суперечність у frozen trace.
- `CONTEXT`: опис режиму/локації.
- `RESEARCH`: накопичення даних без впливу.
- `NOT_CONNECTED`: код або feed відсутній.

SMC і Герчик залишаються `SHADOW` незалежно від стану їхнього observation.

## 5. SMC: специфікація моделей

Повна матриця 47 правил лишається джерелом істини в `docs/office2/SMC_MATRIX.md`. Тут зафіксована інтеграційна семантика.

| Модель | Виявлення | Підтвердження | Інвалідація | Entry/SL/targets | Статус |
|---|---|---|---|---|---|
| Structure | 3-candle swing; HH/HL/LH/LL; BMS за structural swing | MSS за protected level; Confirm — перше оновлення нового напряму | `MSS_FAILED`; break внутрішнього swing = correction | Не є входом самостійно | Реалізовано shadow |
| Range/Deviation | ≥2 high і low у 1.5 ATR; висота ≥2 ATR | повернення ≤3 бари = deviation; ≥2 closes = expansion | вихід >0.5 ATR | Контекст/подія | Реалізовано shadow |
| Liquidity | swing, EQH/EQL, range, previous-period/session levels | SFP або `FRESH_RAID`; lifecycle рівня | `ACCEPTED_BREAKOUT`, `LATE_SWEEP`, `WICK_ONLY` не є fresh raid | Raid extreme задає invalidation | Реалізовано shadow |
| FVG/VI/Void/BPR | правила `office2/smc/imbalance.py` | respect/fill state лише після закриття | body beyond far edge | POI; самостійно входу немає | FVG сильніше; інші частково |
| OB | остання протилежна свічка + body engulf ≤3 bars, impulse ≥0.8 ATR | retest wick/body profile | close beyond MT | POI | Реалізовано shadow |
| Breaker | broken OB після liquidity event + MSS | retest | close behind zone | POI | Реалізовано shadow |
| Mitigation | окремі `MB_TEXT` і `MB_SCHEME` | retest | за профілем | POI | Не зливати профілі |
| Rejection | wick ≥50% range і ≥0.5 ATR через pool | reaction ≥1 ATR або close beyond candle high/low ≤3 bars | close beyond wick MT | POI | Реалізовано shadow |
| Sponsored Candle | OB + liquidity take; два трактування close | не визначено джерелом однозначно | — | Не може бути READY | `verified=false` |
| StB/BtS | SSL/BSL take → MSS ≤20 bars; POI у зоні | retest | close beyond raid extreme | зона між extreme і MSS level | Реалізовано shadow |
| Reversal | HTF POI/raid → RAID → MS → POI → retrace → M15 trigger | chronology + closed trigger | structural break/TTL | shared Brain target geometry | Реалізовано shadow |
| Continuation | HTF bias → RAID → MS1 → HL/LH → MS2 → POI → retrace | second MS + trigger | structure/TTL | shared Brain target geometry | Реалізовано shadow |
| Sessions/Judas/AMD | IANA/DST canonical windows; source-clock окремо | closed events | time/structure | Контекст, не gate | Shadow; D-02 відкрита |

Нерозв'язані SMC суперечності D-01…D-08 з `office2/smc/sources.py` зберігаються як версії, не «виправляються» без джерела.

## 6. Герчик: специфікація моделей

Нижче — формалізація **доступного конспекту**, а не підтвердження за відсутнім оригіналом.

### 6.1. Рівень як спільна сутність

`Level` має:

- `price`, `side`, `tf`, `created_at`, `confirmed_at`;
- `kind`: fixed, trend_break, historical, mirror, limit, gap, abnormal_bar;
- `touches`, `false_breaks`, `undershoots`, `round_number`;
- lifecycle: `IDENTIFIED → APPROACHED → TOUCHED → BROKEN|HELD → RETESTED|INVALIDATED`;
- tolerance, виражений у tick і ATR, а не «пунктах» іншого ринку.

Плаваючий рівень ніколи не є entry anchor.

### 6.2. Відбій БСУ/БПУ

| Поле | Правило доступного конспекту |
|---|---|
| Candidate | D1/HTF level + БСУ |
| Forming | БПУ1 торкається ціни БСУ в межах інструментного tolerance |
| Confirmed | Наступний БПУ2 не пробиває level; недобій не більший за luft |
| Conflict | compression/small bars into level без equalizing bar підтримує breakout, не bounce |
| Entry | У джерелі — limit перед level; для Office лише shadow price, без ордера |
| SL | за level/structural extreme + verified buffer |
| Cancel | break level; undershoot > luft; price moved ≥2 planned stops before fill |
| TP | source variant 3R; окремо structural targets Office для порівняння |

«30 секунд до закриття БПУ2» не переноситься механічно на M15 close-based engine: replay має окремо порівняти `preclose` (потребує intrabar M1) та conservative `after-close`.

### 6.3. Істинний пробій

- Candidate: confirmed level + compression/small bars toward it.
- Confirmed: closed bar beyond level і measurable impulse; «гострий кут» потребує окремої формули, не текстової евристики.
- Invalidated/false breakout: немає follow-through або close повернувся.
- Entry variants мають бути окремими: stop beyond level; conservative retest.
- SL: other side of level/structure.
- Target: source 3R і structural obstacle; якщо obstacle раніше — `NO_TRADE` у методичному shadow.

### 6.4. Хибний пробій

Три окремі варіанти:

1. `FALSE_BREAK_1BAR`: wick/close beyond level і close назад на одному барі.
2. `FALSE_BREAK_2BAR`: перший close beyond, наступний close назад.
3. `FALSE_BREAK_COMPLEX`: ≥3 bars у breakout zone без continuation, потім return.

Обов'язкові поля: breakout depth/ATR, impulse absence, return timestamp, level prior state. Орієнтир конспекту `depth <= 1/3 ATR` є source threshold і тестується окремо, без підгонки. `LATE_SWEEP`/accepted level не називається fresh false breakout.

### 6.5. Дзеркало/ретест

- До role flip потрібні історична роль, closed breakout/acceptance і retest тієї самої price area.
- Простий відкат без попередньої події не є mirror.
- Gerchik mirror, SMC breaker і Brain level retest можуть описувати один факт; він не дає три голоси.

### 6.6. ATR і ризик

Доступний конспект описує ATR за 3–5 попередніх D1 без поточного та без abnormal days. Це **не** тотожне Wilder ATR(14), який використовують інші частини Office. Зберігаються окремі поля:

- `atr_wilder_14`;
- `gerchik_range_3_5`;
- `day_used_pct`;
- `technical_room`;
- `stops_in_range`.

Source-варіант `day_used >=75–80%` і operational `>=80%` не змішуються. До real-data validation це shadow conflict, не production veto. Для crypto SL лише structural; відсоткові межі — audit fields.

### 6.7. Моделі, які не можна атрибутувати Герчику зараз

У доступному конспекті не знайдено достатнього першоджерела для точного алгоритму:

- третя точка трендової;
- «Три індіанці»;
- 1-2-3 High/Low;
- зовнішній бар як самостійний setup;
- блюдце;
- cup and handle;
- wedges як модель Герчика;
- Fibonacci як окремий entry setup Герчика.

Wedges і частина chart patterns уже належать модулю Bulkowski. Cup and Handle згадується лише у похідному розділі сумісності. До надходження архіву вони мають статус `SOURCE_UNAVAILABLE` для Gerchik і не реалізуються під його ім'ям.

### 6.8. Фактичний стан реалізації Герчика

- `office_gerchik_kernel.py` уже обчислює operational score 0–10 та `gerchik_atr_trend_veto` на 80%. Це похідний AI-шар, а не повний book detector.
- ATR-вето 80% реально використовується в частині legacy Lev/radar маршрутів; окремий T0 lifecycle використовує 90%. Тому формулювання «Gerchik лише display-only» було б неправильним. Ці пороги не змінюються цією специфікацією.
- Office2 має level luft/mirror-related evidence, але це не реалізація книжкового role-flip setup.
- Машини станів БСУ→БПУ1→БПУ2, book mirror, трьох варіантів false breakout і причинно правильного Gerchik replay немає.
- Наявні три значення «mirror» з §3.3 мають бути розведені типами до написання detector, інакше тести можуть формально пройти для іншої семантики.

## 7. Existing Office capabilities

| Інструмент | Фактична роль | Заборона на завищену назву |
|---|---|---|
| HTF/LTF, BTC/ETH, relative strength | Context/Evidence | не gate без доведеного edge |
| ATR/RSI | ATR активно; RSI context | індикатор не замінює сценарій |
| Volume/taker delta/CVD | Office2 M15 evidence з `tbv`; окремі legacy/archive контури | Це taker-volume-derived CVD. Live Lev не має універсального CVD feed; не називати повним order flow |
| OI/funding/L:S/liquidations | Research | `fetch_liquidations_proxy` моделює зони з 24h high/low; це не provider heatmap. Реальні force orders є окремим обмеженим потоком |
| DOM | rate-limited legacy short-list через depth endpoint; не Office2 canonical | не називати загальносистемним або історично replayable DOM |
| Wyckoff | H1 Evidence | фаза не є позицією великого гравця |
| Bulkowski | підтверджені формалізовані patterns | назва «схоже на», доки геометрія не пройшла validation |
| Strong Candle | `sc-ours-1` Evidence | не авторська закрита формула |
| Sessions | кілька legacy реалізацій; Office2 canonical треба уніфікувати | не використовувати fixed UTC+3 як Kyiv |
| Calendar | legacy, Office2 `NOT_CONNECTED` | не стверджувати macro gate |
| Volume Profile | реалізації та canonical feed немає | звичайний candle volume не є профілем обсягу за ціною |
| GEX/options | `NOT_CONNECTED` | не виводити proxy як біржовий GEX |

## 8. Replay і критерії права на вплив

### 8.1. Dataset contract

Кожен набір фіксує:

- exchange, market, symbol, contract;
- source URL/API/export hash;
- UTC start/end, TF, expected/actual bars;
- missing/duplicate bars;
- timezone conversion;
- fees, spread, slippage;
- development/holdout regime split;
- immutable dataset hash.

Якщо Binance повертає HTTP 451, дозволений шлях — ліцензований архів, user export або replay у Worker з read-only доступом. Synthetic fixtures не входять у performance result.

### 8.2. Однакове виконання

- рішення тільки після close;
- fill: наступний доступний bar/open або окремо заявлений limit-touch model;
- same-bar TP+SL → консервативно SL;
- outcomes: TP-first, SL-first, unresolved, expired, missed;
- net R після fees/slippage;
- MFE/MAE, time-to-entry, time-to-result;
- drawdown і cluster exposure;
- rejected-signal counterfactual;
- confidence interval/bootstrap і minimum sample declaration.

Порівняння:

1. Brain v2.1 baseline.
2. SMC shadow.
3. Gerchik shadow.
4. Brain∩SMC, Brain∩Gerchik, Brain∩SMC∩Gerchik.
5. Розбіжності й пропущені рухи.

Комбінація — це логічний graph intersection, а не сума балів.

### 8.3. Promotion gate

Методика не переходить із shadow, доки одночасно не виконано:

- primary source provenance complete;
- no-lookahead property tests;
- real-data invariant coverage;
- достатній holdout sample у різних regimes;
- результат після costs не гірший baseline із заявленою невизначеністю;
- rejected-signal audit не показує руйнівного recall loss;
- latency/resource budget;
- restart/idempotency/dedup tests;
- окреме погодження власниці на production rule change.

## 9. Mini App

UI читає єдиний frozen scenario:

- header: symbol, direction, lifecycle, method/version;
- fresh price + source timestamp;
- entry zone, SL, TP1–TP3, R і net assumptions;
- canonical market fact chain;
- confirmations vs contradictions;
- nearest obstacles;
- WAIT/READY/INVALIDATED reason;
- validity deadline в `Europe/Kyiv` та UTC;
- real candles конкретного symbol/market;
- overlays із `source_rule_id`, точками й `confirmed_at`;
- method tabs є різними поясненнями одного scenario, не окремими сигналами.

На 390 px: без горизонтального overflow, без raw JSON, цифри не менше основного readable size; важливі ризики перед деталями. Історичні source images показуються лише у навчальному розділі з маркуванням «приклад методики», ніколи як live chart.

## 10. Telegram

Існуючий `office2/delivery.py` та outbox лишаються єдиним шляхом. Shadow нічого не надсилає.

Коротка картка Brain READY:

```text
LONG|SHORT · SYMBOL
ENTRY …
SL … · TP1/TP2/TP3 …
R …
Підстава: один причинний ланцюг
Критична перешкода/інвалідація: …
Діє до … Europe/Kyiv
Графік: Mini App URL
```

Dedup key — stable scenario/event identity, а не literal message text. Зміна wording не створює повторну подію.

## 11. Безпечна реалізаційна послідовність

1. **Source completion:** отримати й захешувати архів; звірити Gerchik notes із первинними сторінками/схемами; оновити attribution.
2. **Canonical contracts:** винести observation/geometry/lineage contract без зміни Brain output.
3. **Gerchik shadow core:** levels → bounce/breakout/false-break/mirror → ATR variants; feature flag, окрема shadow storage.
4. **Unified evidence graph:** semantic grouping і conflict detection; SMC/Brain/Gerchik не голосують.
5. **Time-frozen replay:** однакові datasets/execution, development/holdout.
6. **UI:** method explanations та overlays з existing frozen candles.
7. **End-to-end:** restart, DB compatibility, dedup, no-data, latency, mobile.
8. **Production shadow deploy:** лише після окремого погодження; READY authority незмінна.
9. **Promotion proposal:** лише з real-data report і окремим погодженням.

Rollback кожного нового шару: feature flag → `0`; старі таблиці/поля не видаляються; migrations additive; Web витримує відсутні shadow fields.

## 12. Acceptance matrix

| Результат | Доказ |
|---|---|
| Старий Office цілий | byte-equivalent Brain decisions у fixtures з feature flags on/off; existing regression suite |
| Немає lookahead | prefix invariance: додавання future bars не змінює past observation |
| Реальний detector | coordinates + timestamps + source rules на real OHLCV |
| Немає дублювання | one canonical scenario, multiple method observations |
| Restart safe | persisted state hydrate, no repeated CONFIRM/Telegram |
| DATA_UNAVAILABLE safe | no READY/promotion from missing required data |
| Telegram safe | outbox idempotency; text change does not bypass event dedup |
| UI professional | desktop + 390 px browser walkthrough; real candle provenance |
| Replay honest | dataset manifest, hashes, costs, holdout, uncertainty |
| Production verified | Web and Worker SHA/deploy ID/logs plus DB/read-only smoke |

## 13. Поточний висновок

Сьогодні production-ready authority має лише чинний Brain v2.1. SMC shadow технічно працює, але не довів edge. Gerchik у коді представлений mirror evidence та спрощеним operational score; це не повна реалізація методики. Повна Gerchik-інтеграція заблокована відсутністю первинного архіву в Cloud VM. Жодна з цих обставин не є підставою змінювати READY, ризик або Telegram.
