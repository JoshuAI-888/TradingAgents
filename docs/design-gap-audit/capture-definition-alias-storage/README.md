# Manual capture alias storage and atomic writer

Local checkpoint, 3 October 2026. The equivalent-filter history-discovery defect remains open; this packet implements its storage/write foundation, not backfill or merged timeline reads.

## Implemented

CLI-generated migration `20261002121721_screen_capture_definition_aliases.sql` adds a version-1 SQL normalizer and immutable manual-capture mapping table. SQL normalization independently removes only `_label` and null bounds, retaining ordering/zero bounds/windows. Each mapping references an exact immutable `(history_key, capture_id)` anchor and proves the canonical screen against that anchor. Owner namespace is derived from the existing raw history key and constrained to match it. An index supports namespace/version/digest/key lookup.

This namespace is the existing **deployment-shared manual history** namespace. It does not convert shared history into authenticated-owner data, and it does not include private scheduled captures. Browser-client roles have no table/RPC grants. RLS is enabled with no client policy; functions use security invoker and an empty search path. The trusted server computes the Python digest, while SQL independently checks the supplied canonical definition. Digest metadata never grants ownership or authorizes a history merge.

`screen_capture_append_with_alias` atomically calls the existing append RPC and registers the alias. Conflicting canonical mappings roll back the whole append. Exact retries confirm the original capture and mapping without duplication. Original raw keys, definitions, capture IDs and review scope remain intact. The API writer selects the new RPC only when `CAPTURE_DEFINITION_ALIASES_ENABLED=1`; the default remains the original append path. The flag is off and no production schema/runtime change occurred.

## Evidence

- Full API/worker suite: **661 passed**. `git diff --check` passes. No static/UI code changed; preceding 152 JavaScript checks apply.
- Actual PostgreSQL 16 rollback-only [contract](../../../web/api/tests/capture-definition-alias-db-contract.sql) passes migration creation, service-role append/register, idempotency, two separate deployment namespaces, original definition preservation, conflicting mappings, rejected mismatched/cross-key anchors and rollback of failed atomic publication. It also checks RLS/grants and update/truncate rejection. The fixture digest is deliberately synthetic: native SQL verifies structural attribution and grants, not the Python serialization algorithm.
- Separate native post-test query confirms both alias schema and fixture captures were rolled back (`t|t`). The test did not mutate production or leave local qualification state behind.
- Python tests verify default-off routing, enabled canonical parameters without raw evidence mutation, tampered identity rejection before RPC, and actual capture-builder/API writer wiring with idempotent retry. The fake checks route wiring only; native SQL supplies transaction evidence.

Reference review used [Supabase's changelog](https://supabase.com/changelog) and [RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security). The recent extension/operator upgrade notice does not introduce an extension/operator dependency in this migration. The earlier database-advisor authorization remains pending; advisors were not retried and this migration is not marked advisor-qualified.

## Remaining build and qualification

1. Add resumable, bounded backfill for provable existing immutable definitions, retaining unknown legacy records separately.
2. Add bounded indexed timeline discovery across equivalent raw keys; prove identical capture-ID deduplication and reject divergent same-ID evidence without silently truncating history.
3. Bridge corresponding raw criterion slots only after exact semantic equivalence, retaining raw captured evidence and pair review scope. Preserve existing notes, selections and downloads.
4. Implement separate authenticated-owner schedule alias mapping with verified sessions, owner fencing and pinned original schedule hashes/revisions; never reuse manual deployment namespaces for it.
5. Qualify concurrent backfill/new captures, actual PostgREST and Auth/grants, device/browser continuity, latency/query limits and rollback; then cut over. All R04/R06/R10/R15 and overall gates remain open.
