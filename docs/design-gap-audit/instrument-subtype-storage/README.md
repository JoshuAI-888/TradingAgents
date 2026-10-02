# Dedicated subtype cache: local storage and publication qualification

This supersedes the preceding collector checkpoint's unbuilt durable-cache and reader statements. Collection job orchestration, true overlapping-worker qualification and production activation remain open.

## Contract

CLI generated `20261002131807_instrument_subtype_cache.sql`. The dedicated US/HK table has RLS enabled, no browser grants or policies, and service-role SELECT/INSERT/UPDATE only. The service-only save RPC uses SECURITY INVOKER and an empty search path. No security-definer privilege escalation or Auth/user-metadata decision exists.

Each canonical code has one revisioned cache record. Expected revision prevents stale publication; same expected revision and exact resulting record replay returns the existing receipt without incrementing the revision. The guard requires exact bounded subtype context, canonical/provider identity, aware retrieval/attempt clocks, forward-only attempt chronology, revision increment and preservation of old evidence/date on failed refresh. Generation snapshots are separate and remain immutable.

Python reads are ordered and bounded with a 20,001-row sentinel. Readers validate full evidence and reject invalid clocks/identities/revisions; publications validate the complete bounded batch before sending individual revisioned writes. Individual per-instrument commits are intentional: no all-market completeness claim derives from a partial collection run. Transport failures propagate; orchestration must retain/retry original bodies where required, rather than silently declaring completion.

`INSTRUMENT_SUBTYPE_CACHE_ENABLED=1` adds dedicated fresh contexts to the already default-off normalized universe path. When valid enrichment and dedicated subtype contexts exist, the newer same-provider receipt wins. Neither original store is mutated. Missing/stale subtype evidence cannot qualify a trust/fund category as stock. When the flag is absent, no dedicated storage read occurs.

## Verification

- Native rollback-only `instrument-subtype-store-db-contract.sql`: create migration, service-role insert, exact insert/update replay, failed-refresh original-date retention, stale revision denial, older attempt denial, mismatched Yahoo identity denial, RLS and browser/service grants, final ROLLBACK. A separate cleanup query returned `t|t`, proving both table and save RPC absent afterward.
- `test_instrument_subtype_store.py`: bounded validated adapter read/publish/replay/conflict, stale-cache exclusion, clone isolation, invalid rows/scope/revisions, actual collector → cache adapter → universe generation → stock-only API handler inclusion, newest receipt selection and default-off storage isolation.
- Previous collector's eight tests remain binding for rotation, cooldown, type-only payload and unknown-type non-inference.

Full local API/worker suite: **722 passed in 6.72 seconds**. `git diff --check` passes. JavaScript was unchanged and retains its previous 155-test checkpoint.

These checks prove local storage and handler integration. They do not prove real PostgREST/Auth routing, vendor full-market membership, overlapping native worker timing or deployed collection reliability.

## Documentation and release constraints

Reviewed official [function privileges/invoker documentation](https://supabase.com/docs/guides/database/functions) and [RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security), and fetched the official changelog index. The recent PostgreSQL minor-release entry concerns ltree/pgcrypto/btree_gist/custom operators; none are introduced here. No production schema change occurred.

Supabase advisor execution remains pending the earlier explicit approval request: automatic approval review rejected the prior command because it could transmit schema/connection metadata. It was not retried or bypassed. Native checks do not substitute for that release requirement.

## Remaining checklist

- [x] Local separate default-off [collection entry and hard process/run deadlines](../instrument-subtype-job/README.md). Distributed leases and deployed schedule/runtime qualification remain open.
- [ ] True concurrent native save/uncertain-transport/restart qualification and runtime dependency checks.
- [ ] Real platform/PostgREST/grants and advisor qualification; deployment migration and rollback.
- [ ] Fresh raw basic-info and full-market subtype coverage; equivalent-universe Moomoo reconciliation.
- [ ] Fresh browser exports, exact generation cutover/rollback and responsiveness acceptance.

Both collection-cache reading and normalized classes remain default-off. All overall R01–R15 gates remain open; no merge/deploy.
