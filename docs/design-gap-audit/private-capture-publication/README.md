# Atomic owner-private publication — local checkpoint

R10 and broader R01–R15 gates remain open. Publication operations are built but not connected to worker execution or private history/Changes UI. The schedule API still refuses enabling. No production migrations, merge or deployment are claimed.

## Implemented

`research_private_captures` stores immutable snapshots linked by a composite foreign key to the occurrence's owner/schedule/revision. Authenticated reads are owner-only RLS; anonymous access/client writes and service UPDATE/DELETE are revoked. No snapshot enters public jobs or deployment-shared capture history.

The service-only security-invoker publication RPC locks schedule then occurrence. It requires the current enabled revision, running worker/token, unexpired lease and 20-minute attempt cap. It checks exact capture ID/definition, complete/version/source envelope, timezone-aware bounded capture/source timestamps, canonical unique market membership and eligible observation count/scope/member containment for stored captures. Generation publication requires a canonical generation ID and matching observation generations. Provider captures remain version 2 with provider-retrieval clock; they do not gain nonmember evidence or inferred exit causes.

Insert and occurrence success/lease clearing happen in one transaction. Failed validation inserts nothing. An exact lost-response retry checks the original worker/token/payload against the immutable committed capture and returns that capture, even after schedule-off; changed retries cannot replace it or create new success.

`CaptureQueue.publish` checks local ID/complete/pinned definition, finite JSON and 32 MiB bound, then confirms returned owner/schedule/revision/hash/worker/token/exact payload and publication timestamp. Empty database fences return no confirmed publication. Transport guards do not replace the capture builder's full criterion/membership validation; the executor must call that builder and validate pinned definitions before publication.

## Executed evidence

2026-10-02: `web/api/tests/capture-publication-db-contract.sql` executed all four additive migrations in actual isolated PostgreSQL 16.14, socket `/private/tmp/tradingagent-research-pg`, port 55439, database `postgres`, followed by rollback. Verified RLS/grants/service immutability, incomplete payload/count/wrong-market/missing-generation/stale-source rejection without state changes; atomic insertion/success; exact duplicate confirmation versus altered payload/worker; lease expiry, replaced token, run-time cap, edited revision and off-state rejection; earlier success preserved and exact confirmation after off; other-owner read exclusion.

12 additional worker publication transport tests pass (27 queue tests total). Full API/worker suite: **558 passed**. Native payload uses an empty complete stored cohort to test transaction contracts; it does not qualify full-market factor data. No actual worker restart/concurrent publication/PostgREST/browser/provider acceptance is claimed.

## Remaining

Connect dispatch/claim/executor/renewal/publication with actual private definition reads; qualify concurrent claim/edit/expiry/publication and genuine restart/lost-response paths; add owner-private history/Changes/review/download readers; opt-in schedule UI with success/failure/retry state; market-session and holiday policy; real Auth/PostgREST and full provider/Moomoo/device/performance/production release checks.

Supabase advisor execution remains pending the earlier explicit approval request after automatic approval rejected possible schema/connection metadata disclosure. It was not retried or bypassed. Current changes remain uncommitted, and no production schema changed.
