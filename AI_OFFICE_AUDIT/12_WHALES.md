# 12. Whales

## Що є (CONFIRMED)

`fetch_order_book_walls`: глибина стакана Binance Futures, стіни ≥ **500_000 USDT**. Поля `whale_bids` / `whale_asks`. Edge: +10 якщо стіна з боку ймовірного напрямку.

Це **стакан**, не переказ BTC на біржу.

## Чого немає

On-chain whale / exchange inflow-outflow. Формат «🐋 BTC — великий переказ» **ABSENT**.

## Чат

Марічка іноді згадує «кит-продавець $957К» — це інтерпретація стакана/tools, не окремий event bus.
