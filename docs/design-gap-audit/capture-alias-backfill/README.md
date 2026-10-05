# Bounded resumable manual-capture alias backfill

Local checkpoint, 3 October 2026. Equivalent-filter history discovery and rollout remain open.

CLI-generated `20261002122251_screen_capture_alias_backfill.sql` adds a service-only metadata RPC and an indexed namespace/key/ID access path. The RPC returns at most page size + 1 records, scoped to one existing deployment namespace; it projects definition/identity metadata rather than complete observation payloads. A cursor must belong to the same namespace. Browser-client roles have no execute grant.

The Python backfill reads one bounded page, validates strictly ordered unique IDs before any registration, requires a complete original ScreenDefinition rather than inferring missing scope defaults, validates optional semantic identity and rejects oversized/nonfinite definitions. Unknown legacy or inconsistent definitions count as unprovable and remain unmapped; original captures/keys are untouched. Eligible definitions use the previously verified idempotent registration RPC. A conflicting mapping or unconfirmed result interrupts the page without claiming completion.

The operator is dry-run by default and derives its namespace from the configured deployment owner, not a browser request. `--apply` requires a durable checkpoint path. Each completed page saves counts/cursor using a temporary file, file fsync, atomic replacement and directory fsync. A failed page replays from the prior checkpoint; prior registrations are idempotent. Checkpoints validate namespace, cursor, version, types and count consistency even when marked scan-complete. Raw definitions, provider observations, credentials and storage exceptions are not printed.

Concurrent old writers can import records behind a keyset cursor. The operator explicitly supports `--restart` for a full rescan after old writers drain and atomic alias publication is enabled. It always reports `cutover_qualified:false`; a finished scan cannot prove complete migration coverage or real platform acceptance.

## Verification

- Full API/worker suite: **677 passed**; focused backfill/operator suite: **16 passed**; `git diff --check` passes. No static/UI changes; preceding 152 JavaScript checks apply.
- Actual rollback-only PostgreSQL [contract](../../../web/api/tests/capture-alias-backfill-db-contract.sql) verifies 205 captures across 20-row pages, correct next/final cursors, other-namespace exclusion, bounded limit, malformed/cross-namespace cursor rejection, metadata projection, server-only grants and the paging index. A separate native query confirms RPC and fixture rows were rolled back (`t|t`).
- Python tests cover dry-run nonmutation, retries, unknown legacy/tampered identities, inconsistent/duplicated/oversized pages, partial-page interruption, checkpoints across runs, late imports requiring restart, namespace/count/type corruption and interrupted checkpoint replacement cleanup.
- Operator `--help` runs. No production backfill or real PostgREST/Auth execution occurred. Native SQL and fake adapter tests do not prove deployed REST projection, query limits, large-history latency or full coverage. Advisor authorization remains pending; no advisor retry occurred.

## Operator sequence after platform qualification

From the repository root, with the existing server environment and `PYTHONPATH=web/api:web/worker`, run `python -m tradingagents_api.capture_alias_backfill` for a bounded dry-run. Review eligible/unprovable counts. For the authorized migration, add `--apply --checkpoint /absolute/path/progress.json`; rerun that command to resume. Use `--max-pages`/`--page-size` to bound each run. Once old append writers drain, rerun with `--restart` and the same checkpoint, then reconcile mapping coverage. These steps never enable the discovery flag themselves.

Next: implement bounded indexed merged history discovery and divergent duplicate-ID rejection; bridge only semantically proven raw criterion slots; retain original pair review/selection/export scope; add separate verified-owner schedule aliases; qualify actual platform/browser/performance/cutover. All overall gates remain open.
