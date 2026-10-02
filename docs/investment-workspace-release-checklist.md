# Investment workspace release checklist

2 October 2026. This checklist separates completed verification from provider limitations. The [build plan](investment-workspace-build-plan.md) retains the full feature inventory and proposed follow-on coverage gates.

The [fresh design-gap review](investment-workspace-design-gap-audit.md) separates this functional-release checklist from full design acceptance. The approved shell/inspector/Explorer/Change Monitor/mobile experience is not complete. Its packages A–F remain open; prior passing checks do not imply mockup fidelity, measured p95 or accessibility compliance.

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

- [x] 199 API/worker tests pass, including all-preset preservation, exclusive boundaries, missing evidence, provider scaling, pagination, saved-state compatibility and snapshot safeguards.
- [x] 17 JavaScript UI-state tests pass, including reset, toggles, saved screens, deep links, pagination, missing sorts, stale-render protection, Explore and drawing restoration.
- [x] Browser: click each of the 22 preset cards and click again; each selection returns to All stocks, both in the fixture and deployed site. Evidence: `preset-ui-checks.json` and `live-preset-ui-checks.json` in the evidence directory.
- [x] Browser: Inspect → full stock research → Analysis/Financials → Back to screen; selected two-stock Compare and return; baseline and no-change snapshots; save a screen without filters.
- [x] Browser/export: all four downloads open and parse. CSV and SpreadsheetML Excel exports contain 500 page rows or 1,176 available fixture matches, exclude all 24 fixture ETFs and use the table's market-cap order.
- [x] Desktop export popup: fix and visually verify clipping and misplaced click targets.
- [x] Mobile: real 390px iframe viewport; document width 379px equals scroll width; filter sheet is 366px wide and fits. Analytical table alone scrolls horizontally.
- [x] Audit public Moomoo criteria, counts and sample tickers, and read-only configured-provider results. See reconciliation below and raw compact evidence.
- [x] Production deployment and asset fingerprint for PR #2/#3; live cursor pagination, stock/Analysis chart, actual balance-sheet/cash-flow/options data, and release screenshots.
- [x] Final PR #4 deployed (`70afb760acbca1538a050c53455251482b523f24`); HTML/CSS fingerprint checked, annual criteria visible, NVDA orderflow verified at 440.71M net / 3.82B gross in / 3.38B gross out.
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
| P/B < 1 | 3,158 | Total 3,157; pages 300 + 300 | One-row point-in-time difference; zero overlap; 598 classified stocks |
| Long Term Dividend | 41 | 41 | Count reconciles |
| High P/E | 426 | Total 426; first page 300 | Count reconciles; pagination available |
| Good P/E | 116 | 116 | Count reconciles |
| Low P/E | 1,427 | Total 1,427; first page 300 | Count reconciles; pagination available |
| RSI < 30 | 1,128 | Unverified | Legacy RSI query is ignored; documented form rejected; fail closed |
| Junk | 374 | Total 374; first page 300 | Count reconciles; this definition does not include RSI |
| Small Cap Growth | 86 | Unverified | Includes RSI > 50; preserved definition, fail closed |
| Blue Chip Dividend | 1 | 1 | RIO sample reconciles |
| Speculative | 227 | 227 | Corrected ten-day low query |
| High ROE | 187 | 187 | Count reconciles |
| Low P/E Dividend | 98 | 98 | Count reconciles |
| Undervalued Semiconductor | 3 | 3 | Count reconciles |
| Undervalued Tech | 67 | 67 | Count reconciles |
| Undervalued Bank | 6 | 6 | Count reconciles |
| High EPS | 90 | 90 | Count reconciles |

Count agreement is a sense check, not proof of equal membership or every factor. Sample CRDO factor values also reconcile: net-income growth 805.043%, gross margin 68.035%, ROE 34.407%, ROE growth 302.801%. Provider financial term is annual. Display snapshot volume remains distinct from the Penny criterion's 30-day average.

The Below 30 RSI and Small Cap Growth definitions remain visible and saved, but cannot currently produce verified complete provider membership. Resolving the provider's documented-query rejection is required before enabling those two screens. Junk Stocks is available and has no RSI criterion. Supplemental computed RSI has insufficient whole-universe coverage to be presented as a replacement.

Bulk enrichment covered only 220/10,606 stocks (2.07%) at the audit. Initial Explore uses existing P/E, P/B, market cap and day change, reporting unplottable values. Forward P/E/growth/sector-based advanced views remain gated. ROIC/net-debt/EBITDA require additional validated derivations. No fabricated sector or institutional factors are supplied.

The current Excel export is Excel-compatible `.xls` SpreadsheetML. Provider screens initially load 300 results; exports explicitly include available loaded matches. Changes rejects partial/stale/unverified cohorts, rather than producing false exits.

## Release and rollback

Deploy the tested merged commit by fast-forwarding Render's configured `product/portal-phase0` branch. Verify the asset fingerprint, health, existing saved screen, baseline ETF exclusion/cap sort, live presets, next-page loading, full stock/Analysis chart and exports. Record deployment commit and evidence here. If a production regression appears, roll the Render service back to prior known-good commit `5ddeb8fb0a864d0b9c73f48d175b9d94c38bcfb1`; preserve the additive saved-screen column. Do not reverse the database protections or overwrite saved definitions.

Sources: [Moomoo recommended screeners](https://www.moomoo.com/screener/stock-strategies), [official stock-screen API](https://open.moomoo.com/zh-cn/api/quote/screening/stock-screen), [published MCP schema](https://open.moomoo.com/mcp-docs/available-tools). Individual public-screen URLs and observations are in `research-workspace-evidence/moomoo-checks.json`. Historical pre-correction provider samples are explicitly labeled in `provider-presets.json`; they are not the final release's results.

## Production verification evidence

The initial workspace was merged in PR #2 (`95d9f53`), cold-library/share-class repairs in PR #3 (`d27bda9`), and final criterion-column/orderflow repairs in PR #4 (`70afb76`). Render uses `product/portal-phase0`; the deployment branch was fast-forwarded without force pushes. Final production status is recorded below after the asset check.

`live-provider-release.json` records all 22 live responses and first/second P/B pages. The second page has zero overlapping canonical IDs. Two items on that page lack verified STOCK classification and are excluded, explaining the 598 displayed count. Provider totals describe the provider cohort before instrument exclusions. Only the two RSI-dependent definitions are unavailable. Public High Dividend loading did not establish a count; provider zero is reported separately.

Production stock checks use NVDA, with actual quarterly/FY labels, balance-sheet assets, operating cash flow, analyst institutions, options expirations, calls/puts and delayed quote disclosure. Offline fixture financial tabs test navigation; they do not establish production balance-sheet/cash-flow coverage.

A real horizontal drawing survived Cursor selection and Time → Candle, then disappeared only after explicit Clear. Fullscreen resized the chart and retained its volume pane. Evidence: `drawing-retained.png`. All seven lower studies were rendered in the local browser earlier.

The investment-team briefing is [investment-team-workspace-brief.md](investment-team-workspace-brief.md). The supported workflow is ready for demonstration; whole-universe enrichment, RSI-provider repair and device/network p95 qualification remain explicit follow-on gates.

### Final stock-only reconciliation

The table below distinguishes all provider matches from classified stocks in the retrieved page. ETF exclusions explain most differences from public Moomoo totals. Unknown types remain excluded; later pages are explicit for large screens. Dates and samples are retained in `live-provider-release.json`.

| Screen | Provider total | Retrieved instruments | STOCK rows | ETF rows | Unclassified |
|---|---:|---:|---:|---:|---:|
| Penny Stocks | 55 | 55 | 55 | 0 | 0 |
| High Dividend Stocks | 0 | 0 | 0 | 0 | 0 |
| Blue Chip Stocks | 40 | 40 | 39 | 1 | 0 |
| Warren Buffett Strategy | 128 | 128 | 125 | 3 | 0 |
| Undervalued Stocks | 5 | 5 | 4 | 1 | 0 |
| Best Growth Stocks | 104 | 104 | 101 | 3 | 0 |
| P/B Ratio Less Than 1 | 3157 | 300 | 300 | 0 | 0 |
| Best Long Term High Dividend Stocks | 41 | 41 | 35 | 6 | 0 |
| High P/E Ratio Stocks | 426 | 300 | 288 | 12 | 0 |
| Good P/E Ratio Stocks | 116 | 116 | 87 | 29 | 0 |
| Low P/E Ratio Stocks | 1427 | 300 | 300 | 0 | 0 |
| rsi-30 | Unavailable | — | 0 | 0 | 0 |
| Junk Stocks | 374 | 300 | 292 | 8 | 0 |
| small-growth | Unavailable | — | 0 | 0 | 0 |
| Blue Chip Dividend Stocks | 1 | 1 | 1 | 0 | 0 |
| Speculative Stocks | 227 | 227 | 202 | 25 | 0 |
| High Return On Equity Stocks | 187 | 187 | 183 | 4 | 0 |
| Low P/E High Dividend Stocks | 98 | 98 | 91 | 7 | 0 |
| Undervalued Semiconductor Stocks | 3 | 3 | 3 | 0 | 0 |
| Undervalued Tech Stocks | 67 | 67 | 67 | 0 | 0 |
| Undervalued Bank Stocks | 6 | 6 | 6 | 0 | 0 |
| High EPS Stocks | 90 | 90 | 89 | 1 | 0 |

Good P/E illustrates the expected stock-only difference: 116 provider instruments = 87 stocks + 29 ETFs. All-stock defaults and Clear exclude ETFs by design. Financial criterion columns show verified annual provider values; for Penny, RFL revenue growth is 43.956%, displayed as 43.96. The current stock Overview uses actual distribution values for gross flows, not a sum of net-flow observations ([Moomoo capital-flow field definition](https://openapi.moomoo.com/moomoo-api-doc/en/quote/get-capital-flow.html)).

Final presentation polish also labels provider totals on complete small screens, so ETF exclusions remain clear, and bounds the initial Market Pulse feed to 12 score-ranked signals. Additional signals remain accessible through Show 12 more / Show fewer; no candidate records are removed. This avoids rendering the entire accumulated discovery backlog on every screener interaction.

## Local design implementation checkpoint — 2 October 2026

- [x] 23 JavaScript tests and 199 API/worker tests pass for the working tree. Selected CSV/Excel content and a stale inspector response race are covered.
- [x] Offline inspector range/tab/focus and selection-removal interactions checked; synthetic screenshot linked in the design-gap audit.
- [ ] Browser-downloaded selected files reconciled; full responsive/modal/keyboard acceptance.
- [ ] A/B combined mockup acceptance, C/D/E/F completion and fresh production/Moomoo evidence.

This checkpoint is unmerged and undeployed; initial-release checkmarks above do not close the design-completion gates.


### Newer local desk checkpoint

- [x] Direct desk, all 22 preset groups, global search, seven-field Overview and saved column compatibility implemented.
- [x] Desktop table starts at 356.6 px at 1487 × 1058; inspector actions remain visible.
- [x] Mobile selection measures 44 × 44; responsive modal Escape restores row Inspect focus and releases background isolation.
- [x] 30 JavaScript tests pass; 199 API/worker tests passed before later frontend-only refinements; whitespace check passes.
- [x] Source/implementation full-view and focused comparisons recorded in [design QA](../design-qa.md).
- [ ] Resolve QA P1/P2 findings; A/B are not complete.
- [ ] Complete C/D/E/F and fresh end-to-end/live-data/download/production gates.

Current QA result is **blocked by remaining implementation and qualification work**, not by a missing user approval. This checkpoint is unmerged and undeployed.


### Local linked Explorer checkpoint

Core C now supports labeled linear/log axes, outlier-view disclosure, numeric/pointer region selection, zoom/clear, a linked results table, shared selection/inspection and explicit region CSV/Excel exports. Advanced forward-P/E/growth/ROIC/sector comparison remains gated on E; C acceptance is not closed. Numeric workflow, linked selection and Clear reset were browser-verified. Pointer dragging and full real-cohort/device qualification remain open.

A/B status work adds no-match library recovery, per-export counts, retained-column labels and Modified saved-screen relationships. Applying saved settings now clones nested arrays/objects so UI edits cannot mutate the saved definition in memory. **37 JavaScript tests pass**; evidence and remaining findings are in [design QA](../design-qa.md). This is a local, unmerged, undeployed checkpoint.


### Local Change Monitor D1 checkpoint — 2 October 2026

Basic D1 is implemented locally: New/Exited/All queues, search, sort, pagination, explicit capture pairs, unavailable/paired evidence inspection and complete filtered comparison CSV. Snapshot safeguards reject incomplete/classification-unknown cohorts, incompatible versions, invalid dates and identities; provider financial evidence cannot borrow unrelated quote fields. Current-screen and review counts/exports are labeled separately. **208 API/worker tests and 43 JavaScript tests pass.** Desktop/phone fixture evidence and remaining fidelity gaps are recorded in [design QA](../design-qa.md). This is unmerged and undeployed, with no production capture writes or fresh financial reconciliation.

D1/D2 are not complete: criterion-specific table fields/sorting, selection, Next unreviewed, notes/shortlists, authenticated ownership, concurrency-safe durable history and scheduling remain open. Storage currently keeps only two captures. Entering/exiting records often lack an observation on the other side, so numeric causes are explicitly unavailable. Do not infer a threshold crossing from absent membership.

- [x] D1 date-pair queue/search/pagination, invalid-pair recovery and phone dialog focus checked against synthetic captures.
- [x] Comparison export pagination/immutable pair and incomplete/duplicate rejection verified in automated tests.
- [ ] Contextual Changes toolbar and compact criterion matrix meet paired visual acceptance.
- [ ] Authenticated independent lists/review ownership, durable concurrent history and schedules qualified.
- [ ] Criterion row selection/sorts and Next unreviewed checked end to end.
- [ ] Numeric causes supported by compatible before/after observations; no missing-member inference.
- [ ] Downloaded comparison files reconciled with actual review scope and production data.


### Local private-research backend checkpoint

Owner-verified shortlist APIs and an additive migration are implemented, with soft archive/removal, canonical instrument membership, private notes/review status, optimistic revisions and atomic parent locks. **226 API/worker tests pass**; an isolated PostgreSQL 16.14 contract and an observed two-connection archive/add race pass. Details and limitations are in [private research ownership](private-research-ownership.md). No browser login/list UI is wired yet; the migration is unapplied to production. Existing 22 presets and shared Phase 0 saved/watchlist/snapshot records are untouched. Owner-private storage does not close shared-team workflow acceptance. Next: authentication UI and shortlist/review integration, legacy ownership migration, live schema/Auth qualification and the remaining D/E/F gates.

## Latest retained-history checkpoint

This supersedes historical statements above that storage currently retains only two captures. The new local build retains immutable captures and reads two payloads only for the default comparison; its date history is metadata-paginated. Legacy blobs/IDs remain intact. [Retained-history contract and rollout gates](durable-screen-history.md) include the nontransparent old-binary rollback limitation.

- [x] 239 API/worker and 62 JavaScript regressions pass.
- [x] Isolated PostgreSQL immutable/grant/idempotency/atomicity contracts and actual two-connection append race pass; the local test server is stopped.
- [x] Synthetic 105-capture browser paging retains selected pair/counts/disclosure/focus; first review row remains 491.4 CSS px with provenance collapsed.
- [ ] Verified capture ownership/team roles and legacy mapping; real Auth/PostgREST/production migration qualification.
- [ ] Complete paired observations with compatible periods/currency/source clocks, pair-scoped review and opt-in schedules.
- [ ] Large-history/device/accessibility/performance, completed downloads, fresh Moomoo/data reconciliation and qualified cutover/rollback.

The shortlist UI is wired locally; older backend-only statements above are historical. This checkpoint is unmerged/undeployed and does not close full-design acceptance.
