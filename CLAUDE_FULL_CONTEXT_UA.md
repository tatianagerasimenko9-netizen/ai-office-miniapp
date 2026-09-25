# Контекст для Claude — повний підсумок роботи AI Office (до 25.09.2026 ~21:08 UTC)

**Призначення цього файлу:** єдиний бриф для Claude / наступного агента. Це не runbook і не MASTER-CHECKLIST. Тут зібрано, що Тетяна і Cursor **визначили, зробили, обговорили, що Live, що лише в коді, що заборонено, що ще не зроблено**. Читай спочатку це, потім код.

**Людина:** Тетяна (Tatiana Duziak / Duzyak). Торгує близько $1000 — сума психологічно велика. Віктор підтримує; Лев — стратег.  
**Продукт:** живий AI-офіс (не бот з правилами): Telegram Worker + Mini App.  
**Репо:** `tatianagerasimenko9-netizen/ai-office-miniapp`.  
**Дата зрізу:** 25 вересня 2026, після створення PR №36 (не злитий).

---

## 0. Як читати статуси (критично)

| Шар | Що це означає |
|-----|----------------|
| **main / Live Worker+Mini App** | Зараз на Render коміт **`714bc7a`** = merge **PR №35**. Фільтр стрічки 3% Live. Контур review PR №36 **ще не на Worker**. |
| **PR №36 (draft)** | Гілка `cursor/office-lev-full-contour-5134` HEAD **`1f7f27c`**. Виправлення якості розбору зовнішнього сигналу. **Не merge, не deploy**, поки Тетяна окремо не дасть дозвіл. |
| **Offline PASS** | Скрипти `scripts/test_*.py`. **Не** Live PASS і **не** доказ прибутковості. |
| **Live PASS стрічки ≥3%** | **Ще не підтверджений.** Бачили, що INSIDE більше не в чат. Не бачили нової торгової картки ≥3% після 23:46. |

**Старі Telegram-повідомлення до деплою `714bc7a` не є доказом нової стрічки.**  
**Картки бота ПРЕМІУМ і CONFIRMED у коді ≠ ордер і ≠ авторозсилка.**

---

## 1. Залізні правила (Тетяна повторила багато разів)

**Заборонено без явної команди «МОЖНА ВНОСИТИ ЗМІНИ» / окремого ТЗ:**
- змінювати торгову логіку «на око»;
- змінювати CONFIG: **ATR 80 (Герчик/вхід по тренду)** і **ATR 90 (T0 SIGNAL)**, **Edge 85**, MIN_RR 1.5;
- рефакторити «заради краси»;
- додавати нові фічі поза ТЗ;
- **реальні ордери**, зміна реальних позицій, auto-merge, деплой Worker/Mini App, production secrets;
- підміна OHLCV / вигаданий WR/PnL;
- вважати heatmap CoinGlass/Hyblock підключеною (її **немає**);
- трактувати T7 `btcusdt@forceOrder` як карту майбутніх ліквідацій;
- трактувати `NO_TRADE 100%` як імовірність, що угода зіллється або ціна не рухатиметься;
- трактувати ATR day_used 120.7% як «бак порожній / ціна фізично не може йти»;
- трактувати нову D1 свічку як авто-вхід або reset ATR(14);
- вважати рейтинг бота ПРЕМІУМ 16/20 дозволом входу;
- `/review` = `/position`; paper / WATCHING / legacy OPEN = реальна позиція Тетяни.

**Дозволено за ТЗ:** реалізація узгодженого плану; баги з root cause; один інтегрований PR; чекати окремий дозвіл на merge/deploy.

**Філософія:** живий офіс (портрет агента + дані + function calling). Не хардкод відповідей, не списки заборонених слів, не «максимум N речень». Ініціативність: агенти пишуть першими по сетапах, не чекають команду. Формат ініціативи — зрозуміла картка, не журнал розрахунків.

Тетяна більше **не хоче** дробити роботу на нескінченні дрібні PR і роль «тестувальниці щовечора». Далі — **один цілісний план**, критерії готовності, **один звіт**. Cursor не повинен питати наступну дрібну задачу після кожної знахідки.

---

## 2. Архітектура (що де крутиться)

| Сервіс | Старт | Роль |
|--------|--------|------|
| **Mini App** | `python -u office_mini_app.py` | Web `https://ai-office-miniapp.onrender.com`, `/api/summary`. **Не** шле Лева в Telegram. |
| **Telegram Worker** | `python -u office_multibot_bootstrap.py` → `office_relay_wizard.py` | Релей, сканер, стрічка Лева, розбір сигналів. **Окремий** Render Background Worker. |
| БД | спільна Postgres (`DATABASE_URL`) | Fingerprint має збігатися (п.17). Live 25.09: Worker підтвердив збіг із Mini App. |

Локально в Cloud: `python3`. SQLite `office_bridge.db` якщо немає `DATABASE_URL`. Binance/Anthropic у VM часто порожні → graceful degrade, не вигадувати ринок.

**Auto-Deploy** на Render увімкнений (принаймні Mini App підхопив `714bc7a` сам). Worker теж опинився на `714bc7a` (підтверджено логами bootstrap 25.09). Повторно деплоїти Mini App «для перевірки Worker» **не треба**.

Cursor **не має** `RENDER_API_KEY`: список сервісів Dashboard з агента не читається (стіна логіну). Ідентифікація Worker: Start Command з `office_multibot_bootstrap.py` / `office_relay_wizard.py`, не `office_mini_app.py`.

---

## 3. Хронологія від початку дуги до цієї хвилини

Нижче — дуга, яку Тетяна і Cursor пройшли в цій робочій нитці (включно з попереднім контекстом сесії, який був стиснутий). Дати — 25.09.2026, якщо не зазначено інше.

### 3.1 База офісу до T8 (уже було Live раніше)

- Інфраструктура MASTER 1–21: репо, Mini App, Worker, спільна БД, гілки чату, runbook.
- **T0** ZONE_REACHED + probe-guard. ATR T0-блок SIGNAL при day_used > **90%**; зона/пошук тривають.
- **T1** `/review` без позиції; `/position` лише з entry+SL+status.
- **T3** дедуп нових WATCHING після SKIP; активні зони не глушити. BBBUSDT колись помилково SKIP як BUSD — фікс exact `STABLE_BASES`.
- **T4** `market_state` upsert/get.
- **T5** `bot_action=BLOCKED` зупиняє ENTER зі сканера.
- **T6** радар рівнів, sweep, картка без позиції. Символи T6 радара заморожені як `("BTCUSDT",)` — повний ринок іде через **market scout**, не через цей кортеж.
- **T7** фактичні ліквідації `btcusdt@forceOrder`. `idle_cold` / `connecting` ≠ «ліквідацій не було». Не heatmap. Не ENTER.
- Evening homework/debrief: без фейкових 0% WR і без OPEN Desk ENTER як позицій Тетяни.
- Paper ізольований від `/position` і `trade_journal`.
- `scanner_enter_opens_position` = False; `CREATES_ENTER` = False.

### 3.2 Office 2.0 / PR №33 (злитий у main раніше)

Парсинг зон, єдина ATR-політика 80 vs 90, сесійний радар, paper, Mini App-шматки.  
**PENGU** як регресія: бот LONG, ATR day_used **120.7%** = денний хід на **+20.7% понад ATR**, не «більш ніж удвічі». Edge нижче 85. ПРЕМІУМ ≠ вхід.

Семантика, яку Тетяна вимагала зафіксувати в коді (`office_atr_policy.py`):
- 80% — вето **конкретного входу по тренду** (Герчик/Лев/Probability). Пошук інших сценаріїв триває.
- 90% — T0 блок SIGNAL; WATCHING/ZONE_REACHED не вбивати оптом.
- `NO_TRADE 100%` = спрацював hard gate, не прогноз ціни.
- Нова D1 лише **перераховує** `day_used = day_range/ATR`. ATR(14) не reset. D1 ≠ сигнал.

### 3.3 T8 «живий контур» — PR №34 (злитий)

Коміт merge main: **`2149e9c`**. Тетяна явно дозволила merge, **без деплою від Cursor** (Worker потім усе одно опинився на цьому SHA через Auto-Deploy / ручний деплой поза агентом).

Що увійшло в T8 на main (до фільтра стрічки):
- `office_external_signal.py` — зберегти оригінал бота; вердикти ПІДТВЕРДЖЕНО / УМОВНО / КОРЕКЦІЯ / ВІДХИЛЕНО; не ордер.
- `office_market_scout.py` — легкий скрін **усіх** ліквідних USDT-перпів; deep до **24** символів; user symbols окремо; BTC/XAU = контекст, не копія напряму.
- `office_range_radar.py` — боковик, INSIDE ≠ спам-картка (після фільтра).
- `office_level_scalp.py` — M1/M5 scalp vs M15/H1; `nearest_target` = найближчий рівень, не дальній TP2; комісія 0.0004, slippage 0.0005.
- `office_lifecycle.py` — WATCHING → ZONE_REACHED → CONFIRMED | INVALIDATED | EXPIRED. CONFIRMED ≠ позиція.
- `office_skip_plan.py` / `office_trader_plan.py` — після SKIP не фінал «мовчи»; один `case_key` на картку бота; альтернативи лише зі свічок, не з чату.
- `office_t7_health.py` — idle_cold / connecting / disconnected.
- `office_telegram_filter.py` з’явився пізніше (PR35).

Cursor **не мав** деплоїти Worker після №34. Live після merge показав **спам Лева**: BTC/XAU/DEXE/SKHYNIX/SPCX RANGE INSIDE + KAITO/AKE/VELVET CONFIRMED з купою float-рівнів і `TP2 None`. Тетяна: «цим неможливо торгувати».

### 3.4 T8 Telegram Opportunity Filter — PR №35 (злитий, Live)

Вимога Тетяни: Лев може аналізувати сотні монет; **Telegram ≠ журнал розрахунків**.  
3% рахуються до **найближчої обґрунтованої цілі (TP1)**, не до далекого TP2 «для красивого PnL».  
CONFIRMED ≠ авто-send. Скальп &lt;3% лишається у **внутрішньому** WATCHING/CONFIRMED.

Реалізація:
- `MIN_ALERT_MOVE_PCT = 3.0` — фільтр **стрічки**, не ATR/Edge.
- `alert_decision` / `level_book_to_alert` / `range_result_to_alert`.
- KAITO/AKE/VELVET з live-прикладів відсіюються бо рух до TP1 ~0.7–1%.
- Фінальна перевірка перед merge: chase після range **не** робить `continue` (інакше губляться level books); `quote_stale` / `quote_asof` перед алертом.

Merge PR №35 у main: **`714bc7aefc8eebe427a9ab47342b247aa836a933`** (25.09.2026 20:46Z).  
Спочатку Cursor злив код, але **не зміг** підтвердити Worker (логи Mini App ≠ Worker).  
Потім Тетяна підтвердила **обидва** сервіси на `714bc7a`:
- Mini App: `python office_mini_app.py`, `/api/summary` 200.
- Worker: `office_multibot_bootstrap.py`, релей, сканер.

**Перший Live-результат фільтра (логи Worker, не чат):**
- Screened **288** інструментів, deep **24**.
- BTC, XAU, DEXE, SKHYNIX, SPCX → внутрішній `RANGE_WATCHING`, у логу **INSIDE (not telegram)**.
- База: fingerprint Worker = Mini App.

**Не плутати з багом деплою:** forceOrder у `connecting` (дані ліквідацій не свіжі — не використовувати як підтвердження входу); `monitor_news` timeout, fallback на Telethon. Релей живий.

**Повний Live PASS фільтра 3% на торговій картці — НІ.** У фрагменті не було сетапа, який пройшов або не пройшов потенціал до TP1 у чат.

### 3.5 Live PENGU #17 о 23:53 — інша проблема, не фільтр 3%

Тетяна переслала картку бота (сигнал **23:09**, пересилка **23:53**, +44 хв). Ціна вже **0.010111** vs entry бота **0.010273**. Edge **65/100** (поріг 85). ATR day_used **120.7%**.

Лев відповів у старому форматі:
```
🦁 ПРОПУСК · PENGUUSDT
Причина: ATR використано на 120.7% — денний бак повністю порожній, запасу ходу нуль.
… Probability Engine каже NO_TRADE 100%.
Чекаю зону: 0.009726–0.009800 (Азійський ренж + добір бота)
Умова входу: нова денна свічка + day_used < 40% + BOS на M15 …
```

**Що правильно:** не копіювати бота (Edge 65, ATR-правило).  
**Що неправильно (чотири пункти Тетяни):**
1. Не сказав насамперед, що **первинний сигнал застарів**.
2. ATR ≠ бак пального / «хід неможливий» — це **ризик-правило**.
3. NO_TRADE 100% ≠ 100% ймовірність збитку — це hard gate.
4. Зона 0.009726–0.009800 не обґрунтована (добір бота **0.010139**). «Нова D1 + day_used&lt;40%» — не план.

**Висновок Тетяни:** фільтр PR №35 **не** виправляє якість відповіді на пересланий сигнал. З цього повідомлення **не** випливає, що 3% зламаний. PENGU **не** є підтвердженим новим входом. **Не відкривати** ні стару картку бота, ні зону Лева без нового аналізу. Пороги ATR/Edge **не чіпати**.

### 3.6 Єдине комплексне ТЗ на 16 кроків → PR №36 (не злитий)

Тетяна явно: один цикл аудит → фікс → тести → **один PR** → один звіт. Не merge/deploy/угоди.

Зроблено в PR №36 (`1f7f27c`):
- Root cause: review **до** ринку; після картки review релей **падав у LLM** `office_handle_signal` (формат «Чекаю зону»).
- `gather_external_market` спочатку (ціна, ATR, Edge, asof).
- Час картки бота `🕐 23:09 25.09.2026` → `source_at` (Europe/Kyiv → UTC). Скальп stale ≈ 15 хв; 44 хв = застарів.
- Одна картка review: статус / правило / що змінилось / **ЗАРАЗ УГОДИ НЕМАЄ**.
- Якщо є symbol+direction — **return**, без LLM-ПРОПУСК.
- ATR/NO_TRADE формулювання як правило, не бак.
- `(50%)` на рядку входу більше не парситься як ціна 50.
- `scripts/test_t8_contour_review.py` + повна офлайн-регресія T0–T8/PR35.

**PR №36 не на Worker.** Поки він не злитий і не задеплоєний, Live Лев на пересланих сигналах може ще говорити по-старому.

---

## 4. Що Live зараз (Worker+Mini App = `714bc7a`)

Працює:
- Весь T0–T8 контур аналізу (scout, range, levels, lifecycle, skip_plan у коді).
- Фільтр Telegram ≥3% до TP1 + RR після витрат; INSIDE/голий WATCHING не в чат.
- Спільна БД Mini App ↔ Worker.
- Сканер ринку (288 / 24 у логах 25.09).

Не доведено Live:
- Перша **зрозуміла** картка можливості ≥3% у чаті після 23:46.
- Якість **повторного** розбору зовнішнього сигналу (це PR36).

Не використовувати як live-підтвердження входу: forceOrder поки connecting; новини після timeout.

---

## 5. Що в коді, але не Live (PR №36)

Гілка `cursor/office-lev-full-contour-5134`.  
Файли: `office_external_signal.py`, `office_trader_plan.py`, `office_relay_wizard.py` (ранній return), `office_level_scalp.py` (clock + strip %), `office_atr_policy.py` (plain), `office_bridge.py` (LEV_RULE ПРОПУСК), `office_skip_plan.py`, тести.

Чекати **окремий** дозвіл Тетяни на merge №36 і деплой Worker (Mini App уже на 35; після merge 36 Auto-Deploy може підхопити обидва — не деплоїти Mini App «другий раз» без потреби, але Worker має бути саме новий SHA).

---

## 6. Що свідомо НЕ зроблено / OPEN

| Тема | Статус |
|------|--------|
| T2 Назар fail-closed | НЕ ПОЧАТО (старий прогрес Mini App) |
| Mini App Home T7 зі state | у старому прогрес-файлі ще «не почато»; Mini App Live як web, це інший шар |
| CoinGlass / Hyblock liquidation heatmap | OPEN, немає інтеграції. Не називати підключеною |
| Прогнозна карта ліквідацій | заборонена підміна forceOrder |
| Live PASS картки ≥3% у Telegram | чекаємо перше нове повідомлення Лева після 23:46 на `714bc7a` |
| Merge/deploy PR №36 | не дозволено на момент цього файлу |
| Реальні угоди | заборонені |
| Зміна ATR 80/90, Edge 85 | заборонена без бектесту і явної команди |
| Окремий режим scalp-алертів &lt;3% у Telegram | не вмикати, поки Тетяна явно не попросить |
| Вигадана статистика / look-ahead свічки | заборонено; немає OHLCV → `DATA_UNAVAILABLE` |

---

## 7. Ключові модулі (карта для коду)

| Файл | Навіщо |
|------|--------|
| `office_multibot_bootstrap.py` | старт Worker |
| `office_relay_wizard.py` | Telegram, scout loop, external review, **не** деплоїти логіку ордерів |
| `office_bridge.py` | desk, LEV_RULE, journal, !ask |
| `office_telegram_filter.py` | 3% стрічка, freshness quote |
| `office_market_scout.py` | увесь ф’ючерсний скрін |
| `office_range_radar.py` / `office_level_scalp.py` | боковик / рівні |
| `office_external_signal.py` | ingest+review бота |
| `office_trader_plan.py` / `office_skip_plan.py` | картка після SKIP / review |
| `office_atr_policy.py` | 80 vs 90, NO_TRADE=правило |
| `office_lifecycle.py` | стани сетапу |
| `office_btc_liquidations.py` + `office_t7_health.py` | фактичні forceOrder |
| `office_review_position.py` | review ≠ position |
| `office_watching_dedup.py` | T3 |
| `office_paper_trading.py` | папір окремо |
| `scripts/test_t8_*.py` | офлайн контур T8+PR35+PENGU |

Комісії скальпу = T6/T8: 0.0004 / 0.0005. MIN_RR 1.5.

---

## 8. Регресійні приклади, які не можна зламати

1. **PENGU #17** — повтор 23:09 vs 23:53; Edge 65; ATR 120.7% = +20.7% над ATR; зона 0.009726–0.009800 **не** з чату; не бак; не D1-вхід; один `case_key`; не ордер.
2. **KAITO / AKE / VELVET** — CONFIRMED всередині, **не** в основну стрічку (&lt;3% до TP1).
3. Картка TP1=1% і TP2=5% — **не** натягувати 3% через TP2.
4. RANGE INSIDE — не Telegram.
5. Stale quote / chase — не алерт, аналіз не стирати.
6. Після range-chase — level books далі.
7. `/review` не створює `/position`.
8. forceOrder idle/connecting — не «ринку немає ліквідацій».
9. Один source/case — кілька **версій** review, не друга незалежна угода.

---

## 9. Приклади карток (офлайн, як має бути після №36)

**Стрічка (можливість ≥3%)** — одна коротка картка: symbol, напрям, ТФ, сетап, чому, entry/SL/TP1, потенціал до TP1 (не чистий PnL), net RR, quote asof, invalidation, «не ордер / лише /position». Без dump рівнів, без `None`, без сирих float.

**Відсів &lt;3%** — тиша в чаті, status CONFIRMED/WATCHING живе всередині.

**Повторний external review** — спочатку «первинний застарів/відхилений»; причина як правило; що змінилось (версія); ЗАРАЗ УГОДИ НЕМАЄ, якщо немає підтвердженої альтернативи на свічках. Не два суперечливі LONG/SHORT wait. Не «Чекаю зону» з азійського ренджа бота.

---

## 10. План / наступні рішення Тетяни (Cursor сам не робить)

1. **Не merge №36**, поки вона не напише окрему команду merge (як було з №34/№35).
2. Після дозволу: злити №36 → переконатися, що Worker SHA = новий main (не логи Mini App).
3. Live-перевірка стрічки: перше нове повідомлення Лева після деплою — чи це одна картка ≥3%.
4. Live-перевірка review: переслати застарілий бот ще раз — чи каже «застарів» і «угоди немає», без бака і без вигаданої зони.
5. Окремо, якщо попросить: heatmap (нове джерело), T2 Назар, Mini App Home, scalp-стрічка &lt;3% як **окремий режим**.
6. Реальні угоди — тільки після явного «відкривай» / `/position`. Зараз — ні.

---

## 11. Тон спілкування з Тетяною

- Українською, по суті, як старший розробник офісу.
- Формат правки: Було / Стало / Чому безпечно.
- Не обіцяти прибуток. Не продавати offline PASS як Live.
- Не дробити на 15 мікро-PR.
- Якщо Live-даних немає — чесно `DATA_UNAVAILABLE` / «не підтверджено», не вигадувати.

---

## 12. Короткий SHA-лист

| Що | SHA |
|----|-----|
| main / Live зараз | `714bc7aefc8eebe427a9ab47342b247aa836a933` (PR35) |
| Попередній main (T8 без фільтра стрічки) | `2149e9c` (PR34) |
| PR36 HEAD (не злитий) | `1f7f27c777518efe2a404a4847a9a89440a1688f` |
| PR35 | https://github.com/tatianagerasimenko9-netizen/ai-office-miniapp/pull/35 MERGED |
| PR36 | https://github.com/tatianagerasimenko9-netizen/ai-office-miniapp/pull/36 DRAFT, чекає рішення |

Кінець брифа. Далі дивись актуальний код гілки, з якої працюєш, і не відкочуй пороги ATR/Edge.
