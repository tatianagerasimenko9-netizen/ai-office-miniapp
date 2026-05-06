# Runbook AI Office (`ai-office-miniapp`)

**Призначення:** швидке відновлення, перевірка env і дій при «тиші» в чатах.  
**Оновлено:** 2026-05-06 (§7.1 журнал перевірок прод; fingerprint relay для звірки з Mini App)  

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
| `OFFICE_BRIEFING_TZ` | Часова зона IANA, напр. `Europe/Kyiv`. У репо в `requirements.txt` додано **`tzdata`** — щоб Windows і мінімальні Linux-образи мали базу зон; без неї Python може не знайти `Europe/Kyiv` і тоді relay логуватиме попередження й брифінги підуть за **UTC** (години «з’їдуть» відносно Києва). |
| `OFFICE_BRIEFING_MORNING` | Час ранкового брифінгу `HH:MM` (за замовчуванням `08:00`) |
| `OFFICE_BRIEFING_EVENING` | Час вечірнього debrief `HH:MM` (за замовчуванням `21:00`) |
| `OFFICE_CIRCUIT_DISABLE` | `1` — вимкнути circuit breaker (п.31); за замовчуванням увімкнено |
| `OFFICE_CIRCUIT_LOSSES` | Мінімум підряд LOSS у журналі для блоку нового входу (за замовчуванням `3`) |
| `OFFICE_DISCIPLINE_REVIEW_EVERY` | Якщо `N ≥ 2`, нагадування про review кожні N **закритих** угод (п.36); `0` — вимкнено |
| `OFFICE_WEEKLY_DISABLE` | `1` — не слати тижневий зріз журналу (п.29) |
| `OFFICE_WEEKLY_TIME` | Час `HH:MM` у зоні `OFFICE_BRIEFING_TZ` (за замовчуванням `20:00`) |
| `OFFICE_WEEKLY_ISO_DOW` | День ISO 1=Пн … 7=Нд (за замовчуванням `7`, неділя) |
| `OFFICE_RISK_COMMITTEE_DISABLE` | `1` — вимкнути щоденний тригер «risk committee» (п.30) |
| `OFFICE_RISK_COMMITTEE_DAY_LOSSES` | Поріг кількості LOSS «сьогодні» (за замовчуванням `4`) |
| `OFFICE_RISK_COMMITTEE_STREAK` | Поріг серії SL підряд у журналі (за замовчуванням `3`) |
| `OFFICE_MARKET_ALERTS_DISABLE` | `1` — вимкнути funding/ATR алерти (п.32–33) |
| `OFFICE_FUNDING_ALERT_ABS_PCT` | Поріг \|funding\| для BTC, у % як у snapshot (за замовчуванням `0.07`) |
| `OFFICE_ATR_ALERT_VOL_PCT` | Поріг 24h range % BTC (за замовчуванням `7.5`) |
| `OFFICE_MARKET_ALERT_COOLDOWN_SEC` | Мінімум секунд між повторними алертами одного типу (за замовчуванням `3600`) |
| `OFFICE_MARKET_ALERT_POLL_SEC` | Інтервал опитування Binance (за замовчуванням `180`) |
| `OFFICE_MINI_VERIFY_URL` | Публічний URL Mini App Web (**без** `/api/summary`). При старті relay автоматично звіряє `db_identity.fingerprint` з БД relay → **MASTER п.17** у логах `[relay][OK] Mini App fingerprint…`. |
| `OFFICE_MINI_VERIFY_DISABLE` | `1` — не викликати перевірку Mini App при старті |
| `OFFICE_SIGNAL_SOURCE_BOT_IDS` | Опційно: список `sender_id` через кому (напр. `123456789,987654321`). Повідомлення цих ботів у MAIN примусово вважаються сигналами навіть при нетиповому форматі. |
| `OFFICE_SIGNAL_SOURCE_BOT_USERNAME` | Опційно: username бота-джерела (напр. `my_crypto_scanner_bot`, можна без `@`). Також форсує запуск офісу по повідомленнях у MAIN. |
| `RELAY_LOG_NONSIGNAL_MAIN` | `1` — debug-лог відкинутих повідомлень у MAIN (`not signal`) для швидкого підбору формату детектора. |
| *(вбудовано в relay)* | Обробка `MessageEdited`: якщо бот спочатку публікує короткий сигнал, а потім редагує його до повного тексту, office-flow теж запускається автоматично. |
| `SOURCE_CHAT_ID` | Джерело повідомлень (якщо відрізняється від MAIN) |
| `RELAY_FORCE_SETUP` / `RELAY_INTERACTIVE` | Майстер першого налаштування |

#### Де взяти `OFFICE_MINI_VERIFY_URL` (Render, покроково)

Це **не** окремий секрет і не URL з BotFather — це звичайна **публічна HTTPS-адреса Web-сервісу**, на якому крутиться `office_mini_app.py`.

1. Увійди в [dashboard.render.com](https://dashboard.render.com) і відкрий **саме той сервіс**, який деплоїть **Mini App** (Web Service; стартова команда на кшталт `python -u office_mini_app.py`).
2. Зверху сторінки сервісу знайди блок **URL** (або **Links**) — рядок виду `https://ім’я-сервісу.onrender.com`. Це і є базовий URL.
3. Перевір у браузері: відкрий цей URL — має відкритися сторінка Mini App (графік, KPI). Якщо відкривається — скопіюй адресу **без** шляху `/api/summary` (суфікс не додавати; код сам допише запит).
4. Відкрий **інший** сервіс — **Office relay / worker** (`office_multibot_bootstrap.py` або аналог).
5. **Environment** → **Add Environment Variable** → ключ **`OFFICE_MINI_VERIFY_URL`** → значення **вставити скопійований URL** (можна з або без слеша в кінці — обидва варіанти підтримуються).
6. **Save Changes** → виконай **Manual Deploy** / дочекайся автодеплою relay.
7. У **логах relay** після старту шукай рядок **`[relay][OK] Mini App fingerprint збігається з relay`** — тоді п.17 підтверджений автоматично. Якщо **`[relay][WARN]`** — перевір, що Mini App живий, що на обох сервісах **однаковий `DATABASE_URL`**, і що Web не «спить» на безкоштовному плані під час першого запиту (інколи потрібна повторна перезагрузка relay).

**Куди не треба додавати:** на сервіс Mini App цю змінну ставити не обов’язково — її читає лише **relay**.

### Mini App

| Змінна | Значення |
|--------|----------|
| `DATABASE_URL` або `OFFICE_DB_PATH` | **Той самий**, що й у runtime |
| `OFFICE_MINI_HOST` / `OFFICE_MINI_PORT` | Bind для веб-сервісу |

**API:** `GET /api/summary?symbol=BTCUSDT&action=SKIP&agent=lev&chart=ETHUSDT` — фільтри рішень/журналу (п.35); параметр **`chart`** задає символ для блоку **live overlay** (OPEN угода з журналу + рівні SL/TP/entry поруч із графіком). KPI по ролях і культура — у JSON; поле **`overlays`**.

**One-click review:** `GET /api/review_draft` або `GET /api/review_draft?trade_id=…` — відповідь JSON з **`draft_ua`** (чернета stop-review українською); без `trade_id` береться останній **LOSS**, інакше остання закрита, інакше відкрита. На сторінці Mini App — кнопки 📋 у таблиці журналу та «останній LOSS».

**Risk heatmap:** у відповіді `/api/summary` поле **`risk_heatmap`** — топ символів за недавніми закритими угодами; колір колонки «Ризик» = частка LOSS серед WIN+LOSS (не прогноз біржі, а **зведення з журналу**).

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

### 7.1 Журнал перевірок прод (заповнюйте вручну)

| Дата | Relay | Mini App fingerprint збігається | E2E §7 пункти 2–5 |
|------|--------|-----------------------------------|-------------------|
| 2026-05-06 | PostgreSQL `fingerprint=c78e00696e638425`; `[relay][OK] Mini App fingerprint… (авто)` | **Так** (`OFFICE_MINI_VERIFY_URL` → [ai-office-miniapp.onrender.com](https://ai-office-miniapp.onrender.com)) | за потреби |

Останній підтверджений відбиток — **`c78e00696e638425`** (relay = Mini App за автоперевіркою при старті relay).

### 7.2 Автоматична звірка п.17

**A) На Render (без локального ПК):** задайте **`OFFICE_MINI_VERIFY_URL`** на сервісі **relay** (той самий базовий URL, що відкриває Mini App у браузері). Після деплою в логах має з’явитися **`[relay][OK] Mini App fingerprint збігається з relay`** — це закриває **п.17** без скрипта.

**B) Локально або CI:** скрипт `office_e2e_preflight.py`

Скрипт у корені репозиторію порівнює **`db_identity.fingerprint`** з `GET …/api/summary` з еталоном:

- або **`RELAY_FINGERPRINT_EXPECTED`** / `--relay-fingerprint` (16 hex з логів `[relay] DB identity`),
- або локальним **`DATABASE_URL`** / **`OFFICE_DB_PATH`** (як у `.env` з тим самим рядком, що на Mini App).

Приклад (PowerShell):

```text
$env:RELAY_FINGERPRINT_EXPECTED="c78e00696e638425"
$env:OFFICE_MINI_URL="https://ВАШ-mini-app.onrender.com"
py -3 office_e2e_preflight.py
```

Вихід **`[preflight][OK]`** і код **0** означає: Mini App віддає той самий fingerprint, що й relay у логах → **п.17 закрито автоматично**.

Якщо порівнюєте з локальним `DATABASE_URL` (скопійованим з Render), relay-прапорець можна не задавати:

```text
$env:DATABASE_URL="postgresql://…"
$env:OFFICE_MINI_URL="https://…"
py -3 office_e2e_preflight.py
```

### 7.3 Повний E2E чеклист (п.20) — приймальні критерії

Після **§7.2 OK** пройдіть таблицю й відмітьте дату / результат у §7.1.

| Крок | Перевірка | Зроблено |
|------|-----------|----------|
| E2E-1 | У логах relay після старту: `[relay][OK] Mini App fingerprint…` (**`OFFICE_MINI_VERIFY_URL`**) **або** `office_e2e_preflight.py` код 0 **або** ручна звірка §3 | ☐ |
| E2E-2 | У MAIN надіслано тестовий сигнал **або** у OFFICE виконано `!ask` з символом | ☐ |
| E2E-3 | У Telegram офісу видно ланцюжок ролей / вердикт без падіння relay у логах | ☐ |
| E2E-4 | У Mini App у «Останні рішення» з’явився рядок з очікуваним символом / дією | ☐ |
| E2E-5 | За наявності угоди в журналі — рядок узгоджений у таблиці «Журнал угод» після Refresh | ☐ |
| E2E-6 | (Опційно) скріни або короткий запис у внутрішній нотатці для freeze | ☐ |

Якщо всі обов’язкові пункти (E2E-1 … E2E-5) виконані — **MASTER п.20** можна вважати закритим для поточного релізу.

---

*Кінець runbook. Доповнюйте після змін інфраструктури.*
