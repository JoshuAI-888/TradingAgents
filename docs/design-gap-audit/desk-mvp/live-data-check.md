# Current public data check — 3 October 2026

Read-only public endpoint checks, without auth or refresh, completed at 19:40 UTC on 2 October. This is deployed legacy data, not the local candidate.

- US reports and returns **12,045 stock-labelled rows**, all unique US canonical IDs. All have finite market caps with zero descending-sort inversions. Stored universe timestamp is `2026-10-02T19:01:44.494347+00:00`; the earlier 10,605 count is superseded. No generation ID is returned.
- HK full-market stock-only response still reports available with **zero rows and no timestamp**. The locally implemented unavailable/recovery state is still needed; this response does not qualify HK readiness.
- US price, day change, volume and market cap have numeric values for 100% of this returned cohort. P/E TTM has 74.71%, EPS 80.16%, P/B 78.37%, dividend yield 28.11%. Presence includes zeros; it is not financial-semantic qualification.
- Revenue growth, ROE, margins, debt ratio, RSI and several other preset evidence fields have zero displayed numeric coverage in this cohort. Provider screen membership can still use criteria that its quote snapshot does not expose; the UI must distinguish those two contracts.
- No row supplies explicit currency or field observations. PLD, AMT and O are absent from the stock-labelled cohort. These observations reinforce the unresolved classification and provenance checks; they do not independently prove which upstream mapping is responsible.

The complete available API cohort reconciles internally. **It does not establish parity with raw Moomoo responses, complete exchange coverage, correct ETF/REIT classification, quote/session freshness, or immutable-generation continuity.** Column availability must describe the selected cohort and market, with missing financial evidence explicit.

Evidence: `live-status-20261003.json`, `live-us-cohort.json` (complete public response, 7.6 MB), `live-us-cohort-verification.json` (response hash and aggregate checks), `live-us-field-presence.json` (complete-cohort denominators and field presence). Do not use those aggregates as preset-specific numeric coverage.

Connected Supabase metadata inspection was rejected by automatic approval review because the exact destination/data disclosure had not received specific consent. Approval has been requested for tradingagents table counts/update metadata and security/performance advisors. No indirect equivalent query or production change was performed.
