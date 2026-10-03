# Same-response provider context and bounded live coverage

2 October 2026. R02/R09 progress; not full-market/financial-period qualification.

## Fresh public source check

probe.py read three public yfinance 1.7.0 info responses at 10:13:36 UTC: US.AAPL → AAPL, US.KO → KO, HK.00700 → 0700.HK. All returned identities match. public-probe.json records selected raw fields and retrieval time; verify.py replays them through actual fetch/context code into replay-verification.json.

| Sample | Quote / financial currency | Sector | Derived LT debt/equity |
| --- | --- | --- | --- |
| Apple | USD / USD | Technology | Unavailable: required same-response LT debt/equity legs absent |
| Coca-Cola | USD / USD | Consumer Defensive | Unavailable: required same-response LT debt/equity legs absent |
| Tencent | HKD / CNY | Communication Services | Unavailable: required same-response LT debt/equity legs absent |

All three supplied forwardPE, revenueGrowth, earningsGrowth, returnOnEquity, lastFiscalYearEnd and mostRecentQuarter. The general calendar dates do not establish which reporting/forecast period belongs to each metric; quote currency cannot qualify a cap from another provider. This is a concrete source-contract gap, not a claim of missing full-market coverage. No Moomoo count reconciliation or issuer filing verification occurred in this packet.

## Implementation

The Yahoo fetcher now retains a versioned same-response context with canonical/provider identity, separate currency and financialCurrency, and reported fiscal/calendar dates (original Unix seconds plus UTC date). It is explicitly labelled not per-metric periods or cross-provider currency attribution. Malformed currencies, Boolean/structured/nonfinite/future calendar stamps and wrong identities cannot qualify.

Nightly successful fundamental refresh replaces this context; empty/missing context clears obsolete metadata without disturbing technical fields. Failed fetches retain the prior fundamental clock/state. The API revalidates context identity/schema/calendar and seven-day fundamental retrieval freshness, exposing it separately from factor sources and quote field observations. Company context includes its retrieval timestamp. Client/server CSV retains structured metadata. No period is assigned to a factor and no existing quote currency/value is replaced.

Existing JSON enrichment storage suffices; no migration or production write was performed.

## Verification

461 API/worker and 138 JavaScript tests pass; after adding the company-context retrieval timestamp, 134 focused API/worker tests also pass. Actual fetch → nightly refresh → current API → server CSV round-trip retains context and does not fabricate a forward-P/E period. Client Blob CSV retains HKD and CNY separately. Tampered identity, dates and stale/future retrieval clocks fail closed; empty successful refresh clears prior context. Public three-row replay confirms distinct currencies and absent derived LT debt ratios.

No browser or production acceptance is claimed for these backend/export changes. Full Moomoo/provider universe, period/denominator/session/currency coverage, real taxonomy/bubble/rank visuals, Auth/PostgREST, migration/cutover and production remain open. R02/R09 are not closed.
