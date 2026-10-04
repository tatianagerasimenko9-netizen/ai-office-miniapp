# READY: фактична карта залежностей (за production-кодом, не за задумом)

Джерела: `office_relay_wizard.py` (сканер `lev`, `_desk_send`, цикл підтвердження), `office_lev_verdict.py`, `office_confluence.py`, `office_desk_card.py`, `office_alert_gate.py`,
`office_indicator_gate.py`, `office_scan_funnel.py`; реальні події з Postgres (`SIGNAL_PLAN`, `THESIS_VERSION`) станом на 2026-10-04 21:20 UTC. Торговий gate не змінювався.

## 1. Схема: як READY утворюється сьогодні
```
СКАНЕР (lev) ── свічки: D1×30, H4×30, H1×30, M15×96, M5×20  (W1×12 лише у _desk_send; МІСЯЦЯ, 3д, 4д немає)
   │
   ▼
[A] ЗОНА СЕТАПУ  (office_confluence.collect_zone_candidates → cluster_zones → evaluate_confluence)
    8 джерел-кандидатів, кластер з ≥2 РІЗНИХ тегів (GRADE_B=2) → «збіги»:
      sc_ote   сильна свічка M15/H1 → її OTE-зона
      ob       останній order block H1
      fib_h4   0,618–0,786 від свінг-діапазону H4 (або H1)
      dw       рівень D (PDH/PDL вчора) і рівень W (PWH/PWL минулого тижня)
      mirror   СЕРЕДИНА вчорашнього діапазону ±0,2 % (назва «дзеркало», фактично середина D1)
      range_edge  край боковика H1
      sweep    знятий пул M15
      bpr      перетин бичачого й ведмежого FVG на H1
    Тут НЕМА: Bulkowski, Wyckoff, регресійного каналу, FVG як самостійної зони, рівнів Герчика з office_levels, структури HTF-тренду.
   │
   ▼
[B] ВЕРДИКТ ЛЕВА  (office_lev_verdict.lev_cycle → finalize_lev)  — SEND / WAIT / WATCHING / SKIP
    SKIP:  ATR-вето (gerchik/t0), немає entry/SL/TP1, RR < 1,5
    WAIT:  SL у пулі ліквідності; індикатор CONTRADICT (див. канал нижче)
    WATCHING: немає HTF-підстав (рядок зони містить H1/H4/D1/W1/HTF/FIB_H4/«рівень D» — це перевірка ТЕКСТУ тегів), немає інвалідації
    + _fun.direction_gate: проти сильного імпульсу лише з підтвердженим CHoCH
    + score у lev-потоці — КОНСТАНТА (score=12, min_score=10): реального балування немає
   │  SEND
   ▼
[C] WATCHING у БД  (prepare_desk_send → mark_live)  — у Telegram нічого
   │
   ▼
[D] ПІДТВЕРДЖЕННЯ НА МОЛОДШОМУ ТФ  (office_confluence.follow_setup → detect_ltf_confirms)
    для H1-сетапу — M15, вікно 40 свічок; ЛЮБЕ непорожнє `confirms` + закриття всередині зони → CONFIRM
    джерела confirms: Bulkowski (office_bulkowski), double/triple (office_patterns), SMC (office_smc), Wyckoff, свічки (office_candles),
                       рівні (office_levels.tags_for), канал (office_regression_channel.tags_for), sfp/engulf/bos/choch
    скасування: таймаут, закриття H1 за SL, злам структури H1 проти сценарію, ціль без входу, маніпуляційне вікно перед сесією (hold)
   │
   ▼
[E] ВОРОТА ПЕРЕД READY  (relay: may_emit_telegram → check_plan → max_entry → find_duplicate)
    may_emit_telegram(CONFIRM): `ltf_confirmed` → «одне LTF-підтвердження» (буквально така причина в коді)
    + геометрія плану, мін. TP1 3 % / RR ≥1,5 (зважений), межа входу max_entry, дубль ідеї, розмір позиції
   │
   ▼
READY → Telegram (#117/#119) + Mini App.   Режим фази (σ) і ринок/календар — лише інформація (картка/Mini App), у рішенні не беруть участі.
```

## 2. Роль кожного блоку (за кодом)
| Блок | Де в коді | Роль у READY | Mandatory? | Вага/бал |
|---|---|---|---|---|
| HTF контекст (D/W) | `collect_zone_candidates` (dw, mirror), `has_htf_grounds` | один із тегів збігів зони; `has_htf_grounds` перевіряє наявність слів H1/H4/D1/W1 у тегах | зона потребує ≥2 різних тегів; HTF-слово — для SEND | ваги немає (кількість різних тегів) |
| HTF структура/тренд (місяць/тиждень/3д/4д) | — | **відсутня**; є лише `structure_break_h1` (скасування) і `direction_gate` (імпульс) | ні | — |
| Рівні (support/resistance/дзеркальні) | `office_levels.zones/tags_for` | лише LTF-підтвердження `level_hold/level_retest/level_false_break`; зона рахується з ≤40 M15 свічок, ≥2 дотики | ні (одне з confirms) | ваги немає |
| Ліквідність/sweep | zone: `sweep` (M15); LTF: `sweep_pool` | тег зони і/або LTF-підтвердження | ні | — |
| SMC/ICT | `office_smc` (sweep_pool, bos, choch, displacement, fvg_retest, ob_retest, breaker_retest, ote) | **лише LTF-підтвердження**; в зоні — тільки ob (H1), bpr, sc_ote | ні | — |
| BOS/CHoCH | LTF `bos/choch`; `structure_break_h1` скасовує | підтвердження і причина скасування | ні | — |
| FVG | zone: лише BPR; LTF: `fvg_retest` | як вище | ні | — |
| Order Block / Breaker | zone: ob (H1); LTF: ob_retest/breaker_retest | як вище | ні | — |
| OTE | zone: sc_ote, fib_h4; LTF: `ote` | як вище | ні | — |
| Bulkowski | LTF `detect_ltf_confirms` (фігури + double/triple) | **лише LTF-підтвердження** | ні | — (формальна відповідність книзі NOT VERIFIED) |
| Wyckoff | LTF `spring/upthrust(+test)` | лише LTF-підтвердження | ні | — |
| Регресійний канал | (1) LTF `channel_edge` (39 свічок M15); (2) `stance_channel` у вердикті Лева | (1) **достатнє саме по собі** підтвердження; (2) задумано як CONFIRM/CONTRADICT, на практиці мертве (див. нижче) | ні | ваги немає |
| LTF-тригер | `follow_setup` | будь-яке одне непорожнє підтвердження + закриття в зоні | **так (одне)** | — |
| RR/ризик/ATR | `finalize_lev`, `office_alert_gate`, `office_atr_policy` | вето: RR<1,5, ATR day_used, SL у пулі, TP1≥3 % | так | пороги, не бал |
| Фаза руху (σ) | `office_phase` (#117) | **лише інформація** (рядок ≥3σ у Telegram) | ні | — |
| Ринок/BTC/календар | `office_market_view` | **лише інформація** | ні | — |

## 3. Відповіді щодо регресійного каналу
1. **Де створюється:** `office_regression_channel.tags_for` (виклик із `detect_ltf_confirms`) → тег `channel_edge`; `stance_channel` (вердикт Лева); живий шар Mini App; докази #119.
2. **Куди передається:** тег → `confirms` → `follow_setup` → `gate.confirm.tags` у знімку READY; stance → `finalize_lev`.
3. **Додає бал?** Ні. Балів у цій частині немає ні для кого: у lev-потоці `score=12/min_score=10` — константи.
4. **Mandatory?** Ні. **Optional confirmation?** Так — рівноправне з усіма іншими тегами.
5. **Може READY не пройти без нього?** Тільки якщо він єдине підтвердження. Структурно так може бути (одне непорожнє `confirms` достатньо; `may_emit_telegram` пише «одне LTF-підтвердження»).
6. **Може слабкому сценарію допомогти пройти?** Так, структурно: `channel_edge` один раз закриває вимогу LTF-підтвердження. **Фактично за 31 READY зі знімком підтвердження:** `channel_edge` є у 7 (23 %), **жодного разу не єдиний** (завжди ≥1 інший тег). Усі 7 — SHORT: EIGEN, SYRUP, DYDX, ONDO, ONE, ZK, SAMSUNG; у SYRUP і ZK лише 2 теги (`level_hold` + `channel_edge`).
7. **Лише текст/evidence?** Ні: тег — повноцінна умова підтвердження, а не підпис.
8. **`stance_channel` (CONFIRM/CONTRADICT, може дати WAIT):** у lev-потоці `regression_channel(h1)` отримує 30 свічок H1 (`fetch_candles(rsym, "1h", 30)`), у `_desk_send` — 48; довжина за замовчуванням 100 → `ok=False` → stance `NOT_CONNECTED / DATA_UNAVAILABLE` (перевірено запуском). **Тобто задумане «канал як контекст за/проти сценарію» у production не працює взагалі.** Робочим залишається лише тег `channel_edge` на 39 свічках M15.
9. **Що ще має виконатись разом із ним:** зона сетапу з ≥2 різних тегів; RR/ATR/ліквідність; закриття M15 у зоні; ворота READY.

## 4. Причинні ланцюги реальних READY (з БД)
**SAMSUNG SHORT (20:33 UTC)** — режим H4 COMPRESSION (ER 0,03; ATR/медіана 0,20), M15 RANGE.
- Зона 204,03–206,42 з 5 тегів: `sc_ote, ob, fib_h4, mirror, range_edge` (H1/H4: OB H1, фібо H4, середина D1, край боковика H1, сильна свічка).
- Очікування (M15): подвійна вершина / ретест FVG / закріплення за рівнем.
- Підтвердження M15 (5 тегів): `double_top, fvg_retest, level_hold, level_retest, channel_edge`.
- RR нетто 3,21; вхід 204,53; межа входу 202,14; SL 206,81. Канал — одне з п'яти підтверджень, не вирішальне.

**DASH SHORT (20:33)** — RANGE.
- Зона 58,60–59,95 з 7 тегів: `sc_ote, ob, fib_h4, mirror, range_edge, sweep, dw` (найсильніша зона з усіх чотирьох). Підтвердження: `level_hold, level_retest` (канала немає).

**LTC SHORT (20:10)** — TRANSITION.
- Зона 71,25–71,54 з **2 тегів** (мінімум): `dw, bpr`. Підтвердження: `flag, level_retest`. Канала немає. Цей приклад показує нижню межу вимог: два теги зони й два LTF-підтвердження.

**JST SHORT (20:23)** — TREND: зона з 3 тегів `sc_ote, ob, range_edge`. **KAITO LONG (20:23)** — RANGE: `sc_ote, ob, mirror`; підтвердження `fvg_retest, engulf`.
- У жодному з цих READY не було: місячного/тижневого/4–3-денного контексту, перевірки HTF-тренду, Bulkowski/Wyckoff/SMC на етапі зони.

## 5. Де фактична архітектура відхиляється від задуму (для обговорення, без змін коду)
1. **Немає ієрархії «місяць → тиждень → 4д → 3д → 1д → 4г → …»:** використовуються лише D/W попередні рівні, H4-фібо, H1 (OB, боковик, BPR), M15. Місяця, 3д, 4д у даних сканера немає.
2. **Назва «дзеркало» = середина вчорашнього діапазону ±0,2 %**, а не дзеркальний рівень, який був опором і став підтримкою (їх Лев бачить у `office_levels.mirror`, але лише у LTF-підтвердженнях, не у зоні).
3. **Рівні (`level_hold/level_retest`) — з ≤40 M15 свічок (≈10 год).** Це не «сильні рівні» старших ТФ. Вони найчастіші тегі READY (22 згадування з 31).
4. **Smart Money/ICT, Bulkowski, Wyckoff беруть участь лише як LTF-підтвердження,** не як причина зони/сценарію. Підтвердження — будь-яке одне.
5. **Бала немає:** у lev-потоці `score` — константа. Усі теги рівноправні; єдиний «фільтр якості» — кількість різних тегів зони (≥2).
6. **Тренду HTF як умови немає:** є лише `direction_gate` проти сильного імпульсу і скасування за зламом структури H1.
7. **`stance_channel` мертвий** (недостатньо свічок), а канал як підтвердження — навпаки, достатнє саме по собі.
8. Усі 7 READY із `channel_edge` — SHORT; без перевірки, чи це збіг, чи систематика (7 з 31).

## 6. Що з цього потрібно рішення, а не просто виправлення
- Чи має `channel_edge` залишатись самостійним LTF-підтвердженням, чи лише додатковим аргументом за вже наявного іншого (твоя вимога «канал — додатково»). Це зміна торгової логіки: **без твого погодження не змінюю**.
- Чи довжину каналу (39 / 95 / 100) визначати дослідженням (train/test, без lookahead), а не «як у Pine» — так, вона визначатиметься дослідженням; жодної автоматичної заміни.
