# Карта системи за кодом (гілка `claude/eager-pascal-t9e1ac`)

Складено читанням коду 2026-09-28/29, не зі старих звітів. Кожен рядок відповідає файлу/функції, які можна відкрити.
Позначка **[знахідка]** — розбіжність або дублювання, яке важливо знати; **[виправлено]** — виправлено в PR #69.

## 1. Шлях даних
```
Binance USD-M REST ─► office_market_data.fetch_candles / fetch_*        (Worker і Web окремо)
        │
        ├─► Worker: proactive_market_scan (щогодини, Kill Zone) ─┐
        ├─► Worker: monitor_trade_radar (радар/Лев)              ├─► lev_cycle (office_lev_verdict)
        └─► Worker: monitor_active_signals (зони, TTL, підтвердження)         │
                                                                    ┌─────────┘
   feed gate (office_feed_quality) → Risk Officer shadow/enforce (office_risk_context)
        → журнал тези (office_thesis_journal → office_events THESIS_VERSION)
        → prepare_desk_send / _desk_send → signal_upsert(office_signals)
        → send_proactive → Telegram (журнал доставки + ланцюжок відповідей)
   Web (office_mini_app.py): читає ту саму БД → /api/v2/* → office_web/mini_v2.html
```

## 2. Етапи: джерело, вхід у коді, власник стану, поведінка після рестарту
| Етап | Точка входу | Власник стану | Формат | Після рестарту |
|---|---|---|---|---|
| Свічки | `office_market_data.fetch_candles` | немає (на вимогу) | list[dict ts/open/high/low/close/volume]; помилка → `{}`/`[]` | не потрібно |
| Сканер | `proactive_market_scan` (`office_relay_wizard.py`) | `market_state` (БД) | кандидат + LLM-репліки | цикл 1 год; поза Kill Zone мовчить |
| Радар/Лев | `monitor_trade_radar` → `lev_cycle` | `office_confluence._LIVE` (пам’ять) + `office_signals` | dict рішення (`action`, `send`, `entry/sl/tp1`, `draft`) | `hydrate_live_from_db` і `hydrate_alert_gate_from_db` на старті |
| Перевірки | `gate_send_on_fresh_data`, `apply_risk_officer` | журнал `office_events` | `feed_check`, `risk_review` | без стану (дедуп у пам’яті обмежений) |
| Сценарій | `signal_upsert` | `office_signals` (БД) | рядок + `analysis_note` (теги `origin=… tf=… basis=… scenario_id=…`) | джерело істини |
| Зона/підтвердження | `monitor_active_signals` + `apply_setup_event` | `office_alert_gate._LIVE` (пам’ять) ↔ статус у БД | стани FOUND/WATCHING/ZONE_REACHED/CONFIRMATION_PENDING/CONFIRMED/CANCELLED/INVALIDATED/EXPIRED | hydrate із БД |
| Mini App | `/api/v2/*` (`office_mini_v2.py`) | лише читає БД | JSON, ціни через `office_price_format` | без стану |
| Telegram | `send_proactive` | `office_telegram_delivery` + `office_telegram_scenario_thread` (за прапорцем) | PENDING/DELIVERED/UNCERTAIN; корінь ланцюжка | стан у БД; `PENDING`/`UNCERTAIN` не повторюються автоматично |
| Журнал | `log_event` | `office_events` | `event_type`, `signal_id`, `payload_json` | append-only |
| Аудит | `audit_payload` | `office_events` | лічильники записів | читає БД |

## 3. Ідентифікатор сценарію
- Канонічний: `setup_key` = `SYMBOL|DIR|lo|hi` (6 значущих цифр) + `scenario_id` у `analysis_note`; збіг зони визначає `find_canonical_scenario` (символ, напрям, ТФ, ринкова основа, перекриття зон ≥ 0.9). Дрейф зони не створює новий сценарій. Той самий ID використовують: рядок БД (`signal_id`), Telegram (`canonical_id`), кнопка Mini App, журнал тези, Risk-журнал.
- **[знахідка]** Не всі рядки `office_signals` канонічні: інші шляхи пишуть власні ID (`watch-edge-…`, `radar-watch-…`, `lev-watch-…`, `watch-sweep-…`, `watch-acc-…`, `manual-…`, `proactive-…`). Вони показуються в Mini App, але ланцюжок Telegram і теза прив’язуються лише до подій, що несуть `canonical_id`.

## 4. Статуси
- У БД: `WATCHING`, `PIERCE_WATCHING`, `RANGE_WATCHING`, `ACTIVE`, `CONFIRMED`, `HIT_ENTRY`, `HIT_TP1`, `HIT_TP2`, `HIT_SL`, `CANCELLED`, `INVALIDATED`, `EXPIRED`.
- **[виправлено]** Mini App не знав `PIERCE_WATCHING`/`RANGE_WATCHING`/`INVALIDATED`; тепер знає, а невідомий статус показується як «Невідомий стан», не як архів і не як план.
- **[знахідка]** Дві машини станів: `office_lifecycle.next_lifecycle_state` (її тестує історичний T8) і `office_alert_gate.apply_setup_event` (її використовує live). T8 не доводить коректність live-переходів. Не зливав, бо семантика різна; потрібне окреме рішення власниці/рев’юера.
- TTL: `office_lifecycle.WATCHING_EXPIRE_SEC` (4 год) раніше застосовувався лише в T8; ACTIVE у live має жорстко зашитий 4-годинний ліміт у `monitor_active_signals`. **[виправлено]** Mini App позначає WATCHING понад TTL; закриття в БД — за прапорцем `OFFICE_WATCHING_TTL_EXPIRE`.

## 5. Дублювання однієї логіки
| Логіка | Реалізацій | Стан |
|---|---|---|
| Формат цін | було: `office_price_format`, `_fmt_level` (:.4f/:.6f), SMC-описи (:.4f), `:g` у сценарних текстах | **[виправлено]** усе відображення через `format_px`/`format_level_span`; ідентифікатори (`setup_key`, fingerprint) навмисно лишилися `:.6g`/`:.8f` |
| Межі сесій | 1) `SESSION_WINDOWS_UTC` (фіксовані, T8/paper), 2) `DESK_SESSIONS` (DST), 3) Kill Zone у `proactive_market_scan` (фіксовані хвилини UTC 08:00–11:00 і 13:00–16:00), 4) Азія Київ 03:00–07:00 у `office_topdown` | **[виправлено частково]** Session Desk і годинник Mini App беруть одну таблицю `DESK_SESSIONS`. **[знахідка]** пп. 1, 3, 4 лишаються (різна мета; п. 3 не враховує DST) |
| Створення ACTIVE | `lev_cycle` та два legacy-шляхи з LLM-тексту (`proactive`, `manual`) | **[виправлено]** legacy без SEND Лева зберігає лише WATCHING (`OFFICE_LEGACY_ACTIVE_REQUIRES_LEV`) |
| Дозвіл на Telegram | `gate_outbound_telegram` (один) | без змін |
| Дедуплікація | пам’ять `office_telegram_policy` + журнал доставки + T3 `office_watching_dedup` | різні шари, не суперечать; журнал — єдине збережене джерело |

## 6. Залежності від зовнішнього
Binance USD-M REST/WS (публічно), Telegram Bot API/Telethon, Anthropic (опційно), FMP календар (ключ, опційно), Yahoo/Stooq (макро-контекст). Детально — `docs/pr69-data-sources-audit.md`.
Render (web, worker, Postgres, диск `/var/data`) у сесії розробки не перевірявся.
