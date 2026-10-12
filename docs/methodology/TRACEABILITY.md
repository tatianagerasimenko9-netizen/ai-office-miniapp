# TRACEABILITY — методики → правила → код → статус

Згенеровано з `docs/sources/evidence.jsonl` (`python3 scripts/gen_traceability.py`). Статус береться з реєстру, не з назви методу. «НЕ ПІДТВЕРДЖЕНО» = у наданих матеріалах числа/правила немає.

Підсумок за статусом реалізації: NOT_IMPLEMENTED: 18, SHADOW_SOURCE_REGISTRY: 9, IMPLEMENTED_SHADOW: 9, SHADOW_ONLY: 8, SOURCE_REGISTRY_ONLY: 7, IMPLEMENTED_PARTIAL: 3, PAPER_COMPARISON_ONLY: 3, SHADOW_MEASURE_ONLY: 3, NO_TRADING_GATE: 2, NOT_IMPLEMENTED_AS_SOURCE_RULE: 2, NOT_ENFORCED_IN_BRAIN: 1, DIFFERENT_APPROACH: 1, IMPLEMENTED: 1, IMPLEMENTED_DIFFERENT_FORM: 1, POLICY_ALIGNED: 1, SCOPE_NOTE: 1, NOT_APPLIED: 1, IMPLEMENTED_AS_OUR_VARIANTS: 1, IMPLEMENTED_APPROX: 1, NOT_IMPLEMENTED_AS_SOURCE_DETECTOR: 1, IMPLEMENTED_AS_OUR_IMPL: 1, SHADOW_FIB_LEVELS: 1, NOT_APPLIED_CONFLICT: 1, IMPLEMENTED_OUR_VARIANT: 1, UX_REFERENCE_ONLY: 1, QA_REFERENCE_ONLY: 1, NOT_IMPLEMENTED_AS_ENTRY_GATE: 1, SHADOW_RESEARCH_REPLAY_ONLY: 1

## BULKOWSKI

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| X-NOT-SPECIFIED-BULKOWSKI | — | — | NOT_SPECIFIED_IN_PROVIDED_SOURCES | office_bulkowski.py (наш код; не з наданих джерел) | NOT_IMPLEMENTED_AS_SOURCE_RULE | NA | усе |

## DARIA

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| D-STOP-STRUCTURE | Дарія Жданова (zdanova_invest) | не вказано | SOURCE_QUALITATIVE | office2/stops.py | IMPLEMENTED_AS_OUR_VARIANTS | PARTIAL | числа немає |
| D-STOP-ATR-MARGIN | Дарія Жданова (zdanova_invest) | ТФ не вказано | SOURCE_NUMERIC | office2/stops.py:ATR_MARGIN_PCT=12.5 | IMPLEMENTED_APPROX | PARTIAL | ТФ розрахунку; що таке «звичайна» (немає порогів) |
| D-ATR-LIMITS | Дарія Жданова (zdanova_invest) | — | SOURCE_QUALITATIVE | — | SOURCE_REGISTRY_ONLY | NOT_IMPLEMENTED | ліміт ризику на слайді обрізаний |
| D-LEVEL-STICKING | Дарія Жданова (zdanova_invest) | D1 + молодший ТФ | SOURCE_QUALITATIVE | office2/daria_shadow.py | SHADOW_MEASURE_ONLY | PARTIAL | кількісні пороги не задані |
| D-PRESSURE | Дарія Жданова (zdanova_invest) | рівень + ТФ | SOURCE_QUALITATIVE | office2/daria_shadow.py | SHADOW_MEASURE_ONLY | PARTIAL | числа немає |
| D-PARANORMAL-IMPULSE | Дарія Жданова (zdanova_invest) | D1 | SOURCE_NUMERIC | — | NOT_IMPLEMENTED_AS_SOURCE_DETECTOR | DIFFERS | розмір вікна ATR; обсяг |
| D-POST-IMPULSE-BASE | Дарія Жданова (zdanova_invest) | D1 (дні) | SOURCE_NUMERIC | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | ТФ інших ніж D1; волатильність у базі (якісно) |
| D-VOLUME-PRICE | Дарія Жданова (zdanova_invest) | — | SOURCE_QUALITATIVE | — | SOURCE_REGISTRY_ONLY | NOT_IMPLEMENTED | числа немає |
| D-CANDLE-STRENGTH | Дарія Жданова (zdanova_invest) | — | SOURCE_QUALITATIVE | office2/strongcandle.py:sc-ours-1 | IMPLEMENTED_AS_OUR_IMPL | PARTIAL | числа немає |
| D-FALSE-BREAK | Дарія Жданова (zdanova_invest) | рівень + ТФ входу | SOURCE_NUMERIC | office2/integration/gerchik_scenarios.py (аналогічна модель Герчика) | SHADOW_SOURCE_REGISTRY | PARTIAL | обрізаний текст щодо ризику |
| D-LEVEL-TYPES | Дарія Жданова (zdanova_invest) | D1/ТФ входу | SOURCE_QUALITATIVE | — | SOURCE_REGISTRY_ONLY | NOT_IMPLEMENTED | межі точності відскоку |
| D-WYCKOFF-CONTEXT | Дарія Жданова (zdanova_invest) | діапазон | SOURCE_QUALITATIVE | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | числові умови фаз Wyckoff відсутні |
| D-SESSIONS-NEWS | Дарія Жданова (zdanova_invest) | — | SOURCE_QUALITATIVE | — | NO_TRADING_GATE | NA | DST/часові пояси |
| D-ELLIOTT-RULES | Дарія Жданова (zdanova_invest) | будь-який | SOURCE_QUALITATIVE | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | автоматична розмітка не задана |
| D-FIB-LEVELS | Дарія Жданова (zdanova_invest) | старший ТФ | SOURCE_NUMERIC | office2/htf_scenario.py:FIB_RETRACE; office2/strongcandle.py | SHADOW_FIB_LEVELS | PARTIAL | вибір якорів — не формалізовано |
| D-FRACTAL-TF | Дарія Жданова (zdanova_invest) | W1/D1/H4/H1 | SOURCE_QUALITATIVE | — | SOURCE_REGISTRY_ONLY | NOT_IMPLEMENTED | — |
| D-SCENARIO-CHECKLIST | Дарія Жданова (контекст власниці; handle на сторіс «домашка») | D1 (+молодші) | SOURCE_QUALITATIVE_ATTRIBUTION_BY_CONTEXT | office2/daria_shadow.py | SHADOW_MEASURE_ONLY | PARTIAL | пороги «біля», «ближній», «хороший запас»; ТФ входу; SL/TP |
| D-HTF-STRONG-CANDLE-PULLBACK | власниця (USER_REQUIREMENT) | D1/H4 → H1/M15 → M5/M1 | USER_REQUIREMENT | office2/htf_scenario.py | SHADOW_ONLY | PARTIAL | усі числові пороги |
| D-ENTRY-CLOSE-WITHIN-HALF-ATR | Дарія Жданова (контекст власниці; сторіс «дом…» 30.11.2021) | ТФ не вказано (графік D1) | SOURCE_NUMERIC_ATTRIBUTION_BY_CONTEXT | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | ТФ; формула ATR; для LONG дзеркально — не показано |
| D-FIB-REACTION-NOT-LIMITS | Дарія Жданова (zdanova_invest) | старший ТФ (розмітка хвиль; приклад хвилі 2 і 4) | SOURCE_QUALITATIVE | — | NOT_IMPLEMENTED | DIFFERS: paper-вхід = ліміт на межі зони, заповнюється від дотику (office_signal_track.simulate) | що саме є «реакцією» (свічковий тригер, ТФ) — НЕ ПІДТВЕРДЖЕНО; ТФ реакції |
| D-HTF-LTF-CONFIRM | Дарія Жданова (zdanova_invest) | W1/D1 → H1 (у прикладі слайда; контекст хвиль Еліотта) | SOURCE_QUALITATIVE | — | SOURCE_REGISTRY_ONLY | PARTIAL: HTF-контекст у Brain є; формальної перевірки «молодший не суперечить» як правила з цього джерела немає | конкретний молодший ТФ входу (M1/M5/M15) — НЕ ПІДТВЕРДЖЕНО; у прикладі слайда молодший = H1 для розкриття хвилі, не для точки входу |
| D-NO-CONFIRMATION-NO-TRADE | Дарія Жданова (zdanova_invest) | рівень + ТФ входу (не названо); сценарій хибного пробою | SOURCE_QUALITATIVE | — | NOT_IMPLEMENTED_AS_ENTRY_GATE | DIFFERS: paper заповнюється від дотику, а не від виконаного тригера | форма підтвердження і ТФ — НЕ ПІДТВЕРДЖЕНО; правило задокументоване для хибного пробою, не для всіх сценаріїв |
| X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP | Дарія Жданова (zdanova_invest) | — | NOT_SPECIFIED_IN_PROVIDED_SOURCES | — | NOT_IMPLEMENTED | UNKNOWN | ТФ входу; тригер; люфт для ТФ входу; управління позицією |
| D-REACTION-AFTER-RETURN | Дарія Жданова (zdanova_invest) | рівень на старшому ТФ; ТФ реакції не названо | SOURCE_QUALITATIVE | office2/reaction_shadow.py (RESEARCH_HYPOTHESIS, shadow) | SHADOW_RESEARCH_REPLAY_ONLY | DIFFERS у чинному алгоритмі (ліміт від дотику); shadow-варіант — окрема дослідницька гіпотеза, не авторське правило | ТФ реакції (M1/M5/M15/H1) — НЕ ПІДТВЕРДЖЕНО; кількість свічок і формальна ознака реакції — НЕ ПІДТВЕРДЖЕНО; відсоток/глибина відкату — НЕ ПІДТВЕРДЖЕНО; коли саме «вихід із боковика» є входом — не задано числом |

## GERCHIK_ATR

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-ATR-CALC | Герчик | D1 | SOURCE_NUMERIC | office_atr_policy.py (ATR(14), інша формула) | NOT_IMPLEMENTED | DIFFERS | — |
| G-ATR-DAYUSED | Герчик | D1 | SOURCE_NUMERIC | office_atr_policy.py:GERCHIK_TREND_ENTRY_BLOCK_PCT=80 | IMPLEMENTED | CONFORMS | — |

## GERCHIK_BOUNCE

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-BOUNCE | Герчик | D1 рівень + ТФ входу | SOURCE_NUMERIC | office2/integration/gerchik_scenarios.py:GERCHIK-08-VIDBIY | SHADOW_ONLY | PARTIAL | 30 с — для ручної торгівлі; для автоматизації не застосовується |

## GERCHIK_BREAKOUT

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-BREAKOUT | Герчик | D1 рівень | SOURCE_QUALITATIVE | office2/integration/gerchik_scenarios.py:GERCHIK-09-PROBIY | SHADOW_ONLY | PARTIAL | кількісна межа «малі бари» |

## GERCHIK_CRYPTO

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-STOP-CRYPTO | Герчик | — | SOURCE_NUMERIC | office2/integration/gerchik_source_rules.py:G-CRYPTO-CONTEXT | SHADOW_SOURCE_REGISTRY | PARTIAL | точний множник — «до 2%» |
| G-CRYPTO-SCORE | Герчик (приклад студентів) | — | STUDENT_EXAMPLE_NOT_RULE | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | ваги — прикладні |
| G-STOP-CRYPTO-TECHNICAL | Герчик | — | SOURCE_NUMERIC | office2/stops.py (v2 «за структурою», кругле число як ліквідність) | IMPLEMENTED_PARTIAL | PARTIAL | пункти для крипти |

## GERCHIK_FALSE_BREAK

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-FALSE-BREAK-DEF | Герчик | D1 рівень | SOURCE_QUALITATIVE | office2/integration/gerchik_scenarios.py | SHADOW_SOURCE_REGISTRY | PARTIAL | — |
| G-FB-1BAR | Герчик | D1 рівень, вхід у тому ж ТФ | SOURCE_NUMERIC | office2/integration/gerchik_scenarios.py:GERCHIK-06-LP-1BAR | SHADOW_ONLY | PARTIAL | відступ у крипті |
| G-FB-2BAR | Герчик | D1 | SOURCE_NUMERIC | office2/integration/gerchik_scenarios.py:GERCHIK-06-LP-2BAR | SHADOW_ONLY | PARTIAL | — |
| G-FB-COMPLEX | Герчик | D1 | SOURCE_NUMERIC | office2/integration/gerchik_scenarios.py:GERCHIK-06-LP-COMPLEX | SHADOW_ONLY | PARTIAL | — |
| G-FB-DEPTH | Герчик | D1 ATR | SOURCE_NUMERIC | office2/integration/gerchik_scenarios.py | SHADOW_ONLY | PARTIAL | — |

## GERCHIK_FIGURES

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-FIGURES-UNMAPPED | Герчик (за термінологією; автор на зображеннях не підписаний) | — | NEEDS_SOURCE_MAPPING | — | SOURCE_REGISTRY_ONLY | NA | посторінкова прив'язка до GERCHIK_BOOK.txt відсутня |

## GERCHIK_LEVELS

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-LVL-FLOATING | Герчик | будь-який ТФ | SOURCE_QUALITATIVE | office2/integration/gerchik_source_rules.py:G-LEVEL-FLOATING-NO-TRADE | SHADOW_SOURCE_REGISTRY | PARTIAL | — |
| G-LVL-LIMIT | Герчик | не вказано; приклади D1 | SOURCE_NUMERIC | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | допуск для крипти (не вказано) |
| G-LVL-PARANORMAL | Герчик | D1 | SOURCE_NUMERIC | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | як рахувати «середній» для крипти — див. G-ATR-CALC |
| G-LVL-TRENDBREAK | Герчик | D1 | SOURCE_QUALITATIVE | — | SHADOW_SOURCE_REGISTRY | NOT_IMPLEMENTED | — |
| G-LVL-MIRROR | Герчик | D1/локальний | SOURCE_QUALITATIVE | office2/evidence.py:Gerchik mirror level | IMPLEMENTED_PARTIAL | PARTIAL | — |
| G-LVL-CONSOLIDATION | Герчик | D1 | SOURCE_QUALITATIVE | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | тривалість проторговки (не вказано) |
| G-LVL-CONFIRM-SIGNS | Герчик | D1 | SOURCE_NUMERIC | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | вага ознак окрім «≈20%» для круглих цифр — не вказано |
| G-LVL-CONSTRUCTION | Герчик | D1 (+локальний ТФ для входу) | SOURCE_QUALITATIVE | office2/integration/gerchik_source_rules.py:G-LEVEL-HTF-FIRST; G-LEVEL-LEFT-TO-RIGHT | SHADOW_SOURCE_REGISTRY | PARTIAL | — |

## GERCHIK_RANGE

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-CHANNEL | Герчик | — | SOURCE_NUMERIC | office2/integration/gerchik_source_rules.py:G-CHANNEL | SHADOW_SOURCE_REGISTRY | PARTIAL | — |

## GERCHIK_RISK

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-RR-MIN3 | Герчик | — | SOURCE_NUMERIC | office2/brain.py (мінімальна перша ціль 1.0R) | NOT_ENFORCED_IN_BRAIN | DIFFERS | — |
| G-STOP-CALC | Герчик | — | SOURCE_NUMERIC | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | для крипти див. G-STOP-CRYPTO |
| G-STOP-TECH | Герчик | — | SOURCE_NUMERIC | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | — |
| G-LUFT | Герчик | — | SOURCE_NUMERIC | office2/stops.py (люфт = медіана проколів рівня) | DIFFERENT_APPROACH | DIFFERS | — |
| G-RISK-DAY | Герчик | — | SOURCE_NUMERIC | office2/engine.py portfolio_gate: 3 SL/доба UTC (не обов'язково поспіль) | IMPLEMENTED_DIFFERENT_FORM | PARTIAL | «поспіль» і «сесія» для крипти 24/7 |
| G-BE | Герчик | — | SOURCE_NUMERIC | office2/paper.py | PAPER_COMPARISON_ONLY | PARTIAL | — |
| G-TP-TRAIL | Герчик | — | SOURCE_QUALITATIVE | office2/paper.py | PAPER_COMPARISON_ONLY | PARTIAL | — |
| G-STOP-ATR | Герчик | D1 ATR | SOURCE_NUMERIC | office2/stops.py (ATR(M15), 12.5%) | NOT_IMPLEMENTED | PARTIAL | формула ATR — як у G-ATR-CALC |
| G-LUFT-FILL | Герчик | — | SOURCE_NUMERIC | — | NOT_IMPLEMENTED | DIFFERS | — |
| G-RISK-TRADE | Герчик | — | SOURCE_NUMERIC | office2/risk.py (фіксовано $10) | NOT_APPLIED | DIFFERENT_APPROACH | — |
| G-BE-2R | Герчик | — | SOURCE_NUMERIC | office2/paper.py | PAPER_COMPARISON_ONLY | PARTIAL | — |

## GERCHIK_SCOPE

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-INDICATORS-NOT-USED | Герчик | — | SOURCE_QUALITATIVE | — | SCOPE_NOTE | NOT_IMPLEMENTED | — |

## GERCHIK_SIGNALS

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-SIGNAL-CLOSE | Герчик | будь-який | SOURCE_QUALITATIVE | office2/integration/gerchik_source_rules.py:G-SIGNAL-CLOSE | SHADOW_SOURCE_REGISTRY | CONFORMS | — |
| G-IMPULSE | Герчик | D1/робочий | SOURCE_NUMERIC | office2/integration/gerchik_source_rules.py:G-IMPULSE-CONFIRM | SHADOW_SOURCE_REGISTRY | PARTIAL | вікно часу, за яке має з'явитись імпульс — не вказано |
| G-NO-CHASE | Герчик | будь-який | SOURCE_QUALITATIVE | office2/brain.py:MAX_CHASE_R | IMPLEMENTED_PARTIAL | PARTIAL | — |
| G-PRESS | Герчик | будь-який | SOURCE_QUALITATIVE | office2/daria_shadow.py (виміри без порогів) | SHADOW_ONLY | PARTIAL | кількісні межі «малий/високий» — не вказано |
| G-PROGNOSTIC | Герчик | будь-який | SOURCE_QUALITATIVE | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | ваги |

## GERCHIK_TRAINING

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| G-TRIAL-100 | Герчик | — | SOURCE_NUMERIC | docs/strategies/SOURCE_RULES.md (n≥30 для статистики Office) | POLICY_ALIGNED | PARTIAL | — |

## OFFICE_PRODUCT_QA

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| X-QA-RUNE | AI Office (власний продукт) | — | PRODUCT_QA_NOT_RULE | — | QA_REFERENCE_ONLY | NA | — |

## OFFICE_UX_EXAMPLE

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| X-UX-CRB-BTW | CRYPTO RICH BEARS (зовнішній канал) | — | UX_EXAMPLE_NOT_RULE | — | UX_REFERENCE_ONLY | NA | будь-які відсотки |

## OTHER_VERIFIED_PATTERNS

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| O-CANDLE-PATTERNS | kavya_thetrader (Instagram) | — | SOURCE_QUALITATIVE | — | NOT_IMPLEMENTED | NOT_IMPLEMENTED | усі умови кількісно |

## OTHER_VERIFIED_SMC

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| S-KAVYA-CONCEPTS | kavya_thetrader (Instagram) | — | SOURCE_QUALITATIVE | — | SOURCE_REGISTRY_ONLY | NOT_IMPLEMENTED | числових порогів немає (окрім поради 1–2%) |

## SMC

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| S-RISK | SM Trader (методичка 20.03.2026) | — | SOURCE_NUMERIC | office2/engine.py portfolio_gate (3 SL/доба) | NOT_APPLIED_CONFLICT | CONFLICT_WITH_GERCHIK | — |
| S-SWING3 | SM Trader | будь-який | SOURCE_NUMERIC | office2/smc/structure.py; office2/htf_scenario.py:SWING_N=2 (інше) | IMPLEMENTED_OUR_VARIANT | DIFFERS | — |
| S-STRUCTURE | SM Trader | W1/D1 → H4/H1/M15 | SOURCE_QUALITATIVE | office2/smc/structure.py | IMPLEMENTED_SHADOW | PARTIAL | числових порогів немає |
| S-RANGE | SM Trader | — | SOURCE_NUMERIC | office2/smc/structure.py | IMPLEMENTED_SHADOW | PARTIAL | критерій «є range» кількісно не заданий |
| S-OTE-PD | SM Trader | — | SOURCE_NUMERIC | office2/smc/pd.py | IMPLEMENTED_SHADOW | CONFORMS | — |
| S-FVG | SM Trader | — | SOURCE_NUMERIC | office2/smc/imbalance.py | IMPLEMENTED_SHADOW | CONFORMS | — |
| S-OB | SM Trader | — | SOURCE_NUMERIC | office2/smc/blocks.py | IMPLEMENTED_SHADOW | PARTIAL | умови виникнення OB кількісно не задані (≥0.8 ATR тощо — наше) |
| S-SESSIONS | SM Trader | — | SOURCE_NUMERIC_AMBIGUOUS_CLOCK | office2/smc/sessions.py | NO_TRADING_GATE | NA | часовий пояс/DST |
| S-PO3 | SM Trader | — | SOURCE_QUALITATIVE | office2/smc/sessions.py | IMPLEMENTED_SHADOW | PARTIAL | — |
| S-LIQUIDITY-RAID | SM Trader | — | SOURCE_QUALITATIVE | office2/smc/liquidity.py | IMPLEMENTED_SHADOW | PARTIAL | пороги проколу не задані |
| S-BLOCKS-OTHER | SM Trader | — | SOURCE_QUALITATIVE | office2/smc/blocks.py | IMPLEMENTED_SHADOW | PARTIAL | формальні умови не задані |
| S-REVERSAL-CONT | SM Trader | HTF → LTF | SOURCE_QUALITATIVE | office2/smc/models.py | IMPLEMENTED_SHADOW | PARTIAL | — |

## WYCKOFF

| rule_id | автор | ТФ | клас доказу | реалізація (код) | статус | відповідність | НЕ ПІДТВЕРДЖЕНО / бракує |
|---|---|---|---|---|---|---|---|
| X-NOT-SPECIFIED-WYCKOFF-NUMERIC | — | — | NOT_SPECIFIED_IN_PROVIDED_SOURCES | office_wyckoff.py (наш код) | NOT_IMPLEMENTED_AS_SOURCE_RULE | NA | усі пороги |

