# Desk responsiveness checkpoint — 3 October 2026

Current local build, synthetic 1,176-stock US cohort, in-app browser at 1280px. This is controlled interaction evidence, not source-data reconciliation or a production performance sign-off.

- At 500 displayed rows, one warm market-cap direction change measured 316 ms to the instrumented usable frame. Initial rendering measured 385.2 ms.
- After choosing 100 rows, the initial page-size transition measured 157 ms; six subsequent warm direction changes measured 93.7, 60.4, 70.5, 68.9, 74.9 and 85.4 ms. Small sample; no broad p95 claim.
- Fresh state now defaults to 100 rows. Saved page sizes are retained by the existing defaults-then-saved-state merge. Options for 250/500/1000/2000 remain; filtering/sorting still uses the complete available cohort and all-matches export is unchanged.
- Clear returned to All stocks, ETFs excluded, market-cap descending, preserving the 100-row page size. The result summary stayed at 1,176 stocks. At the measured viewport document width equaled 1280px; the table can scroll internally.
- No browser warning/error logs were observed in these checks. Navigation was already at the Screener route; meaningful content and expected controls rendered without an error overlay.
- Actual available-matches CSV download event timed out after 10 seconds in the in-app browser. Do not interpret the lack of a console error as successful download acceptance. No actual downloaded file is claimed here.
- Both current JS suites pass: 171 tests. This includes existing multi-page US/HK CSV/XML payload reconciliation and source/scope/return behavior. Payload tests do not replace actual browser download checks. `git diff --check` passes.

Evidence: [browser timing/layout/log record](browser-evidence.json), [default Desk screenshot](desk-100-rows.png). Test output: `/private/tmp/tradingagent-mvp-responsive-tests.txt`.

Remaining review gates: real US/HK data and classification/preset reconciliation; working browser downloads; real chart/quote identity and research journey; representative live performance; minimal required migration/security/cutover qualification. Optional feature decisions remain pending and the confirmed Desk-only MVP flag remains unchanged.
