# Distributed subtype acquisition lease and native overlap qualification

CLI-generated migration: `20261002132749_instrument_subtype_leases.sql`. Local/uncommitted; no production schema or schedule activation.

## Implemented

Each market has a service-only lease slot and immutable run-token receipt. Claim locks the market slot; active competing runs receive no lease and do not read the cohort or call providers. Exact claim retry preserves the original start and expiry. Tokens cannot be reused after release/expiry or on another market.

A lease has a fixed **330-second** lifetime. The existing CLI's **300-second** whole-run process-group budget is shorter. Renewal is deliberately absent: a delayed job cannot indefinitely extend its acquisition ownership. Interrupted runs become recoverable after the fixed expiry. Each scheduled job generates a fresh UUID.

Publication uses the new leased save RPC. It holds the market row lock through revisioned cache publication and checks current token, active state and server-clock expiry. Expired, released or replaced runs cannot publish, including exact receipt replay. The earlier unfenced RPC is revoked from service_role in this migration; the Python publication adapter now requires an explicit canonical run UUID. Same active-run exact cache retries remain idempotent.

Completion releases only the matching token. Unknown release status cannot be reported as successful completion. Error cleanup attempts release without masking the original failure; failure to release leaves bounded natural expiry. Stored prior evidence remains intact.

Tables have RLS and no browser grants/policies. Functions use SECURITY INVOKER and empty search paths. Run receipts grant service SELECT/INSERT, without UPDATE/DELETE; lease slots grant SELECT/UPDATE, without insertion/deletion. Service-role table privileges remain trusted-server privileges; the application always uses the fenced RPC.

`render.yaml` now declares a separate hourly cron at :20 with **INSTRUMENT_SUBTYPE_COLLECTION_ENABLED=0**. This is an inert local deployment definition; no service was created remotely. Throughput, live rate limits and operational cost must be qualified before activation. Reader/normalization flags are not enabled by this schedule.

## Evidence

- `instrument-subtype-lease-db-contract.sql` passed rollback-only native PostgreSQL checks: exact claim/release replay, overlap rejection, token non-reuse, fixed expiry recovery, expired/replaced/released save rejection, exact leased publication retry, old RPC revocation and browser/service privileges. Clock passage is injected by the local DB owner in this fixture; it is not a natural-expiry timing test.
- [Native two-session script](native_concurrency.py) and [result](native-concurrency.json) observe actual PostgreSQL blocking for claim versus claim and publication versus release. The contender does not acquire; a successor acquires after release, stale publication is rejected, and the original revision-1 evidence remains exact. A separate query proves the disposable database removed.
- Worker tests prove busy-market no-read/no-provider behavior, invalid lease receipt rejection, unconfirmed-release failure, and preservation of committed cache evidence across injected lost-response recovery. The adapter-only cache tests use an explicit assumed-held fixture token; native tests qualify the actual lease contract.

Full local API/worker suite: **730 passed in 7.53 seconds**. `git diff --check` passes; the blueprint parses with collection explicitly disabled. JavaScript is unchanged and retains the preceding 155-test checkpoint.

No advisor invocation was retried; the prior approval requirement remains pending. These local native checks do not prove deployed PostgREST/Auth/runtime supervision. The follow-up below qualifies natural local process-death recovery.

## Remaining acceptance

- [x] Actual runner SIGKILL, immediate idle replacement, unchanged natural 330-second expiry, replacement acquisition and exact prior-record retention via native storage. Deployed PostgREST/runtime qualification remains open.
- [ ] Real platform/PostgREST/permissions and exact uncertain-transport/release recovery; advisor/schema rollout and rollback.
- [ ] Deployed version pinning, provider rate limits/backoff, request throughput and monitoring sufficient for observed cohort/TTL.
- [ ] Fresh raw vendor enumeration and full classification coverage; equivalent Moomoo membership/sorting/count reconciliation.
- [ ] Current browser exports, performance/accessibility and production release acceptance.

All overall R01–R15 gates remain open. No feature activation or merge/deploy occurred.

## Actual process-death and natural expiry follow-up

[Native restart script](native_restart.py) runs the actual collection runner with native lease/cache RPCs through a psql adapter, controlled published-metadata/provider fixtures, and no production data. It preserves a prior PLD record, kills the blocked SPY collection worker with SIGKILL (return code -9), and confirms an immediate replacement remains idle. No deadline shortening, database clock mutation, renewal or early release occurred.

After **330.396 seconds**, the natural lease expires; a replacement attempts/saves the one unfinished instrument, preserves the exact prior PLD JSON/revision and records SPY as ETF. A subsequent run attempts zero providers. A separate query proves the disposable database removed. [Result](native-restart.json). This qualifies local runner/storage interruption recovery, not real vendor/generation completeness or Auth/PostgREST/deployed supervision.

The runner process loaded before the parallel throttle/source-freshness follow-up edits; those edits are independently covered by the final **734-test** suite and public transport probe. Lease/runner recovery behavior under test did not change in those edits.

[Public bounded transport probe](public-provider-probe.json) at 13:39 UTC produced exact-identity PLD/AMT EQUITY and SPY ETF responses. It verifies three source-type samples without inferring full market coverage, fresh Moomoo raw classification, source effective dates or reconciled row counts.
