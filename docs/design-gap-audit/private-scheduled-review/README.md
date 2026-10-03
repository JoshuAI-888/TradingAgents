# Owner-private scheduled pair review — local checkpoint

R06/R10 and all broader release gates remain open. Review storage/API are implemented; private revision-safe export and UI integration remain unfinished. Automation is still disabled. No production schema, merge or deployment is claimed.

## Implementation

A separate owner/schedule/before/after/code review table references both immutable private captures using composite owner/schedule foreign keys. Authenticated reads use owner RLS; anonymous reads and client writes are revoked. Service-only security-invoker saves validate complete same-definition/version chronological pairs and union membership, then create at revision 0 or update the exact current revision. Stale creates/edits return no row. General shortlist notes and deployment-shared manual pair reviews remain separate.

Private `GET/PATCH /api/research/capture-schedules/{schedule_id}/pair-reviews` validates scoped capture evidence through the shared engine before applying review state/saving. Strict revision/note/code input prevents Boolean revision coercion or client-selected owner. Save confirmation checks exact scope, note/status and next revision; conflicts preserve the client's draft by returning explicit 409. Responses project known fields.

Read RPCs aggregate one lightweight code/status/revision state with a SHA-256 fingerprint, then fetch only the requested visible notes (at most 500) against that fingerprint. Changed state returns `confirmed=false` without notes; the API returns 409 instead of mixing revisions. Review filters apply before paging; Next unreviewed uses the same pair/search/status/sort scope. Missing reviews retain revision 0 and empty note. Full long-note payloads are not sent just to filter/page a comparison. Large-state database memory/latency still needs measurement.

## Executed evidence

2026-10-02: `web/api/tests/scheduled-pair-review-db-contract.sql` executed all five additive migrations in isolated native PostgreSQL 16.14 (socket `/private/tmp/tradingagent-research-pg`, port 55439, database `postgres`) and rolled back. Verified grants/RLS, stale create/update, independent same-ticker pair state, wrong-owner/reversed/absent-member rejection, lightweight state without notes, visible-note retrieval with matching fingerprint and suppression after a concurrent revision update. Fixture captures were directly inserted to isolate review SQL; this is not a claim of provider qualification or concurrent two-process CAS.

Ten HTTP tests cover save/read/CAS, review filter/default/visible-note scopes, auth/owner isolation, invalid revisions/owner properties/absent membership, raced fingerprint rejection, malformed confirmed/hash/status/revision/duplicate metadata and Next unreviewed. They use controlled Auth/storage and actual validated synthetic capture evidence. Full API/worker suite: **597 passed**. `git diff --check` passes.

## Remaining

Private filtered/selected exports pinned to pair definition and review revision; browser timeline/pair/editor/queue/download integration; real Auth/PostgREST and two-client CAS/read race qualification; 40,000-union/paging/long-note performance and account-switch/revocation; connected runtime/session/provider/calendar checks; complete R01–R15 release/data/device/production acceptance.

The existing Supabase advisor request remains pending after automatic approval review rejected possible local schema/connection metadata disclosure. It was not retried or bypassed. All current schedule-related changes remain uncommitted; production is untouched.
