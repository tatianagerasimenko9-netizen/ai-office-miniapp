# Runbook AI Office (`ai-office-miniapp`)

**Призначення:** швидке відновлення, перевірка env і дій при «тиші» в чатах.  
**Оновлено:** 2026-05-06 (fingerprint БД, E2E чеклист)  

---

## 1. Що запускається де

| Сервіс Render | Команда старту | Роль |
|---------------|----------------|------|
| **Mini App** (Web) | `python -u office_mini_app.py` (або як у Dashboard Render) | Читання журналу / KPI через браузер |
| **Office runtime / relay** | `python -u office_multibot_bootstrap.py` | Telegram relay, `!ask`, міст до `office_bridge` |

Обидва сервіси мають бачити **однакову БД** (див. §3).

---

## 2. Еталон змінних оточення (runtime + Mini App)

Значення не комітити; назви змінних — орієнтир для Render.

### Обов’язкові / типові для relay

| Змінна | Значення |
|--------|----------|
| `TG_API_ID` | Застосунок Telegram API |
| `TG_API_HASH` | Хеш API |
| `TG_BOT_TOKEN` | Токен головного бота (офіс / fallback) |
| `MAIN_CHAT_ID` | Чат джерела сигналів (MAIN) |
| `OFFICE_CHAT_ID` | Чат офісу |
| `DATABASE_URL` **або** `OFFICE_DB_PATH` | Спільна БД: Postgres URL або шлях до SQLite |

### Форумні гілки (3 канали в одному чаті)

| Змінна | Призначення |
|--------|-------------|
| `OFFICE_GENERAL_THREAD_ID` | Загальний desk |
| `OFFICE_TASKS_THREAD_ID` | Задачник |
| `OFFICE_TECH_THREAD_ID` | Техніка / Артем |

Якщо `0` або не задано — логіка може слати в корінь теми (залежить від версії relay).

### Мультибот (агенти)

Для кожного ключа з `OFFICE_RULES_UA.md` §9:

`AGENT_BOT_TOKEN_<КЛЮЧ_У_ВЕРХНЬОМУ_РЕГІСТРІ>` — наприклад `AGENT_BOT_TOKEN_LEV`.

### Інше

| Змінна | Призначення |
|--------|-------------|
| `NEWS_API_KEY` | Новини (якщо увімкнено парсер новин) |
| `OFFICE_RELAY_CONFIG` | Шлях до JSON конфігу relay (за замовчуванням у проєкті) |
| `RELAY_SEND_AGENT_CARDS` | `1` — надіслати картки агентів при старті |
| `RELAY_TECH_HEALTH_ON_START` | `0` — не надсилати стартовий health Артема в гілку «Техніка» (за замовчуванням надсилається, якщо задано `OFFICE_TECH_THREAD_ID`) |
| `OFFICE_BRIEFING_DISABLE` | `1` — вимкнути авто-брифінги (п.28) |
| `OFFICE_BRIEFING_TZ` | Часова зона, напр. `Europe/Kyiv` (якщо `zoneinfo` не знає ім’я — fallback UTC) |
| `OFFICE_BRIEFING_MORNING` | Час ранкового брифінгу `HH:MM` (за замовчуванням `08:00`) |
| `OFFICE_BRIEFING_EVENING` | Час вечірнього debrief `HH:MM` (за замовчуванням `21:00`) |
| `SOURCE_CHAT_ID` | Джерело повідомлень (якщо відрізняється від MAIN) |
| `RELAY_FORCE_SETUP` / `RELAY_INTERACTIVE` | Майстер першого налаштування |

### Mini App

| Змінна | Значення |
|--------|----------|
| `DATABASE_URL` або `OFFICE_DB_PATH` | **Той самий**, що й у runtime |
| `OFFICE_MINI_HOST` / `OFFICE_MINI_PORT` | Bind для веб-сервісу |

---

## 3. Спільна БД (критично)

- **Один і той самий** `DATABASE_URL` (або один і той самий файл SQLite на спільному диску) на **обох** сервісах Render.
- Якщо Mini App порожній, а runtime працює — найчастіше **різні** змінні БД або Mini App дивиться на локальний шлях без persistent disk.

**Перевірка в Dashboard:** однакові значення `DATABASE_URL` / `OFFICE_DB_PATH` на **Web (Mini App)** і **Worker (relay)**.

**Звірка fingerprint (MASTER п.17):** після деплою коду з `office_db_identity`:

1. У **логах** runtime: рядок `[relay] DB identity: … fingerprint=XXXXXXXX` (16 hex).
2. У **Mini App** (верх сторінки): рядок `fingerprint …` або `GET /api/summary` → поле `db_identity.fingerprint`.
3. У **гілці «Техніка»** (якщо увімкнено стартовий health): той самий fingerprint у повідомленні Артема.

Якщо рядки **не збігаються** — сервіси дивляться на різні БД; Mini App показуватиме «чужі» або порожні дані.

---

## 4. Якщо «тиша» в офісі

1. Логи Render → немає crash після старту `office_multibot_bootstrap.py`.
2. `MAIN_CHAT_ID` / фільтр джерела: у логах було `strict source filter (MAIN chat only)` — повідомлення з інших чатів не релейляться.
3. Токени `AGENT_BOT_TOKEN_*`: бот не може писати без токена або якщо бота вилучили з групи.
4. БД: runtime пише події; якщо БД недоступна — шукати traceback у логах.

---

## 5. Freeze (коротко)

Перед зміною критичних env або масовим деплоєм:

1. Зафіксувати поточний коміт `main` і скрін env у Render (без секретів — лише назви).
2. Після деплою — один тестовий сигнал або `!ask` у OFFICE.
3. Перевірити Mini App на тій же БД.

---

## 6. Відновлення з репозиторію

```text
git clone <repo>
cd ai-office-miniapp
pip install -r requirements.txt
```

Локально: створити `.env` (не комітити), задати `OFFICE_DB_PATH` або `DATABASE_URL`, запустити wizard/relay за документацією в коді.

---

## 7. E2E перевірка (MASTER п.20)

Ручний сценарій після успішної звірки п.17:

1. **Fingerprint** у логах relay = у Mini App (див. §3).
2. Надіслати у **MAIN** повідомлення у форматі сигналу (як у проді) або виконати `!ask …` у OFFICE — залежно від того, що тестуєте.
3. Переконатися, що в офісі з’явився ланцюжок / вердикт (Загальна гілка або тред сигналу).
4. Відкрити Mini App: у блоці **«Останні рішення»** або **«Журнал угод»** з’являється запис, узгоджений з подією (може знадобитися кілька секунд і Refresh).
5. За бажанням зберегти скрін логів + Mini App + Telegram для внутрішнього архіву.

---

*Кінець runbook. Доповнюйте після змін інфраструктури.*
