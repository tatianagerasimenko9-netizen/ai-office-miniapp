# OFFICE_2_ARCHITECTURE.md — ціль і протоколи

Не імплементація. Код не змінювати зараз.

## Цикл

```
MARKET DATA → MARKET CONTEXT → EVENT DETECTION → WATCH
  → SETUP (scalp|intraday|swing окремо)
  → CONFIRMATION → RISK → SIGNAL
  → TRADE MANAGEMENT → RESULT → STATISTICS
```

## Єдиний стан символу (протокол OFFICE ↔ BOT)

```
symbol
regime
watch[]: {kind: BSL|SSL|ENTRY, low, high, tf, created_ts}
event: none | APPROACH | ZONE | SWEEP | ...
confirmation: none | WAITING | YES | NO | EXPIRED
signal: none | {side, entry_low, entry_high, sl, tp1, tp2, rr, horizon}
office_decision: NO_TRADE | SIGNAL | WATCH
bot_action: BLOCKED | ACCEPT | IGNORE_SOURCE
trade: none | PAPER | MANUAL | AUTHORIZED   # AUTHORIZED лише після окремого дозволу етапу 6
intent: none | REVIEW | MY_POSITION
data_quality: OK | DEGRADED | UNAVAILABLE
```

Інформаційний SIGNAL ≠ MY_POSITION ≠ PAPER ≠ live order.

## Хто ухвалює (ціль)

| Крок | Двигун | LLM |
|------|--------|-----|
| Дані / подія / watch | детерміновано | ні |
| Setup candidates | правила + статистика | опційно |
| Confirm | правила (мікро BOS/reject) | опційно `/why` |
| Risk / size | Дарина-модуль | ні на кожен тік |
| Текст у чат | оркестратор, 1 повідомлення | коротко |
| Ордер | executor етап 6 | ніколи без стану AUTHORIZED |

## Аварії (обов’язково в ТЗ)

- Ідемпотентність event_id  
- TTL сигналу  
- Дубль ордерів заборонено  
- API fail → DEGRADED, не «фон чистий»  
- OFFICE NO_TRADE → bot_action BLOCKED навіть якщо SOURCE шле картку  
- Секрети не в логах/звітах  

## Гілка відкату

Окремий git branch на кожен етап. `file-1` не чіпати. Feature flag `OFFICE_RADAR=0` повертає старий Q&A.
