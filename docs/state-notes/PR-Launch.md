# Final launch (2026-09-30)

- Карта ліквідацій: `office_liq_map.py` — фактичні події Binance (`!forceOrder@arr`, `/market/stream`) + власна оцінка з OI × плечі (5/10/25/50/100×, MMR 0,5%). Шар «ліквідації» у Mini App (`/api/v2/liqmap`, за замовчуванням вимкнений). Платних джерел немає.
- Стакан BTC/ETH: `OFFICE_DEPTH_ENABLED=auto` — вмикається сам, коли 24 год поспіль ф'ючерсні свічки ≥95% і 0×429 (`office_data_stability.py`, подія DATA_STABILITY). Свічки мають пріоритет.
- Календар: основна адреса + дзеркало `cdn-nfs.faireconomy.media`; `diagnose()`.
- Replay журналу: LONGXIA, ENA — вхід шукається в ±2 год від часу запису (`office_replay.run_journal`).
- Одноразова діагностика `office_launch_once.py` пише підсумок у `office_events` (LAUNCH_DIAG).
- Прибрано хуки OFFICE_REPLAY_ON_START / OFFICE_RR_ANALYSIS_ON_START.
