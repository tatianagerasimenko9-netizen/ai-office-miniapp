# AI Office — прогрес до готової Mini App

**Оновлено:** 2026-09-25  
**T0:** ЗАКРИТО LIVE / ПЕРЕВІРЕНО (`993c720`).  
**T4:** таблиця `market_state` LIVE на Worker `dfa1369` (upsert/get перевірено).  
**T5:** Worker `f383795` **LIVE на Render** (деплой PASS). `bot_action=BLOCKED` у коді зупиняє kickoff/ENTER; SOURCE-форвард не глушиться. **Блокування на production ще не перевірено** (Cursor без `DATABASE_URL`; INSERT-probe не запускався).

Статуси: `НЕ ПОЧАТО` · `В РОБОТІ` · `ГОТОВО В КОДІ` · `LIVE НА RENDER` · `ПЕРЕВІРЕНО`

Порядок: **T0 ✅ → T4 ✅ → T5 (блок. ще не ПЕРЕВІРЕНО) → T1 → T3 → T2 → T6 → T7**.

| Задача | Зміст | Статус |
|--------|--------|--------|
| T0 | ZONE_REACHED | LIVE / ПЕРЕВІРЕНО |
| T4 | таблиця `market_state` | LIVE (read/write) |
| T5 | MAIN шанує `bot_action` | LIVE НА RENDER (блок. не перевірено) |
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
| 11 єдиний стан | В РОБОТІ | таблиця LIVE; T5 задеплоєно `f383795`; BLOCKED-шлях на прод не гоняли; Mini App ще ні |
| 12 Mini App | НЕ ПОЧАТО | T7 |
| 13 GitHub→Render | В РОБОТІ | T0+T4 LIVE; T5 Worker Live, поведінка BLOCKED не підтверджена |

До Mini App: підтвердити T5 BLOCKED на прод (після дозволу на INSERT probe), далі T1, T3, T2, T6, T7 і пункти 1,3–10,12.
