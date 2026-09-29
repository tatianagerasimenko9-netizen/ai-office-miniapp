# Стан проєкту для продовження роботи (оновлюється наприкінці кожної сесії)

Оновлено: 2026-09-29. Постійні вимоги — `docs/project-requirements.md`; порядок робіт — `docs/completion-plan.md`. Не починати аудит заново.

## Що в production (перевірено на Render 2026-09-29 13:07 UTC)
- `main` = `d2a4ad7` (PR #74 злито). Web `srv-d7seub3eo5us73c10svg` і worker `srv-d7sui7ok1i2s73a4qod0` Live на ньому (git_sha у логу worker збігається). Fingerprint БД web = worker (`c78e00696e638425`). PostgreSQL `dpg-d7t2lvbrjlhs73d85sng-a`, workspace `tea-d6qnqkc50q8c73bluj6g`, https://ai-office-miniapp.onrender.com. Автодеплой з `main`: кожне злиття = deploy обох сервісів.
- Прапорці: `OFFICE_FEED_GATE`, `OFFICE_LEGACY_ACTIVE_REQUIRES_LEV` увімкнені; Risk Officer — shadow; `OFFICE_AUTO_MIGRATE=0`; `OFFICE_LEV_WATCH_NOTIFY` не задано (сповіщення трекера ВИМКНЕНІ); `OFFICE_NOTIFY_VERIFIED` не задано; запис угод вимкнено (немає ключа/ID).
- Реалізовано й розгорнуто: діалог `/lev`; повідомлення простою мовою; єдиний стан сценарію; цілі 2/3 за рівнями Pine; трекер умов з доставкою через `send_proactive` + результат/повтор; передача карток основному трекеру; сторінка `W-…`; дедуп списку; кеш/пауза 429; звірка порту PUMP&DUMP.
- Пороги/TP1 не змінювались. Ордерів у коді немає.
- Резервна копія БД перед релізом: приватний артефакт claude.ai `XkvVjJWfrFnkWMbkUfbV3F` (лише власниця).
- Перевірка #74 перед злиттям: CI зелений; replay на реальних свічках Binance Vision (7 монет, травень–серпень): помилок 0, дублів термінальних подій 0; проба на старому проді показала застарілі M5/H1/H4/D1 (429) — це і виправляє PR-D.

## Відкриті PR
- PR-D #76 (`claude/pr-d-candle-fallback`): резервні свічки (спот Binance → Bybit) при 429/збої fapi. **Причина: після деплою #74 лог worker `[data] binance ok=4 errors=224`, `[radar] no candles BTCUSDT` — Лев без даних.** Не розгорнуто; потрібен дозвіл на deploy.
- PR-C #75 (`claude/pr-c-market-context`): розділ «Що ще перевірив Лев» (фандинг/OI/співвідношення; лише інформація, не аналізує стакан/карту/новини). CI зелений. Не розгорнуто.

## Порядок продовження (безпечно)
1. `git fetch && git checkout main && git pull`; переглянути відкриті PR (`docs/STATE.md` цей файл).
2. Дочекатись CI відкритого PR (offline-safety, postgres-integration, mini-app-ui-smoke, dependency-audit) → запит на deploy → merge → перевірка Render (`list_deploys`, `list_logs`, запит до БД) → `prod-probe.yml` (Actions → Run workflow, ref = потрібна гілка).
3. Після deploy PR-B: за погодженням `OFFICE_LEV_WATCH_NOTIFY=1` на worker, потім перевірка на першій реальній події → `OFFICE_NOTIFY_VERIFIED=1`.
4. Далі PR-C…G з `docs/completion-plan.md`.

## Відомі проблеми/залежності
- Binance 429 з IP Render: при старті burst → 429 → тимчасові прогалини свічок (проба 12:38 UTC: M5/H1/H4/D1 без даних). PR-B не вирішив (13:07 UTC: ok=4, errors=224). PR-D додає резервні джерела; якщо й вони недоступні з Render — спільний кеш свічок у БД.
- `follow_setup` hydrate: `_LIVE` містить ~106 ключів при старті (старі сценарії); перевірити, чи не шле старі підтвердження/скасування.
- Потрібно від власниці: (1) повний Pine ICT SMC HUNTER (у репо лише фрагмент) і CSV-експорт значень обох індикаторів з TradingView; (2) рішення про поріг TP1 за типом угоди (`docs/min-tp1-analysis.md`); (3) платні джерела (карта ліквідацій, календар) — лише за погодженням витрат; (4) дозволи на deploy і на вмикання сповіщень.
- Не було: реальної події «в зоні/підтверджено/скасовано» через новий трекер (сповіщення вимкнені, події пишуться в `LEV_WATCH_EVENT`). Не називати автоповідомлення перевіреними до першої реальної доставки.
