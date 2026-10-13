# Рушій гіпотез (SHADOW) — `office2/hypothesis.py`

**Роль:** бачити знайому структуру → висунути пояснювану гіпотезу → перевірити на ТФ/контексті → сценарії А/Б/В → спостерігати → оцінити, чи справдилась.
**Не робить:** не створює READY, угоди, lifecycle, Telegram; не змінює ризик і LIVE-гейти. Гіпотеза ≠ READY.

## Що формується
| Родина | Джерело ідеї | Дані |
|---|---|---|
| FALSE_BREAK_RECLAIM | Герчик D-FALSE-BREAK, SMC liquidity raid | закриті M15 (прокол рівня + повернення), глибина vs D1 ATR |
| BREAKOUT_RETEST | Герчик G-BREAKOUT / G-LVL-MIRROR | закриті M15 (пробій опору, ретест) |
| POST_IMPULSE_BASE | Герчик D-POST-IMPULSE-BASE | закриті D1 (паранормальний рух, база в третині, відкат <50%) |
| SMC_REVERSAL / SMC_CONTINUATION | SMC-моделі (`office2.smc`) | кроки моделі, що саме бракує (`need`) — будується у фоновому SMC-циклі |

Не формуються (немає джерела/визначення): Еліотт, Wyckoff-фази, Bulkowski-фігури — див. `METHOD_CARDS_STATUS.md`.

## Поля гіпотези
`what_seen`, `why_this_model`, `supports`, `contradicts` (включно з конфліктами D1/H4), `missing`, `next_checks`, `level`, `invalidation`, `tf` (D1/H4/H1/M15: структура і ставлення до напрямку), `context` (BTC/сесія/новини; **що недоступне — явно**), `scenarios` A/B/C (умови, наступна дія, момент переоцінки), `plan` (лише якщо існує реальний READY того ж напрямку; інакше `None`).

## Спостереження (`office2_hypothesis`)
Дедуплікація за `id = символ|родина|напрям|рівень`; стани ACTIVE → CONFIRMED / REFUTED / EXPIRED (термінальні не оживають). Події: RETEST_HELD, TOUCH_LOST, REFUTED, CONFIRMED, EXPIRED, зміна стадії. `GET /api/v2/hypotheses?state=ACTIVE|CONFIRMED|REFUTED|EXPIRED`.

## Наші конвенції (ГІПОТЕЗА, не джерело)
TTL 24 год (база D1 — 20 діб, за джерелом старша база втрачає актуальність); «справдилась» = 1R у напрямку до закриття за інвалідацією; R = відстань ref→інвалідація (не ризик угоди; підлога — середній діапазон M15).

## Перевірка
`scripts/test_hypothesis.py` (9 тестів, включно з no-lookahead, життєвим циклом, replay-core); replay `scripts/replay_hypotheses.py` на Binance Futures (workflow `replay-hypotheses.yml`) з контролем «протилежний напрямок» і розділом DISCOVERY/HOLDOUT; параметри не підбираються на цих вікнах.
