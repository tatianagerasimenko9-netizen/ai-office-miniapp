# 13. Ліквідації / heatmap

## Proxy (основний шлях)

`fetch_liquidations_proxy`:  
`liq_zone_above = high_24h * 1.002`, `liq_zone_below = low_24h * 0.998`, плюс `current_price`.

Це **не** heatmap. Цифри «зони ліквідності» в `full_auto_analysis` часто саме ці два числа.

## Реальні force orders

`fetch_recent_liquidations` / tool `get_liquidations_real`. LLM **може** викликати, не зобов’язаний. Окремого циклу «ліквідаційна стіна наблизилась» немає.

## Mini App heatmap

`build_risk_heatmap` у `office_mini_app.py` — **по журналу угод** (winrate по символах), не по ліквідаціях ринку.

## Висновок

Вимога «верхня зона 86525–86610 з відстанню і силою» **не реалізована**. Зараз — сурогат 24h high/low.
