# Стан проєкту для продовження роботи (оновлюється наприкінці кожної сесії)

Оновлено: 2026-09-29. Постійні вимоги — `docs/project-requirements.md`; порядок робіт — `docs/completion-plan.md`. Не починати аудит заново.

## Що в production (перевірено на Render)
- `main` = `297bb53` (PR #73), web `srv-d7seub3eo5us73c10svg` і worker `srv-d7sui7ok1i2s73a4qod0` Live на ньому. PostgreSQL `dpg-d7t2lvbrjlhs73d85sng-a`, workspace `tea-d6qnqkc50q8c73bluj6g`, URL https://ai-office-miniapp.onrender.com. Автодеплой із `main` увімкнений: кожне злиття = deploy обох сервісів.
- Прапорці: `OFFICE_FEED_GATE` і `OFFICE_LEGACY_ACTIVE_REQUIRES_LEV` увімкнені (дефолт); Risk Officer — shadow; `OFFICE_AUTO_MIGRATE=0`; `OFFICE_LEV_WATCH_NOTIFY` не задано (сповіщення трекера ВИМКНЕНІ); `OFFICE_NOTIFY_VERIFIED` не задано; запис угод вимкнено (немає ключа/ID) — необов’язкова функція.
- Реалізовано й розгорнуто: діалог `/lev` із контекстом монети; повідомлення простою мовою; єдиний стан сценарію (`office_scenario_state.py`) на сторінці Mini App; цілі 2/3 за рівнями Pine (`office_targets.py`); кеш і пауза 429 (`office_market_data.py`); звірка порту PUMP&DUMP.
- Пороги/TP1 не змінювались. Ордерів у коді немає.
- Резервна копія БД перед релізом (логічна, перевірена відновленням): приватний артефакт claude.ai `XkvVjJWfrFnkWMbkUfbV3F` (лише власниця).

## Відкриті PR
- PR-B (гілка `claude/pr-b-tracking-delivery`, див. PR у GitHub): діалог і Mini App читають один стан; доставка повідомлень трекера через `send_proactive` з результатом і повтором; передача карток основному трекеру (`follow_setup`) без дублів; сторінка для умов з діалогу (`W-…`); дедуп списку; пауза 429 для aiohttp; replay трекера на реальних свічках; проба сценаріїв. **Не розгорнуто — потрібен дозвіл власниці.**
- Гілка `claude/docs-requirements-audit` злита в #73.

## Порядок продовження (безпечно)
1. `git fetch && git checkout main && git pull`; переглянути відкриті PR (`docs/STATE.md` цей файл).
2. Дочекатись CI відкритого PR (offline-safety, postgres-integration, mini-app-ui-smoke, dependency-audit) → запит на deploy → merge → перевірка Render (`list_deploys`, `list_logs`, запит до БД) → `prod-probe.yml` (Actions → Run workflow, ref = потрібна гілка).
3. Після deploy PR-B: за погодженням `OFFICE_LEV_WATCH_NOTIFY=1` на worker, потім перевірка на першій реальній події → `OFFICE_NOTIFY_VERIFIED=1`.
4. Далі PR-C…G з `docs/completion-plan.md`.

## Відомі проблеми/залежності
- Binance 429 з IP Render: при старті burst → 429 → тимчасові прогалини свічок (проба 12:38 UTC: M5/H1/H4/D1 без даних). Мітигація в PR-B (довший кеш повільних ТФ, лічильники `[data] binance …` у логах worker, `source_health` в `/api/v2/overview`). Якщо повторюватиметься — спільний кеш свічок у БД між worker і web.
- `follow_setup` hydrate: `_LIVE` містить ~106 ключів при старті (старі сценарії); перевірити, чи не шле старі підтвердження/скасування.
- Потрібно від власниці: (1) повний Pine ICT SMC HUNTER (у репо лише фрагмент) і CSV-експорт значень обох індикаторів з TradingView; (2) рішення про поріг TP1 за типом угоди (`docs/min-tp1-analysis.md`); (3) платні джерела (карта ліквідацій, календар) — лише за погодженням витрат; (4) дозволи на deploy і на вмикання сповіщень.
- Не було: реальної події «в зоні/підтверджено/скасовано» через новий трекер (сповіщення вимкнені, події пишуться в `LEV_WATCH_EVENT`). Не називати автоповідомлення перевіреними до першої реальної доставки.
