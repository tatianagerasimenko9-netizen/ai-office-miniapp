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
