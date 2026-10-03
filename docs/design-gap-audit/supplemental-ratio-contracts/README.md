# Supplemental identity, units and corrected-cache contracts

2 October 2026. This implements part of packet 1 in the [current build review](../mockup-recheck-e0131ef/README.md). R02 remains open; this is not full data or production acceptance.

## Corrected behavior

- Canonical `US.BRK.B` maps to Yahoo `BRK-B` while remaining `US.BRK.B` in stored/output rows. Exact duplicate input codes are fetched once. Distinct canonical codes mapping to the same Yahoo alias are rejected, as are malformed/wrong-market inputs. A nonempty response with missing/wrong symbol is a failed fetch and cannot replace old fundamentals or renew their clock. Empty success retains the existing category-clearing behavior.
- `payoutRatio` is converted from a fraction to percent, consistent with the UI's percent field contract. Valid zero is retained.
- P/C (`pcf`) is `marketCap / totalCash`, using aggregate cash rather than `totalCashPerShare`. This avoids borrowing an uncertain share-class denominator or an unrelated stored quote price. P/FCF is `marketCap / freeCashflow`. Both require finite positive operands and explicitly identical uppercase three-letter quote/financial currency codes from the same provider response; absent/mismatched currency stays unavailable. No FX conversion is inferred. Negative/zero cash or free cash flow yields unavailable for these positive-multiple fields.
- Transforms reject booleans, strings/structured numeric inputs, huge-number conversion overflow and nonfinite results. One invalid ticker/field cannot abort valid peers.
- The fetcher supplies versioned contracts for these three corrected fields. Nightly persistence replaces their `_meta.field_contracts` only on successful fundamental refresh. The shared API eligibility function withholds unversioned/obsolete values even if their cache clock is fresh; successful corrected refresh re-enables them. Legacy corrected fields receive priority in the existing bounded sweep. Failed fetches preserve cached data and old clocks, without qualifying old units. Technical refresh cannot renew the contract or fundamental clock.
- Eligible field origins include the contract version, so downstream provenance can distinguish the corrected derivation. This version establishes transformation behavior; it does not establish a reporting period, quote/session timestamp or complete coverage.

This is additive JSON metadata in the existing enrichment table, with no destructive data migration or rewrite of saved filter thresholds. Existing numerical thresholds are interpreted in the documented UI units; values are corrected to those units. All 22 original recommended definitions remain unchanged.

## Bounded public-provider evidence

The [raw and processed packet](public-probe.json) was captured at **2026-10-02T08:30:55.550902+00:00**, through the actual fetcher and a transparent wrapper around public `yfinance.Tickers` responses. It performed two ticker-info reads. Test runtime used yfinance **1.7.0**, installed in the disposable test environment from the repository's declared dependency range; this does not establish the production-installed version. Deliberately unrelated stored prices of 1 were passed to prove they do not affect the ratios.

| Canonical identity | Raw payout fraction | Percent output | Aggregate cash | Market cap | P/C output | P/FCF output |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| US.BRK.B → BRK-B | 0 | 0% | 365,513,998,336 | 1,071,425,257,472 | 2.9313 | 14.886 |
| US.KO → KO | 0.6246 | 62.46% | 16,371,000,320 | 370,449,448,960 | 22.6284 | 70.9843 |

Both samples explicitly reported USD quote and financial currency. BRK-B's response also reported price 500.5 and cash-per-share 256,115.53: that per-share basis is not independently qualified and is not used. Do not infer a specific alternative share-class basis from the mismatch alone. The aggregate ratios use provider-reported company market cap; they do not reconstruct it from one class's outstanding shares.

[Replay verification](probe-verification.json) checks exact canonical identity, explicit matching currency, independent arithmetic, the actual API eligibility helper and rejection of unversioned legacy ratios. Public-source arithmetic agreement is a narrow qualification; the public records' fiscal period, balance-sheet versus cash-flow basis, session/adjustment semantics and full-universe coverage remain unverified. These ratios are not reconciled against Moomoo in this checkpoint.

## Regression evidence

**422 API/worker tests and 98 JavaScript tests pass.** Commands:

```sh
PYTHONPATH=web/api:web/worker /private/tmp/tradingagent-ui-venv/bin/python3 -m pytest web/api/tests web/worker/tests -q
node --test web/api/tests/ui/screener.test.cjs
git diff --check
```

New meaningful cases exercise share-class deduplication/alias collisions, wrong/missing response identity, aggregate versus ambiguous per-share inputs, conflicting stored prices, payout zero and 0.6246 scaling, missing/mixed currencies, invalid operands/overflow, old-cache withholding, bounded correction priority, successful actual fetcher → nightly persistence → actual screener filtering, failed correction and wrong-identity clock preservation. Existing all-preset preservation and category-clock regressions remain green.

No UI markup changed, so the prior design captures remain presentation evidence; they are not screenshots of these public financial samples. No production refresh, migration, merge or deployment occurred.

## Remaining closure work

- [ ] Persist/qualify broader per-field inputs, fiscal/TTM/forward periods, quote currency/session/source clocks and eligibility coverage for the entire supported universe.
- [ ] Verify corrected contracts against actual production runtime/provider behavior and repeated share-class/market cases, including failure recovery and missing financial currencies.
- [ ] Finish currency consistency in Changes/Compare/private lists/plots and reconcile all actual export scopes.
- [ ] Complete generation/PostgREST/capture cutover, live Moomoo comparison, real Auth, accessibility/performance, analyst tasks and production release/rollback acceptance in R01–R15.
