# MINI_APP_SPEC.md

Натхнення UX: GGShot (екрани, картки, пресети пізніше). Власний дизайн.  
Не малювати фейкові wr. Backend спочатку.

## Що вже є (ПІДТВЕРДЖЕНО)

`office_mini_app.py`: `/`, `/api/summary`, `/api/review_draft`, `POST /api/webhook/tradingview`.  
Дані: journal KPI, decisions, heatmap по **журналу**, TV overlay.  
Немає: event tape, MarketState, My Positions як intent, ENTER, біржа.

## Екрани MVP (етап 5)

| Екран | Показ | Джерело |
|-------|-------|---------|
| Home | BTC ціна, regime, сесія, активні EVENT/WATCH, 3 рядки бриф | MarketState API |
| Scanner | монети, фільтр scalp/intraday/swing, статус confirm | той самий стан |
| Signals | картка side, entry, sl, tp, rr, px, ts, status | signals registry |
| My Positions | лише confirmed MY_POSITION | journal + intent flag |
| Statistics | період, сетап, сесія, монета, **джерело** office/scanner/manual/paper | registry; порожньо = чесно |
| Notifications | ті самі 👀⚠️🚨🟢📈 | Telegram + in-app |

## API-контракт MVP (проєкт)

```
GET /api/state?symbol=BTCUSDT
GET /api/events?since=
GET /api/signals?status=
GET /api/positions?intent=MY_POSITION
GET /api/stats?from=&to=&source=
POST /api/watch  {symbol, low, high, kind}
POST /api/intent {review|position, payload}
```

Auth: існуюча модель Mini App / Telegram initData — **НЕ ПЕРЕВІРЕНО** чи вже є (зараз локальний bind без TG WebApp auth). Додати на етапі 5.

## Права

Тетяна = owner. Боти не пишуть позицію без intent. Немає withdraw.

## Не в MVP

Автоордер, Bybit OAuth, 4 TP GGShot, Hyperliquid. Це етап 6 + окремий дозвіл.

## Як «створити таке»

1. Стан і радар (етапи 1–2).  
2. API вище.  
3. Замінити HTML summary на вкладки.  
4. Пуші = ті самі event id що в апці.  
5. Потім пресет + ENTER.

Критерій MVP: Home показує той самий BTC watch, що й чат, без роз’їзду.
