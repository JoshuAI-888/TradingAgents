# Enabled MVP migration and cutover sequence

3 October 2026. This is a release dependency/runbook artifact, not permission to skip source or production acceptance. Cutover has started. Legacy universe and enrichment cron jobs are suspended. The server-owned access migration is applied and verified; generation/runtime/data acceptance remain pending.

## Migration set

| Migration | Enabled-path dependency | Release position |
| --- | --- | --- |
| `20261003105144_screener_generation_publication.sql` | Universe refresh fencing, immutable reader/export cohort | Required before current universe writers run |
| `20261003103407_server_owned_data_access.sql` | Existing provider caches, operational data and server analytics | Required remediation; preserve service access |
| `20261003105155_instrument_subtype_cache.sql` | Separate same-response subtype storage | Required if subtype cache/collector is enabled |
| `20261003105208_instrument_subtype_leases.sql` | Current subtype collector's fenced claim/save/release | Required with collector; cache migration alone is insufficient |

Normalized classification uses existing enrichment contexts when the separate subtype cache is disabled. That does not establish sufficient coverage: current nightly stock-only enrichment does not acquire every ambiguous trust/fund instrument. Do not omit subtype dependencies merely to avoid resolving ETF/REIT coverage. Choose the classification acquisition route only after fresh evidence shows it meets the US/HK contract. Unknown trust/fund categories must remain disclosed, rather than becoming inferred stocks or ETFs.

The private-list/history/review/capture/schedule/alias migrations are excluded from the enabled MVP sequence. Preserve their local source and historical records; neither hiding their navigation nor omitting activation authorizes deleting them. Read-only production inspection on 3 October verified that the recorded `20261002002748` investment-workspace SQL exactly matches the local SQL after comment/whitespace normalization. The local filename is aligned to that deployed timestamp; production history is unchanged. Do not push the entire directory indiscriminately.

## Local combination evidence

[Rehearsal results](mvp-migration-rehearsal.json) hash the four actual migration files. They install together on a new disposable PostgreSQL 16.14 database using synthetic baseline tables. Actual service-role generation begin/abort and HK subtype claim/release work with the combined schema. Service reads/writes and original rows remain intact; 36 direct browser reads are denied across server tables, views, generation tables and subtype cache. The test database was removed. The first harness attempt used the wrong abort signature; after correction the complete rehearsal passed. No production schema, data or platform grant is proven by this test.

## Ordered cutover

1. Inspect current production history, target PostgreSQL/platform behavior, table counts and advisors using the specifically authorized connection. Resolve the known history discrepancy and verify required baseline objects. Read-only production inspection is complete; target PostgreSQL is 17.6. Keep private inspection receipts outside this public repository.
2. Freeze the exact candidate commit, migration hashes, portal/worker artifact hashes and previous deployed commit/configuration. Keep extended workspace features and unqualified collector flags off.
3. Stop all legacy universe writers and universe cron launches before schema/runtime cutover. Do not let legacy and generation writers overlap. Leave prior successful cohorts intact and avoid exposing partial batches as current data.
4. Apply only the reviewed required migrations. Qualify actual service/API access and browser denials on the target platform. Apply both subtype migrations before enabling that collector if the evidence requires it.
5. Deploy the same candidate to portal and worker. Acquire qualified classification evidence and publish complete successful US/HK generations. Verify canonical IDs, raw/normalized classes, stock eligibility, unclassified counts, provider clocks and generation identity before turning recurring writers back on. An empty HK cohort cannot satisfy this gate.
6. Qualify the 20 provider presets against source requests/results and declared sorting; preserve the two unavailable RSI definitions. Check any outside-cohort membership and classification separately. Perform bounded like-for-like Moomoo checks without equating unmatched session/filter scopes.
7. Run production default/Clear/preset toggle, ticker/analysis/KLine/Back and actual page/all-loaded/selected CSV/Excel downloads. Reconcile rows/order/currencies/source times/generation and measure core desktop interaction latency. Verify served assets match the frozen candidate.
8. Enable reviewed US/HK schedules only after the first successful qualification. The blueprint's subtype schedule currently targets US and is disabled; HK acquisition requires its own qualified execution/configuration if using that route. Do not assume one market's collector covers both.

## Recovery

Pause new writers on failed publication or acceptance, retain the prior successful generation and its source clocks, and investigate the failed stage. The additive tables need not be deleted to restore a previous application release. Reverting the application/configuration requires checking reader/writer compatibility with any already published generation; old code may ignore generation pointers and read compatibility mirrors. Do not automatically restart legacy writers or describe the old release as source-qualified. Preserve acquired subtype evidence and existing saved screens. Never restore insecure anonymous writes as a rollback mechanism.

The local combined rehearsal reduces migration-interaction uncertainty. Target-platform compatibility, live coverage/preset accuracy, deployment access and exact-candidate smoke/rollback qualification remain open release gates.

## Cutover progress — 3 October

The access migration was applied through Supabase MCP as `20261003103407`; its SQL bytes are unchanged from the rehearsed `20261002142613` file (SHA-256 `4f773b1d4c9c3b85ec5592448d896cbc89d8aec68ac156cbe100ddef238215e8`). Local filenames and executable contract references now match production history; the historical rehearsal receipt retains its original name. Target checks verified RLS and denied anon/authenticated SELECT on all 12 tables, retained service CRUD grants, denied browser SELECT on all three views, retained service SELECT, and security-invoker on both regular views. Actual service-role count reads succeeded. Security advisors no longer report the 12 RLS-disabled tables, two definer views, or public materialized view. Existing unrelated warnings remain outside this cutover.

Automatic approval review rejected suspension of the shared worker because of possible analysis interruption. It is still running; no queued/running universe job was present at preflight, but that does not prevent a future request. Explicit interruption approval has been requested. Do not bypass this rejection or run generation publication until the legacy queue consumer is fenced. Portal and worker are still on the previous release. Both cron schedules remain suspended pending continuation.

User explicitly approved the shared-worker interruption on 3 October. Worker suspension is verified. Generation publication and both subtype migrations are applied with unchanged rehearsed SQL, recorded respectively as `20261003105144`, `20261003105155`, and `20261003105208`. Production service-role generation begin/abort and HK subtype claim/release succeeded inside rolled-back verification transactions. Runtime deployment and source/data acceptance are next.
