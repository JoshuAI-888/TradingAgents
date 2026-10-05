# Bounded off-request-path subtype collection job

Local cron entry: `python -m tradingagents_worker.instrument_subtype_job`.

The command defaults to `{"status":"disabled"}` without database or provider access. `INSTRUMENT_SUBTYPE_COLLECTION_ENABLED=1` is a separate explicit runtime flag; `INSTRUMENT_SUBTYPE_MARKET` is strictly US or HK. No Render service/schedule was added or activated pending lease and platform qualification.

## Implemented

- Reads exact published universe metadata via the generation-aware reader. Missing original raw category/receipt rejects the job; normalized stock labels are never used as raw source classification.
- Reads the bounded validated dedicated cache and collects oldest-attempt trust/fund instruments, up to 100 attempts per run. Fresh evidence and one-day failed-attempt cooldowns avoid repeated collection.
- Each actual Yahoo call runs in a spawned, killable process with a 15-second budget. Only bounded symbol/quoteType tokens cross the process boundary; general financial payloads and provider exception messages do not.
- Stops starting new collection at 240 seconds. Unstarted instruments are deferred, not labelled failed or given fresh attempt receipts.
- CLI supervision puts the job and provider descendants in a POSIX process group and imposes a 300-second whole-run limit, including database reads/publication. Hard group termination prevents a blocked provider from continuing after a job deadline. Process cleanup is outside the polling budget and bounded by join/kill checks.
- Publishes independent per-instrument revisioned receipts. Partial storage is not whole-market success. Unknown transport outcomes propagate; on a subsequent run, committed fresh evidence is read and skipped while untouched instruments remain eligible.
- Returns counts with `coverage_qualified:false`; it neither enables normalized classifications nor asserts that the market is complete.

## Verification

`test_instrument_subtype_job.py` exercises actual spawn success/failure/provider timeout and child cleanup. A real job+descendant test proves whole-group termination through EOF on a pipe held by both processes (leader-only termination leaves the descendant writer alive). Additional checks cover actual published metadata/cache acquisition, fresh-cache retries, untouched deadline deferral, default-off no-access, scope/budget rejection, and injected receipt loss after commit followed by runner restart/remaining acquisition. The latter is a storage-double recovery test, not real PostgREST or process-crash publication qualification.

Full local API/worker suite: **728 passed in 7.35 seconds**. `git diff --check` passes. No UI code changed; JavaScript retains the preceding 155-test checkpoint.

Local installed yfinance is **1.7.0** and exposes `Ticker.get_info`. Existing requirements permit different lower versions (`web/worker/requirements.txt` versus project dependency); deployed dependency/version qualification remains open. No dependencies were installed or upgraded in this checkpoint.

## Explicit throttle and source-freshness follow-up

The actual Yahoo `YFRateLimitError` now becomes a sanitized subtype throttle signal across the spawned-process boundary. The collector records the one attempted unavailable retrieval, retains any prior evidence/receipt, stops the run and defers untouched instruments without retry timestamps. It returns `stop_reason=provider_rate_limited`. This is an honest partial run, not full coverage; live vendor cooldown/throughput acceptance remains open.

Universe refresh now checks the original basic-info retrieval receipt before both fresh-cache skip and enumeration decisions. Normalization reserves the maximum bounded refresh duration inside the one-day source evidence window (22-hour enumeration horizon with a two-hour maximum refresh). A later publication/quote clock cannot make older basic-info evidence fresh. The regression uses an actual stored generation with fresh quote/publication clocks and an ageing raw receipt, and verifies a new enumeration/generation.

Full local suite after these changes: **734 API/worker tests passed in 8.01 seconds**; `git diff --check` passes. No UI code changed. The three actual bounded public samples at 13:39 UTC reported identity-matched PLD/AMT EQUITY and SPY ETF; see [probe](../instrument-subtype-leases/public-provider-probe.json). These are source-type samples, not fresh Moomoo raw-basic-info or full-market reconciliation.

## Remaining acceptance

- [x] Local [fixed-duration distributed leases, stale-job fencing and actual native overlap](../instrument-subtype-leases/README.md); natural process-death/platform qualification remains open. Fixed lifetimes replace renewal to preserve the bounded run contract.
- [ ] An explicitly disabled local Render schedule is now declared; throughput, vendor rate limits/backoff, operational status and activation qualification remain open.
- [ ] Native/real-platform uncertain-response and interruption checks, runtime version and memory/CPU qualification.
- [ ] Fresh full vendor cohort/classification coverage, equivalent-universe Moomoo counts/membership/sorts and current browser export/performance checks.
- [ ] Platform/advisor/migration/cutover/rollback/release gates.

This checkpoint does not close R01–R15, enable any feature, or merge/deploy the richer build.
