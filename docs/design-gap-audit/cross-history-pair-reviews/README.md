# Cross-history private pair review contract

Local checkpoint, 3 October 2026. Native, HTTP and synthetic browser/download qualification; not production acceptance.

## Implementation

CLI-generated `20261002124757_cross_history_pair_reviews.sql` adds a separate owner-private table with two original history keys, two capture IDs and canonical code in its primary key. Each side has an immutable-capture foreign key. The same deployment namespace, distinct keys/IDs, note bounds/status/revisions and owner RLS are enforced. Existing same-key notes/table/RPCs are unchanged; no note migration or inferred ownership occurs.

Service-only security-invoker save/read RPCs use empty search paths. Save verifies both mappings share canonical definition, digest/version and deployment namespace; it independently normalizes each exact capture definition, checks completeness/version/chronology and actual pair membership. Revision zero creates, stale creates/edits return no row. The API still performs full replay and attribution validation before invoking storage. Read uses one statement and a 40,001-row sentinel; existing API rejects excessive scope instead of silently returning a partial review.

`CROSS_HISTORY_PAIR_REVIEWS_ENABLED=1` enables the separate route contract after alias discovery. Default is off. Common-key pairs retain old storage. Cross-key pairs use a tuple of original keys internally, expose `review_contract: cross_history`, retain a null common `review_history_key` and use existing private-capture review controls/filters/revision fingerprints. Browser ownership comes from verified server auth, never a request-supplied owner. Review revisions now reject boolean/string coercion.

## Verified evidence

- `cross-history-pair-review-db-contract.sql`: actual rollback-only local PostgreSQL; save/reload, stale create/edit, two owners, reversed/absent-member rejection, deployment namespace fence, later changed definition despite valid history mapping, existing same-key note/revision preservation, RLS and client grants. The first added legacy-read assertion exposed that this isolated baseline lacks the later legacy read RPC; the final contract verifies unchanged legacy records directly. Final native contract passes.
- `test_capture_alias_routes.py`: actual capture builders and HTTP routes with injected discovery/storage adapters; enabled cross-key save/reload/filter/CAS, original-key preservation, no old note calls, owner switch, strict boolean revision rejection. Default-off unavailable/save-rejection case remains covered.
- Full API/worker suite after strict revision edit: 703 pass. JavaScript suite after reload freshness fix: 154 pass.
- Native schema and fixtures rolled back; separate cleanup query confirms new review and alias tables absent.

## Browser/download and recovery follow-up

Local port 8907 uses the current API/UI and optional `RESEARCH_CROSS_HISTORY_REVIEW_FIXTURE=1` with synthetic Auth, alias discovery and in-memory notes. Before captures retain the minimal rule; after captures carry UI label/null-bound decoration under a different raw history key. This is not real vendor/Auth/PostgREST evidence.

Actual browser sign-in, note save/reopen and explicit Reload retrieve revision 1. A second synthetic actor edits through the same HTTP endpoint. A stale browser save returns conflict without replacing its draft. [Initial recovery](01-conflict-recovery.png) exposed stale table review status after inspector reload. The UI now refreshes the current cohort and review fingerprint on Reload while preserving the note/status draft; a regression exercises removal/count refresh under a reviewed-only filter. Asset fingerprint is `20261003-review-refresh1`.

[Fixed recovery](02-fixed-refresh.png) shows latest revision 3 alongside the retained draft and refreshed table status. Saving that draft succeeds at revision 4. [Actual browser CSV](03-downloaded-comparison.csv) and [parsed checks](03-download-validation.json) contain exactly US.S0001, revision 4, the exact note, private scope/fingerprint, distinct original before/after history keys, blank common key, both original definitions and captured USD 12 / USD 8 observations. File was verified in Downloads, not replaced with a direct server export.

[390 × 844 phone review](04-phone-review.png) contains the saved draft/evidence. Inspector width/scrollWidth are both 389 px; Save, Reload and Next unreviewed each measure 44 px tall. Temporary viewport reset; synthetic tab retained for further qualification.

## Open qualification

Broader device/account/full-filtered and interrupted-download cases; real Auth/PostgREST/schema deployment; duplicate-ID representative continuity; maximum-size reads/downloads/performance; separate owner-private scheduled aliases; advisor/platform/backfill/cutover/rollback and all R01–R15 gates remain open. The feature is not enabled in production. The prior advisor action remains pending explicit permission after automatic approval rejected potential schema/connection metadata transmission; it was not retried or bypassed.
