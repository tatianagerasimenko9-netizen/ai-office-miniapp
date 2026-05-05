# Runbook AI Office (`ai-office-miniapp`)

**Призначення:** швидке відновлення, перевірка env і дій при «тиші» в чатах.  
**Оновлено:** 2026-05-06  

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

**Перевірка:** порівняти значення `DATABASE_URL` / `OFFICE_DB_PATH` у двох сервісах у Render Dashboard.

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

*Кінець runbook. Доповнюйте після змін інфраструктури.*
