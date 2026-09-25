# 10. Ринковий контекст (модулі даних)

| Модуль | Задум | У коді | Реально в чаті |
|--------|-------|--------|----------------|
| PRICE / structure | Свічки, BOS | REST klines; `get_market_structure` 1h | Так, коли LLM кличе tools |
| LIQUIDITY / sweep | ICT | `fetch_liquidity_sweep` 1h 3 свічки | Лише в момент аналізу |
| LIQUIDATION HEATMAP | Карта ліквідацій | **Proxy** 24h high/low ×1.002; опційно `forceOrders` | Текст «зверху/знизу» без dens map |
| OI | Відкритий інтерес | Реальний endpoint | Макс/Лев інколи |
| FUNDING | Funding | `premiumIndex` | Так |
| VOLUME | Обсяг | ticker 24h для сканера | Сканер топ-30 |
| WHALE | Кити | Стакан ≥500k USDT, не on-chain | «кит BID/ASK» |
| NEWS | Новини | NewsAPI, деградація | Не головний потік |
| GEX / OPTIONS | Опціони | **ABSENT** | Немає |
| SESSION | Сесії | Рівні + банери | Банери є, event немає |
| PATTERNS | Bulkowski | Текст Марічки | Лекції, не detector |
| WYCKOFF / SMC / ICT | Методологія | Промпти + грубі tools | Текст |
| HISTORICAL STATS | Edge по історії сетапів | Журнал без MFE/MAE, без backtest | Мета-звіт LLM |

Пріоритетів «не всі модулі щоразу» **немає**: `full_auto_analysis` тягне пачку REST **завжди**; LLM може ще до 5 tools.

У cloud VM Binance часто порожній — у чаті є «ціна None» (AKE 22:18 19.09). Це **окремий failure mode**, не методологія.
