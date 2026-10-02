# TradingAgents: combined screener and research workflow

Prepared 2 October 2026. This records the approved design, implementation sequence and release checks. Implementation and verification status is recorded in [the release checklist](investment-workspace-release-checklist.md). Based on the current repository, live browser inspection, read-only API probes and read-only database aggregates. The approved Research Desk, Factor Explorer and Change Monitor become views of one workflow, rather than separate products.

## Product decision

**Discover → inspect → research → compare → save/export → revisit changes.** The table stays the default and the main working surface. Explore visualizes the same results; Changes compares membership of the same saved screen over time. One shared screen state determines criteria, universe and sort in all three views.

1. Start at **All stocks**, ETFs excluded, market cap descending. Keep Clear visible at all times; disable it when already at the default. Preserve the selected market when resetting, matching the existing reset behavior. Current reset also restores Moomoo source, Overview columns, page 1, no watchlist restriction, and no custom criteria.
2. Pick a recommended or saved screen. Show its exact criteria, applicable periods, result scope and sort. Clicking its selected library entry again returns to the default. Recommended screens and user-saved screens have separate identities even when names match.
3. Work in **Table / Explore / Changes**. These are presentation views; Overview / Valuation / Financial / Ownership / Performance / Technical remain column templates. Switching either must not silently change criteria or sort.
4. Click **Inspect** to open a lightweight right panel: quote, small KLine preview, watchlist action and screen context. Ticker/name links continue opening the full stock page. No information is removed from that page to make the inspector fit.
5. Full research offers **Back to screen** and previous/next within the originating result set. Returning restores criteria, selected screen, sort, columns, page, selection and scroll. Direct links remain usable without a parent screen.
6. Select stocks for the existing **Compare** workspace. Keep its layouts, synchronized chart controls and indicators. Return to the originating screen without losing selections.
7. **Export** presents format and scope explicitly: this page or available matches; selected rows can be added later. **Save screen** preserves the complete reproducible screen definition. Changes becomes usable only after comparable, complete snapshots exist.

Do not put every current action on the new top bar. Retain infrequent controls in labeled menus, keep full functionality discoverable, and use the existing page routes as compatibility aliases. Use “Run agent analysis” for the job action to distinguish it from the stock Analysis tab and the global Analyze workspace.

## Updated layout and responsiveness

![Combined workflow concept](research-workspace-evidence/05-combined-research-workflow.png)

The mockup illustrates hierarchy and interaction, not live quotes or an implementation contract. Its illustrative screen counts, saved names, sector labels and shortened recommended names must not replace production data or the exact 22-screen inventory below. The seven displayed rows are a composition sample, not the actual All stocks result count. Keep the current full column set; the open export menu obscures some columns in this frame. An explicit Inspect icon must be distinguishable from the illustrated ellipsis menu. Apply the documented availability and export-limit labels during implementation.

Desktop: collapsible searchable screen library on the left, results in the center, optional inspector on the right. Filter criteria are readable chips with period/unit context; a pinned toolbar contains Clear, Save and Export. A single selection bar provides Compare. The default table has the current Overview columns; users retain all current column choices.

Explore initially offers supported axes such as P/E TTM, P/B, market cap and day change. Scatter selection links to table rows and selection; show a count of plotted versus unplottable results. Negative/nonmeaningful P/E, missing values and log-scale eligibility need explicit treatment. Do not silently discard these stocks from the underlying screen. Sector coloring and forward-P/E-versus-growth axes are gated until their coverage is verified.

Changes shows newly qualifying, exited and unchanged results with before/after evidence. A first snapshot produces “Baseline captured”, not fabricated additions. An incomplete fetch, stale factor or changed criterion produces an unknown/comparison-unavailable state, not an exit alert. Watchlist and saved-screen memberships remain distinct.

Tablet: collapse the library and allow the inspector to overlay. Mobile: compact result rows with key values; horizontal table scrolling remains available for analytical columns. Library, filters and inspector become sheets. Keep ticker navigation and Clear easy to reach. Full research keeps a large chart with a horizontally scrollable tab strip and collapsible tool menus. Do not squeeze every chart tool into an unreadable toolbar.

## Existing features that must survive

| Area | Preservation requirement |
| --- | --- |
| Universe and filters | US default, strict ETF exclusion, market/provider selection, watchlist-only, numeric/text column filters, filter modal categories, quick signals, facets, column chooser, pagination and sorting |
| Screens | All 22 recommended screens, exact boundaries and periods, provider factor mappings, saved-screen create/read/update/delete, shareable URLs and persisted preferences |
| Column templates | Overview, Valuation, Financial, Ownership, Performance, Technical and Custom; user column order |
| Exports | CSV page/all and Excel page/all, displayed filter/sort/column order, global row numbering, escaped values and UTF-8 BOM CSV |
| Full stock page | Overview, Options, Financials, Analysis, Company, News, Comments; quote statistics, sessions, search, watchlist, research reports and agent-analysis handoff |
| Financials | Earnings, Revenue Breakdown, Financial Indicators, Income Statement, Balance Sheet, Cash Flow; quarterly/annual, period count, YoY, hide blank, currency and reporting dates |
| Options | Expiry, calls/puts, bid/ask, open interest, IV/delta and existing sorting/moneyness controls |
| Main KLine engine | Candle/area modes, MA/EMA 5/20/50/100/200, Bollinger bands, volume, MACD, RSI, KDJ, CCI, Williams %R, ROC, BIAS, OHLCV crosshair, zoom/pan, sessions/ranges, fullscreen and responsive resizing |
| Drawing tools | Trend, horizontal line, ray, vertical line, parallel channel, Fibonacci and explicit Clear drawings; serialize drawings by instrument/timeframe/adjustment |
| Compare workspace | Single, split, stacked, 1+2 and 2×2 layouts; add/remove panels, synchronized ticker/timeframe/crosshair, extended sessions and existing studies/panes |
| Compare studies | Volume Profile, Donchian, Keltner, Supertrend, Pivot, VWAP, SAR; ATR, Aroon/Aroon oscillator, MFI, Force, relative volume, performance %, Stochastic, OBV, DMI/ADX, earnings/dividend markers |
| Other workspaces | Existing Analyze, Ledger, Groups, quotes and report/dossier chart entry points remain reachable |

Volume Profile is estimated from OHLCV today: retain the feature and explain that limitation rather than relabeling it as exchange volume-at-price. Chart range and bar interval must be separate concepts: the current quarter-range request uses daily bars, not native quarterly candles.

### Recommended screen inventory

Penny Stocks; High Dividend Stocks; Blue Chip Stocks; Warren Buffett Strategy; Undervalued Stocks; Best Growth Stocks; P/B Ratio Less Than 1; Best Long Term High Dividend Stocks; High P/E Ratio Stocks; Good P/E Ratio Stocks; Low P/E Ratio Stocks; Below 30 RSI Stocks; Junk Stocks; Small Cap Stocks with Huge Growth Potential; Blue Chip Dividend Stocks; Speculative Stocks; High Return On Equity Stocks; Low P/E High Dividend Stocks; Undervalued Semiconductor Stocks; Undervalued Tech Stocks; Undervalued Bank Stocks; High EPS Stocks.

Keep definitions versioned, including exclusive boundaries, financial reporting period, 30-day average volume, RSI and industry plate IDs. Current recommended execution defaults to day-change descending; the saved “Penny Stocks” screen in the database uses market-cap descending. Preserve each recorded behavior, and make each recommended screen's sort explicit in its definition instead of inferring it from its name.

Current “Excel” export is SpreadsheetML `.xls`, not native `.xlsx`. Preserve compatibility initially. A native XLSX option is a separate enhancement. Recommended execution currently caps results at 300: “available matches” must disclose that scope until complete provider pagination is validated. The fallback export must use the same provider and state as the visible screen.

## Data coverage: capability versus actual availability

Database observation: **2 October 2026, 13:01 NZDT** (00:01 UTC). Counts below refer to the stored US STOCK universe, not ETFs or indices. This is a point-in-time audit, not a freshness guarantee for every instrument.

| Data | Actual coverage | UX consequence |
| --- | --- | --- |
| Stock universe | 10,606 instruments; 10,605 quoted (99.99%) | Table/quote-based Explore are feasible now |
| Price, market cap, day change | 10,605 numeric values each in the follow-up quote aggregate | Suitable initial axes and sort fields; timestamps still need validation |
| P/E TTM / P/B | 8,019 / 8,445 numeric values | Show missing/nonmeaningful values and plotted coverage |
| Dividend yield | 2,941 numeric values | Absence must not automatically mean zero yield |
| Any enrichment row | 220 stocks (2.07%) | Presence of a row does not prove fundamental data exists |
| Forward P/E, ROE, revenue growth, normalized sector | **0 stocks each** in stored enrichment | Current bulk store cannot support the earlier fundamental scatter or sector peer percentiles |
| RSI 14 / one-year performance | 214 / 172 stocks | Current computed technical coverage is too sparse for a broad-universe claim |
| Stored KLine state | 5,373 stocks (50.66%) | There is an existing historical-data base to expand from |
| At least 200 stored bars | 4,419 stocks (41.66%) | Potential SMA/technical cohort; last fetch is not proof of the latest trading bar |
| ROIC / net debt to EBITDA | 0 stored values; neither registered as a screener field | New definitions and a validated financial-statement pipeline are required |

The latest enrichment row stamps were 30 September 01:06 UTC. Stock quote database writes ranged from 29 September 21:18 UTC to 1 October 21:01 UTC. A write timestamp is not the source's actual quote timestamp; expose source time, retrieval time, session, currency and quote delay separately.

On-demand NVDA estimates returned revenue/EPS forecasts, trends and earnings surprises successfully. That request took approximately seven seconds in one cold probe; this is evidence of availability, not a latency benchmark or universe-wide coverage guarantee. Full stock-page financials and chart data also exist independently of screener enrichment. The redesign must not hide them just because the bulk factor table is sparse.

The live Penny preset returned 39 members, while numeric evidence for its average-volume, revenue-growth, profit-growth and debt-ratio factors was absent across those rows. Thus provider-qualified membership and locally displayed numeric factor evidence must have different statuses. Never show every criterion as numerically verified when its value is missing; never replace 30-day average volume with today's volume or mix incompatible growth periods.

**Conclusion:** the current providers are sufficient for the core workflow and an initial quote-based Explore view. Integration/storage problems block the richer fundamental view. Change Monitor also requires an application-owned snapshot pipeline. A new provider is not the first step; repair and measure the existing pipeline, then assess residual gaps and entitlements.

Moomoo documents screen pagination with total/has-more/next-key. The application's 300-row limit should not be assumed to be a provider limitation; confirm the account's REST response and entitlements, then implement pagination. Its historical KLine endpoint documents a maximum 370 bars per response plus `next_time`, so long-history completeness needs paging. [Moomoo screening tools](https://open.moomoo.com/mcp-docs/available-tools), [historical KLine API](https://open.moomoo.com/zh-hk/api/quote/basic-data/history-kline).

Yfinance exposes per-ticker statements, history and estimates, but those APIs do not establish complete bulk factor coverage. Registered metadata, successful per-stock fetching and a reliable stored universe are three separate tests. [Yfinance Ticker reference](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html).

## Foundation issues discovered

- **Reproduced:** opening stock Analysis throws a chart initialization error because analysis state is read before initialization. The chart area stays blank. Fix before migrating the host.
- **Observed:** Compare displays `NaN%` in chart headers and several native unstyled controls. Add explicit missing-value display and consistent tool styling while preserving functionality.
- **Code risks requiring regression tests:** chart rebuild can discard user drawings; Cursor follows the clear-overlay path; resize listeners lack corresponding cleanup. Store chart state separately from DOM rendering and implement lifecycle cleanup.
- **Navigation/state:** stock navigation uses history replacement and canonical symbol conversion needs care for share classes and non-US instruments. Add real back/forward navigation and guard every asynchronous stock request against stale symbol responses.
- **Filtering integrity:** absent fields can currently cause criteria to be skipped. A custom screen must explicitly report unsupported/incomplete criteria instead of appearing fully applied. Provider-backed preset membership can remain valid with an evidence-unavailable label.
- **Enrichment integrity:** the nightly upsert can replace a previously enriched JSON object with only this run's technical fields; row timestamps also conflate technical updates with fundamental freshness. Merge existing data safely, preserve last successful field/source timestamps, and distinguish stale values from authoritative deletions.
- **Worker scheduling:** missing rows are ranked after existing rows despite the stated missing-first intent; mixed ETFs/indices consume stock enrichment budget. Prioritize the eligible STOCK universe and recover missing fundamentals with bounded batches and observable failures.
- **API health:** `/api/meta` returned HTTP 500 in one probe. Reproduce and repair before relying on it for capabilities.
- **Verified database exposure:** RLS is disabled on enrichment/KLine tables and both `anon` and `authenticated` hold broad write grants. Add an access-control migration and test that public writes fail while service-role API/worker operations continue. Check the broader exposed-table list; do not assume simply enabling RLS addresses every grant. [Supabase RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).

Evidence: [database coverage](research-workspace-evidence/baseline/database-coverage.json), [live API probes](research-workspace-evidence/baseline/live-api-probes.json). These audits did not mutate production data or saved screens.

## Build plan and release gates

### Phase 0 — feature baseline, data contracts and repairs

Inventory routes/buttons/chart controls and record expected behavior. Fix the reproduced chart error, missing-value rendering, source-consistent exports, request races, filtering integrity and API metadata health. Repair enrichment merging, scheduling and field-level freshness. Harden database access with separately validated migrations. Define a field registry containing unit, currency, source, financial period, dependencies, eligibility and coverage. Normalize canonical instrument IDs across routes, provider adapters and exports.

**Gate:** default/reset/preset toggles pass; all 22 definitions retain their boundaries/sort; unsupported fields are explicit; service-role operations work and unauthorized database writes fail. Existing charts load without console errors. Test on staging rather than editing production saved-screen definitions for QA.

### Phase 1 — shared screen state and research-desk shell

Extract current screener behavior into modular state, query, export and rendering layers incrementally; no framework rewrite is necessary. Version the screen schema and migrate old saved screens with compatibility defaults. Store universe, criteria, source, sort, columns, column-template and presentation view; keep navigation context (page/scroll/selection) separately. Add the library, persistent Clear, unified Export menu and responsive table. Put the shell behind a rollout flag.

**Gate:** existing saved screens and shared links reopen identically; same-name recommended/saved screens remain distinct; old routes still work. Export matches visible semantics. No regression in default table speed.

### Phase 2 — inspector and full research continuity

Add Inspect independently of ticker navigation. Preserve all seven tabs and six financial sub-tabs. Add Back to screen, previous/next and selected-stock Compare handoff. Reuse the existing KLine adapter; initialize state before controls and persist drawings/studies/viewport separately from page rendering. Lazy-load heavy tabs, cancel stale requests and clean up chart listeners.

**Gate:** a user can screen → inspect → full research → financials → options → Compare → return with state intact. Every chart feature in the preservation table has a functional acceptance check. Verify cursor does not clear drawings and instrument/timeframe changes do not leak prior-stock data.

### Phase 3 — coverage recovery and Explore

Backfill normalized fundamentals, sector/industry and computed technicals using the corrected worker. Validate field meanings against provider units/periods and collect coverage by eligible universe. Recompute technicals only for instruments with sufficient bars; check latest completed market session and adjustment consistency. Ship P/E/day-change or other supported axes first. Add sector peers and forward-P/E/growth after coverage qualifies.

**Gate:** each selected axis displays eligible, missing and stale counts. Proposed broad-cohort gate: at least 95% of eligible instruments have valid, sufficiently fresh values; otherwise offer an explicitly named covered subset. This is a product target, not a measured current capability. ROIC and net-debt/EBITDA require separate validated derivations (NOPAT/average invested capital; interest-bearing debt less cash over TTM EBITDA) with consistent currency/period and sector applicability.

### Phase 4 — complete snapshots and Change Monitor

Validate provider result pagination before collecting membership snapshots. Store screen-definition version/hash, canonical instrument IDs, source/period timestamps, completeness and comparison evidence. Collect at least two comparable successful snapshots. Separate changed membership from missing coverage, delistings, stale data and definition edits. Add new/exited queues and review handoff into the same inspector/full research flow.

**Gate:** incomplete or mismatched snapshots cannot generate exits; reasons cite comparable before/after values or clearly indicate provider membership only. First-run, no-change and failed-refresh states are designed and tested. No notification service is needed for the initial in-app view.

### Phase 5 — performance, accessibility and staged release

Profile against the existing production baseline before changing the query architecture. Keep thin cached result data for fast local interactions where appropriate; do not substitute slow requests for every sort/filter. Virtualize visible table rows, batch DOM work, debounce expensive input and compute scatter subsets off the main thread when profiling justifies it. Load only visible chart instances and requested tabs. Replace blanket warming of all preset requests with bounded, prioritized prefetching. Server-side queries must be authoritative for complete large result sets and exports.

Proposed budgets: visible feedback within 100 ms; cached state changes within 300 ms at p95 on an agreed reference device. Cold provider requests are asynchronous with a visible loading/stale state and no fabricated instant-response claim. Measure desktop, mid-range mobile and throttled-network behavior; monitor render long tasks, memory and provider request counts.

**Gate:** keyboard/focus behavior, screen-reader labels, contrast, touch targets and reduced motion pass; chart resizing works across layouts; no console errors or wrong-stock responses. Merge only passing changes, deploy progressively to Render, verify production routes/data/export/chart flows and retain rollback capability. Keep data migrations and UI rollout independently reversible where possible.

## Release checklist

The executable checklist, measured results, live Moomoo reconciliation and remaining coverage/performance gates are maintained in [investment-workspace-release-checklist.md](investment-workspace-release-checklist.md). The phases above retain acceptance requirements for the supported initial release and the gated institutional-factor expansion.

## Inspection screenshots

Current full research and financial views establish the preservation baseline. The Analysis screenshot records the reproduced blank chart; the Compare screenshot records the current header/control issues.

![Current screener](research-workspace-evidence/baseline/01-screener.png)
![Current stock Overview and KLine](research-workspace-evidence/baseline/02-stock-overview.png)
![Analysis chart initialization failure](research-workspace-evidence/baseline/03-stock-analysis.png)
![Financial tab baseline](research-workspace-evidence/baseline/04-financials.png)
![Compare baseline](research-workspace-evidence/baseline/05-compare.png)
