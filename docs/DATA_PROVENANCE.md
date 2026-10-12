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
