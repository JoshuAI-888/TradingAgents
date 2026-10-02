# Explorer sector and cap encoding

2 October 2026. Scoped implementation and data-contract checkpoint; no live financial qualification.

## Source assessment

Grain is one canonical loaded security. The actual screener src=yf merge supplies sector/industry through display_field_sources with independent freshness clocks (main.py _fresh_supplemental and screener merge). Company context and Groups expose the same current cached source; neither pins classifications to quote generations or validates financial reporting periods. Provider plates are vendor lists and cannot substitute for sector. Thus source-labelled current sector context is implementable, while normalized taxonomy and qualified financial peer percentiles remain open.

Market-cap monetary attribution already requires matching canonical identity, field name, exact finite value, currency unit and explicit currency through researchFieldCurrency. Cap sizes are safe only when all plotted members have positive attributed cap in one common currency; incomplete or mixed attribution disables sizing rather than silently dropping rows. Financial peer-rank eligibility is not inferred from this check.

## Implementation

- Collapsible sector legend gives plotted/loaded counts, known coverage and explicit Unknown. Only canonical rows with nonempty yfinance labels retrieved within seven days qualify. Missing, stale, future, invalid-source or invalid-clock labels stay Unknown; no plate fallback. Counts describe loaded screen scope, not the full market.
- Deterministic sector colours accompany named labels and keyboard point announcements. Colours may repeat; the legend says so. Region membership retains a white outline; screen filters, exports and IDs are unchanged.
- Point-size control offers Uniform and qualified Market cap with explicit currency. Positive caps use bounded area encoding, radius 3–12 px; the lower bound prevents invisible points. If the plotted cohort becomes incompatible the renderer uses uniform points and explains why. No conversion or inferred currency.
- New controls use 44 px targets. No new per-row requests.

## Evidence and limits

135 JavaScript tests pass. New tests check source/clock/identity qualification, loaded/plotted reconciliation, no plate substitution, stable colours, and complete positive single-currency cap sizing including mismatched identity, unknown currency, negative/zero/Boolean caps. Backend unchanged from 457-test checkpoint.

Current actual-route offline browser: 1,176 synthetic loaded/plotted stocks reconcile 0 classified plus 1,176 Unknown. Missing cap attribution disables Market cap with an explicit reason. At 390 × 844 document width is 379 px, point-size and legend controls are 44 px high. No captured browser errors. Screenshot 01-desktop.png shows that unavailable state. The synthetic fixture does not qualify real classifications, cap sizing visuals, prices or full-market coverage; qualified multi-sector/bubble visual acceptance remains pending.

R09 remains open for normalized full-provider taxonomy, real attributed bubble qualification, financial periods/cohorts/rank ties and eligible advanced factors. Existing monetary-axis compatibility is a separate unresolved gate: cap sizing does not establish that arbitrary cap-axis comparisons/region handoffs are currency-qualified. No merge/deploy or production acceptance.
