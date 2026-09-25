# AI Office — MASTER

**Статус:** аудит і ТЗ зафіксовані. Робочий код **не змінювався**. Чекаємо `МОЖНА ВНОСИТИ ЗМІНИ`.  
**Дата:** 2026-09-25. Деталі: `AI_OFFICE_AUDIT/`.

---

## Коротко українською

**1. Що вже є і працює (ПІДТВЕРДЖЕНО)**  
Telegram-офіс з травня 2026: Лев/команда, NO TRADE замість вигаданих входів, зони в таблиці `office_signals`, REST Binance (свічки, OI, funding, стакан), kill zone / circuit, вечірній debrief (~128 у чаті), Mini App-зародок журналу, форвард карток My Crypto Scanner у MAIN.

**2. Що зламано або не зв’язано (ПІДТВЕРДЖЕНО)**  
Офіс — коментатор на запит (`BTC?` → аналіз), не радар подій. Сканер `file-1` — окремий процес: офісний NO TRADE **не блокує** його картки (немає доказу конкретної угоди «всупереч», є доказ **відсутності протоколу**). Sweep BTC ~07:35 23.09 не пішов алертом. Немає `/review` vs `/position`. Назар 22× «фон чистий». GEX/heatmap/кити on-chain немає.

**3. Що змінити / прибрати**  
Змінити: один MarketState OFFICE↔BOT, радар 👀→🚨→🟢, класифікація MENTION≠SIGNAL, intent команд, fail-closed новини, debrief→RESULT.  
Прибрати як KPI: «більше сигналів», «зменшити Лева». Прибрати хор LLM на SKIP, WATCHING після SKIP, шаблон «фон чистий» при помилці API. Не видаляти debrief і NO TRADE-дисципліну.

**4. Як виглядатиме 2.0 і апка**  
Цикл: дані → контекст → подія → watch → setup → confirm → risk → сигнал → менеджмент → результат → статистика.  
Чат: короткі події з цифрами. Апка: Home / Scanner / Signals / My Positions / Statistics / Notifications (як GGShot за UX, не копія auto-trade). ENTER на біржу — етап 6, окремий дозвіл.

**5. Скільки етапів до MVP і що першим**  
Етапи 0–5: аудит (цей пакет) → P0 стан/intent/новини → радар → перевірка фільтрів на даних → журнал → Mini App MVP.  
Етап 6 — paper / автоордери лише після окремого дозволу.  
**Першим після дозволу:** **T0** — `ZONE_REACHED` навіть якщо ATR/NO TRADE (IRYS 13.05). Далі T4 `market_state` → T1 `/review`≠`/position` → T3 дедуп → T5 BLOCK сканера. Не починати з T2 лише бо простіше. Деталі: `AI_OFFICE_AUDIT/26_TZ_CONSISTENCY.md`.

---

## Пакет документів (імена з ТЗ)

| Файл | Зміст |
|------|--------|
| `AI_OFFICE_MASTER.md` | цей файл |
| `AI_OFFICE_AUDIT/CURRENT_SYSTEM.md` | що існує |
| `AI_OFFICE_AUDIT/AUDIT_EVIDENCE.md` | знахідки + джерела |
| `AI_OFFICE_AUDIT/KEEP_CHANGE_REMOVE.md` | таблиця рішень |
| `AI_OFFICE_AUDIT/OFFICE_2_ARCHITECTURE.md` | ціль і протоколи |
| `AI_OFFICE_AUDIT/TRADING_RADAR_SPEC.md` | події та сигнали |
| `AI_OFFICE_AUDIT/MINI_APP_SPEC.md` | екрани, API MVP |
| `AI_OFFICE_AUDIT/IMPLEMENTATION_ROADMAP.md` | етапи 0–6 |
| `AI_OFFICE_AUDIT/CURSOR_TASKS.md` | дрібні задачі |
| `AI_OFFICE_AUDIT/OPEN_QUESTIONS.md` | дірки даних |
| `AI_OFFICE_AUDIT/00…26_*.md` | розтин по темах + фінальна перевірка ТЗ |

Код, промпти агентів, CONFIG, БД — **не чіпати** до дозволу.

Закриття кожної задачі — `AI_OFFICE_AUDIT/CURSOR_TASKS.md` §8 (GitHub → Render). Push не дорівнює LIVE.
