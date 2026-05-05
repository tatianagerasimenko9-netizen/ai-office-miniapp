# Статус MASTER-CHECKLIST (37 кроків)

**Зафіксовано:** 2026-05-06  
**Репозиторій:** `ai-office-miniapp`  
**Правила відміток:**

| Символ | Значення |
|--------|----------|
| ✅ | Зроблено: є в коді та/або підтверджено типовим прод-налаштуванням |
| 🟨 | Частково або код готовий, потрібна фінальна перевірка в проді / процесі |
| ⬜ | Не зроблено або не оформлено як окремий артефакт |

---

## P0 — інфраструктура та робочий контур

| № | Статус | Пункт | Короткий доказ / заувага |
|---|--------|--------|---------------------------|
| 1 | ✅ | Ядро `file-1.py.py` не чіпати; Office — sidecar | Політика зафіксована в `OFFICE_RULES_UA.md` |
| 2 | ✅ | Окремий GitHub repo Office (`ai-office-miniapp`) | Цей репозиторій |
| 3 | ✅ | Mini App на Render | `office_mini_app.py`, HTTP-сервер, читання БД |
| 4 | ✅ | Кнопка Open Office (BotFather) | Підтверджено в експлуатації (зовнішній крок Telegram) |
| 5 | ✅ | Базовий `!ask` + live snapshot | `office_bridge.py`, relay у `office_relay_wizard.py` |
| 6 | ✅ | Журнал + stop-review + learning guard | Таблиці / логіка журналу в bridge + relay |
| 7 | ✅ | 9 ролей (Софія / Віктор / Артем тощо) | `AGENTS` / ролі в `office_bridge.py` |
| 8 | ✅ | `!scenario` + сценарні шаблони | `SCENARIO_TEMPLATES` та обробка в relay/bridge |
| 9 | ✅ | `OFFICE_RULES_UA.md` | Файл у репо |
| 10 | ✅ | `OFFICE_DIALOG_SCENARIOS_UA.md` | Файл у репо |
| 11 | ✅ | Повний Office runtime у репо | `office_bridge.py`, `office_relay_wizard.py`, `office_multibot_bootstrap.py` |
| 12 | ✅ | `.gitignore` (сесії, конфіг, `.env`, БД-файли) | `*.db`, `*.session`, `office_relay_config.json`, `.env` |
| 13 | 🟨 | Commit + Push; контрольний список релізів | Деплої з GitHub є; окремий «freeze-лист» комітів не ведеться |
| 14 | 🟨 | Другий Render service (runtime окремо від Mini App) | За замовчуванням два сервіси; уточнити тип Web/Worker у панелі |
| 15 | 🟨 | Env vars runtime на Render | Задано; варто зафіксувати **еталон** у runbook (п. 21) |
| 16 | ✅ | Стабільне сховище БД (disk / external / managed Postgres) | `DATABASE_URL` + `init_office_db` у bridge/relay; managed PG на Render |
| 17 | 🟨 | Mini App читає ту ж БД, що runtime | Код: `office_mini_app.py` → `psycopg` при `postgresql://`; **перевірити**, що на обох сервісах **однаковий** `DATABASE_URL` |
| 18 | ✅ | Три гілки (Загальний / Задачник / Техніка) | `OFFICE_GENERAL_THREAD_ID`, `OFFICE_TASKS_THREAD_ID`, `OFFICE_TECH_THREAD_ID` у `send_office` |
| 19 | ⬜ | Технічний health / report канал Артема | Окремий регулярний health-стрим не виділено |
| 20 | 🟨 | E2E: сигнал → діалог → вердикт → журнал → mini app | Сигнал/діалог/журнал — так; повне закриття з Mini App — перевірка в проді |
| 21 | ⬜ | Freeze + короткий runbook | Документ процесу ще не додано |

---

## P1 — якість діалогу та логіки

| № | Статус | Пункт | Короткий доказ / заувага |
|---|--------|--------|---------------------------|
| 22 | ✅ | Natural chat-style (без службових префіксів у видимому чаті) | Приховані теги маршрутизації; `[data: …]` прибрано з `_enforce_data_grounding` |
| 23 | 🟨 | Повний Persona Pack для 9 ролей | Профілі в коді є; окремий «production pack» (файл/версія) не оформлено |
| 24 | 🟨 | Cross-reply (відповіді в нитці) | `reply_to` у Bot API + теми; «живий» багатохідовий суперечковий діалог — обмежено |
| 25 | ⬜ | Factor Pack v2 (funding, ATR, FVG, OB, … єдина структура) | У коді немає єдиного factor-pack шару для всіх ролей |
| 26 | ✅ | Natural Dialog Templates v2 (6 живих сценаріїв) | `OFFICE_DIALOG_SCENARIOS_UA.md` + шаблони в bridge |
| 27 | ⬜ | Style QA Gate (авто-перевірка тону/мови/довжини) | Окремого гейту немає; спрощення тексту — через промпти/шаблони |
| 28 | ⬜ | Auto Briefing Scheduler (ранок + вечір) | Не реалізовано |
| 29 | ⬜ | Weekly Review Engine | Не реалізовано |
| 30 | ⬜ | Risk Committee Trigger | Не реалізовано |
| 31 | ⬜ | Circuit Breaker (3 SL поспіль) | Не реалізовано |
| 32 | ⬜ | Funding Alert Rule | Не реалізовано |
| 33 | ⬜ | ATR Exhaustion Alert Rule | Не реалізовано |
| 34 | ⬜ | KPI by Agent у Mini App | Загальні KPI є; по ролях — ні |
| 35 | ⬜ | Decision History Filters у Mini App | Не реалізовано |
| 36 | ⬜ | Discipline Pack (правила проп-фірми) | Не реалізовано як окремий enforcement |

---

## P2 — пізніше / складне

| № | Статус | Пункт | Короткий доказ / заувага |
|---|--------|--------|---------------------------|
| 37 | ⬜ | Culture layer (leaderboard, trade of week, roast) | Не реалізовано |

**Також з попередніх планів (без окремого № у базовому 37):** live overlays у Mini App, One-Click Review, Risk Heatmap — ⬜.

---

## Підсумкові цифри (за цим документом)

| Категорія | Кількість |
|-----------|-----------|
| ✅ | 16 |
| 🟨 | 7 |
| ⬜ | 14 |
| **Усього** | **37** |

---

## Наступні кроки (рекомендовано)

1. Закрити **п. 17**: однаковий `DATABASE_URL` на runtime і Mini App + швидка перевірка даних у UI.  
2. Закрити **п. 20**: один прохід E2E з фіксацією скрінів/логів.  
3. Додати **п. 21** + **п. 19** (runbook + health від Артема).  

Після змін у статусах — оновлюйте таблиці вище та дату «Зафіксовано».
