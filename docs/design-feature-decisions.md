# Original design feature decisions

3 October 2026. Compared original three-view proposal, combined build plan and gap reviews with current source and narrowed MVP contract. This is a feature inventory, not a fresh browser/live-data acceptance pass. No feature is newly enabled or deleted by this review. All decisions below are pending unless explicitly identified as previously confirmed.

## Dropped from launch, deferred, or incomplete

| ID | Original feature | Current position | Recommendation | User decision |
| --- | --- | --- | --- | --- |
| D01 | Data-aware column chooser | Basic chooser retained under More; enumerates all SCR_COLS without per-field cohort availability, coverage or freshness | Keep for MVP; make Columns directly visible, searchable/grouped, distinguish available/partial/unavailable/unknown and preserve selections | Pending |
| D02 | Factor Explorer linked scatterplot/table | Local implementation preserved, hidden by MVP flag; axes/region selection/apply/save/export foundations exist | Defer activation | Pending reconfirmation |
| D03 | Change Monitor: New/Exited/All, date pairs, before/after criteria | Local implementation preserved, hidden by MVP flag; historical evidence needs production qualification | Defer activation | Pending reconfirmation |
| D04 | Named shortlists separate from watchlist | Local private-list implementation preserved, hidden for MVP | Defer; retain existing watchlist | Pending |
| D05 | Review status, notes and Next unreviewed | Local shortlist/pair-review foundations exist; part of deferred workflows | Defer | Pending |
| D06 | Manual screen captures and retained dated history | Local capture foundations exist, Changes not exposed | Defer user-facing workflow | Pending |
| D07 | Automatic capture schedules | Local foundations; activation/operational qualification deferred | Defer | Pending |
| D08 | Advanced factors: forward growth, ROIC, debt ratios | Availability varies; several definitions/derived fields not qualified broadly | Keep discoverable as unavailable where cataloged; do not activate unsupported filters | Pending |
| D09 | Sector-colored/cap-sized Explorer bubbles and peer percentiles | Original design elements; reliable cohorts/coverage and UI qualification incomplete | Defer with Explorer | Pending |
| D10 | Row sparklines | Proposed optional feature; not part of enabled Desk rows | Defer or add only with batched qualified history | Pending |
| D11 | Rich company sector/industry/website context | Some inspector context implemented locally; source coverage/verification incomplete | Keep qualified values, explicit Unknown otherwise | Pending |
| D12 | Explain zero matches and offer explicit constraint-relaxation actions | Current empty state points to loosen/reset; richer suggestions not found in enabled Desk path | Keep a small deterministic version; never silently relax | Pending |
| D13 | Full mobile/tablet workflow | Responsive foundations retained; user confirmed US/HK and desktop first, mobile low priority | Defer dedicated optimization; keep basic usable layout | Previously confirmed |
| D14 | Native XLSX export | Existing CSV and SpreadsheetML .xls retained | Defer XLSX | Pending |
| D15 | Exact mockup fidelity and extensive animation | Usability changes built; exact visual matching deferred | Keep readability/compact hierarchy, defer decorative work | Pending |
| D16 | Formal accessibility/multi-analyst study | Basic checks in release scope; comprehensive qualification deferred | Defer formal study; retain keyboard/focus/readability checks | Pending |
| D17 | All 22 presets operational | User confirmed 20 working, two RSI definitions preserved as unavailable | Keep confirmed policy | Previously confirmed |
| D18 | Exhaustive independent Moomoo site comparison | Bounded like-for-like sanity check retained; exhaustive external-site comparison not qualified | Defer exhaustive external-site comparison; matching the actual connected source remains mandatory | Pending |
| D19 | Team roles, login expansion, shared permissions | Explicitly excluded by user; local private workflow code retained inactive | Exclude from MVP | Previously excluded |
| D20 | Opt-in alerts for screen membership changes | Original proposal lists alerts as later work; no qualified notification workflow in the enabled Desk | Defer alongside Change Monitor; schedules alone do not implement alerts | Pending |

D01 availability must refer to selected market/source and the relevant cohort, not just whether a provider supports a field. Distinguish provider-qualified membership from locally available numeric values. Do not report page-only coverage as universe coverage or hide a previously selected column because a later request has missing data.

## Decision sequence and scope of the column gap

Source recheck on 3 October: `scrToggleColPick()` lists every `SCR_COLS` entry, supports checkbox drafts and Apply/Cancel, and permits dragging columns. It has no search, grouping or field-availability disclosure. Preserve these existing custom-column behaviors whichever option is selected. An availability-aware upgrade is additional work, not permission to remove the basic chooser.

Recommended D01 acceptance if retained:

- Expose a direct Columns action; search and group fields without changing preset rules.
- Label available, partial, unavailable and unknown using the selected market/source and stated cohort. Show the count denominator and observation date where established.
- Treat provider-supported criteria separately from display-value coverage. An unavailable displayed value does not prove the provider cannot screen on it.
- Preserve selected columns across market switches and research return, including columns whose new cohort has no values; show missing values honestly.
- Use existing coverage responses or cached cohort information; do not fetch each field or company separately when opening the chooser. Unknown coverage stays unknown.
- Keep templates, reorder/remove and current-column exports compatible. Verify keyboard, Escape, focus return and laptop fit.

Review optional items in small rounds, recording an explicit keep/defer/drop choice for each ID. Current continuation prioritizes D01 (chooser), D10 (row trends) and D12 (empty-result recovery), because these affect the enabled Desk. Previously unanswered Explorer/Changes/shortlist/capture choices remain pending; continuation alone does not activate them. Next rounds cover D02–D07/D20, D08–D09/D11, then D14–D16/D18. D13/D17/D19 already have explicit scope decisions and need no repeated approval.

“Defer” preserves the existing implementation and excludes activation from this release. “Drop” removes the feature from the proposed roadmap; it does not authorize deleting compatibility code or existing user data. Core data truth, source qualification and existing export/preset/chart preservation are mandatory regardless of optional choices.

## Retained design inventory — next decision round

Each item is present in local code or retained in the agreed scope; full production acceptance is separate.

| ID | Feature | Current position |
| --- | --- | --- |
| K01 | US/HK selection; all stocks default; ETFs excluded; cap descending | Retained, with explicit missing-market loading state |
| K02 | Permanent Clear; active-preset second click resets | Retained contract |
| K03 | All 22 preset identities, rules and sorts; searchable/grouped screen library | Retained, two explicitly unavailable |
| K04 | Existing saved screens, Save/update/copy and Modified state | Retained compatibility |
| K05 | Filters, removable chips, sort/direction and pagination | Retained |
| K06 | Overview/valuation/financial/ownership/performance/technical column templates | Retained independently of screen criteria |
| K07 | Custom columns, reorder/remove and criterion-driven columns | Retained basic functionality; data-aware chooser gap is D01 |
| K08 | Compact market context, symbol/company/screen search, density controls | Local shell/search foundations; acceptance remains separate |
| K09 | Provider/source, exchange, theme/list, symbols, watchlist and optional ETF controls | Retained in labeled secondary menus |
| K10 | Inspector Overview/Why it matches/News, chart ranges and watchlist | Local implementation retained |
| K11 | Visible criterion values versus provider membership evidence; unit/currency/period/source status | Local implementation retained; live field qualification open |
| K12 | Row selection, removable selection chips, Compare 2–4, selected exports | Retained |
| K13 | Ticker → full research; Back/previous/next preserve originating screen state | Retained |
| K14 | Seven research tabs, six financial subtabs, original KLine and Compare features | Retention requirement; regression/live verification remains required |
| K15 | CSV/Excel-compatible exports: page/available matches/selected, current columns/sort | Retained; actual production downloads still need qualification |
| K16 | Honest loading/stale/unavailable/failed states; older-response guards | Retained required behavior |
| K17 | Desktop responsiveness, core keyboard access and snappy feedback | Retained requirement; measured acceptance still needed |

QuantDinger-inspired measurement, indicator chips, zones, history paging and incremental updates are a subsequent proposal, not features dropped from the original three designs. Review these separately after original-design decisions.

Sources: `design-gap-audit/references/screener-product-proposal.md`, `investment-workspace-build-plan.md`, `investment-workspace-design-gap-audit.md`, `investment-workspace-current-gap-plan.md`, `screener-mvp-delivery-plan.md`, `web/api/static/index.html`, `web/api/static/research-workspace.js`.
