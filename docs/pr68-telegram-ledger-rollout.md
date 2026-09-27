# PR #68 — Telegram delivery ledger rollout (NOT AUTHORIZED FOR PRODUCTION)

This is a deployment checklist, not permission to deploy. PR #68 stays draft until
the owner explicitly approves both the production DB migration and Worker deploy.

## Current state

- `OFFICE_TG_PERSISTENT_DEDUP` is OFF unless explicitly set to `1`.
- The relay must not create the ledger table during message delivery.
- `migrate_delivery_ledger(db_path)` is additive and must be invoked separately,
  only after owner approval and backup verification.
- The existing in-memory dedup remains the default while the feature is OFF.
- No auto-trading or order placement is introduced.

## Required before enabling

1. Confirm the Worker and Web are using the intended same PostgreSQL DB
   (compare `office_db_identity` fingerprints without printing credentials).
2. Take/verify a recoverable production DB backup and a rollback plan.
3. Obtain explicit owner approval for the additive `office_telegram_delivery`
   table and a separate explicit approval for Worker deploy.
4. Run the migration once on the approved DB, verify the table schema, and
   verify the application DB role can INSERT, SELECT, UPDATE, and DELETE.
5. Run offline tests and same-HEAD security review; review current PR diff.
6. Enable `OFFICE_TG_PERSISTENT_DEDUP=1` on the Worker only after step 4.
   A missing table or DB error blocks tracked sends (fail closed).
7. Observe a controlled, explicitly authorized test event and verify one
   Telegram message and a corresponding DELIVERED row. Do not generate a
   live test event without the owner's permission.

## Failure and rollback

- Disable the flag to restore the previous in-memory behavior; this is an
  operational rollback, NOT a guarantee against duplicates after restart.
- Do not drop the ledger table during an incident; preserve it for diagnosis.
- A Telegram-accepted message followed by a crash before the DB commit
  cannot be made exactly-once by this ledger; retries may duplicate it.
- Leases are 120 seconds by default and the relay attempts renewal every 30 seconds.
  If renewal fails or ownership is lost, the current relay logs the error but
  does not yet abort the in-flight Telegram request. Treat this as a BLOCKER
  for multi-Worker production until cancellation and recovery are tested.
- Do not mark PR ready, merge, or deploy on the basis of fixture-only T6 tests.
  The separate real BTC/MANTA historical replay and final review remain gates.

## Security/reliability review findings (current branch)

- MITIGATED IN CODE: the heartbeat cancels the in-flight send task if the
  renewal fails or the lease is lost. A Telegram request already accepted
  before cancellation remains an ambiguous delivery; live verification pending.
- MITIGATED IN CODE: a Telegram success followed by a failed ledger commit
  returns no successful delivery ID to the caller. Ambiguous delivery may
  still have reached Telegram; investigate before retrying.
- LIMITATION: the ledger cannot atomically commit with the Telegram API.
  An ambiguous timeout/crash can produce a duplicate on retry.
- NOT VERIFIED: final same-SHA independent security review and real historical
  BTC/MANTA OHLCV replay. The repository fixture test is not that replay.

## Historical replay evidence, 2026-09-27

- Offline PR68 safety workflow on commit `700dc558`: SUCCESS.
- Real historical OHLCV workflow run `36346568741`: FAILED before any replay.
  Binance USD-M `fapi.binance.com/fapi/v1/klines` returned HTTP 451 from
  GitHub-hosted runner. No BTC/MANTA candles were downloaded, and no real-data
  backtest result exists. Do not substitute the fixture replay or fabricate data.
- Next step requires an authorized data source reachable from the runner or
  owner-supplied verified historical BTC/MANTA OHLCV files. MANTA strategy
  replay needs its own harness: existing T6 evaluates the BTC-only radar.

## Ambiguous delivery quarantine (2026-09-27)

- Lost lease cancels the sender and attempts to mark the event UNCERTAIN.
  UNCERTAIN keys cannot be reclaimed after lease expiry; manual Telegram
  reconciliation is required before any administrative resolution.
- If Telegram acknowledges a message but DELIVERED commit raises, relay
  attempts UNCERTAIN quarantine and returns no successful lifecycle result.
  If both DB writes fail, exact-once delivery cannot be guaranteed; do not
  automatically retry or enable production dedup until the DB is restored and
  the Telegram message has been manually reconciled.
- Temporary-SQLite regression covers UNCERTAIN expiry and stale tokens.
  Real Telegram failure injection and independent final security review remain
  required before rollout.
- Alternative public Binance Vision monthly archive fetch is implemented in
  `scripts/fetch_binance_archive.py`; real-data workflow `pr68-real-replay.yml`
  fetches BTC/MANTA archives without credentials. BTC T6 replay and MANTA
  data validation are separate; this is NOT MANTA strategy replay.

## Verified real archive replay result (2026-09-27)

GitHub Actions run `36347711570` SUCCESS on commit `190b69d`.
Source: Binance Vision USD-M completed July 2026 monthly archives, 31 D1,
744 H1, 2976 M15 real candles per BTCUSDT and MANTAUSDT.
BTC-only T6 evaluated 542 hourly-spaced decisions; WATCHING 256,
SIGNAL 40, SKIP 502, simulated closed trades 40 (17 wins, 23 losses),
WR 42.5%, average R 0.468, simulated total 18.7201 R after configured
costs, max drawdown 11.6107 R. These are historical simulation outputs,
NOT realized returns, a forecast, live order authorization, or an
independent strategy validation. MANTA historical data passed integrity
checks only; no MANTA strategy replay was performed.

The historical replay run predates the later incremental-pointer optimization
and control-test commit. Its evidence applies to its exact workflow SHA.

## Real MANTA WATCHING gate replay (2026-09-27)

GitHub Actions run `36348088790` SUCCESS at SHA `4fabdb06`.
On July 2026 real Binance Vision MANTAUSDT candles, the safety-gate
harness evaluated 2,973 M15 observations against the preceding closed H1
range; 2,254 observations were in-zone, 369 in-zone observations had
ATR >90%, and zero WATCHING checks granted entry. This is an intentionally
incomplete-SL/TP gate stress test; previous-H1 ranges are test inputs, NOT
Lev's independent market-selected zones. It is NOT a full Lev MANTA strategy
replay, performance validation, or a live Telegram delivery test.
BTC T6 historical replay also succeeded in the same run. Offline safety
workflow `36348088818` succeeded at the same SHA.

## Crash-after-send reservation safety (2026-09-27)

An expired PENDING reservation is now fail-closed, even if its lease elapsed:
Telegram may have accepted the message before the process crashed. No worker
may automatically reclaim that key. An operator must compare the event with
actual Telegram history and reconcile the database under a separately
approved procedure. This trades automatic recovery for duplicate prevention.
The offline SQLite regression explicitly tests expired PENDING, lease loss,
UNCERTAIN, and stable DELIVERED behavior. Production migration and enablement
remain OFF and require separate owner approval.

## MANTA T6 radar historical replay (2026-09-27)

Run `36349201584` SUCCESS at `dfc0ec6` on actual Binance Vision
July 2026 MANTAUSDT monthly candles: 561 hourly-spaced decisions, 188
WATCHING, 56 SIGNAL cards, 55 closed simulated trades (20 wins, 35 losses),
36.36% simulated WR. The engine reported 224.4202 total simulated R,
4.08 average R and 9.8556 R maximum drawdown. **These unusually large R
figures are UNVALIDATED diagnostics**, not an expected return or evidence of
strategy profitability. They require independent fill/SL/TP/fee/position-size
and look-ahead audit before any use in a release decision. T6 runs the
`evaluate_radar` historical engine, NOT the full Lev cognition pipeline;
no full Lev MANTA replay or live Telegram delivery was performed.
The same run passed BTC T6 and MANTA WATCHING gate; offline workflow at
`ab8f551` succeeded. No production orders or Telegram sends occurred.

## T6 fill/geometry audit follow-up (2026-09-27)

The original MANTA 224.4202 R diagnostic must not be used: the prior
simulator filled at the card's proposed midpoint without verifying an
actual market fill at that price. The revised offline simulator uses the
NEXT M15 candle OPEN plus adverse slippage, validates the resulting SL/TP
geometry, applies TP1 minimum (3% MANTA, 1.2% BTC/ETH), RR >=1.5, and
requires stop distance >= ATR(14) from fully closed H1 candles. A synthetic
control fixture that previously forced a simulated trade is now required
to show an explicit rejection when it violates those gates. A fresh real
replay is required before reporting any revised trade counts or R values.
This remains an illustrative radar-only backtest, not a Lev strategy audit.

## Verified conservative re-run (2026-09-27)

GitHub Actions `36349771803` SUCCESS at `b99cf334` with real July
2026 candles after next-open fill, 3% MANTA/1.2% BTC TP1, RR and H1 ATR
stop checks. MANTA: 714 decisions, 75 radar SIGNAL cards, only ONE closed
simulated trade, 1 win, 1.4644 simulated R; 67 candidates rejected by TP1
minimum, 7 by next-open RR. BTC: 720 decisions, 66 SIGNAL cards, ZERO
simulated trades, 61 rejected by TP1 minimum and 5 by next-open RR.
The single MANTA win is statistically insufficient for any WR or return
inference; previous 224.4202 R was invalidated. The conservative T6 engine
is not full Lev cognition or a fill-verified exchange execution model.
Offline tests for the revised fixture succeeded in `36349828028`.
