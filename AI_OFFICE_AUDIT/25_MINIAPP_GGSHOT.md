# 25. Mini App і GGShot (як створити подібне, не скопіювати)

Референс: [GG-Shot Auto-Trading Guide](https://www.ggshot.com/post/gg-shot-auto-trading-guide) (прочитано 2026-09-25).  
Не копіювати продукт. Брати **принцип UX**: складне всередині, прості екрани.

## Що показує GGShot

- Mini App у Telegram: Home, Signals, My Portfolio, трейди OPEN/PENDING/CLOSED.  
- Картка сигналу + **ENTER одним тапом** (після пресета).  
- Пресет: market/limit, частки TP, SL→BE після TP1, розмір від ризику/%.  
- Біржа: Bybit (OAuth) / Hyperliquid (ключ). Бот **не** виводить кошти.  
- Автопілот **після** тапа: ордери живуть на біржі, апку тримати відкритою не треба.  
- **Не** бере всі сигнали сам — користувач обирає картку.  
- Telegram-повідомлення лишаються: сигнал, fill, close.

Це шар **виконання (наш P4)**, не заміна радара.

## Що вже є в нас

`office_mini_app.py`: HTML на `:8790`, `/api/summary`, журнал, примітивний risk heatmap **по журналу**, webhook TradingView. Немає: live BTC-панель, стрічки подій, ENTER, біржі, пресетів, My Positions як intent.

## Як будувати «таке» у AI Office (послідовність)

1. **Спочатку радар і єдиний стан** (P0–P1). Без SIGNAL у state кнопка ENTER безглузда (два боти знову роз’їдуться).  
2. **P3 Mini App екрани** (без біржі):  
   - Home: BTC, режим, рівні, активні EVENT/WATCH.  
   - Signals: картки зі status APPROACH/SWEEP/SIGNAL.  
   - My Positions: лише `/position`.  
   - Statistics: тільки ланцюг з RESULT.  
   - Scanner: watchlist, не 200 альтів.  
   - Push у Telegram = ті самі короткі події, що й апка.  
3. **P4 виконання (пізніше, окреме ТЗ):**  
   - Підключення біржі з **мінімальними** правами (торгівля, без withdraw). Для Тетяни реалістичніше Binance/Bybit API keys у secrets, не копія GGShot OAuth.  
   - Entry Preset: ризик 1% на $1000, RR, SL buffer, BE після TP1.  
   - На картці SIGNAL + BOT ACTION=ACCEPT: кнопка «Розглянути вхід» / ENTER.  
   - Ордери на біржі; апка показує fill/PnL; CLOSE.  
   - Не авто-входити в усі сигнали.

Поки P4: офіс пише картку, Тетяна входить руками (як зараз).

## Чого не робити

- Не ставити auto-trade, доки NO TRADE офісу не блокує сканер.  
- Не переносити Hyperliquid/Bybit гайд один-в-один.  
- Не роздувати Mini App, поки чат ще 17 реплік на SKIP.
