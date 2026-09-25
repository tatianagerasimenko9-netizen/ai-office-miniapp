# AI Office — прогрес до готової Mini App

**Оновлено:** 2026-09-25  
**T0:** ЗАКРИТО LIVE / ПЕРЕВІРЕНО (`993c720`).  
**T4:** таблиця `market_state` LIVE на Worker `dfa1369` (upsert/get перевірено).  
**T5:** Worker `f383795` **LIVE**. Прод-проба без ордерів: `T5PROBEUSDT` + `bot_action=BLOCKED` → у БД **немає** kickoff/ENTER/journal (рядок probe видалено). Картку `T5-LIVE-PROBE` надіслано в MAIN (`msg_id=439`). Текст «Сканер BLOCKED офісом» з цієї ВМ не читався (Bot API не віддає outbound бота). Інші символи не блокували — у `market_state` інших рядків не було.

Статуси: `НЕ ПОЧАТО` · `В РОБОТІ` · `ГОТОВО В КОДІ` · `LIVE НА RENDER` · `ПЕРЕВІРЕНО`

Порядок: **T0 ✅ → T4 ✅ → T5 LIVE (проба без ENTER) → T1 → T3 → T2 → T6 → T7**.

| Задача | Зміст | Статус |
|--------|--------|--------|
| T0 | ZONE_REACHED | LIVE / ПЕРЕВІРЕНО |
| T4 | таблиця `market_state` | LIVE (read/write) |
| T5 | MAIN шанує `bot_action` | LIVE НА RENDER (немає ENTER на BLOCKED-probe) |
| T1 | `/review` ≠ `/position` | НЕ ПОЧАТО |
| T3 | дедуп WATCHING після SKIP | НЕ ПОЧАТО |
| T2 | Назар fail-closed | НЕ ПОЧАТО |
| T6 | радар BTC stub | НЕ ПОЧАТО |
| T7 | Mini App Home зі state | НЕ ПОЧАТО |

## 13 пунктів

| # | Статус | Факт |
|---|--------|------|
| 1 рівні | НЕ ПОЧАТО | |
| 2 проактивний моніторинг | LIVE / ПЕРЕВІРЕНО | T0 |
| 3–10 | НЕ ПОЧАТО | T1/T2/T6… |
| 11 єдиний стан | В РОБОТІ | таблиця LIVE; T5 `f383795` + BLOCKED-probe без ENTER; Mini App ще ні |
| 12 Mini App | НЕ ПОЧАТО | T7 |
| 13 GitHub→Render | В РОБОТІ | T0+T4+T5 Worker Live |

До Mini App: T1, T3, T2, T6, T7 і пункти 1,3–10,12. Наступну задачу з цього кроку не стартуємо.
