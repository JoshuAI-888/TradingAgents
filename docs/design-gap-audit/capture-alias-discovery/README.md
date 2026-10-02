# Scoped merged history discovery primitives

Local checkpoint, 3 October 2026. The primitives are implemented and verified; the existing UI/Changes/review routes are not yet connected to them, so the observed equivalent-filter history defect remains open.

CLI-generated migration `20261002122855_screen_capture_alias_discovery.sql` adds two server-only security-invoker RPCs with empty search paths. Metadata discovery joins the exact requested raw key with mappings that match namespace, identity version, digest and canonical screen. It returns at most limit + 1 rows with bounded offset, deterministic descending capture-time/ID order, an original representative history key and duplicate-copy count. Requested original key is preferred when it contains the capture. It avoids returning observation payloads for timeline paging.

Detail discovery resolves one ID in one SQL statement, returns one original payload and compares all candidate duplicate payloads exactly. A divergent copy sets `conflicting:true`; the Python adapter rejects it before any membership/review inference. Identical payload copies can share one metadata entry. The adapter also validates response cardinality, namespace, IDs, metadata types/times/order, supplied semantic identity and alias-definition compatibility. Unknown legacy records remain discoverable only through their requested original key, rather than receiving inferred semantic scope.

The raw history key remains necessary for existing review-note foreign keys. The current review schema requires both captures to belong to the same original key. No notes, keys, captures or definitions were remapped in this packet. A merged timeline is discovery, not authorization to silently move notes or qualify a cross-key pair review.

## Verification

- Full API/worker suite: **695 passed**; focused discovery adapter suite: **18 passed**; `git diff --check` passes. No UI/static changes; preceding 152 JavaScript checks apply.
- Actual rollback-only PostgreSQL [contract](../../../web/api/tests/capture-alias-discovery-db-contract.sql) verifies 105 alternating-key captures plus identical/divergent duplicate cases: bounded 101-record first page, seven-record final page after deduplication, deterministic order, original requested-key preference, exact duplicate versus conflicting detail behavior, separate-namespace exclusion, incompatible canonical-definition exclusion and browser-client execute-grant denial.
- Separate native query confirms discovery RPC and fixture records rolled back (`t|t`). No production schema or data changes occurred.
- Python adapters reject duplicated/unordered/oversized/nonlist metadata, invalid dates/types, wrong namespaces/record IDs/payload IDs, divergent evidence, semantic identity tampering, incompatible definitions and unconfirmed detail cardinality. These are storage-adapter/native contracts, not actual PostgREST/browser acceptance.

## Next integration and remaining qualification

1. Connect bounded metadata/detail discovery behind the default-off rollout flag, retaining legacy raw-key fallback and selected-pair metadata across pages.
2. Bridge only corresponding semantically equivalent criterion slots; replay each v3 capture against its own original immutable definition, without relabelling or replacing captured observations. Preserve window ordering and monetary/unit/time protections.
3. Use the original common history key for existing same-key pair reviews and saves. Add an explicit qualified cross-key pair contract before enabling notes on cross-key captures; do not reuse the requested definition's new hash or silently lose old notes.
4. Verify UI-created labelled/null-bound screen versus minimal deep link, actual comparison ordering, private notes/conflicts, selected/bulk handoffs and downloaded membership. Add separate verified-owner schedule aliases.
5. Qualify real Auth/PostgREST, concurrent publication/discovery, large-history duplicate resolution and p95 query/UI performance, advisor checks, backfill coverage, cutover and rollback. All overall gates remain open; discovery rollout remains off.
