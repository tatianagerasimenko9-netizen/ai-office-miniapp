# B&R-only intraday launch checklist — 2026-10-19

## Scope / safety
- **ONLY** B&R LIVE and its isolated research, data, signal cards, manual-trade tracking.
- Do not change Office2 READY, its detector, gates, notifications, risk, or existing main signal flow.
- No automatic order placement. User makes the trade decision and confirms “Я відкрила угоду”.
- All new rules are hypotheses until tested. Do not attribute invented thresholds to a blogger, Gerchik, ICT, Wyckoff, or Smart Money.
- Do not merge into main or enable production filters without CI, independent historical replay, out-of-sample evidence, and a rollback path.
- Do not optimize for TP3 count > SL by shifting TP. Optimize validated net expectancy after costs and risk.

## Execution checklist (mark [x] only with commit, tests, and evidence)
- [x] 01. Inventory current B&R implementation and explicitly separate its hypotheses from verified source methodology. Evidence: office_br/detect.py HYP; office_br/live.py; 2026-10-19 review.
- [x] 02. Preserve isolated B&R LIVE namespace and observational/manual-only operation. Evidence: office_br/live.py; separate br_test_signal tables.
- [x] 03. Read-only production outcome audit (334 terminal: TP3=76, SL=258 at inspection). Evidence: Render PostgreSQL read-only query, 2026-10-19.
- [x] 04. Add causal breakout strength, close location, volume ratio, retest depth and risk metrics in SHADOW_ONLY. Evidence: office_br/structure_metrics.py and scripts/test_br_structure_metrics.py. **CI of latest revision still pending; this item is code-complete only.**
- [x] 05. Implement independent historical M1 replay and event ledger comparator (code-complete, not yet validated against entire production cohort). Evidence: office_br/m1_replay.py, ledger_m1_compare.py, binance_m1_history.py, m1_batch_replay.py, m1_export.py, m1_run_production.py.
- [ ] 06. Run current-commit CI and new-module tests; fix all failures.
- [ ] 07. Complete historical M1 Futures replay for entire terminal B&R cohort; report mismatches, ambiguous bars, missing candles, Binance errors.
- [ ] 08. Define session clock with DST: Asia, London, New York, session premarket, session high/low and previous-day/week high/low. **PARTIAL CODE**: office_br/session_shadow.py has DST-aware Tokyo/London/New York local clocks and closed-M15 same-day high/low; tests added. Still missing premarket, previous-day/week high/low, live integration, full CI. Session windows are explicit operational assumptions, not source-verified author rules.
- [ ] 09. Causal HTF-to-LTF context: MN/W1/D1/H4/H1 -> M15/M5/M1. Closed-candle-only pivots, trend/range, PDH/PDL, HTF liquidity and obstacle distance.
- [ ] 10. Implement separate measurable BOS, CHOCH, liquidity sweep, displacement, FVG, order block, breaker; no future-candle leakage, each has source/time/strength metadata.
- [ ] 11. Define and validate Gerchik-style mirror support/resistance, breakout/retest quality, rejection/false breakout and Wyckoff spring/upthrust as **separate** setups; do not claim author equivalence without source.
- [ ] 12. Define B&R intraday candidate pipeline: session context -> HTF map -> M15/M5 setup -> M1/M5 closed-candle trigger -> structural invalidation SL; dedup/TTL/cancellation.
- [ ] 13. TP1/TP2/TP3 from real opposing liquidity/structure only, no forced R or percentage target; evaluate 3–7% move opportunities as *observed outcomes*, not fabricated goals. Reject setups without adequate net reward/risk.
- [ ] 14. Cost model: maker/taker fees, spread, slippage, funding where applicable, position size, leverage, and realized net R; distinguish underlying price % from leveraged ROI.
- [ ] 15. Manual position tracking: “Я відкрила угоду”, partials, BE only on validated condition, structure trailing, session continuation/invalidations, no auto-orders.
- [ ] 16. Walk-forward chronological OOS + session/regime stratification + conservative M1 intrabar ambiguity and robustness/uncertainty; no leakage or cherry-picking.
- [ ] 17. B&R-only Telegram and Mini App cards with entry zone, SL, liquidity targets, session, setup rationale, candle confirmation, TTL, invalidation, source and risk.
- [ ] 18. Shadow run and compare baseline vs candidate after costs; require credible evidence of positive expectancy before enabling live recommendation gates.
- [ ] 19. Isolated B&R release: PR review, full CI, migration/compatibility, feature flags default off, backup, deploy smoke, rollback, explicit proof that Office2 signals unchanged.
- [ ] 20. Production verification: live B&R data freshness, cards, event timestamps, manual confirmation and alerts; publish evidence-backed final checklist.

## Operational note
The existing B&R LIVE observational stream is NOT equivalent to validated profitable active trading. Production activation is contingent on #06–20. This checklist is the source of truth; no unsupported green checkmarks.
