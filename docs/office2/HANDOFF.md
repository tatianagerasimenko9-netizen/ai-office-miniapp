# HANDOFF — AI Trading Office (оновлено 11.10.2026 ~10:05Z)

Нова сесія: прочитай цей файл, перевір факти в GitHub/Render/БД (не довіряй файлу сліпо), продовжуй з «Наступний крок».

## Production (перевірено 10.10)
- Сервіс із живим циклом Office2 (`[o2shadow]`, `[o2smc]`, `[o2learn]`): `srv-d7sui7ok1i2s73a4qod0`; другий: `srv-d7seub3eo5us73c10svg` (у master-промпті підписані навпаки). Postgres `dpg-d7t2lvbrjlhs73d85sng-a`; workspace `tea-d6qnqkc50q8c73bluj6g`.
- Обидва `live` на `d397b77` (#189). Режим: LIVE-аналіз + shadow/paper. Реальних ордерів немає і без окремого дозволу власниці не вмикаються.
- Learning-звіт у БД: `office2_learning_report` (scope office2 / old_lev_delivered / old_lev_shadow), раз на 6 год (`OFFICE2_LEARNING=0` вимикає).

## Злито: #164 SMC shadow (30d2b7e), #181 радар 30 с (9e40a10), #184 movers (879e3bf), #185 dynamic universe + контроль протилежних сценаріїв (9ba4e0b), #186/#187 docs, #188 learning-контур (577fd56), #189 Binance replay + мітка сесії (d397b77).
Далі в гілці: `learning_flags` (COST_HEAVY/OFF_HOURS, лише annotate), таблиця фільтрів у replay — див. останній PR.

## 11.10 (після #191/#192)
- #191 (563ed23) latency-fix у production з 10.10 22:46Z: кеш `office_signals`, окремі пули доставки/трекера, діагностика `[loop-stall]`/`[db-slow]`. Ефект на реальній доставці НЕ підтверджено (потрібен наступний READY: `OFFICE2_READY_SENT.timing`).
- #192 (49b20ad) DYNAMIC WATCH_ONLY: `OFFICE2_DYNAMIC_UNIVERSE=watch` виставлено на Worker 11.10 08:59Z (`live` = єдиний шлях в основний цикл; `1/on/watch` = лише спостереження). Таблиці `office2_dynamic_candidate`/`office2_dynamic_log` створюються при першому оновленні; перевірити рядки. Mini App: Радар → «DYNAMIC · WATCH_ONLY», `/api/v2/dynamic_watch`.
- P3 (PR #193): `office2/paper.py` — paper-позиції за правилами «вхід лише після доставки» (open першої 1m-свічки ≥ delivered_ts, MISSED якщо chase>0.5R/ціна за SL/TP1/нема даних), моделі A/B/C, витрати 0.15%, потік `office2-paper` (60 с), `/api/v2/paper`, `OFFICE2_TELEGRAM_FAILURE` у БД.
- Прогалини: 41-ша SMC-схема відсутня — не вигадувати (unverified).

## 11.10 10:05Z — що змінилось після #193–#195
- **Злито й задеплоєно:** #192 DYNAMIC WATCH_ONLY (6 монет, 12 кандидатів, 0 витоків у LIVE), #193 paper-контур (`office2/paper.py`, потік `office2-paper`), #194 scope LIVE/BACKFILL/BACKFILL_INVALID (33 NO_DATA збережені, але поза статистикою), #195 Trade Intelligence (`office2/postmortem.py`: класи помилок з доказами, альтернативи V0–V8, evidence-digest; Mini App «Чому ця угода?»). #196 (контрольний потік без PAPER_SINCE) — у роботі.
- **Підтверджено в production:** paper-розрахунок збігся з milestone-трекером на 4 сигналах до запуску (LINK/HBAR/NEAR SL, SOL відкрита); авто-розбір записаний (`postmortem_json` pm-2). LIVE paper-позицій після запуску ще 0 (немає нових READY).
- **Чому немає нових READY:** денний ліміт «3 стопи за добу UTC» (діє до 00:00 UTC), за добу відсік 30 would-be READY на 18 монетах. Ліміт НЕ змінювався (рішення власниці). Контрольний потік (`scope='CONTROL'`) рахує, що було б.
- **V7/V8:** `fixtures/learning/replay_paired_2026-10.json`, `BINANCE_REPLAY_2026-10.md`: переваги не підтверджено в обох періодах; у LIVE не вмикати.
- **Знання:** `KNOWLEDGE_AUDIT.md`, `GERCHIK_AUDIT.md`, `COST_MODEL.md`. Прогалини: окрема модель BREAKOUT+RETEST у v2.1 відсутня; DOM/GEX/календар не підключені; книги Вайкоффа немає.
- **Актуальний контекст:** артефакти Actions не завантажуються з sandbox (host заблоковано) — читати aggregate через `get_job_logs(return_content=true)` + розбір JSON; `gh api` працює лише для api.github.com.

## Інструменти (без участі Render)
- Replay на реальних свічках Binance: GitHub Actions → `binance-replay.yml` (workflow_dispatch; inputs symbols/end_date/days; публічний архів data.binance.vision; жодних секретів). Результат — у логу job `aggregate` + артефакт `aggregate.json`. Запуск через `actions_run_trigger` з `ref=<гілка>`.
- Звіти: `docs/office2/LEARNING.md`, `BINANCE_REPLAY_2026-10.md`, `SL_AUDIT_2026-10.md`.

## Стани перевірки (не змішувати)
- Learning-контур: код, тести, CI, merge, deploy, перший звіт у production БД ✔.
- Binance replay: два незалежні періоди (11–25.09, 25.09–09.10) на 29 монетах ✔; Brain ≈0R (A) і −0,148R (B); SMC ≈0; жодна зміна правил (відкладений вхід, ширший SL, лімітний retest, LATE_SWEEP, напрям) не покращує очікування в обох періодах.
- Кандидати зі стабільним знаком у обох періодах: COST_HEAVY, OFF_HOURS (лише paper-forward annotate).
- Dynamic universe: код/тести/deploy ✔, у production вимкнено. Conflict gate: annotate активний.
- Не перевірено: структурний SL за swing/ліквідністю, sweep-/BOS-вхід, bear/bull окремо, затримки доставки 297–1062 с (причини), мобільний WebView, restart/recovery під навантаженням, DYNAMIC на Binance, UI «Аналітика помилок».

## Відкриті рішення власниці
1. Увімкнути `OFFICE2_DYNAMIC_UNIVERSE=1`? (змінює набір монет для READY).
2. Чи вмикати блокування за COST_HEAVY / OFF_HOURS після paper-forward (зараз лише мітки)? Зміна торгової політики — лише з погодження.
3. `OFFICE2_CONFLICT_GATE=block`: після accumulating evidence.
4. `OFFICE2_SMC_REPLAY` на живому сервісі НЕ потрібен — замінено Actions-replay.

## Наступний крок
0. Дочекатись першого справжнього READY після запуску: перевірити ланцюг сигнал → Telegram → paper-позиція → TP/SL → postmortem → Mini App.
1. Paper-forward: накопичувати `learning_flags`/`session_tag`/`conflict` у READY; через ≥ 30 розв'язаних угод з кожною міткою перерахувати (звіт `office2_learning_report`).
2. Причини затримок доставки 297–1062 с: логи 6.10 17:45 BTC, 9.10 01:15 WLD / 02:15 NEAR+ONDO.
3. Структурний SL та sweep/BOS-вхід у counterfactual (потрібні swing-и в подіях replay).
4. UI «Аналітика помилок» у Mini App (читає `office2_learning_report`).
5. Restart/recovery і 429: офлайн-тести + логи.
