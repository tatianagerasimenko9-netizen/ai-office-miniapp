# Risk Officer у робочому циклі Лева (shadow → enforce)

Не дозвіл на deploy. Ордерів модуль не створює й не авторизує (`order_authorized=False`).

## Поточний стан
- Обидва виклики `lev_cycle()` у relay проходять через `office_risk_context.apply_risk_officer()`.
- За замовчуванням **shadow**: рішення Лева не змінюється; для кожного потенційного SEND
  у `office_events` пишеться `RISK_SHADOW_REVIEW` (would_veto + причини). Mini App →
  «Ризик» → «Тіньові перевірки».
- `OFFICE_RISK_OFFICER_ENFORCE=1` — **enforce**: veto переводить SEND у WAIT (той самий
  `finalize_lev(risk_context=…)`), запис `RISK_VETO`. Помилка ризик-контролю в enforce = WAIT.
  Veto ніколи не підвищує WAIT/SKIP до SEND.

## Джерела контексту (невідоме лишається невідомим)
| Поле | Джерело | Обмеження |
|---|---|---|
| equity | `OFFICE_DEPO_USDT` | налаштування, не баланс біржі (`equity_source=config`) |
| ризик угоди | 1% депо (`office_position_size`) | пороги не змінювались |
| існуючий ризик | OPEN `/position` з entry/SL/qty у `trade_journal` | позиція без qty → ризик невідомий → veto |
| дані | свіжість останньої LTF-свічки (`office_feed_quality`, ≤900 с) | |
| контекст | `market_context.data_status` | BTC-контекст без даних → UNAVAILABLE |
| виконання | — | стакану/спреду немає → завжди `EXECUTION_NOT_VERIFIED` |

## Наслідок для enforce
Поки немає перевіреного джерела виконання (спред/глибина), enforce заблокує **кожен** SEND.
Вмикати enforce — рішення власниці після підключення execution-даних і аналізу shadow-журналу.
