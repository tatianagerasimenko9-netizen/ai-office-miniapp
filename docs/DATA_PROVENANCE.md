# Походження ринкових даних (12.10.2026)

## Висновок
- **Brain v2.1 (сканер і підтвердження READY)** читає свічки напряму з Binance USDⓈ-M Futures (`fapi.binance.com/fapi/v1/klines`), без fallback. При 429/backoff цикл кидає виняток — нового READY немає (спостереження й діагностика лишаються).
- **Супровід (paper, радар, follow-up сигналів, shadow-цикли)** раніше ішов через `fetch_candles`, який при 429 падав на `binance_spot_vision` (Binance Spot) і `bybit_linear`. Production-логи 12.10 10:54–11:02 UTC це підтверджують (`[data] fallback …`, `by_src spot 851/bybit 285`; WS: події 85156, hits 0, seeds 0).
- Корінь: вичерпання ваги fapi (2400/хв на IP, спільний з `binance-scanner-etalon`; піки 2306) + холодний кеш після рестарту; WS-свічки стають використовуваними лише після успішного REST-seed.

## TIA d37a: чому 21:30 у production і 21:15 у replay (доведено)
inval_px = 0.5692. Бар 21:00 UTC: Futures close **0.5690** (< inval_px → скасування о 21:15), Spot close **0.5697** (не нижче → скасування лише після бару 21:15, close 0.5691 → 21:30).
Production тоді рахував на спотових свічках → 21:30; replay на ф'ючерсах → 21:15. Джерело: `scripts/data_provenance_compare.py` (Actions «Data provenance compare»).
На 17 картках статус/час розійшовся у 5 (RUNE, ALGO, ETC, JUP, TIA d37a) між futures і spot.

## Що змінено
- `office_market_data.fetch_candles_futures` — приймає лише свічки з `src=binance_futures`; інакше `{}` + лічильники `decision_ok / decision_rejected_nonfutures / decision_no_data` у `[data] binance` і throttled-лог `[data] рішення: …відхилено`.
- Усі торгові споживачі (paper tick, radar track, HTF/source shadow, `office_signal_track`) переведені на нього.
- READY snapshot містить `data_provenance` (джерело, ринок, ендпоінт, TF, відкриття/закриття останнього закритого бару, момент рішення).
- `office2_radar_card.data_src` — джерело свічок останнього обчислення.
- Ризик-ліміти, LIVE-гейти, ордери — без змін.

## Не підтверджено
- Легасі-монітори relay (`office_relay_wizard.py`) — чи беруть рішення зі спотових свічок: НЕ ПЕРЕВІРЕНО.
- Bybit з GitHub-раннера недоступний (403), Bybit-порівняння не виконано.

## Перші природні READY після змін (12.10, 11:30 UTC): ADA і FIL
- Обидва: джерело `binance_futures` у `snapshot_json.data_provenance`, доставлені (msg 10528/10529), SL-віха о 11:41 (ADA) і 11:47 (FIL), `SIGNAL_RESULT=STOP`. Дві ідеї з двох зупинені за ~10–16 хв — це факт вибірки з 2 угод, не висновок про стратегію.
- Дефект журналу: paper FIL став `MISSED` («NO_DATA: немає 1m-свічок після доставки»), хоча супровід показав SL. Причина — гонка: paper-tick спрацював до появи першої 1m-свічки після доставки, і рішення зафіксувалось остаточно.
- Виправлення: відкладення рішення до 10 хв після доставки (`_no_bars_yet`) і `repair_no_bars` з записом `PAPER_CORRECTION` у журнал подій (старі записи не видаляються).
- Після рестарту c7ac8ba, 45 хв спостереження: 0 помилок fapi, 0 × 429, `by_src` лише `binance_futures`, `decision_ok` 17620, відхилень немає, пік заголовка ваги 1435 з 2400.
