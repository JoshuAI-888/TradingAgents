# Enabled MVP migration and cutover sequence

3 October 2026. This is a release dependency/runbook artifact, not permission to skip source or production acceptance. Cutover has started. Legacy universe and enrichment cron jobs are suspended. All four required migrations and service-role access checks are verified. Portal and worker are live on the reviewed release; data and end-to-end acceptance remain pending.

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

Automatic approval review initially rejected suspension of the shared worker because of possible analysis interruption. The user subsequently explicitly authorized that interruption. Suspension and replacement of the legacy consumer were verified; both recurring screener services remain suspended pending source qualification.

User explicitly approved the shared-worker interruption on 3 October. Worker suspension is verified. Generation publication and both subtype migrations are applied with unchanged rehearsed SQL, recorded respectively as `20261003105144`, `20261003105155`, and `20261003105208`. Production service-role generation begin/abort and HK subtype claim/release succeeded inside rolled-back verification transactions. Runtime deployment and source/data acceptance are next.

Portal and worker successfully deployed `b8223b1f6f92c77b743ed0ed1866023386fb6d08`. All seven exact-candidate CI jobs passed. The first US generation refresh found invalid legacy index IDs and correctly refused publication. A forced **first** generation can now rebuild membership from the provider without trusting invalid legacy mirrors; existing published generations still require intact metadata. Regression coverage proves normal refresh refusal and fresh canonical publication. HK initial enumeration is underway. Neither a queued refresh nor provider traversal progress establishes a qualified published generation.

### Existing-resource US/HK scheduling

`market_cron` routes the existing universe and enrichment services by UTC session; it ignores the legacy fixed US market environment variables. Configure universe command `cd web/worker && python -m tradingagents_worker.market_cron universe` with schedule `0 1-8,13-21 * * 1-5`, and enrichment command `cd web/worker && python -m tradingagents_worker.market_cron enrich` with schedule `45 8,21 * * 1-5`. Off-window/weekend manual runs fail closed unless an explicit `--market US|HK` override is provided. This replaces the proposed separate HK cron resources. Enable only after both first generations qualify, and verify deployed cron artifacts before resuming.

Worker auto-deploy is temporarily disabled to avoid interrupting an active refresh while preparing its recovery patch. Restore the recorded setting after controlled deployment and acceptance.

### Alternate provider screening acquisition

The initial HK plate traversal failed after three attempts: the provider returned `response transform failed`, with one HTTP authorization failure. No partial generation was published. The existing read-only stock-screen route returned explicit pagination totals of HK 2,825 and US 9,421; the current Moomoo US default page also showed 9,421, superseding the earlier session's 12,141 reference count. Source totals are session-specific, not fixed acceptance constants.

An opt-in `UNIVERSE_ENUMERATION_MODE_US=screen` / `UNIVERSE_ENUMERATION_MODE_HK=screen` mode traverses the whole-market screener until the provider explicitly reports exhaustion, with stable total and exact unique canonical membership. Classification and quotes must still qualify before atomic publication. Its scope is `exhausted_provider_market_screen`; it does not prove complete exchange coverage or an ETF catalog. Plate mode remains available. Switching modes must not be presented as recovering a complete plate union. Missing pages, repeated/nonadvancing cursors, duplicate IDs, changed totals and provider errors retain the previous generation. The alternate scope needs live qualification before schedules resume.

The live legacy US page exported 500 rows as both CSV and SpreadsheetML `.xls`; the parsed records matched exactly, matched visible symbol order, retained unique canonical codes and market-cap descending order. Missing currency evidence stayed `Unavailable`. These are actual production downloads, but do not qualify the pending first generations. All 20 preset endpoints responded in US; 18 responded in HK, with two temporary provider rate-limit responses awaiting a paced recheck. Both preserved RSI definitions remained explicitly unavailable in each market.

A controlled rollout race left a refresh claimed by the retiring worker. Its specific generation lease was explicitly aborted and its job cancelled after confirming a different active worker. No generation was published. Recurring services remain paused. Background acquisition now supports bounded request spacing (`UNIVERSE_REQUEST_SPACING_SECONDS=2` for this cutover), following [Moomoo's batching/staggering/backoff guidance](https://open.moomoo.com/api/overview/rate-limit). HTTP 439 is not documented there and is not silently reclassified as a normal quota response; further provider failures must remain visible.

The library's initial render now says `Loading…` instead of `0 screens`. Failed definition retrieval preserves existing definitions and offers `Retry screen library`, which bypasses the failed panel cache. The updated asset has a distinct cache version.

Daily subtype collection now shares the existing US/HK enrichment router, preceding its factor acquisition for the same explicit market. Its own default-off collection flag, deadline, attempt budget, child process isolation and market lease are retained. Enable `INSTRUMENT_SUBTYPE_COLLECTION_ENABLED=1` on that service only after live qualification. No separate subtype cron resource is needed. Worker acquisition uses normalized classes and the installed subtype cache for new generations; initial unresolved trust/fund subtypes remain `UNKNOWN` until acquired and republished.
