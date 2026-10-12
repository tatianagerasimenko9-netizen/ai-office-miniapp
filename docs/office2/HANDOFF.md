# HANDOFF — AI Trading Office (оновлено 12.10.2026)

Нова сесія: прочитай цей файл, перевір факти в GitHub/Render/БД (не довіряй файлу сліпо), продовжуй з «Наступний крок».

## 12.10.2026 (вечір): підтверджений вхід замість орієнтира — radar-1 зміни

Рішення власниці: Telegram = реальні підтверджені сигнали; навчання — у БД/Mini App; спостереження ≠ вхід.
- `radar_watch.plan_of`: вхід за ціною підтвердження (закриття M15) більше НЕ переноситься лімітом на межу зони (було: TIA e008 — підтвердження 0,591, ліміт 0,5805).
- `radar_watch.pick_for_tg`: у Telegram за замовчуванням лише ARMED-спостереження; навчальні BLOCKED і ранні RETRACE не надсилаються (`RADAR_TG_STAGES=ARMED,RETRACE,BLOCKED` повертає старе).
- `radar_text.card_text` (WATCH): зона інтересу / потрібне підтвердження / скасування окремо; вхід, стоп, цілі НЕ показуються до підтвердження.
- `radar_watch.track`: новий WATCH не відкриває paper-вхід (дотик орієнтира ≠ підтвердження); старі WATCH із paper-станом дотрекуються.
- **Життєвий цикл paper (radar): скасований сценарій не відкриває позицію.** Власна умова картки — закриття закритої M15-свічки за екстремумом події (`inval_px`, береться з `thesis.invalidation.price`; для старих карток — `backfill_inval`). Якщо воно виконане ДО заповнення — `paper_status=INVALIDATED` + `inval_ts` + `inval_why`; прокол тінню без закриття за рівнем скасуванням не є. Перерахунок стабільний після рестарту (стан виводиться зі свічок), враховує запізнілу доставку (відлік від бару створення). Контрольний приклад — TIA d37a: бар 21:00–21:15 закрився 0,569 < 0,5692, а paper увійшов о 21:45.
- Brain READY не змінювався: вхід = закриття M15-свічки підтвердження (бар закритий: `live.wait_bar_closed`), SL = екстремум події − люфт; 3 SL/добу, ризик, ордери — без змін.
- Replay на ф'ючерсах (`scripts/reaction_shadow_replay.py`): докази покращення середнього R відсутні (n=17, один день); див. `docs/sources/REACTION_SHADOW.md`.

## 12.10 — РЕЄСТР ПЕРШОДЖЕРЕЛ (пакет «Dzherela 2026-10-12», 427 файлів)
- Усі 427 файлів перевірено за `FULL_FILE_MANIFEST.csv`: 427/427 SHA-256 збігаються, дублікатів і відсутніх немає. Прочитано візуально всі 415 зображень; книга Герчика й методичка SMC — за розділами (див. `docs/sources/unresolved.md`).
- `docs/sources/`: `manifest.csv`, `evidence.jsonl` (77 записів правил), `unresolved.md`, карти методів, `CONFORMITY_2026-10-12.md`. Оригінали в GitHub не комітяться.
- Додано `office2/source_shadow.py` (+ API `/api/v2/source_shadow`, блок у Mini App «Правила з джерел», цикл `OFFICE2_SOURCE_SHADOW=0` вимикає): паранормальний D1-бар (Герчик ≥2×, ATR 3–5 D1 без паранормальних) і база після нього (Дарія). Shadow; на READY/Telegram/ордери не впливає.
- `htf_scenario` перемічено: сценарій = `USER_REQUIREMENT` (слайда-першоджерела немає), а не авторське правило.
- Не змінено: LIVE-гейти, 3 SL/добу, ризик, ордери, dynamic universe. Знайдені розбіжності код↔джерело — у `CONFORMITY_2026-10-12.md` (R:R ≥3 vs перша ціль ≥1R; ліміт 3 vs 2 збитки; формула ATR; люфт) — потрібні рішення власниці.
- Replay на реальних D1 Binance: workflow `Source shadow replay` (ручний) — після злиття запустити й додати результат. До цього всі правила `EDGE_NOT_PROVEN`.

## 11.10 12:50Z — ЖИВИЙ WATCH/PAPER РАДАР (пріоритет власниці в Issue #199, замість нових досліджень)
- **Діагноз 0 READY (production):** сканер живий (≈314 WAIT-сценаріїв, 28 монет, LINK SHORT 3/3 ARMED), але в Telegram ішов лише READY, а новий READY з 6.10 щодня відсікав захист «3 стопи/добу UTC» (82 would-be READY). Захист не змінювався.
- **Додано (PR #204):** `brain2` → `preview` плану для WAIT 2/3–3/3 (стан/причини не змінені); `office2/radar_watch.py` — картки WATCH (ARMED/RETRACE) і BLOCKED, таблиця `office2_radar_card`, paper-супровід (`evaluate_card`, вхід лімітом після появи картки, SL першим, витрати 0.15 %), Telegram-потік «не вхід» (`send_pass`, антиспам ≤4/год, ≤12/добу, 1/монету/4 год; `OFFICE2_RADAR_TG=0` вимикає, `OFFICE2_RADAR=0` вимикає цикл), потік `office2-radar` у worker (sync+track щохвилини), `monitor_office2_radar` у релеї, `/api/v2/live_radar`, Mini App «Живий радар» (головна й Радар) + картка з графіком (`?tab=radar&card=ID`) + блок «чому немає READY».
- **Тренажер (наступний PR):** `office2/trainer.py` + `/api/v2/trainer`, `/api/v2/trainer_reveal`: історія на момент T без майбутнього (тест: рішення не залежить від майбутніх свічок), прогноз → розкриття → paper-оцінка.
- **Не підтверджено до першої реальної картки в Telegram:** доставка WATCH у production, follow-up за віхами, поведінка антиспаму на живих даних. Перевіряти: `SELECT * FROM office2_radar_card ORDER BY created_ts DESC`, логи `[radar]`.
- Shadow-позначки `learned_flags` lf-2 (WEEKEND/COST_HEAVY/OFF_HOURS/COUNTER_TREND) у paper; дослідження — `FEATURE_STUDY.md`, `HISTORY_STUDY.md`. Висновок: edge не підтверджено (Brain-replay −0.115 R, старі плани −0.067 R).

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

## 11.10 ~10:40Z — ліміт «3 стопи/добу»
- `GATE_STUDY.md`: на 82 відсічених would-be READY — результат ≈ 0 (A +$19,7, CI [−0,31; +0,40] R), жодне альтернативне правило не підтверджене; лічильник `day_stops` рахує й стопи після TP1/TP2. Ліміт НЕ змінено.
- Повторити `gate-study.yml` (ref=main) після 00:30 UTC 12.10 (архів 11.10) і коли в CONTROL буде ≥30 розв'язаних. Скрипт тепер виводить `actual_delivered` та розрізняє «немає даних після кінця архіву».
- Mini App: Радар → PAPER → картка «Денний ліміт» (стопи, початок/кінець блоку, відсічені, shadow).

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
