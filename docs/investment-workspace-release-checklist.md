# Investment workspace release checklist

2 October 2026. This checklist separates completed verification from provider limitations. The [build plan](investment-workspace-build-plan.md) retains the full feature inventory and proposed follow-on coverage gates.

## Build sequence and completed work

- [x] Freeze all 22 original recommended definitions in a golden fixture; retain saved screens and their individual sort orders.
- [x] Build a shared Table / Explore / Changes workspace with a searchable library, permanent Clear, compact secondary controls and explicit export scopes.
- [x] Retain ticker navigation to full research; add Inspect, Back to screen, previous/next results and selected-stock Compare.
- [x] Preserve the existing chart engine, studies, financials, options, seven stock tabs and comparison layouts; repair Analysis initialization, missing quote formatting and chart disposal/drawing persistence.
- [x] Correct 30-day average volume, ROE-growth mapping, ten-day low period, nested/scaled provider results and day-change ranking. Preserve share-class and market identities.
- [x] Retain pagination metadata; add incremental provider pages with deduplication and complete-snapshot validation.
- [x] Save full presentation state alongside existing definitions, using an additive migration. Existing definition count/hash remained unchanged when the migration was applied.
- [x] Make missing/unverified criteria fail closed. Exclude unknown instrument types from the stock-only view; hydrate missing classification when possible.
- [x] Preserve successful enrichment during provider failures, prioritize missing fundamentals, and separate technical/fundamental timestamps. Screening accepts technical values up to 24 hours old and fundamentals up to seven days old.
- [x] Protect enrichment/chart tables with RLS and revoke anonymous/authenticated direct writes; verify service-role operations remain permitted.

## Verification completed before release

- [x] 196 API/worker tests pass, including all-preset preservation, exclusive boundaries, missing evidence, provider scaling, pagination, saved-state compatibility and snapshot safeguards.
- [x] 15 JavaScript UI-state tests pass, including reset, toggles, saved screens, deep links, pagination, missing sorts, stale-render protection, Explore and drawing restoration.
- [x] Browser: click each of the 22 preset cards and click again; each selection returns to All stocks. Fixture verification is recorded in `research-workspace-evidence/preset-ui-checks.json`.
- [x] Browser: Inspect → full stock research → Analysis/Financials → Back to screen; selected two-stock Compare and return; baseline and no-change snapshots; save a screen without filters.
- [x] Browser/export: all four downloads open and parse. CSV and SpreadsheetML Excel exports contain 500 page rows or 1,176 available fixture matches, exclude all 24 fixture ETFs and use the table's market-cap order.
- [x] Desktop export popup: fix and visually verify clipping and misplaced click targets.
- [x] Mobile: real 390px iframe viewport; document width 379px equals scroll width; filter sheet is 366px wide and fits. Analytical table alone scrolls horizontally.
- [x] Audit public Moomoo criteria, counts and sample tickers, and read-only configured-provider results. See reconciliation below and raw compact evidence.
- [ ] Production deployment, live cursor pagination, final chart/data smoke checks and release screenshots — complete after deployment.
- [ ] Device-specific p95 latency and network-throttling acceptance — not established by deterministic local tests. Cached fixture transitions are quick; cold provider requests retain visible loading feedback.

## Moomoo reconciliation and remaining data constraints

Observed 2 October 2026, approximately 00:20–02:00 UTC. These are point-in-time observations. Moomoo's public screener and our classified stock universe have different membership; do not claim all-market count parity. Its public default reported 9,454 instruments while our stored universe contained 10,605 quoted STOCK instruments. Classification, inclusion, session and refresh differences need instrument-level reconciliation before treating that difference as a missing-data count.

| Recommended screen | Moomoo visible count | Provider observation before deployment | Interpretation |
|---|---:|---:|---|
| Penny | 55 | 55 | Corrected 30-day average volume |
| High Dividend | Not established from loaded public empty state | 0 | Empty provider response; public `--` is not proof of zero |
| Blue Chip | 40 | 40 | Count reconciles |
| Buffett | 128 | 128 | Corrected ROE-growth mapping |
| Undervalued | 5 | 5 | Count reconciles |
| Growth | 104 | 104 | Corrected ROE-growth mapping |
| P/B < 1 | 3,158 | First page 300 | Full count requires cursor metadata |
| Long Term Dividend | 41 | 41 | Count reconciles |
| High P/E | 426 | First page 300 | Corrected legacy growth-factor alias; pagination required |
| Good P/E | 116 | 116 | Count reconciles |
| Low P/E | 1,427 | First page 300 | Pagination required |
| RSI < 30 | 1,128 | Unverified | Legacy RSI query is ignored; documented form rejected; fail closed |
| Junk | 374 | Unverified | Includes RSI; preserve definition and fail closed |
| Small Cap Growth | 86 | 86 | Count reconciles |
| Blue Chip Dividend | 1 | 1 | RIO sample reconciles |
| Speculative | 227 | 227 | Corrected ten-day low query |
| High ROE | 187 | 187 | Count reconciles |
| Low P/E Dividend | 98 | 98 | Count reconciles |
| Undervalued Semiconductor | 3 | 3 | Count reconciles |
| Undervalued Tech | 67 | 67 | Count reconciles |
| Undervalued Bank | 6 | 6 | Count reconciles |
| High EPS | 90 | 90 | Count reconciles |

Count agreement is a sense check, not proof of equal membership or every factor. Sample CRDO factor values also reconcile: net-income growth 805.043%, gross margin 68.035%, ROE 34.407%, ROE growth 302.801%. Provider financial term is annual. Display snapshot volume remains distinct from the Penny criterion's 30-day average.

RSI-dependent definitions remain visible and saved, but cannot currently produce verified complete provider membership. Resolving the provider's documented-query rejection is required before enabling those two screens. Supplemental computed RSI has insufficient whole-universe coverage to be presented as a replacement.

Bulk enrichment covered only 220/10,606 stocks (2.07%) at the audit. Initial Explore uses existing P/E, P/B, market cap and day change, reporting unplottable values. Forward P/E/growth/sector-based advanced views remain gated. ROIC/net-debt/EBITDA require additional validated derivations. No fabricated sector or institutional factors are supplied.

The current Excel export is Excel-compatible `.xls` SpreadsheetML. Provider screens initially load 300 results; exports explicitly include available loaded matches. Changes rejects partial/stale/unverified cohorts, rather than producing false exits.

## Release and rollback

Deploy the tested merged commit by fast-forwarding Render's configured `product/portal-phase0` branch. Verify the asset fingerprint, health, existing saved screen, baseline ETF exclusion/cap sort, live presets, next-page loading, full stock/Analysis chart and exports. Record deployment commit and evidence here. If a production regression appears, roll the Render service back to prior known-good commit `5ddeb8fb0a864d0b9c73f48d175b9d94c38bcfb1`; preserve the additive saved-screen column. Do not reverse the database protections or overwrite saved definitions.

Sources: [Moomoo recommended screeners](https://www.moomoo.com/screener/stock-strategies), [official stock-screen API](https://open.moomoo.com/zh-cn/api/quote/screening/stock-screen), [published MCP schema](https://open.moomoo.com/mcp-docs/available-tools). Individual public-screen URLs and observations are in `research-workspace-evidence/moomoo-checks.json`. Historical pre-correction provider samples are explicitly labeled in `provider-presets.json`; they are not the final release's results.
