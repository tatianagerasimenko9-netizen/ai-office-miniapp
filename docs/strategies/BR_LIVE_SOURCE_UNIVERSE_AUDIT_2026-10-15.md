# B&R LIVE — source conformity and universe gap (2026-10-15)

## Verified implementation (not a statement of authors' methods)
- `office_br/live.py::SYMBOLS`: fixed 12 USDT symbols. `BR_LIVE_SYMBOLS` accepts a manually configured comma-separated override. No all-USDT-M discovery, liquidity ranking, market regime or trend/countertrend classification is called by the B&R monitor.
- `office_br/live.py::scan_symbol`: last 240 **closed M15** candles; only a pattern whose confirmation is the most recently closed candle is emitted. `track`: closed M1 for paper outcomes; no exchange orders.
- `office_br/detect.py::HYP`: all numeric parameters are explicitly hypotheses, **not attributed to Gerchik, Daria, or SMC**. Pivot k=3; level age 96 M15; retest window 24 M15; tolerance 0.30 ATR14; confirmation window 4 M15; stop buffer 0.10 ATR; fallback targets 1R/2R/3R.
- B&R implements **one** breakout → retest → bounce pattern. It does not invoke `office2/integration/gerchik_scenarios.py`, `office2/scenarios.py`, `office2/daria_steps.py` or `office2/dynamic_universe.py`.
- `office2/dynamic_universe.py` is a **separate** optional selection mechanism (24h volume ≥$20M, absolute change ≥5%, spread ≤12 bps, at most six dynamic candidates). Those numbers are operational heuristics, **not authors' entry rules**, and this module is not the B&R universe.

## What the source registry actually supports
- `docs/sources/METHOD_MAP_GERCHIK.md`: D1 levels and bounce, breakout, false breakout; source: *Курс активного трейдера* (2019), pp. 56–147; risk R:R ≥3:1, pp. 92–112. The shadow implementation in `office2/integration/gerchik_scenarios.py` has five scenarios, but its M15 tolerances are expressly operational assumptions.
- `docs/strategies/SOURCE_RULES.md`: source → exact rule → code → conformity → market verification; unattributed numerical thresholds must be HYPOTHESIS / OUR_IMPLEMENTATION.
- `docs/sources/CONFORMITY_2026-10-12.md`: known mismatches include Gerchik R:R ≥3:1 vs Brain first target ≥1R, D1 3–5-day ATR vs ATR14, swing conventions, stop buffer and unverified SMC numerical thresholds. These are **not resolved** by enabling B&R LIVE.
- `docs/sources/unresolved.md`: incomplete source attribution for some screenshots, unverified Daria lower-TF trigger details, conflicting risk rules, incomplete SMC chapters, and **no proven edge**. Do not present an unverified pattern as an author's rule.

## Required next acceptance gates — do not silently widen LIVE
1. Inventory all eligible Binance Futures USDT-M perpetual contracts from exchangeInfo, with exchange status and contract type. Record total eligible, rejected, and reason codes; do not use an unexplained fixed top-12 as a methodological choice.
2. Establish a **separate, bounded, rate-limit-aware universe observer** with quote volume, bid/ask spread, data completeness and freshness; report selection provenance. This is infrastructure, not a trading strategy.
3. Define a **source-linked scenario registry** for Gerchik bounce/breakout/false breakout, SMC continuation/reversal, Daria strong candle/retracement, and distinguish source-verified vs implementation-hypothesis fields. Never combine all scenarios into one mandatory checklist.
4. Tag trend/countertrend/range using explicit higher-TF context; no implied classification from an M15 breakout alone.
5. Replay each scenario and universe selection without lookahead, with fees/slippage, independent out-of-sample periods, rejected candidates and TP-before-SL comparisons. No claims of edge without evidence.
6. Run **shadow/paper only** until source conformity, regression, Binance rate limits and delivery behavior are confirmed. Do not change existing Office2 gates, risk, live orders or Telegram streams implicitly.
7. For the existing B&R LIVE, separately verify each real candle scan, detection, persistence, Telegram READY, M1 tracking, manual authenticated actions and E2E. Zero signals is not evidence of a broken detector without scan health and rejection diagnostics.

## Decision
The current B&R LIVE is a **12-symbol experimental single-pattern paper monitor**, not a source-verified multi-method market-wide scanner. A wider source-conformant scanner is a separate development task. Do not label the two equivalent.
