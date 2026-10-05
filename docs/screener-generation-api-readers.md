# Generation-consistent API reader checkpoint

Local progress, 2 October 2026, following worker commit `fe7f703`. R01 remains open. No UI code, production migration, merge or deployment changed here.

## Implemented

The stored-universe loader resolves market state on every request. If a generation pointer exists, it validates the immutable header, exact row count, canonical identities, classifications, timestamp bounds and cohort fingerprint through the shared reader. It verifies the current success clock/count receipt, including JSON value types. Missing/corrupt pointers or generations return HTTP 503 without falling back to retained legacy rows or a live provider.

Immutable contents are cached by market + generation identity with a bounded four-entry process cache. Callers get deep copies. Generation metadata overrides quote classification and plate fields; legacy metadata caches cannot alter that cohort. Requests made before any generation pointer retain the migration-compatible legacy reader.

The whole-market screener bypasses old whole-market TTL payloads, reads stored generations without requiring live-provider credentials, and returns `generation_id` even for zero filter matches. An explicit `generation_id` pins subsequent server pages or CSV/SpreadsheetML downloads to that original market cohort. Both download formats expose `X-Screener-Generation`; rows carry the generation ID. A watchlist request rejects explicit market generation IDs.

Facets, preset previews, group summaries and Settings coverage counts now derive the published cohort rather than all historical mirror rows. Preset/group cache keys include generation identity; state validation occurs before those cache hits. Group summaries expose generation identity. Preview rules/financial approximations, enrichment consistency and unsupported factors remain separate correctness gaps, not closed by cohort pinning.

## Verification

Full suites pass **360 API/worker tests and 68 JavaScript tests**. Thirteen new API tests verify a publication between pages, old-generation pinning, zero-result/export identity, market isolation, corrupt/missing rows/header/fingerprint/classification/clock, cache mutation isolation, metadata authority, 1,201-row cohort retention, coverage/group legacy exclusion and validation before cached previews.

The actual API loader also read the 401-row generation published by the actual worker in the isolated PostgreSQL 16.14 test database. [Native evidence](design-gap-audit/generation-reader-checkpoint/native-reader-evidence.json) confirms exact membership/classification, historical legacy exclusion and protected cached contents. [Reproduction script](../web/api/tests/generation-reader-contract.py) accepts no production parameters and uses the fixed test-socket adapter; it performs no provider requests or database mutations. This verifies native reader integration, not PostgREST transport or production behavior.

## Next required work

- [ ] Update remaining direct compatibility readers, particularly preset execution quote filling and canonical symbol/search hints. Preserve provider execution membership separately from the stored generation; label live outside-cohort fills and avoid implying one financial/source generation.
- [ ] Retain generation identity in captures and their provenance contracts; exercise publication during capture and exact export/capture membership.
- [ ] Carry generation identity through frontend server paging, reload and explicit download flows. Browser downloads must reconcile files/headers/rows under concurrent publication; API tests alone do not qualify the UI.
- [ ] Decide and qualify enrichment snapshot/period/currency policy independently of the immutable cloud quote cohort.
- [ ] Qualify real PostgREST grants/schema cache/paging/payload/timeout/retry behavior, bounded retention with active readers/history references, and migration/cutover/rollback. The isolated native server does not prove these gates.
- [ ] Complete R02–R15: live provider coverage and Moomoo membership, original feature preservation, full mockup workflow, Auth/team roles, schedules, devices/accessibility/performance/analyst tasks and production release checks.
