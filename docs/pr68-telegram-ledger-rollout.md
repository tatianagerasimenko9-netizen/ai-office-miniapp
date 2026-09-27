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
