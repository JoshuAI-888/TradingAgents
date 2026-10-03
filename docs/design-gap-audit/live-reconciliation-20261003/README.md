# Fresh deployed data and instrument-classification investigation

3 October 2026 NZ time / 2 October UTC. R02/R14 evidence and source-contract change; not investment-team release acceptance.

## Recorded observations

`probe.py` reads the public deployed older release with TLS verification and the installed certifi CA bundle. No auth, refresh flag or production write is requested. Initial system Python lacked a CA bundle; corrected probe completed with verification enabled. [Recorded responses](deployed-probe.json) and [verifier output](verification.json) retain URLs and request/response/source clocks.

- All 22 deployed preset keys, filters and sorting definitions exactly match the current local catalog. Twenty execute; `rsi-30` and `small-growth` retain unavailable RSI criteria. No definition was removed or relaxed.
- Default declares 10,605 stock-classified matches; only its first 500 rows were retrieved. Those rows are stock-labelled with no finite market-cap descending inversions. Its stored universe clock is `2026-10-01T21:01:40.430487+00:00`. This is not a fresh market total or full-membership/immutable-generation proof.
- Twelve bounded preset first pages contain rows labelled `ETF` by the deployed metadata. Some are Prologis (`US.PLD`) or American Tower (`US.AMT`), so applying that label as an exact ETF exclusion requires further qualification.
- Two Moomoo public strategy pages returned 403 “Operations too frequent.” Search snippets/earlier counts were not substituted for live page evidence. Fresh like-for-like Moomoo counts and membership remain unavailable in this packet.

The [official Moomoo security-type documentation](https://openapi.moomoo.com/moomoo-api-doc/quote/quote.html) describes the legacy ETF category as trusts/funds. That is consistent with the observed discrepancy, but we have not retrieved fresh raw `stock-basicinfo` for these samples: it does not prove whether the current vendor response or an earlier local mapping caused the stored label. Local Moomoo keys are not configured. No company name/symbol heuristic or automatic reclassification was applied.

[Public same-response sample](classification-probe.json) records identity-matching Yahoo info for PLD/AMT/SPY/AAPL. PLD and AMT return `quoteType: EQUITY`, SPY returns `ETF`, AAPL returns `EQUITY`. These four observations do not classify the unsampled market or qualify a combined taxonomy.

## Implemented source retention

The existing versioned same-response provider context now retains an optional raw `quoteType` plus explicit scope that it does not reinterpret another provider's trust/fund category. Values must be bounded uppercase tokens; unknown well-formed provider types remain raw evidence, not mapped stocks. Existing contexts without this optional field remain valid.

Actual fetch → nightly enrichment → API/company context → CSV retains this field. Strict canonical identity/context equality, freshness and tampered-scope guards still apply. No classification override, larger job cohort or production enrichment was enabled. Tests reject boolean/structured/lowercase/oversized/injection-shaped types; legacy absence remains valid.

## Build checklist driven by this evidence

- [x] Record bounded deployed responses and exact preservation of all 22 definitions/sorts.
- [x] Record independent same-response identity/type samples and retain type through the existing data/export path.
- [ ] Acquire fresh raw Moomoo basic-info for observed equity/ETF/trust examples; verify current web API subtype contract, separate from legacy SDK enum documentation.
- [ ] Retain raw provider category separately from normalized instrument class and per-class source/observation identity/time. Explicit equity REITs should survive the stock-only default; actual ETFs should be excluded. Unknown trust/fund subtype must remain disclosed and must not become an inferred stock/ETF.
- [ ] Build bounded subtype enrichment for ambiguous categories, with retry/freshness/coverage budgets. Current nightly cohort excludes provider-labelled ETF rows, so current coverage cannot resolve this defect by itself.
- [ ] Publish classified membership in an immutable generation; qualify classification failure, coverage exclusions, full paging, captures and exports against that same version. Do not rewrite prior capture classifications/evidence.
- [ ] Reconcile default and every preset with fresh Moomoo canonical IDs, source session/as-of and aligned classification scope; resolve RSI availability or retain honest unavailable definitions.
- [ ] Complete real platform/Auth/migration/performance/cutover and production checks. All overall gates remain open.
