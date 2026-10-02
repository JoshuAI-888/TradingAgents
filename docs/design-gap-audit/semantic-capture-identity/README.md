# Additive semantic capture identity

Local implementation checkpoint, 3 October 2026. This begins the [compatibility migration](../criterion-sort-qualification/definition-compatibility-plan.md); it does not yet resolve equivalent-filter history discovery.

`screen_definition_identity.py` derives a versioned SHA-256 identity from a deep copy of the complete screen definition. Version 1 removes only criterion `_label` and null `min`/`max`. It preserves filter ordering, repeated slots, every other criterion key, currency, exclusivity, periods/windows and all screen scope fields. Nonfinite or non-JSON definitions cannot obtain an identity. No raw definition is edited.

The actual shared capture builder adds `definition_identity` to new v2/v3 captures. Original raw history keys, schedule definition hashes, capture IDs and review pair keys stay unchanged. Older captures without this optional metadata remain valid under their existing contracts. Supplied wrong/extra/malformed identity metadata is rejected in v3 replay and the shared manual/private comparison engine before membership inference. This digest is metadata, not ownership, authorization, financial validity or permission to merge histories.

## Verification

Full API/worker suite: **657 passed**. `git diff --check` passes. Tests establish equivalent UI-label/null-bound identities without mutating the original; distinct actual bounds/currency/windows/scope/exclusivity/unknown semantic keys; preserved duplicate/window ordering; all 22 original preset keys/rules/sorts untouched; rejection of nonfinite definitions and tampered identity metadata; and v2/v3 comparison rejection before membership inference. The actual private capture builder/HTTP entry-exit test now verifies persisted identity metadata while retaining exact before/after criterion sorting and pagination.

No static/UI assets changed in this checkpoint; preceding JavaScript suite remains 152 passed. No new browser or live vendor claim is made. No database schema or production deployment was changed.

## Next required implementation

Build the owner-scoped alias storage/backfill and indexed bounded discovery; retain exact legacy raw keys and pinned schedule envelopes. Prove alias paging, raw-slot evidence mapping, notes/selection/export continuity, two-owner/account-switch isolation, concurrent publication/backfill and reversible cutover through real Auth/PostgREST. Ambiguous legacy definitions remain separate. R04/R06/R10/R15 and all overall gates remain open.
