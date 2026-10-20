# B&R LIVE read-only production cohort — 2026-10-20

Source: Render production PostgreSQL read-only SQL queries (br_test_signal, br_test_event). No DB writes, no trading changes.

## Latest observed statuses
- SL: 291
- TP3: 78
- AMBIGUOUS: 7
- TIMEOUT: 1
- SENT: 7
- Total: 384; SL/TP3 terminal cohort: 369.
- Terminal cohort TP3 frequency: 78/369 = 21.14%. **Not a net-R or profitability metric.**

## Symbol stratification, SL/TP3 only
| Symbol | N | TP3 | SL | TP3 % |
|---|---:|---:|---:|---:|
| ETHUSDT | 42 | 14 | 28 | 33.3 |
| BTCUSDT | 36 | 4 | 32 | 11.1 |
| DOGEUSDT | 35 | 4 | 31 | 11.4 |
| SOLUSDT | 35 | 2 | 33 | 5.7 |
| NEARUSDT | 33 | 9 | 24 | 27.3 |
| LINKUSDT | 31 | 3 | 28 | 9.7 |
| TIAUSDT | 30 | 7 | 23 | 23.3 |
| XRPUSDT | 28 | 2 | 26 | 7.1 |
| ADAUSDT | 27 | 9 | 18 | 33.3 |
| SEIUSDT | 27 | 7 | 20 | 25.9 |
| AVAXUSDT | 23 | 9 | 14 | 39.1 |
| ONDOUSDT | 22 | 8 | 14 | 36.4 |

## Interpretation and restrictions
These are live observational outcomes, not verified Binance M1 fills. Symbol differences are descriptive only, heavily correlated, over a short period. Do NOT auto-disable or promote any symbol based on these ratios; no validated positive expectancy. Full Binance Futures M1 reconciliation, costs, purged OOS and production feature snapshots remain open.

## ML implementation
Versioned frozen causal rows: office_br/learning_dataset.py.
Purged time split: purged_chronological_split.
Interpretable single-feature training and untouched test Brier comparison: office_br/ml_baseline_shadow.py.
No actual model fit on live feature snapshots has been performed, because verified causal per-signal features have not yet been extracted. Model promotion remains prohibited.
