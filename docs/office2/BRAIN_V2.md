# Office2 Brain v2 (`o2-brain-2.0`) — інтегрований конвеєр і gap-аудит

LIVE BETA, UNPROVEN. Office нічого не торгує сам. Версія Brain заморожена: `version_id` є в кожному сценарії (`office2_live_scenario.version`, `office2_live_signal.version`, snapshot `version_id`). Відкат: `OFFICE2_BRAIN=1` (brain v1).

## Конвеєр рішення (`office2/brain2.py` + `office2/evidence.py`)
HTF → BTC/ETH/ринок → сильні рівні/mirror/люфт → PDH/PDL/PWH/PWL/PMH/PML/сесії → sweep-подія або захист origin-зони → MSS/BOS з displacement → нога → зона входу (OTE 62–79% ∪ OB/FVG) → контрольований ретрейс у зону → M15-тригер → структурна інвалідація → люфт (медіана проколів саме цього рівня) → SL → перевірка шуму ATR(M15) (стоп не розширюється) → цілі від реальних рівнів → простір ≥ 1R → розмір за фіксованими $ → портфельна ємність → READY / WAIT / NO_TRADE / MISSED / INVALIDATED.

`sweep → reclaim → 1 бар` більше НЕ дає READY: sweep — лише подія, READY потребує повної послідовності (тест `test_no_ready_from_sweep_reclaim_hold_only`).

## Gap-аудит
| Модуль | Роль | Впливає на decide() | Лише показується/збирається | Немає |
|---|---|---|---|---|
| Рівні (PDH/PDL/PWH/PWL/PMH/PML/сесії/H1-4H-D1 swing), BSL/SSL/EQH/EQL | GATE | подія, SL-інвалідація, цілі, перешкоди | — | — |
| MSS/BOS + displacement | GATE | так | — | — |
| Entry zone OTE/OB/FVG, ретрейс, тригер M15 | GATE | так | — | — |
| Люфт (медіана проколів рівня) | GATE | SL | — | — |
| ATR(M15) шум, простір до цілі, fixed-$ розмір | GATE | так | — | — |
| HTF MN/W1/D1/H4/H1, premium/discount | CONTEXT | ні (факт у тезі) | так | — |
| Gerchik mirror (role-flip) | EVIDENCE | ні | ЗА/ПРОТИ | — |
| Wyckoff, Bulkowski, CVD/taker-delta, M5 | EVIDENCE | ні (немає доведеного edge) | ЗА/ПРОТИ | M1 тригер |
| Regression channel | CONTEXT | ні | так | — |
| OI/funding/L:S/ліквідації | RESEARCH | ні (FLOW-1 FAIL OOS) | збирається для READY | — |
| DOM, GEX/options, макро-календар | NOT_CONNECTED | ні | ні | немає джерела/не підключено |

Evidence-модулі не голосують: вони не блокують і не відкривають READY, а потрапляють у знімок (`evidence`, `evidence_counts`) і в Mini App (картки «Послідовність до READY», «Що перевірено»). Кожна ПРОТИ-кількість зберігається для пакетного аналізу.

## Матриця provenance (що існує, що впливає на READY)
| Модуль | Файл | Працює | Роль | Впливає на READY | У trace | Тест |
|---|---|---|---|---|---|---|
| HTF MN/W1/D1/H4/H1 | office2/brain.htf_context | так | CONTEXT | ні | так | live/brain2 |
| Level Engine (PDH/PDL/PWH/PWL/PMH/PML, swing H1/H4/D1/W1, сесії, EQH/EQL, BSL/SSL) | office2/brain.all_levels | так | GATE | подія, інвалідація, цілі | так | live/brain2 |
| Gerchik: люфт рівня (медіана проколів) | brain2.level_luft | так | GATE | SL | так | brain2 |
| Gerchik: mirror (role-flip) | evidence.mirror_level | так (наша реалізація, не авторські правила) | EVIDENCE | ні | так | brain2 |
| Sweep, MSS/BOS, displacement, OTE, OB/FVG зона | brain2 | так | GATE | так | так | brain2 |
| Strong Candle | office2/strongcandle.py | так, **OUR_IMPLEMENTATION** (Pine ict_smc_hunter_v9_9: vol>2×SMA20, range>1.2×ATR14); формулу документа Tester не розкрито | EVIDENCE | ні (edge не доведено) | так, з параметрами/версією | strongcandle |
| Fibonacci OTE/розширення від Strong Candle | strongcandle.fib | так | EVIDENCE | ні | так | strongcandle |
| Volume / taker-delta / CVD | evidence | так (Binance tbv) | EVIDENCE | ні | так | brain2 |
| Wyckoff (spring/upthrust/фаза), Bulkowski, regression channel | office_wyckoff / office_bulkowski / office_regression_channel | так, H1 | EVIDENCE/CONTEXT | ні | так | існуючі |
| RSI/divergence | office_* (старий Лев) | не підключено до Office2 | — | ні | ні | — |
| OI/funding/L:S/ліквідації | office_market_data | так, лише для кандидата | RESEARCH | ні (FLOW-1 FAIL) | так | brain2 |
| DOM, GEX/options | — | немає джерела | NOT_CONNECTED | ні | позначено | brain2 |
| Макро-календар | office_calendar (старий Лев) | не підключено до Office2 | NOT_CONNECTED | ні | позначено | — |
| Portfolio Risk | engine.portfolio_gate | так | GATE | так | так | live |
