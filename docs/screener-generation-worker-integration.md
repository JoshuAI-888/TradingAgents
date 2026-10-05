# Screener generation worker integration

Local checkpoint, 2 October 2026, following storage commit `7989c32`. The refresh worker now stages the complete classified cohort in memory and publishes through the fenced generation RPC. It no longer writes quote batches or enumeration metadata directly. **R01 remains open:** API readers still use compatibility mirrors, and production migration, PostgREST, retention and cutover are unqualified.

## Verified behavior

- Acquire a unique run token and market lease before collection; renew around provider calls and every 30 seconds during rate-limit waits. A wait is bounded to 900 seconds per provider operation and a run to 7,200 seconds. The loader disables the cloud client's internal retries so those sleeps cannot silently bypass renewal.
- Enumeration returns staged metadata. Every quote batch must return exactly its requested canonical identities. Only the complete payload publishes. A later batch failure preserves prior successful quotes, metadata, enumeration/success clocks and generation pointer.
- Quote-only refreshes read the immutable base generation and validate its header, identities, row count, fingerprint, metadata and timestamps. Historical compatibility rows do not enter the next cohort. A present but invalid generation pointer fails closed rather than falling back to legacy rows.
- Transport retries repeat the same RPC token and payload once. A response lost after commit returns the original SQL receipt on exact replay. SQL errors are not blindly retried. Success receipts must match expected market, generation, exact typed counts and fingerprint.
- Expired or superseded workers cannot publish or overwrite their successor's attempt status. Failure reporting uses the fenced abort RPC; transport failure never falls back to an unfenced settings write.

## Evidence and reproducibility

[Machine evidence](design-gap-audit/worker-plan-review/native-worker-evidence.json) records six contracts using the actual worker and PostgreSQL 16.14 RPC functions with a synthetic 401-security provider and two quote batches. The SQL adapter deliberately rejects direct upserts. It exercises failure after enumeration and batch one, complete retry, retained legacy history, fresh pinned-cohort skip, lost response after SQL commit, expiry/successor ownership and quote-only metadata retention.

Run `PYTHONPATH=web/api:web/worker /private/tmp/tradingagent-ui-venv/bin/python3 web/worker/tests/generation-worker-contract.py` with the existing isolated socket cluster running. The script accepts no production connection parameters; its fixed test database is `screener_generation_migration_verification`. It appends synthetic test generations. It uses native SQL rather than PostgREST and does not contact the real market provider.

Full regression suites passed: **347 API/worker tests and 68 JavaScript tests**. Transport tests also cover malformed JSON numbers before mutation, bounded retry and incomplete-response replay. Provider tests exercise the actual HTTP-200 rate-limit branch without internal sleeping. The existing migration's native concurrency/atomicity/grant tests and isolated advisors are recorded in the [storage checkpoint](screener-generation-publication.md); the migration is unchanged here.

## Remaining R01 exit checks

- [ ] Make screener, facets, groups, search and coverage readers validate and pin the current generation, with no corrupt-pointer legacy fallback.
- [ ] Pin multi-page results, captures and downloaded exports to one generation; qualify a publication between pages and during export/capture. Make cache keys generation-aware.
- [ ] Exercise the actual HTTP/PostgREST schema cache, role grants, request size, timeout and ambiguous gateway responses with representative full payloads. Native SQL is insufficient evidence for these limits.
- [ ] Define and verify bounded generation retention/archive capacity, including in-flight readers and captured history references.
- [ ] Qualify real provider identities, source clocks, financial periods/currency and complete exchange coverage independently of exact requested-cohort publication.
- [ ] Apply additive migration before enabling the new worker; stop old unfenced writers during cutover. Verify deployment and rollback ordering against existing binary readers/writers.

No production mutation, merge or deployment occurred. Native performance or synthetic cohort counts do not establish production speed, live market completeness or investment accuracy.
