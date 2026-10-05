# Normalized instrument classification and bounded subtype acquisition

Current local implementation; no production activation, merge or deployment.

## Implemented and verified

- Original Moomoo basic-info category and local retrieval receipt are retained alongside normalized classes. The receipt is not a vendor effective/publication date.
- With `NORMALIZED_INSTRUMENT_CLASSES_ENABLED=1`, fresh provider STOCK qualifies as equity unless conflicting valid subtype evidence exists. The broad ETF trust/fund category requires fresh, exact-identity Yahoo EQUITY/ETF/MUTUALFUND evidence; unresolved categories remain UNKNOWN.
- Exact classification JSON is frozen in generation rows/metadata, validated on generation reads and immutable observation capture/replay, and retained in whole-screen and before/after comparison exports. Existing observations without the additive record remain readable.
- A fresh-cache flag transition forces a new generation. Default-off rollback restores original provider categories in a new cohort; earlier generation evidence is unchanged.
- Native PostgreSQL rollback-only contract verifies exact nested JSON in rows and metadata, atomic compatibility-mirror publication, and service-role update denial. This does not prove real Auth/PostgREST or current vendor semantics/coverage.
- `instrument_subtypes.collect` separately prepares bounded trust/fund cache updates: maximum 100 attempts per run, maximum 20,000 identities, deterministic oldest-attempt rotation, exact Yahoo identity and collision guards, seven-day evidence freshness and one-day failure cooldown. It retains failed-refresh evidence with its original receipt and never infers equity from an unsupported subtype.
- The acquisition cache emits only identity/type context. Yahoo `get_info` still obtains a general provider info response; this is not a dedicated low-cost subtype endpoint. No financial enrichment calculations or KLine jobs are invoked by the collector.

## Evidence

`test_instrument_classification.py` exercises actual universe publication → generation reader → stock-only API → parsed screen CSV → observation capture, plus activation/rollback. `instrument-classification-db-contract.sql` passed transactionally against native PostgreSQL with final ROLLBACK. Parsed scheduled CSV/SpreadsheetML and JavaScript comparison export tests preserve exact each-side records.

`test_instrument_subtypes.py` verifies bounded rotation, type-only payload, failed-fetch aged evidence/cooldown, canonical/HK identity, alias collisions, invalid response types, tampered/future receipts, TTL boundaries and unsupported subtype non-inference.

Latest full local suite: **717 API/worker tests passed in 6.70 seconds**, **155 JavaScript tests passed**, and `git diff --check` passed. Eight collector checks were added beyond the previous 709-test backend checkpoint.

## Remaining activation checklist

- [x] Local durable isolated cache adapter and native revision/clock/evidence guards: see [storage checkpoint](../instrument-subtype-storage/README.md). True overlapping-worker/platform qualification remains open.
- [ ] Worker scheduling/leases/retries, bounded provider request deadlines and dependency availability qualification.
- [x] Default-off dedicated reader connects validated fresh evidence to universe publication with newer same-provider receipt preference; real platform/coverage qualification remains open.
- [ ] Fresh Moomoo basic-info enumeration and full-market normalized coverage acceptance; unknown/conflicting classifications stay visible.
- [ ] Full stock-only and all 22 preset membership/sort/export reconciliation against equivalent Moomoo universe/session/as-of clocks.
- [ ] Real platform/Auth/permissions, latest browser downloads and performance checks, staging cutover and rollback.

The collector is not wired into a deployed job. The newer storage checkpoint adds a local durable adapter and default-off universe reader. Normalization remains default-off. Public Yahoo samples corroborate PLD/AMT as EQUITY, but no full vendor cohort or fresh Moomoo count comparison has been accepted. All R01–R15 overall gates remain open.
