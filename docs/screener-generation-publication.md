# Immutable screener generation storage contract

Local progress, 2 October 2026. This completes the additive **database storage/fencing contract** for R01. The storage-only checkpoint below is historical. The [new worker integration](screener-generation-worker-integration.md) stages complete cohorts and calls the fenced atomic RPCs; the API still reads legacy rows. **Complete runtime generation consistency is not qualified yet**. The migration is unapplied to production; no merge/deployment or production mutation occurred.

## Implemented contract

Migration: [`20261002060206_screener_generation_publication.sql`](../supabase/migrations/20261002060206_screener_generation_publication.sql), created with the installed official Supabase CLI `migration new` command.

- Immutable run IDs and generation headers/rows; repeated run tokens cannot reacquire after expiry/completion/supersession. Canonical requested identities and actual returned classified rows must match exactly, with a 20,000-row and 64 MiB row-payload bound.
- Per-market leases serialize US refreshes separately from HK. Acquisition and publication use actual PostgreSQL locks. Renewal refuses expired/superseded tokens. An expired unsuperseded owner may record its failure; a superseded owner cannot change newer attempt/success state.
- Publish writes the immutable generation, compatibility mirrors and per-market success pointer in one transaction. A database error rolls back every part. Old mirror records are retained for historical lookups; only generation rows establish that generation's exact membership.
- Exact retry returns the original receipt, including after a successor starts; conflicting payload replay is rejected. Payload array order is part of exact replay. The database computes the cohort fingerprint and authoritative counts rather than accepting client count claims.
- Cache receipts must be aware timestamps within the run interval. Source observations are retained separately and may be stale; this storage contract does not qualify freshness, currency, periods or financial causes.
- RLS enabled on all new tables, no anonymous/authenticated table/function grants, service-only security-invoker RPCs with empty search paths. Immutable run/header/row records cannot be updated, deleted or truncated through the contract.
- Global cadence remains separate; market state preserves unrelated existing fields and prior success on failed attempts. Running attempts expose their lease expiry. Invalid persisted state fails before acquisition.

## Native verification

Tests: [`generation-db-bootstrap.sql`](../web/worker/tests/generation-db-bootstrap.sql) and [`generation-db-contract.py`](../web/worker/tests/generation-db-contract.py). These accept no production database parameters and use a fixed isolated Unix socket/database. The bootstrap requires pre-existing test-cluster roles and installs minimal existing table contracts plus the additive migration. Re-running the contract appends synthetic immutable generations to its disposable database.

The final migration installed from scratch into a second empty isolated database. PostgreSQL 16.14 native tests passed for actual grants/RLS/invoker access; exact replay/hash/source-cache round-trip; update/delete/truncate guards; malformed/missing/duplicate/foreign identities and invalid dates/classification; previous-success preservation; expired-owner failure and successor fencing; malformed state/market/lease inputs; maximum and overflow bounds.

Two simultaneously live sessions were observed through `pg_stat_activity`: the second US acquisition waited on the advisory lock, then was rejected because the first owner held the committed lease. HK published independently. Another live uncommitted publication proved readers saw the old pointer/rows/mirrors until commit; old-generation rows remained unchanged after the new pointer became visible. An injected mirror-write error occurred **after header/row insertion** and rolled back header, rows, pointer and mirrors.

The final 20,000-row synthetic fixture was 6,828,890 JSON bytes and published in **0.690 seconds** locally. This is one storage measurement, not a p95 or provider/PostgREST/network/device result. 20,001 rows failed closed. [Machine-readable evidence](design-gap-audit/generation-publication-checkpoint/native-contract-evidence.json) records the migration hash and twelve native contract groups.

Official Supabase CLI 2.119.0 `db advisors --db-url ... --type all` returned **No issues found**, exit 0, on the isolated database after final SQL changes. This does not qualify the live Supabase schema, real Auth or production grants. Fresh regressions: **331 API/worker and 68 JavaScript tests pass**. No UI was changed in this storage checkpoint, so earlier screenshots do not verify generation-backed runtime behaviour.

Current official guidance was checked for invoker functions, schema qualification and execute grants: [Supabase database functions](https://supabase.com/docs/guides/database/functions). The [PostgreSQL minor-release breaking changes](https://supabase.com/changelog/postgres-15-19-17-11-breaking-changes) concern extensions/operators not introduced by this migration; target-version/platform qualification remains required.

## Required runtime continuation and closure gates

- [ ] Worker: acquire/renew a lease around bounded provider work; stage every enumerated classification and quote in memory; publish once. Remove direct enumeration/quote batch writes and unfenced market-state saves from the refresh path. Busy/expired ownership must not mark another run failed. Lost HTTP responses retry the same token/payload rather than creating a different generation.
- [ ] Readers: pin a validated generation header/pointer before ordered paging; validate row count, canonical identities and immutable metadata. Once a generation pointer exists, missing/incomplete rows must fail closed rather than silently fall back to legacy mirrors. Audit screener/facets/groups/search/status/capture readers and preserve separately qualified enrichment clocks.
- [ ] Pagination/export/capture: carry the same generation identity across requests; reconcile complete cohort and source/classification metadata. A cache may serve a labelled older coherent generation; it must not combine metadata from a different generation.
- [ ] Runtime tests: whole-batch/provider failure, newly enumerated cohort failure, overlapped cron/manual runs, expired lease during rate-limit sleep, uncertain publication response, pinned pages/export/capture across publication, and real PostgREST maximum payload/timeout behaviour. Existing partial-write expectations must be replaced by atomic preservation tests.
- [ ] Operational qualification: bounded retention/archival capacity for large generations, real normalized-row size/latency, target PostgreSQL/Supabase advisors/grants, provider US/HK contracts and source clocks. A successful requested-cohort publication still does not prove complete exchange coverage.
- [ ] Cutover: stop old/unfenced writers; install/verify additive migration, deploy compatible worker/API together, publish one qualified generation per market and verify consumers. Before a generation exists, legacy reads remain explicitly unqualified. Preserve saved definitions, 22 presets, watchlists, private lists and capture history.
- [ ] Rollback: retain immutable data and existing successful pointer. An old binary would revert to unpinned legacy readers/writers; do not describe that as a transparent safe rollback. Qualify a generation-aware rollback build and stop incompatible writers.

R01 remains open until all runtime and operational gates pass. R02–R15 and the original full-design/preservation/data/release requirements remain unchanged in the [current build-to-design plan](investment-workspace-current-gap-plan.md).
