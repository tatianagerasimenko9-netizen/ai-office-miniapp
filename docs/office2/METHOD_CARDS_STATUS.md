# Реєстр 82 методологічних карток — стан за кодом

Автогенерація: `PYTHONPATH=. python3 scripts/method_coverage_audit.py --md`. Статус виводиться з виконання коду, а не з документів.

- **IMPLEMENTED** — входи формуються з реальних джерел (закриті свічки / READY-план / календар / D1), є predicate і тести. Це НЕ означає «доведено прибутковим» чи «активний фільтр у production».
- **PARTIAL** — входи формуються, але форма/таймфрейм/пороги — наша інтерпретація (ГІПОТЕЗА), джерело її не фіксує.
- **BLOCKED** — у реєстрі зафіксовано, чого бракує (`missing_parameters`); без нового матеріалу не реалізується.
- **UNKNOWN** — builder відсутній, блокера в реєстрі немає (потрібна робота).
- **NOT_APPLICABLE** — реєстр сам визначає запис як не-торгове правило (приклад/QA) або замінене для крипти.

Підсумок: {'FORMED_SOURCE': 45, 'BLOCKED': 27, 'NOT_APPLICABLE': 4, 'FORMED_HYPOTHESIS': 6}

| Правило | Метод | Статус | Деталь |
|---|---|---|---|
| G-LVL-FLOATING | GERCHIK_LEVELS | IMPLEMENTED | PASS |
| G-LVL-LIMIT | GERCHIK_LEVELS | IMPLEMENTED | PASS |
| G-LVL-PARANORMAL | GERCHIK_LEVELS | IMPLEMENTED | FAIL |
| G-LVL-TRENDBREAK | GERCHIK_LEVELS | IMPLEMENTED | FAIL |
| G-LVL-MIRROR | GERCHIK_LEVELS | IMPLEMENTED | FAIL |
| G-LVL-CONSOLIDATION | GERCHIK_LEVELS | IMPLEMENTED | PASS |
| G-LVL-CONFIRM-SIGNS | GERCHIK_LEVELS | IMPLEMENTED | PASS |
| G-LVL-CONSTRUCTION | GERCHIK_LEVELS | UNKNOWN | потрібна таблиця дотиків/хибних пробоїв по рівню (джерело радить її вести) — у Brain її немає; допуск близькос |
| G-SIGNAL-CLOSE | GERCHIK_SIGNALS | IMPLEMENTED | PASS |
| G-IMPULSE | GERCHIK_SIGNALS | BLOCKED | вікно часу, за яке має з'явитись імпульс — не вказано |
| G-NO-CHASE | GERCHIK_SIGNALS | UNKNOWN | джерело не дає числа «запізно»; MAX_CHASE_R у Brain — наш параметр, не правило автора |
| G-PRESS | GERCHIK_SIGNALS | IMPLEMENTED | FAIL |
| G-PROGNOSTIC | GERCHIK_SIGNALS | IMPLEMENTED | PASS |
| G-FALSE-BREAK-DEF | GERCHIK_FALSE_BREAK | IMPLEMENTED | PASS |
| G-FB-1BAR | GERCHIK_FALSE_BREAK | IMPLEMENTED | PASS |
| G-FB-2BAR | GERCHIK_FALSE_BREAK | IMPLEMENTED | FAIL |
| G-FB-COMPLEX | GERCHIK_FALSE_BREAK | IMPLEMENTED | PASS |
| G-BOUNCE | GERCHIK_BOUNCE | IMPLEMENTED | FAIL |
| G-BREAKOUT | GERCHIK_BREAKOUT | IMPLEMENTED | FAIL |
| G-RR-MIN3 | GERCHIK_RISK | IMPLEMENTED | PASS |
| G-STOP-CALC | GERCHIK_RISK | NOT_APPLICABLE | stock-market stop (0.1-0.2%); for crypto the source gives G-STOP-CRYPTO |
| G-STOP-TECH | GERCHIK_RISK | IMPLEMENTED | PASS |
| G-STOP-CRYPTO | GERCHIK_CRYPTO | IMPLEMENTED | PASS |
| G-LUFT | GERCHIK_RISK | UNKNOWN | число джерела (0,04% ціни / 20% розрахункового стопа) — для акцій РФ; для крипти розрахунковий стоп не визначе |
| G-ATR-CALC | GERCHIK_ATR | IMPLEMENTED | PASS |
| G-ATR-DAYUSED | GERCHIK_ATR | IMPLEMENTED | PASS |
| G-CHANNEL | GERCHIK_RANGE | UNKNOWN | потрібна розмітка каналу (окремий аудит регресійного каналу не завершено); ширина «в стопах» визначена для акц |
| G-RISK-DAY | GERCHIK_RISK | IMPLEMENTED | PASS |
| G-BE | GERCHIK_RISK | UNKNOWN | у LIVE-супроводі немає перенесення стопа (лише paper-порівняння); автор не вважає BE обов'язковим |
| G-TP-TRAIL | GERCHIK_RISK | UNKNOWN | у LIVE-супроводі немає трейлінгу; джерело якісне (тренд із запасом), порогів немає |
| G-TRIAL-100 | GERCHIK_TRAINING | IMPLEMENTED | PASS |
| G-CRYPTO-SCORE | GERCHIK_CRYPTO | NOT_APPLICABLE | registry class STUDENT_EXAMPLE_NOT_RULE: example/QA, not a trading rule |
| G-INDICATORS-NOT-USED | GERCHIK_SCOPE | IMPLEMENTED | PASS |
| G-STOP-ATR | GERCHIK_RISK | PARTIAL | PASS |
| G-STOP-CRYPTO-TECHNICAL | GERCHIK_CRYPTO | IMPLEMENTED | PASS |
| G-LUFT-FILL | GERCHIK_RISK | UNKNOWN | прив'язане до розрахункового стопа акцій/FX; для крипти немає визначення |
| G-RISK-TRADE | GERCHIK_RISK | IMPLEMENTED | PASS |
| G-FB-DEPTH | GERCHIK_FALSE_BREAK | IMPLEMENTED | PASS |
| G-BE-2R | GERCHIK_RISK | UNKNOWN | у LIVE-супроводі немає перенесення стопа; правило умовне («лише для нервового інструмента») |
| D-STOP-STRUCTURE | DARIA | IMPLEMENTED | PASS |
| D-STOP-ATR-MARGIN | DARIA | BLOCKED | ТФ розрахунку; що таке «звичайна» (немає порогів) |
| D-ATR-LIMITS | DARIA | BLOCKED | ліміт ризику на слайді обрізаний |
| D-LEVEL-STICKING | DARIA | BLOCKED | кількісні пороги не задані |
| D-PRESSURE | DARIA | IMPLEMENTED | FAIL |
| D-PARANORMAL-IMPULSE | DARIA | IMPLEMENTED | PASS |
| D-POST-IMPULSE-BASE | DARIA | IMPLEMENTED | PASS |
| D-VOLUME-PRICE | DARIA | IMPLEMENTED | PASS |
| D-CANDLE-STRENGTH | DARIA | IMPLEMENTED | PASS |
| D-FALSE-BREAK | DARIA | IMPLEMENTED | PASS |
| D-LEVEL-TYPES | DARIA | BLOCKED | межі точності відскоку |
| D-WYCKOFF-CONTEXT | DARIA | BLOCKED | числові умови фаз Wyckoff відсутні |
| D-SESSIONS-NEWS | DARIA | IMPLEMENTED | PASS |
| D-ELLIOTT-RULES | DARIA | BLOCKED | автоматична розмітка не задана |
| D-FIB-LEVELS | DARIA | IMPLEMENTED | PASS |
| D-FRACTAL-TF | DARIA | UNKNOWN | потрібна розмітка хвиль різних ТФ (Еліотт — розмітка в джерелі «гіпотеза», автоматичної немає) |
| D-SCENARIO-CHECKLIST | DARIA | BLOCKED | пороги «біля», «ближній», «хороший запас»; ТФ входу; SL/TP |
| D-HTF-STRONG-CANDLE-PULLBACK | DARIA | BLOCKED | усі числові пороги |
| D-ENTRY-CLOSE-WITHIN-HALF-ATR | DARIA | BLOCKED | ТФ; формула ATR; для LONG дзеркально — не показано |
| G-FIGURES-UNMAPPED | GERCHIK_FIGURES | BLOCKED | посторінкова прив'язка до GERCHIK_BOOK.txt відсутня |
| S-RISK | SMC | IMPLEMENTED | PASS |
| S-SWING3 | SMC | IMPLEMENTED | FAIL |
| S-STRUCTURE | SMC | IMPLEMENTED | PASS |
| S-RANGE | SMC | IMPLEMENTED | PASS |
| S-OTE-PD | SMC | IMPLEMENTED | PASS |
| S-FVG | SMC | IMPLEMENTED | FAIL |
| S-OB | SMC | PARTIAL | PASS |
| S-SESSIONS | SMC | BLOCKED | часовий пояс/DST |
| S-PO3 | SMC | PARTIAL | PASS |
| S-LIQUIDITY-RAID | SMC | IMPLEMENTED | PASS |
| S-BLOCKS-OTHER | SMC | BLOCKED | формальні умови не задані |
| S-REVERSAL-CONT | SMC | PARTIAL | PASS |
| S-KAVYA-CONCEPTS | OTHER_VERIFIED_SMC | IMPLEMENTED | PASS |
| O-CANDLE-PATTERNS | OTHER_VERIFIED_PATTERNS | IMPLEMENTED | PASS |
| X-UX-CRB-BTW | OFFICE_UX_EXAMPLE | NOT_APPLICABLE | registry class UX_EXAMPLE_NOT_RULE: example/QA, not a trading rule |
| X-QA-RUNE | OFFICE_PRODUCT_QA | NOT_APPLICABLE | registry class PRODUCT_QA_NOT_RULE: example/QA, not a trading rule |
| X-NOT-SPECIFIED-BULKOWSKI | BULKOWSKI | BLOCKED | усе |
| X-NOT-SPECIFIED-WYCKOFF-NUMERIC | WYCKOFF | BLOCKED | усі пороги |
| D-FIB-REACTION-NOT-LIMITS | DARIA | BLOCKED | що саме є «реакцією» (свічковий тригер, ТФ) — НЕ ПІДТВЕРДЖЕНО; ТФ реакції |
| D-HTF-LTF-CONFIRM | DARIA | PARTIAL | PASS |
| D-NO-CONFIRMATION-NO-TRADE | DARIA | PARTIAL | PASS |
| X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP | DARIA | BLOCKED | ТФ входу; тригер; люфт для ТФ входу; управління позицією |
| D-REACTION-AFTER-RETURN | DARIA | BLOCKED | ТФ реакції (M1/M5/M15/H1) — НЕ ПІДТВЕРДЖЕНО; кількість свічок і формальна ознака реакції — НЕ ПІДТВЕРДЖЕНО; ві |
