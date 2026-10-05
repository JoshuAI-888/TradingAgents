# Explorer monetary-axis and region currency

2 October 2026. Local contract/browser checkpoint; no real provider currency qualification.

## Problem and resulting behavior

The earlier Explorer used market-cap numbers without ensuring a common attributed currency, and numeric region filters could admit another currency after apply/save. Optional bubble sizing alone did not fix that axis/region risk.

When either axis is market cap, Explorer now requires an explicit currency from identity/value/unit-checked field observations. It neither infers a listing currency nor converts amounts. Numeric-valid rows with another/unknown currency are counted separately from missing numeric observations and excluded from plot, region, point groups and region exports. Axis/linked values and numeric-bound instructions disclose the chosen units. Changing currency clears the region and preview.

Applying a region includes currency on the market_cap rule. The existing saved-definition/deep-link JSON retains it, and visible chips/filter descriptions/edit headings show it. Client and server filters enforce the same strict ISO/identity/value/unit attribution. Cap-region downloads include explore_context with axes, bounds, chosen cap currency and sort, as well as per-value currency/observations.

Immutable capture creation/replay reconstructs criterion rows from actual observations. Every eligible member/nonmember must have valid currency-unit evidence for a currency-scoped criterion; missing attribution rejects capture rather than becoming a false exit. Different valid currencies remain observed nonmembers. Persisted capture currency metadata is revalidated before comparison. Existing 22 preset definitions are unchanged; no currency is retroactively invented for their original provider rules.

## Evidence

- 458 API/worker and 137 JavaScript tests pass.
- Actual server screener CSV response for a controlled USD/HKD cohort contains only US.A and attributed USD cap.
- Actual capture → persisted pair comparison reproduces USD membership. Corrupted nonmember currency makes the pair noncomparable; missing currency rejects a new capture with 409 and preserves both prior captures.
- Client model, numeric rules, saved definition reload and filters agree on exact USD membership; mixed/unknown rows cannot qualify. Actual CSV Blob records chosen currency context and excludes other identities/currencies.
- Current-route browser static UI at port 8903: all 1,176 fixture numeric caps lack currency, so zero plot and 1,176 currency exclusions, with explicit no-inference explanation. Changing back to P/E restores all 1,176 plotted matches. At 390 px document width is 379 px and currency control height is 44 px. Screenshot 01-unavailable-currency.png.

## Limits and next qualification

Browser preview backend was not restarted; new capture/filter backend behavior is established by tests executing current API code, not claimed as browser acceptance. The fixture lacks real currencies, so it verifies unavailable state only. Actual provider/reference-data cap attribution, qualified multi-currency UI/region downloads, real Auth/PostgREST and production remain open. Monetary attribution does not qualify fiscal denominators, peer ranks or quote-session comparability. R02/R08/R09/R11 remain open; no merge/deploy occurred.
