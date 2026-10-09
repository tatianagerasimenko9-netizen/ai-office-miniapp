# SMC: матриця відповідності (генерується з `office2/smc/matrix.py`)

Пункт методички SM Trader → правило → код → тест → схема → статус → вплив на рішення. **Усі детектори зараз у режимі SHADOW: живі READY не змінено.** Статус «СИНТЕТИКА» означає: правило реалізовано й перевірено на якісних фікстурах за схемами та на властивостях (без lookahead, дзеркальна симетрія LONG/SHORT, випадкові ряди), але на реальних OHLCV ще не перевірено (потрібен replay у worker з доступом до біржі). Жодних тверджень про прибутковість.

| Правило | Розділ | Що саме | Код | Тест | Схеми | Статус | Вплив на рішення | Brain v2.1 |
|---|---|---|---|---|---|---|---|---|
| R-STR-01 | S09.2/S10.1 | Swing = 3 свічки: центр вищий/нижчий за обидві сусідні; підтвердження закриттям правої; 2 свічки без центру — не swing | `office2.smc.structure.swings` | `scripts/test_smc_structure.py::test_swing_three_candles_and_negative` | 4 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково (n=2, 5 свічок — D-05) |
| R-STR-02 | S10.2/S10.3 | HH/HL/LH/LL/EQH/EQL за порівнянням з попереднім swing того ж типу | `office2.smc.structure.label_swings` | `scripts/test_smc_structure.py::test_uptrend_bms_chain_and_labels` | 5, 6 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково |
| R-STR-03 | S09.3 | BMS = закриття тілом за структурним swing у напрямку тренду; структурний high = найвищий підтверджений swing після останнього зламу | `office2.smc.structure.analyze` | `scripts/test_smc_structure.py::test_uptrend_bms_chain_and_labels` | 8 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає (є простий displacement-зсув) |
| R-STR-04 | S12 | MSS = закриття за захищеним мінімумом (початок останньої ноги) ПІСЛЯ останнього BMS; Confirm = перше оновлення в новому напрямку; MSS_FAILED при поверненні над вершину | `office2.smc.structure.analyze` | `scripts/test_smc_structure.py::test_mss_then_confirm` | 9, 10 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково |
| R-STR-05 | S12 | Злам внутрішнього мінімуму (не початок останньої ноги) — корекція в межах розширення, НЕ MSS | `office2.smc.structure.analyze` | `scripts/test_smc_structure.py::test_correction_break_is_not_mss` | 10, 11 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-STR-06 | S10.4 | Range: ≥2 swing high і ≥2 swing low у допуску 1,5 ATR, висота ≥2 ATR; межі 0/1, EQ 0,5 | `office2.smc.structure.detect_range` | `scripts/test_smc_structure.py::test_range_and_deviation` | 7 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-STR-07 | S10.4/S11 | Девіація (вихід + повернення ≤3 бари) vs прийнятий вихід (≥2 закриття) = expansion | `office2.smc.structure.deviation_events` | `scripts/test_smc_structure.py::test_accepted_breakout_is_expansion_not_deviation` | 7 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-STR-08 | S09.4/S08 | Синхронізація ТФ: пріоритет старшого; локальна корекція ≠ зміна старшої структури | `office2.smc.structure.tf_sync` | `scripts/test_smc_structure.py::test_tf_sync_local_correction_vs_htf_change` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | є (HTF-карта, counter-trend gate) |
| R-STR-09 | S06 | Фази ринку/Wyckoff накопичення-розподіл — гіпотеза, не детектор; спостережувані стани UP/DOWN/RANGE/TRANSITION реалізовано | `office2.smc.structure.analyze` | `scripts/test_smc_golden.py::test_every_scheme_is_mapped_to_a_runnable_golden_check` | 1, 2, 3 | НЕ АЛГОРИТМІЗОВАНО | — | є (Wyckoff як EVIDENCE) |
| R-TF-01 | S07/S08 | Три перспективи: LTP (W/D) → ITP (H1/M15) → STP (M5/M1). SMC читає D1/H4/H1/M15; STP M1/M5 для виконання входу НЕ інтегровано (M5 лишається EVIDENCE у Brain) | `office2.smc.engine.analyze` | `scripts/test_smc_models.py::test_reversal_long_full_sequence_ready` | — | ЧАСТКОВО | SHADOW: показ у картці/логу, READY не змінює | є (HTF-карта MN→M15, M5 EVIDENCE) |
| R-LIQ-01 | S15 | Пули: swing, EQH/EQL (допуск 0,15 ATR), межі range | `office2.smc.liquidity.swing_levels` | `scripts/test_smc_liquidity.py::test_eqh_eql_and_pools` | 15 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково (levels PDH/H4SW…) |
| R-LIQ-02 | S15 | PDH/PDL/PWH/PWL/PMH/PML лише від ПОПЕРЕДНЬОГО закритого періоду | `office2.smc.liquidity.htf_levels` | `scripts/test_smc_liquidity.py::test_htf_levels_previous_closed_period_only` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | є |
| R-LIQ-03 | S15/S27 | Session High/Low завершених сесій (канонічні NY-вікна з DST) | `office2.smc.sessions.session_levels` | `scripts/test_smc_sessions_pd_flow.py::test_session_levels_known_after_session_end_only` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | є (власні вікна) |
| R-LIQ-04 | S15 | Ліквідність за трендовою: проєкція лінії через 2 останні swing (наближення) | `office2.smc.liquidity.trendline_levels` | `scripts/test_smc_liquidity.py::test_eqh_eql_and_pools` | 15 | ЧАСТКОВО | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-LIQ-05 | S15 | External vs Internal liquidity відносно поточного range | `office2.smc.liquidity.ie_class` | `scripts/test_smc_liquidity.py::test_internal_vs_external_liquidity` | 15 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-LIQ-06 | S15/S22 | Життєвий цикл рівня IDENTIFIED→APPROACHED→TOUCHED→SWEPT|ACCEPTED_BREAKOUT→RETESTED|INVALIDATED з перевіркою допустимих переходів | `office2.smc.liquidity.track` | `scripts/test_smc_liquidity.py::test_accepted_breakout_then_retest_then_invalidated` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково (prior closes_beyond) |
| R-LIQ-07 | S22 | Raid/Sweep: FRESH_RAID, SFP, ACCEPTED_BREAKOUT, LATE_SWEEP (не свіжий), WICK_ONLY (шум), PENDING | `office2.smc.liquidity.track` | `scripts/test_smc_liquidity.py::test_late_sweep_after_prior_acceptance_is_not_fresh` | 32 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково |
| R-LIQ-08 | S23 | SFP: прокол swing і закриття назад на тому ж барі | `office2.smc.liquidity.track` | `scripts/test_smc_liquidity.py::test_sfp_same_bar_close_back` | 33 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково |
| R-IMB-01 | S14 | FVG з трьох свічок; ефективне ціноутворення (перекриття тіней) — не FVG | `office2.smc.imbalance.fvgs` | `scripts/test_smc_imbalance.py::test_fvg_geometry_and_efficient_negative` | 13, 14 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | є (FVG у зоні входу) |
| R-IMB-02 | S14.1 | Рівні 0,25/0,5/0,75/FF, «повага» зони, тіла vs тіні (тінь через зону не ламає; закриття тілом за дальньою межею — ламає) | `office2.smc.imbalance.fill_state` | `scripts/test_smc_imbalance.py::test_fill_levels_and_respect_wick_vs_body` | 13, 14 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-IMB-03 | S14.2 | VI (OHLC-проксі), Liquidity Void, Opening Gap (24/7 крипто майже немає), BPR | `office2.smc.imbalance.volume_imbalances` | `scripts/test_smc_imbalance.py::test_vi_void_gap_bpr` | — | ЧАСТКОВО | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-PD-01 | S13 | Dealing range, EQ, Premium/Discount; застарілі якорі — stale | `office2.smc.pd.dealing_range` | `scripts/test_smc_sessions_pd_flow.py::test_pd_ote_and_stale_anchor` | 7, 12 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково (premium/discount EVIDENCE) |
| R-PD-02 | S13.1 | OTE 0,5/0,62/0,705/0,79 від ноги; OTE без POI/тригера — не вхід | `office2.smc.pd.ote` | `scripts/test_smc_golden.py::g_ote_with_ob` | 12 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | є (OTE 62–79%) |
| R-OF-01 | S16 | Order Flow як структурний proxy (UP/DOWN + FVG не зламано); біржових агресорів не імітуємо | `office2.smc.flow.order_flow` | `scripts/test_smc_sessions_pd_flow.py::test_order_flow_and_hrlr_lrlr_proxy` | 16, 17 | ЧАСТКОВО | SHADOW: показ у картці/логу, READY не змінює | є (CVD/taker-delta EVIDENCE — реальні дані) |
| R-OF-02 | S17 | HRLR/LRLR за ефективністю ходу й розворотами (proxy) | `office2.smc.flow.path_resistance` | `scripts/test_smc_sessions_pd_flow.py::test_order_flow_and_hrlr_lrlr_proxy` | 18 | ЧАСТКОВО | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-BLK-01 | S18 | OB: остання протилежна свічка перед імпульсним поглинанням (закриття ТІЛОМ за high/low свічки); без поглинання — не OB | `office2.smc.blocks.order_blocks_bull` | `scripts/test_smc_blocks.py::test_bull_ob_requires_engulfing_and_mt_lifecycle` | 19, 20 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково (OB у зоні входу) |
| R-BLK-02 | S18.1 | Структура OB: wick / open / MT=50% тіла; режим wick (тіло<40%) або body; живий поки тіло не закріпилось за MT; тести лічаться | `office2.smc.blocks.order_blocks_bull` | `scripts/test_smc_blocks.py::test_ob_wick_mode_for_small_body_long_wicks` | 21, 22, 23 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-BLK-03 | S18.1 | Фрактальність OB: блок HTF = серія M15 | `office2.smc.blocks.ob_fractal` | `scripts/test_smc_blocks.py::test_ob_fractality_htf_candle_is_series_on_m15` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-BLK-04 | S18.2 | Агресивний (від POI) і консервативний (після підтвердження) вхід; READY лише консервативний | `office2.smc.models.evaluate` | `scripts/test_smc_models.py::test_aggressive_entry_is_shown_but_never_ready` | 22, 23 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | є (консервативний) |
| R-BLK-05 | S19 | Breaker: OB пробито імпульсом після зняття ліквідності + MSS; ретест | `office2.smc.blocks.breakers_bull` | `scripts/test_smc_blocks.py::test_breaker_vs_mitigation_profiles` | 24 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-BLK-06 | S20 | Mitigation: два профілі MB_TEXT і MB_SCHEME (D-03), без «тихого злиття» з BB | `office2.smc.blocks.breakers_bull` | `scripts/test_smc_blocks.py::test_breaker_vs_mitigation_profiles` | 25, 26, 27 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-BLK-07 | S21 | Rejection Block: довга тінь (≥50% діапазону, ≥0,5 ATR) через SSL/BSL з реакцією; MT тіні | `office2.smc.blocks.rejection_blocks_bull` | `scripts/test_smc_blocks.py::test_rejection_block_bull_wick_on_ssl` | 28, 29, 30, 31 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-BLK-08 | S24 | StB/BtS: зняття SSL/BSL → MSS; зона = [екстремум raid, зламаний рівень MSS]; POI всередині | `office2.smc.blocks.stb_bull` | `scripts/test_smc_blocks.py::test_stb_zone_between_sweep_extreme_and_mss_level` | 34, 35, 36, 37 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-BLK-09 | S25 | Sponsored Candle: два варіанти закриття тілом (D-04), неверифіковано | `office2.smc.blocks.sponsored_bull` | `scripts/test_smc_blocks.py::test_sponsored_two_variants_unverified` | 38 | ЧАСТКОВО | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-MDL-01 | S26 | Reversal (LONG/SHORT): контекст HTF → RAID → MS → POI → ретрейс → тригер → SL/цілі; хронологія обов'язкова; без HTF-контексту проти старшої структури — не береться | `office2.smc.models.evaluate` | `scripts/test_smc_models.py::test_reversal_long_full_sequence_ready` | 39, 40 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | частково (sweep→зсув→ретрейс→тригер) |
| R-MDL-02 | S26 | Continuation: bias HTF + RAID + MS1 + MS2 («2 MS») + POI + ретрейс + тригер | `office2.smc.models.evaluate` | `scripts/test_smc_models.py::test_continuation_needs_two_ms_and_aligned_bias` | 40 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-MDL-03 | S26 | SHORT = точне дзеркало LONG (симетрія перевірена) | `office2.smc.engine.analyze` | `scripts/test_smc_models.py::test_reversal_short_is_mirror_of_long` | 39, 40 | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | є |
| R-SES-01 | S27 | Killzones/optimal time: source-clock «UTC+3/KZ» зберігається окремо від канонічних NY-вікон з DST; торгового gate немає (D-02) | `office2.smc.sessions.window_view` | `scripts/test_smc_sessions_pd_flow.py::test_source_vs_canonical_windows_are_separate_and_not_a_gate` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | — | є (власні сесії) |
| R-SES-02 | S29 | NYM = північ Нью-Йорка (America/New_York, DST), а не фіксовані 08:00; Київ першим, UTC у дужках | `office2.smc.sessions.nym_utc` | `scripts/test_smc_sessions_pd_flow.py::test_nym_follows_us_dst_not_fixed_0800` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-SES-03 | S29 | Judas Swing відносно NYM: FORMING → JUDAS → CONFIRMED, лише закриті бари | `office2.smc.sessions.judas` | `scripts/test_smc_sessions_pd_flow.py::test_judas_bear_forming_judas_confirmed` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-SES-04 | S28 | PO3/AMD: діапазон Азії (проксі) → маніпуляція → розподіл | `office2.smc.sessions.amd` | `scripts/test_smc_sessions_pd_flow.py::test_amd_manipulation_then_distribution` | — | ЧАСТКОВО | SHADOW: показ у картці/логу, READY не змінює | немає |
| R-RSK-01 | S05 | Ризик 0,5–1%/угоду, стоп після 2 SL, тижневий ліміт — portfolio_gate Brain; SMC SL/цілі рахуються тими ж brain.targets_for і порогами (MIN_STOP_ATR15, MIN_TP1_R) | `office2.smc.engine._finalize` | `scripts/test_smc_models.py::test_reversal_long_full_sequence_ready` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | Brain v2.1 без змін | є |
| R-INT-01 | інтеграція | SMC shadow у фоні не затримує Brain/Telegram, помилка SMC не ламає READY, рішення Brain побітово ті самі з SMC і без | `office2.smc.shadow.run_cycle` | `scripts/test_smc_integration.py::test_smc_does_not_change_brain_decision` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | — |
| R-INT-02 | інтеграція | Знімок READY зберігає display-поле smc (overlay на свічках, кроки ✓/✗, збіг з Brain); Mini App малює шар SMC | `office2.smc.overlay.build` | `scripts/test_smc_integration.py::test_smc_does_not_change_brain_decision` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | SHADOW: показ у картці/логу, READY не змінює | — |
| R-INT-03 | інтеграція | Time-frozen replay Brain vs SMC на однакових барах; R, хибні READY, recall пропущених рухів | `office2.smc.replay.replay_arrays` | `scripts/test_smc_replay.py::test_replay_finds_smc_ready_exactly_when_sequence_completes_and_not_before` | — | СИНТЕТИКА (реальні OHLCV — replay у worker, ще не виконано) | — | є (replay_at — одне рішення) |
| R-SRC-01 | PDF Strong Candle Tester | PDF = опис індикатора TradingView (Volume Delta, Supertrend, Fibonacci-сітка); формул «сильної свічки» не розкрито — вигадувати не можна; Strong Candle лишається EVIDENCE | `office2.strongcandle.detect` | `scripts/test_smc_golden.py::test_sources_cover_all_toc_sections_and_discrepancies` | — | НЕ АЛГОРИТМІЗОВАНО | Brain v2.1 без змін | є (sc-ours-1, EVIDENCE) |
| R-SRC-02 | S01–S04, S30, S31 | Освітній/мотиваційний контекст, реклама, посилання на відео — не алгоритмізується; відео/статті за посиланнями недоступні й не вважаються прочитаними | `office2.smc.sources.SECTIONS` | `scripts/test_smc_golden.py::test_sources_cover_all_toc_sections_and_discrepancies` | 1 | НЕ АЛГОРИТМІЗОВАНО | — | — |

## Схеми (40 із «41»)

| № | Схема | Розділ | Фікстура | Примітка |
|---|---|---|---|---|
| 1 | Теханализ и Smart-Money | S04 | — | ілюстрація: класичний ТА як наживка; не алгоритмізується |
| 2 | Фазы рынка | S06 | — | падіння → накопичення → ріст → розподіл → падіння; гіпотеза Wyckoff, не детектор READY |
| 3 | Рыночный цикл | S06 | — | реальний графік із фазами; якісний приклад |
| 4 | Swing | S10.1 | swing_3candle | 3 позитивні + 1 негативний приклад для Swing High/Low |
| 5 | Восходящая структура | S10.2 | uptrend_structure |  |
| 6 | Нисходящая структура | S10.3 | downtrend_structure |  |
| 7 | Консолидация — Range (0 / 0,5 / 1, девиация) | S10.4 | range_deviation |  |
| 8 | BMS | S09.3 | bms_chain |  |
| 9 | MSS + Confirm | S12 | mss_confirm |  |
| 10 | MSS: валідний vs «нет обновления максимума» | S12 | mss_valid_vs_invalid |  |
| 11 | Не MSS (корекція в межах розширення) | S12 | not_mss_correction |  |
| 12 | OTE вместе с Ордер Блоком | S13.1 | ote_with_ob |  |
| 13 | Применение объёмов с FVG | S14 | fvg_basic | профіль обсягів на схемі — OHLC-only FVG не доводить дисбаланс біржового bid/ask |
| 14 | Имбаланс: эффективное vs неэффективное ценообразование | S14 | fvg_basic |  |
| 15 | Типы ликвидности (EQH/EQL, Swing, Range, Trendline) | S15 | liquidity_types |  |
| 16 | ORDER FLOW (висхідний/низхідний + FVG) | S16 | order_flow |  |
| 17 | Медвежий Order Flow после смены тренда (POI старшого ТФ: OB+FVG) | S16 | order_flow |  |
| 18 | HRLR и LRLR | S17 | hrlr_lrlr |  |
| 19 | Бычий ордер блок (FVG, біля ключового рівня) | S18 | bull_ob |  |
| 20 | Медвежий ордер блок | S18 | bear_ob |  |
| 21 | Структура блока. Mean Threshold | S18.1 | ob_levels |  |
| 22 | Пример использования Ордер Блока (BSL, 2 OB) | S18.2 | ob_usage |  |
| 23 | Приклад угоди: захват ліквідності → OB → вхід/SL/TP | S18.2 | ob_usage |  |
| 24 | Breaker Block (висхідна й низхідна структура) | S19 | breaker_block |  |
| 25 | Mitigation Block | S20 | mitigation_block |  |
| 26 | Отличие MB от BB (обновили / не обновили максимум) | S20 | mb_vs_bb |  |
| 27 | MB в сочетании с BB | S20 | mb_vs_bb |  |
| 28 | Пример Rejection Block (BSL, FVG, MSS, BMS) | S21 | rejection_block |  |
| 29 | Скріншот TradingView: RJB+ (long, R:R 9,65) | S21 | — | реальний приклад ціни; без OHLC в документі |
| 30 | Rejection Block / Wick (бичачий, EQL, SSL, 0,5) | S21 | rejection_block |  |
| 31 | Rejection Block / Wick (ведмежий, EQH, BSL, 0,5) | S21 | rejection_block |  |
| 32 | Захват ликвидности (Stop Hunt / Raid), рух проти тренду | S22 | raid_sweep |  |
| 33 | SFP (Swing Failure Pattern), long і short | S23 | sfp |  |
| 34 | Зоны StB и BtS | S24 | stb_bts |  |
| 35 | Пример Sell to Buy (Breaker + SSL) | S24 | stb_bts |  |
| 36 | Пример Sell to Buy (2 OB, MSS, 0,5) | S24 | stb_bts |  |
| 37 | Пример Buy to Sell (BSL, MSS, OB) | S24 | stb_bts |  |
| 38 | Спонсированная цена / Institutional Sponsorship (FVG, SSL, OB, RJB) | S25 | sponsored_candle |  |
| 39 | REVERSAL TYPE 1 (контекст HTF POI/RAID BSL; без контексту — не шукати вхід) | S26 | reversal_type1 |  |
| 40 | Reversal vs Continuation (4 схеми: напрям, RAID, MS, вхід) | S26 | rev_vs_cont |  |

## Розбіжності джерела (зафіксовано, не вирішено мовчки)

- **D-01** (S09.3 / схеми 08–11): Текст: «BOS = BMS = CHoCH = MSB — одне й те саме», MSB — зміна напрямку, MS/Confirm — оновлення в напрямку тренду. Схеми 08–09 позначають BMS кожен злам максимуму В напрямку тренду, MSS — перший злам захищеного мінімуму проти тренду, Confirm — наступний злам у новому напрямку. → Реалізовано за схемами: BMS (в напрямку тренду) → MSS (проти, захищений swing) → CONFIRM (оновлення в новому напрямку). Синонім MSB = MSS.
- **D-02** (S27 killzones): Вікна London 03–07, Asia 09–12, NY 14–17, «optimal» 10:00–11:30 / 15:00–17:00 подані як «UTC+3 / KZ». Це не вже сконвертований час Борисполя; не зрозуміло, чи UTC+3 — абсолютне зміщення, чи місцевий час іншого ринку. → Зберігаємо source-clock як є, показуємо обидві інтерпретації (фіксоване UTC+3 і канонічні NY-вікна) з DST; торгового gate на ці вікна немає, поки автор не уточнить.
- **D-03** (S20 / схеми 25–27): Текст: Mitigation Block — той самий Breaker, але БЕЗ MSS і без зняття ліквідності (продовжує BMS). Схеми 25–27 підписують MSS на MB; відмінність схем 26: BB — «обновили максимум», MB — «нет обновления максимума». → Два профілі: MB_TEXT і MB_SCHEME; жодного «тихого злиття» MB і BB.
- **D-04** (S25 Sponsored Candle): «Знімає екстремум і закріплюється тілом» — не вказано, з якого боку рівня закривається тіло. → Два варіанти: SC_RECLAIM (закриття назад за рівнем) і SC_ACCEPT (закриття за рівнем); у READY не використовуються до ручної верифікації.
- **D-05** (S09.2 vs існуючий Brain v2.1): Методичка: swing = 3 свічки (центральна вища за обидві сусідні). Brain v2.1 (office2.features.swings, n=2) використовує 5-свічкові фрактали. → SMC-детектори використовують n=1 за методичкою; Brain v2.1 не змінюється (різниця фіксується в shadow-порівнянні).
- **D-06** (S10.4 / схема 07): Range позначається сіткою 0; 0,5; 1 (EQ = 0,5), OTE-сітка — 0; 0,5; 0,62; 0,705; 0,79; 1. Для FVG/OB — 0,25/0,5/0,75. → Усі набори рівнів реалізовано окремо за призначенням.
- **D-07** (Запит vs документ): Запит: «41 схема». У Masterplan і docx — 40 зображень (Схема 01…40). → Доступні й прочитані 40; 41-ї немає — зафіксовано, не вважається прочитаною.
- **D-08** (Strong Candle PDF): PDF описує індикатор/стратегію TradingView (Volume Delta, Supertrend, Fibonacci-сітка); внутрішні алгоритми «сильної свічки» автор не розкриває. → Strong Candle лишається EVIDENCE (office2.strongcandle), не READY-ґейтом; формул із PDF не вигадуємо.

## Розділи джерела

| ID | Заголовок | Клас | Примітка |
|---|---|---|---|
| S01 | Знакомство с концептом Смарт Мани | CONTEXT |  |
| S02 | Глоссарий терминов | CONTEXT |  |
| S03 | Что такое Smart Money? | CONTEXT | твердження про «крупний капітал» — гіпотеза, не спостережувані дані |
| S04 | Разница между Тех Анализом и Смарт Мани | CONTEXT |  |
| S05 | Риск-менеджмент и дисциплина | ALGO | 0,5–1% на угоду, стоп після 2 SL, 3%/тиждень — вже є в office2.risk/engine.portfolio_gate; не змінюється |
| S06 | Рыночный цикл и тренды, фазы рынка | ALGO | Wyckoff-фази — лише гіпотеза; спостережувані стани RANGE/UP/DOWN |
| S07 | Стиль торговли и таймфреймы | ALGO | для Office: день → 4H → 15m |
| S08 | Анализ Таймфреймов: LTP / ITP / STP | ALGO |  |
| S09.1 | Трендовые движения | ALGO |  |
| S09.2 | Свинги (Swing High / Swing Low) | ALGO |  |
| S09.3 | BOS/MSB и Confirm | ALGO |  |
| S09.4 | Синхронизация структуры | ALGO |  |
| S10.1 | Структурные точки Swing | ALGO |  |
| S10.2 | Восходящая структура | ALGO |  |
| S10.3 | Нисходящая структура рынка | ALGO |  |
| S10.4 | Боковое движение цены (Range, Deviation) | ALGO |  |
| S11 | Range и Expansion: консолидация → расширение | ALGO |  |
| S12 | MSB (Market Structure Break) — слом структуры | ALGO |  |
| S13 | Fibonacci / PD Array: Premium / Discount и Dealing Range | ALGO |  |
| S13.1 | OTE (Optimal Trade Entry) | ALGO |  |
| S14 | Имбаланс — FVG | ALGO |  |
| S14.1 | Уважение FVG / VI / Gap; ключевые уровни 25/50/75/FF; тела vs тени | ALGO |  |
| S14.2 | Виды неэффективности: FVG, VI, Liquidity Void, Opening Gap, BPR | ALGO |  |
| S15 | Ликвидность: external/internal, пулы (PDH/PDL/PWH/PWL/PMH/PML, session H/L), EQH/EQL, трендовая | ALGO |  |
| S16 | Поток приказов — Order Flow | ALGO | структурний proxy; біржових агресорів/дельти методичка не дає |
| S17 | HRLR / LRLR | ALGO | структурний proxy |
| S18 | Ордер блоки (Order Block): умови, поглощение, по фитилям/по телу | ALGO |  |
| S18.1 | Структура OB: Wick / Open / Mean Threshold; тесты; фрактальность | ALGO |  |
| S18.2 | Агрессивный / консервативный вход от OB | ALGO |  |
| S19 | Брейкер Блок (Breaker Block) | ALGO |  |
| S20 | Митигейшн блок (Mitigation Block) | ALGO | текст і схеми розходяться — два профілі (D-03) |
| S21 | Rejection Block / Wick | ALGO |  |
| S22 | Захват ликвидности (Raid / Sweep / Stop Hunt) | ALGO |  |
| S23 | Ложный пробой — SFP | ALGO |  |
| S24 | STB (sell to buy) / BTS (buy to sell) | ALGO |  |
| S25 | Спонсированная свеча (Sponsored Candle) | ALGO | сторона закриття не уточнена — два варіанти (D-04) |
| S26 | Reversal vs Continuation: два типа сделок | ALGO |  |
| S27 | Торговые сессии, killzones, optimal trader time | ALGO | годинник джерела «UTC+3/KZ» неоднозначний — без торгового gate (D-02) |
| S28 | PO3 / AMD | ALGO |  |
| S29 | Judas Swing / NYM (True Daily Open) | ALGO |  |
| S30 | Как собрать свою торговую систему (чек-лист); Резюмирую | CONTEXT |  |
| S31 | Видеокурс / Telegram / платное обучение / ссылки | EXTERNAL | відео й статті за посиланнями не прочитані — недоступні |
