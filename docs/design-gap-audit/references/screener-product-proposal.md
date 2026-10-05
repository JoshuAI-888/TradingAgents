# TradingAgents screener: product and UX proposal

Prepared 2 October 2026. Proposal only; the existing screener fixes remain deployed. The three generated mockups are concept illustrations with sample data, counts, and features. Any vendor names in an illustration are placeholders, not connected integrations. The mockups demonstrate hierarchy, not production-ready data semantics or pixel specifications.

## Recommendation

Use the table and contextual inspector in the first displayed mockup as the primary workflow. Add visual exploration as a secondary view after the core workflow is validated. Introduce membership-change monitoring only after reliable snapshots and historical coverage exist.

The product promise: define a universe, find matching companies, understand why they qualify, compare a few, and save a shortlist without losing screening context.

## Findings from the current screen

The production screenshot was inspected during this proposal. This was a screen-level review, not a fresh comprehensive usability or accessibility test.

- The large market banner pushes the first results down. Collapse it into one compact contextual strip; expand on demand.
- Industry, concept, exchange, and ticker inputs repeat in two places. Consolidate them into one source of visible filter state.
- Four export buttons compete with filtering. Use one Export menu with explicit formats and scope: selected, loaded, or all matching results.
- Recommended screens consume the right-hand space with repeated top-three price moves. Group saved and recommended screens into a collapsible library; use the inspector for a selected company's evidence. Show screen purpose, rules, sort, and coverage rather than using daily gainers as the main preview.
- Vendor list names and themes should not masquerade as industries. Separate Sector, Industry, Theme, and Provider list. Keep instrument identity, ADRs, and share classes explicit; do not silently collapse them.
- Preserve the existing dark palette but reduce container borders, increase readable text size, use tabular figures, and reserve color for state and meaningful change. Use text/signs as well as color.

## Institutional patterns and intended user outcomes

The existing references already supply useful foundations: Moomoo groups criteria and saves screening strategies; Finviz organizes descriptive, fundamental, and technical filters and supports presets. Keep that familiarity while improving the transition from matching results to evidence and a shortlist. [Moomoo screener help](https://www.moomoo.com/us/support/topic3_68), [Finviz screener introduction](https://finviz.com/knowledge-base/screener/getting-started-with-screener/introduction-to-screener)

These are documented capabilities from public primary sources, not firsthand terminal benchmarks. The user outcomes below are design inferences; no measured productivity or investment-return improvement is claimed. Some sources are older documentation, so they support durable workflow patterns rather than exhaustive current feature inventories.

| Platform | Documented pattern | Inferred benefit to borrow |
|---|---|---|
| Bloomberg | Equity screening connects to financials, filings, estimates, relative valuation, and monitoring. | Move from discovery to verifiable evidence without rebuilding context. [Bloomberg workflow](https://professional.content.cirrus.bloomberg.com/professional2023/insights/financial-services/integrated-earnings-tools-a-guide-for-equity-analysts-2/) |
| LSEG Workspace | Visual constraints generate an exportable screening formula that can be reused programmatically. | Make screens reproducible, inspectable, and portable. [LSEG screening documentation](https://developers.lseg.com/en/article-catalog/article/ai-de-universe-screening) |
| S&P Capital IQ Pro | Cross-dataset screens combine company information, fundamentals, transactions, and developments with custom formulas and filters. | Broaden evidence beyond isolated price or valuation signals. [Platform brochure, p. 5](https://www.spglobal.com/content/dam/spglobal/mi/en/documents/general/SP-Capital-IQ-Pro-Platform-Brochure-updated.pdf) |
| FactSet | Saved screen universes can be extracted for downstream work. Documentation distinguishes bulk screening from individual-company retrieval. | Reuse one defined universe and optimize screening separately from detail loading. [FactSet reference manual, pp. 14 and 50](https://go.factset.com/hubfs/Website/Website_Downloads/Statistical%20Package%20Integration/factset%20ondemand%20web%20services%20reference%20manual_2.0.pdf) |
| Koyfin, an adjacent professional comparator | Screening criteria become table columns; results support watchlist handoff. Relative percentile ranks are available for peer context. | Expose why stocks qualify, then compare on consistent criteria. A high valuation percentile means a higher multiple, not automatically better quality. [My Screens](https://www.koyfin.com/help/my-screens/), [Percentile ranks](https://www.koyfin.com/help/percentile-rank-snapshot-feature/) |

## Three displayed mockups

1. **Research Desk** — a screen library, criteria-led table, and company evidence inspector. Best default because it preserves familiar precise scanning while removing duplicated controls. Filter criteria become relevant columns. Selecting rows enables a small comparison set.
2. **Factor Explorer** — a linked scatterplot and table reveal distributions and tradeoffs. Axis choices, units, peer cohort, brush bounds, and missing observations must be explicit. Brush selection becomes editable numeric criteria. Provide the same selection through accessible form controls; dragging cannot be required.
3. **Change Monitor** — a daily review queue explains new matches and exits using before/after values. Requires screen-versioned snapshots and distinguishes financial updates, price changes, provider corrections, and changed definitions. Suppress comparisons when periods or coverage are incompatible.

## Behavior contract

- Initial view and Clear: all stocks in the selected market, ETFs excluded, market cap descending, default Overview columns. Clear remains present and resets ticker, watchlist-only, quick signals, custom criteria, and selected screen. Preserve the selected market/provider unless changing them is explicitly part of the reset contract; match the existing deployed behavior during implementation.
- A screen applies its universe, criteria, relevant columns, and declared sort atomically. Clicking it again returns to the default. Editing its rules marks it Modified rather than implying the saved definition still applies.
- Always expose active sort and direction, including sort tie-breaking. Screen headings and exports carry the same query and snapshot identity.
- Zero matches shows which constraints can be relaxed, with explicit one-click changes. Missing data is distinct from a failed criterion. Unsupported provider criteria are disabled with an explanation.
- Selecting a company opens detail without changing filters, sort, scroll, or row selection. Closing the inspector restores focus. Shortlisting remains separate from editing a screen.
- Totals, percentile cohorts, and summaries must describe the complete matching dataset or clearly state their subset. Never imply a displayed-page average represents all stocks.
- Show units, currency, metric definition, reported period, source, and quote age on demand. Delayed/stale/missing values receive distinct labels. Do not mix annual, trailing, and forward metrics under one column title.
- Empty, loading, refreshing, offline, and failed states retain understandable context. Keep prior results during refresh but visibly label them as previous results until the current request commits. Late responses cannot overwrite a newer selection.

## Responsiveness and speed

Proposed performance budgets, not measured results: p95 warm filter/sort feedback under 100 ms, cached inspector response under 150 ms, warm usable results under 1 second. Establish a baseline and record device, dataset, cache state, and network before accepting these targets. Track network completion separately from immediate interaction feedback.

Use a small initial table payload, incremental pages, cached normalized data and keyed queries. Execute full-universe filters and sorts on the server when only a subset is loaded; local manipulation must not pretend to cover unseen stocks. Use a worker only if profiling shows local filtering blocks interaction. Virtualize large tables with stable row identity and tested keyboard/focus behavior; retain an accessible paged presentation where needed. Lazy-load charts, fundamentals, and comparison views. Cancel obsolete requests and use generation guards. Avoid a full-market refresh on ordinary UI actions. AI, if later introduced, proposes editable deterministic rules outside the interaction-critical path.

At wide desktop sizes, show library/table/inspector. On smaller laptops, collapse the library and open the inspector as a drawer so columns remain readable. On phones, show company identity plus two task-relevant metrics, with expandable detail and an optional horizontally scrolling table. Filters open a sheet; active screen, result count, sort, and Clear remain accessible. Comparison becomes a stacked metric view. Use approximately 44 px touch targets, visible focus, reduced-motion support, and no hover-only actions.

## Delivery priorities and validation

**First:** consolidate filters and exports, compact market context, persistent screen/sort state, proper taxonomy, criteria-driven columns, trustworthy data labels, and the inspector. Validate availability of each proposed metric before exposing its filter.

**Next:** comparison and shortlist handoff; then the optional visual explorer with complete cohort and missing-data disclosure.

**Later:** historical snapshots, membership-change explanations, and opt-in alerts. These require data/storage work and coverage checks, not just layout changes.

Test with 5–8 intended users across desktop and phone tasks: find qualifying stocks, explain a match, compare three, and return to all stocks. Measure time to an accurately justified shortlist, task completion, reset/sort errors, and p95 interaction latency. A proposed initial goal is 25% shorter task time versus the current interface without increased errors; treat it as a hypothesis. Require deterministic universe/reset/sort correctness on every tested path. Investment returns are not a UX acceptance metric.

## Visual artifacts

- [Current production screen](01-current-screener.jpg)
- [First displayed mockup](02-research-desk.png)
- [Second displayed mockup](03-factor-explorer.png)
- [Third displayed mockup](04-change-monitor.png)

Select or refine a visual direction before implementation. The research recommends the first mockup as the foundation, with the other workflows available progressively.
