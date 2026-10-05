# Compatible capture routes and export provenance

Local checkpoint, 3 October 2026. This packet supersedes the earlier discovery-only checkpoint; it does not close an overall release gate.

## Implemented behavior

With `CAPTURE_DEFINITION_ALIASES_ENABLED=1`, manual snapshot history and Changes discover captures whose definitions differ only in UI `_label` and null bounds. Each capture validates against its original definition before comparison. Original criterion slots, raw observations and original history keys are retained. Numeric evidence/sort qualification accepts equivalent corresponding criteria without changing currency, windows, units or attribution. All 22 preset definitions remain preserved.

Private pair notes on a common original key save and reload under that original key. Public comparisons between different original keys remain readable, but private review is explicitly unavailable: the existing same-key foreign-key contract must not silently migrate old notes. Changed semantic definitions, divergent duplicate payloads and unavailable storage reject inference.

Comparison responses, client CSV and scheduled CSV/SpreadsheetML append both original definitions, optional versioned identities and original/manual review-key metadata. Scheduled private exports leave shared-history identifiers blank.

## Evidence

- `test_capture_alias_routes.py`: actual capture builder plus HTTP history/Changes/review routes; common-key continuity, cross-key unavailable/save rejection, discovery conflict and storage failure. Alias adapters are injected, so this is not native RPC or PostgREST evidence.
- `test_scheduled_exports.py`: parsed CSV and SpreadsheetML preserve both root definitions and versioned identities; private scheduled evidence does not acquire manual-history identifiers.
- Full API/worker suite: 702 passing tests. JavaScript suite: 153 passing tests.
- [UI-created filter](01-ui-created-filter.png): Price maximum 10 entered through Add filter, then Changes; decorated definition discovers original minimal captures. Each has 107 members, union 108, one entry, one exit, 106 unchanged. Captured entered-stock price is USD 12 before / USD 8 after.
- [Actual downloaded CSV](02-downloaded-comparison.csv) and [parsed validation](02-download-validation.json): exact US.S0001 new-match row; requested decorated definition versus both original minimal definitions; original common key; USD observations and raw criteria retained. Legacy absent identity stays blank. Browser download observation timed out, but the actual newly saved file was found in Downloads and parsed; no server-generated substitute was used.
- [Final view after export](03-export-verified-view.png): collapsed menu and same committed comparison. Temporary viewport override reset.

Browser uses local synthetic generation/observation/private-history/alias-discovery fixture flags on port 8906. Discovery fixture synthesizes equivalent candidates from fake immutable captures. Native rollback-only storage/backfill/discovery contracts are documented in preceding packets; this browser run does not qualify real Auth, provider values, production backfill or platform RPC exposure.

## Remaining acceptance work

Cross-key private review schema/continuity, owner-scoped scheduled aliases, real PostgREST/Auth, production backfill/cutover/rollback, maximum-size history/export/performance and fresh provider/session/Moomoo reconciliation remain open. Flag stays off by default. No production migration, merge or deployment occurred. All R01–R15 overall gates remain open.
