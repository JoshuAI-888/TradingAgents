# Private capture leases and bounded retry — local checkpoint

R10 remains open. These operations are not connected to the worker loop and cannot publish a capture; schedule API enabling remains explicitly blocked. No production migration, merge or deployment is claimed.

## Implemented

Service-only security-invoker claim/renew/failure RPCs use schedule-then-occurrence locking and database clock checks. Claim examines at most 100 eligible candidates and skips locked schedules/occurrences. A schedule has at most one live attempt; each claim increments attempts and generates a fresh UUID lease token. Leases last 120 seconds and renewal is capped at 20 minutes per attempt. Exhausted expired attempts become failed; changed/disabled schedule revisions become cancelled. Other workers, old tokens and expired leases cannot renew or report failure.

Retryable failure clears the lease and waits 30 seconds after attempt one or 120 seconds after attempt two. Attempt three and nonretryable failures terminate. Only safe enumerated failure codes are stored, not raw provider details or private definitions. Successful private publication remains absent; claim state does not mean capture success.

`CaptureQueue` validates transport replies for canonical IDs, owner/schedule/attempt/revision, lease holder/token and bounded timestamps. Renewal cannot silently adopt a different token; failure cannot silently adopt an unexpected retry state. Empty/fenced replies mean no confirmed operation. This helper is not yet invoked by the service.

## Executed evidence

2026-10-02: `web/api/tests/capture-leases-db-contract.sql` ran against actual isolated PostgreSQL 16.14, socket `/private/tmp/tradingagent-research-pg`, port 55439, database `postgres`. All three additive migrations and fixtures rolled back. Verified service-only execution, one live attempt per schedule, worker/token checks, renewal, retry delay, fresh-token reclaim after simulated crash expiry, stale rejection, three-attempt termination, expired third-attempt termination, permanent failure, 20-minute renewal/failure cap and schedule-off cancellation.

15 worker transport tests pass. Full API/worker suite: **546 passed**. `git diff --check` passes. No frontend changes or browser acceptance claimed. Actual two-client dispatch was previously verified; actual concurrent claims/renewal/edit/publication remain to qualify. Forced fixture timestamps exercise expiry logic without waiting two minutes; no real worker-restart execution is claimed.

## Remaining

Atomic complete private capture publication plus occurrence success; publication fencing against schedule edit/off, token replacement, lease expiry and run-time cap; idempotent publication after lost response; private readers/Changes/review/export; connected worker dispatch and execution; real Auth/PostgREST, concurrent claims, genuine restart/failure/off-on and market-session policies; opt-in UI and broad R01–R15 release qualification.

The existing Supabase advisor approval request remains pending after automatic approval review rejected possible schema/connection metadata disclosure. It has not been retried or bypassed. Schema changes remain uncommitted pending that check; local native verification does not substitute for platform or production acceptance.
