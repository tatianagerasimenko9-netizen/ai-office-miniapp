# Архітектура бота

## Стек

- Python 3.12
- asyncio
- python-binance
- python-telegram-bot

## Основний файл

- `C:\Users\Pentagon\Downloads\2scanner_bot_1.py`

## Головні модулі

- `scan_sym()` — базовий ICT/SMC сканер.
- `trade_watcher()` — супровід угоди (TP/SL/trailing).
- `update_macro()` — макроконтекст (BTC/SPX/Gold).
- `detect_pump_dump()` / `scan_pump_dump()` — окремий PUMP/DUMP канал.
- `hourly_report()` / `daily_report()` — звіти.

## Поточний робочий режим (канонічно)

- `ENTRY_CONFIRMATION_MODE=SC_OR_ENTRY`
- `PUMPDUMP_ENABLED=true`
- `PUMPDUMP_SIGNAL_ONLY=false`
- `PUMPDUMP_TRAIL_MODE=ema21`
- `DAILY_REPORT_HOUR=23`
- `TELEGRAM_PLAIN_TEXT_ONLY=true`

## Налаштування проти шуму

- `PUMPDUMP_WATCH_MIN_SCORE=999`
- `SEND_WATCH_MESSAGES=false`
- `SEND_ADAPTIVE_SCAN_NOTICE=false`
- `SEND_ENTRY_WAITING_MSG=false`
- `SEND_ENTRY_PASSED_MSG=false`
