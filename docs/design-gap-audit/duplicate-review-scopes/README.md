# Original private review variants across duplicate capture histories

Local discovery primitive; the subsequent [integration checkpoint](../duplicate-review-integration/README.md) connects routes, inspector scope choices and CSV. This does not close duplicate-note continuity or any overall release gate.

## Observed gap and contract

Alias discovery chooses a duplicate capture representative by requested raw history key. Switching an equivalent screen's labels can change that representative. Existing private notes under a different original same-key or cross-key anchor can therefore become invisible to the current review lookup.

CLI-generated `20261002134257_duplicate_capture_review_scopes.sql` adds a service-only SECURITY INVOKER/empty-search-path resolver and owner/capture/code indexes. It verifies the selected pair's completeness, chronological order, version, namespace, alias identity/digest/canonical definition and each original definition before discovering variants. Unmapped/unprovable target scope returns explicitly unqualified, allowing later integration to preserve the legacy original-key path rather than fabricate aliases.

Discovery joins owner-private original notes to both exact original immutable capture payloads. Only exact before/after copies with matching qualified namespace/canonical scope and actual instrument membership qualify. Each note retains its original previous/current history anchors, revision, status, timestamp and contract. Other owners, namespaces and divergent payloads are excluded. No note is moved, merged, renumbered or silently selected; separate same-code variants remain separate even when display representatives differ.

The response has a 40,001-row sentinel. The Python adapter rejects over-bound, malformed, out-of-owner/namespace, wrong-pair, duplicate-anchor, unordered, invalid-content or clock responses before returning grouped variants and explicit ambiguous codes. It deep-copies returned evidence. Browser roles cannot execute the RPC.

## Evidence

- `duplicate-review-scopes-db-contract.sql`: rollback-only native PostgreSQL verifies another selected duplicate representative still discovers original revision-2 note, separate revision-1 cross-anchor note and another instrument's same-key note. Other owner/namespace/divergent copies do not appear. Existing stored note is unchanged; reversed pair is unqualified and namespace escape denied. Browser RPC grants are denied.
- Separate cleanup query returns `t|t`: resolver and supporting original-review index absent after rollback.
- `test_review_scope_variants.py`: preserves original anchors/revisions and explicit ambiguity, verifies clone independence, strict owner/pair/namespace/content/clock checks, 40,001 rejection, duplicate/order rejection, unqualified-response rules and no-read invalid inputs.
- Full local API/worker suite: **746 passed in 8.12 seconds**. `git diff --check` passes. UI is unchanged and retains the preceding 155-test checkpoint.

## Remaining implementation and acceptance

- [ ] Connect qualified variant discovery to private comparison read/filter/fingerprint/export without changing raw capture representatives.
- [ ] Preserve unique original note anchors for reads and CAS saves; a changed label must not create a replacement note under a different key.
- [ ] Present multiple variants explicitly in the inspector; require an explicit scope choice before editing and keep independent drafts/revisions.
- [ ] Carry review anchors into comparison exports; do not imply a note was recorded against a different raw history pair.
- [ ] Account/source/late-response fences, stale draft recovery, beyond-page review behavior and actual browser/download qualification.
- [ ] Full platform/Auth/permissions/advisors/migration/performance/backfill/cutover/rollback qualification.

No new table/grant to browser roles, production write, merge, deployment, alias cutover or note migration occurred. Advisor execution remains pending the earlier specific approval requirement and was not retried.
