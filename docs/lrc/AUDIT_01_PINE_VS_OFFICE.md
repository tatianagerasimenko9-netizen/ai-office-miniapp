# Linear Regression Channel — аудит Pine (LonesomeTheBlue v4) → Office

Еталон: незалежна реалізація семантики Pine у `scripts/lrc_parity.py` (numpy, побарно). Office: `office_regression_channel.py`, `office_mini_v2.py` (`channel_payload`, `chart_context_payload`), `office_ready_evidence.py`.
Тести: `scripts/test_lrc_parity.py`. Контрольні графіки еталона: `docs/state-notes/lrc-controls/`. Production не змінювався, PR немає.

## Таблиця PINE → OFFICE
| # | Правило Pine | Office зараз | STATUS | Різниця / вплив |
|---|---|---|---|---|
| 5 | `src = close` | `_src_close`: поле `close` | MATCH | — |
| 6 | `len = 100` | `regression_channel(length=100)`; **у різних місцях Office довжина різна** (див. нижче) | PARTIAL | теги READY: 39 свічок; докази #119: 95; Mini App: 100 |
| 7 | `slope = linreg(src,len,0) − linreg(src,len,1)` | `get_channel`: МНК, `slope = y0 − y1` | MATCH | різниця з еталоном ≤ 6·10⁻¹⁴ (12 синтетичних послідовностей) |
| 8 | `mid`, `intercept = mid − slope·floor(len/2) + ((1−len%2)/2)·slope` | та сама формула | MATCH | ≤ 1·10⁻¹⁴ |
| 9 | `endy = intercept + slope·(len−1)` | та сама | MATCH | ≤ 1·10⁻¹⁴ |
| 10 | `dev = sqrt(Σ(src[x] − (slope·(len−x)+intercept))² / len)` | та сама, включно з особливістю `len−x` (зсув на 1 бар відносно намальованої лінії) | MATCH | ≤ 6·10⁻¹⁴ |
| 11 | межі = центр ± dev·devlen (2) | `upper/lower_start/end` | MATCH | ≤ 1·10⁻¹⁴ |
| 12 | напрямок: slope>0 вгору (зелений), <0 вниз (червоний), 0 нейтрально | є `slope` у відповіді; окремого поля `direction` немає; на графіку колір за знаком не задано в payload | PARTIAL | знак можна взяти зі slope, готового стану немає |
| 13 | momentum: стрілки ⇑⇗⇓⇘⇒ (slope vs slope[1]) | немає | **MISSING** | `slope[1]` Office не рахує (перерахунок на попередньому барі відсутній) |
| 14 | `trendisup/trendisdown` (зміна знака slope) | немає | **MISSING** | події зміни напрямку каналу не існують |
| 15 | `outofchannel`: slope>0 і close<нижня → 0; slope<0 і close>верхня → 2; інакше −1 (асиметрично, проти напрямку каналу) | немає | **MISSING** | у Office жодна логіка «пробою каналу» не існує |
| 16 | `alertcondition(outofchannel,'Channel Broken')` | немає | NOT APPLICABLE | **особливість оригіналу:** за неявним приведенням int→bool у Pine v4 (0 → false, інше → true) умова true і при 2, і при −1, тобто «майже завжди», і false лише при пробої висхідного каналу вниз. Це моя інтерпретація правил Pine, у TradingView не перевірено |
| 17 | `showbroken`: на барі переходу −1 → x зберігається **одна** лінія попереднього бару з індексом x (0 — нижня, 2 — верхня) синім пунктиром, extend none; решта ліній видаляється | немає | **MISSING** | уточнення до опису: «старий пробитий канал» = одна пробита межа, а не весь канал (перевірено на еталоні, тест H/I) |
| 18 | синій пунктир ≠ окремий детектор trendline | окремого trendline/counter-trend алгоритму в Office немає (518 комітів) | — | синій пунктир на скріні = broken-line із п.17, а не окрема функція |
| 19 | новий активний канал після пробою (rolling 100) | `chart_context_payload` перераховує канал щоразу на нових свічках | MATCH (активний) / MISSING (старий пробитий поруч) | обидва стани одночасно Office показати не може: другого немає |
| 20 | extend right (активний), extend none (пробитий) | `ch` віддає start/end; продовження вправо робить renderer | PARTIAL | семантики «пробитий — без продовження» нема |
| 21 | Fibonacci 0,236/0,382/0,618/0,786 (за замовчуванням вимкнено) | немає | NOT APPLICABLE | опційна функція оригіналу, у Office не додавати без окремого рішення |
| 22 | READY vs LIVE | READY: `gate.evidence` (заморожено в #119); LIVE: `/api/v2/chart_context`, не залежить від `gate.chart` | MATCH (розділення) | але див. п.6: канал у READY рахується на іншій довжині |
| 27 | без lookahead; forming-бар | Office: лише закриті свічки (`closed_only`), forming відкидається | DIFFERENT by design | Pine на реальному барі перераховується щотіка; Office чекає закриття — поведінка стабільніша, але не 1:1 з live-графіком TradingView |

## Знахідка: довжина каналу = три різні числа
- **Теги READY** (`office_regression_channel.tags_for`, виклик із `detect_ltf_confirms`): relay бере для підтвердження `fetch_candles(sym, tf_wait, 40)` → 40 свічок → `n = min(100, len−1)` = **39**. Тобто `channel_edge` у READY (наприклад, SAMSUNG 20:33 UTC) визначений за каналом на **39** M15 свічках, а не на 100.
- **Докази #119** (`office_ready_evidence.build`): рахуються на frozen 96 свічках → `n = 95`.
- **Mini App LIVE** (`chart_context_payload`, `channel_payload`): 100.
- Тест `test_lrc_parity.py` друкує числа на одній послідовності: slope при 39 / 95 / 100 = −0,12005 / −0,12063 / −0,12048 (на гладкій серії різниця мала; на реальних даних вплив невідомий, потрібна таблиця з `--real`).
- Наслідок для #119: доказ каналу на картці **не** відтворює той канал, за яким поставлено тег `channel_edge`, і не збігається з Mini App. Чесне рішення (після погодження): окреме заморожене вікно розрахунку ≥100 закритих свічок + окреме вікно показу 96; детекція тегу і доказ мають брати те саме вікно.

## Висновки A–H
- **A. Математика каналу:** MATCH (slope, intercept, endy, dev, межі: ≤ 6·10⁻¹⁴ відносної різниці на 12 синтетичних послідовностях; реальні Binance — таблиця буде з `--real` у CI).
- **B. Slope/direction:** PARTIAL (є slope, немає готового напряму/кольору).
- **C. Momentum (⇑⇗⇓⇘⇒):** MISSING.
- **D. Trend change (Up/Down trend):** MISSING.
- **E. Channel break (`outofchannel`, асиметричне правило):** MISSING.
- **F. Broken channel history (синя пунктирна межа):** MISSING.
- **G. LIVE Mini App:** PARTIAL (живий активний канал є; стану, дії та історії немає).
- **H. READY freeze:** PARTIAL (геометрію заморожено, але довжина вікна не 100: тег — 39, доказ — 95).

## Класифікація знахідок (без змін у production)
1. **PARITY BUG:** довжина вікна каналу в тегах READY і доказах #119 ≠ еталону 100; відсутні C, D, E, F (Office заявляє порт Pine, але реалізує лише математику get_channel).
2. **OPTIONAL ORIGINAL FEATURE:** Fibonacci-рівні, колір за знаком, extend.
3. **NEW PRODUCT FEATURE:** показ у Mini App «на момент сигналу → зараз → що змінилось», будь-яке використання пробою каналу як invalidation/Brain — лише після formal rule + історичного тесту.
