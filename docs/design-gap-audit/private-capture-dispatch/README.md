# Durable private dispatch — local checkpoint

R10 remains open. Dispatch is implemented but not connected to the service loop; the schedule API still refuses enabling. No provider capture, publication, merge or deployment is claimed.

## Built

- Separate owner-private occurrence table with composite schedule/owner foreign key, unique schedule/revision/due slot, authenticated owner-only RLS reads and service-only writes/RPC.
- One transaction locks the current schedule, checks owner/revision/enabled/expected-next-due and temporal bounds, inserts one occurrence and advances next due. A lost-response retry returns the existing occurrence without another advance. A different identity for the same slot is rejected.
- Worker planner uses validated civil-time cadence, latest eligible due slot, activation floor, future next slot and deterministic occurrence ID. It does not backfill missed observations, use public jobs or claim a capture occurred at the scheduled due time.
- Planner verifies returned owner/schedule/revision/slot/ID before claiming dispatch. Obsolete database fences return no dispatch; malformed responses fail rather than report success.
- Lease/attempt/status columns and constraints establish queue storage only. Claim, renewal, failure/retry, cancellation and successful private publication operations are not implemented yet.

## Executed verification

2026-10-02, PostgreSQL 16.14, isolated socket `/private/tmp/tradingagent-research-pg`, port 55439:

- `web/api/tests/capture-dispatch-db-contract.sql`: actual new migrations; owner/grant checks; wrong owner/revision/expected due rejected; one insert plus next-due advance; duplicate/lost-response identity; conflict rejection; disable revision fence; two-owner RLS. All changes rolled back.
- `concurrency.py` and `concurrency-result.json`: actual separate PostgreSQL processes in disposable `capture_dispatch_qualification`, cloned from local `postgres`, with both new migrations loaded. The first transaction's schedule lock was observed before the second client started. Both returned the same ID; exactly one occurrence persisted. The database was dropped after evidence collection. Fixture cadence/definition and historical slot are deliberately minimal; this checks transaction concurrency, not semantic cadence/definition qualification.
- 16 worker dispatch tests cover latest-only catch-up, stable retry ID, disabled/future no-op, revision fence, malformed inputs and returned identities, DST gap skipping and later fold.
- Full API/worker suite: **531 passed**. No frontend code changed in this checkpoint.

## Next acceptance

Implement bounded claim/renew/retry with expiring lease tokens; invalidate obsolete schedule revisions and prevent overlapping obsolete completion. Publish only a complete qualified snapshot privately and atomically with occurrence success. Integrate dispatcher and executor with worker/session/provider policies and owner-private readers/Changes/export. Complete restart, expiry, failure, off/on, real Auth/PostgREST and production qualification before enabling UI.

Supabase advisor execution remains pending the existing explicit approval request following automatic approval rejection over possible schema/connection metadata disclosure. It was not retried or bypassed. New files remain uncommitted; no production schema was changed.
