# Private capture schedule configuration — local checkpoint

The schedule API and additive migration establish owner-private immutable definitions and revision-safe edits. This is groundwork for R10, not functioning automation. Enabling through the API returns an explicit 409 until private dispatch, executor and publication are connected. No UI, production migration, merge or deployment is claimed.

## Implementation

- Authenticated `GET/POST /api/research/capture-schedules` and `PATCH /{uuid}` validate active verified sessions using the existing research authorization path. Ownership comes from that session, never request data.
- Definition identity hashes canonical JSON containing the screen, expanded original criteria and complete original preset snapshot. Unknown presets, unknown definition properties and shared watchlist scope are rejected. No original preset definitions are changed.
- Definitions remain immutable; an owner has one schedule per definition hash. Creation and edits use the service-only security-invoker RPC, with revision checks and per-owner transaction locking. The collection is bounded at 100; editing remains possible at that limit.
- The table exposes authenticated owner-only reads through RLS, no client writes or anonymous reads. Service responses with invalid owner scope or unconfirmed revisions fail closed.
- Cadence validates IANA timezone, integer hour/minute and distinct weekdays. Enabling requires a future next due time at database level; disabling removes it. Each successful edit advances the revision and activation floor, allowing later workers to fence obsolete definitions/runs. Dispatch must still verify cadence and apply the current revision before publishing.
- Lists use deterministic created-time/ID ordering and explicit paging. Storage errors and malformed saved configuration produce safe errors; callers must reload after an unconfirmed write.

## Executed evidence

2026-10-02, isolated PostgreSQL 16.14 at Unix socket `/private/tmp/tradingagent-research-pg`, port 55439, database `postgres`:

```
/opt/homebrew/opt/postgresql@16/bin/psql -h /private/tmp/tradingagent-research-pg -p 55439 -d postgres -f web/api/tests/capture-schedules-db-contract.sql
```

Passed actual migration execution, grants, RLS for two owners, duplicate-create/stale-edit/immutable-definition conflicts, revision progression, disable semantics, invalid weekday/timezone/due rejection and 100-record limit with edits permitted. All schema and records rolled back. This is not PostgREST, real Auth or two-connection concurrency qualification.

28 HTTP/definition/static-route tests in `web/api/tests/test_research_schedules.py` pass, including active-session authorization, other-owner isolation, original preset preservation, definition lookup, strict cadence/edit validation, duplicate/stale saves, paging and invalid storage-confirmation handling. The full API/worker suite passes 515 tests after all schedule tests were added.

## Remaining delivery

- Durable unique occurrence dispatch; concurrent claims; expiring leases, bounded retry and revision fencing.
- Complete private immutable publication and private readers/comparison/review. Evidence building is now extracted as `build_screen_capture`; scheduled definitions are checked by `build_schedule_capture` before calling it. The worker invocation, lease/revision fencing and private publication remain unconnected.
- Real Auth/PostgREST and concurrent database qualification, schedule on/off/restart/failure tests, market-session/holiday policy.
- Opt-in UI with cadence, last successful capture, running/failure/retry state and preserved prior success.
- Full R01–R15 release checks including Moomoo reconciliation, responsiveness, accessibility and production cutover/rollback.

Supabase database-advisor execution remains pending the existing approval request: automatic approval review rejected the command because it may disclose local schema/connection metadata to Supabase. It has not been retried or bypassed. Native local checks do not replace that pending advisor or production qualification.

## Capture-builder follow-up

The manual route still owns its original idempotent shared-history append and reply. It delegates evidence construction to a builder that never reads or writes capture history. Existing provider/stored completeness, timestamp, criterion and observation checks remain. Provider captures now reject malformed, duplicated and wrong-market canonical IDs before additional filters can hide them, including duplicates across pages.

A pinned scheduled definition is normalized and hashed again against the original preset snapshot before any capture call. Tampered definitions, unsupported schema versions and preset catalog drift stop without publication. Scheduled due times are not used as observation timestamps. Twelve builder tests cover history independence, generation/nonmember preservation, rejected provider identities/page duplicates and invalid inputs; six schedule-definition tests cover preserved original criteria and tampering/catalog drift. These are local backend tests, not real provider, private dispatcher or production acceptance.

Production-config route ordering is verified in a fresh Python process with `PORTAL_STATIC_DIR` set: the private schedule route reaches authentication instead of the static catch-all and carries `private, no-store`. No deployed request is claimed.
