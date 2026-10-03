# Screener MVP delivery plan — 3 October 2026

This narrows the release scope at the user's request. The investment-workspace gap register remains a backlog, not a requirement to close all R01–R15 before launching. Existing work is preserved; deferred capabilities stay disabled or are omitted from the MVP navigation rather than deleted. No authorization/team-feature development is required for this release.

## Release contract — views and preset policy confirmed

The user confirmed Research Desk → ticker analysis with the existing KLine/research controls → return to the same screen → CSV/Excel export. Ship 20 working presets and preserve the two RSI presets clearly marked unavailable, retaining all 22 IDs, definitions and declared sorts. Explorer and Changes are deferred from the first launch; their local implementation is preserved. The user confirmed US + HK, desktop first; mobile is low priority.

Implementation inventory: `research-workspace.js` currently exposes Table/Explore/Changes in the Desk and accepts all three presentation modes. The MVP must omit deferred navigation and normalize persisted/deep-linked Explore/Changes state to Table without altering saved filter definitions or deleting advanced code. Audit Desk actions for links into deferred private review/scheduling workflows. Keep existing saved-screen and analysis/Compare functionality, rather than stripping unrelated existing features. Apply the same supported/unavailable preset policy in both the library and filter-modal preset list.

## Must-have checklist

- [x] Initial load, Clear and second click on the active preset restore the selected market's stock-only default, excluding ETFs and sorting market cap descending. Clear remains reachable in every filter state.
- [x] Each supported preset applies its original criteria and declared sort. Preserve all 22 definitions and saved-screen compatibility; never silently substitute a different rule.
- [x] Filters, sorting, search and paging agree. Slow/obsolete responses cannot overwrite a newer choice. Explain loading, failure, unavailable and stale states; retain usable previous data where appropriate.
- [x] Confirm canonical ticker/market identity, ETF exclusion, REIT handling, currency and dates for fields shown and used in filters. Missing data stays unknown. Counts distinguish provider total, retrieved cohort and excluded/unclassified instruments. Do not claim a complete exchange universe without evidence.
- [x] Screen paging and exports use a consistent data generation. A partial refresh cannot replace the previous successful dataset.
- [x] Ticker opens the existing analysis page. Check the original seven research tabs, six financial subtabs and KLine controls for regression; Back restores filters, preset, sort, page and scroll. Retain existing Compare functionality without adding new modes.
- [x] Actual CSV and existing SpreadsheetML Excel downloads match the chosen scope, row IDs, order and displayed values, including datasets larger than one page. Guard formula injection and avoid silent truncation.
- [x] Main analyst journey works on desktop and narrow layouts with reachable controls, keyboard focus and no blocking overflow. Measure core interactions with representative data; fix material regressions rather than undertaking a broad optimization project.
- [x] Address the known public database write exposure, validate only the migrations needed by enabled MVP paths, and preserve server/API access. No new login, team roles or legacy-owner migration project.
- [ ] Run existing regression suites and a focused live/browser acceptance pass. Deploy the exact reviewed commit, verify assets/data/downloads in production and retain a practical rollback path.


## Independent workstreams

These are delivery lanes, not newly created Codex chats. They can run in parallel with separate file ownership; final integration/deployment is sequential. Start implementation lanes against the agreed release contract, avoiding optional-feature activation before the user's decisions.

| Lane | Scope | Primary ownership | Completion evidence | Dependency |
| --- | --- | --- | --- | --- |
| A — Screener behavior and continuity | Default/Clear/preset toggle, filter/sort/paging states, analysis/KLine/Back and recovery | Static Desk/routing code and browser regression checks | Button/state matrix, preserved preset hashes, actual analyst journey | Uses B's supported-field contract; fixture checks can start independently |
| B — Data and preset accuracy | Stock/ETF classification, displayed field currency/as-of, cohort counts, refresh consistency and 22-preset audit | Provider/universe/API data contracts | Dated real samples, preset results/sorts, honest coverage and unavailable indicators | Critical path; RSI depth depends on user decision |
| C — Export and usability | CSV/Excel scope and pagination, desktop/narrow layouts, core keyboard and measured responsiveness | Export paths, CSS, download/performance checks | Parsed real downloads and matched IDs/count/order; representative viewport/timing evidence | Final reconciliation needs B's stable cohort; UI work can start independently |
| D — Production readiness | Minimal migration inventory, known table-access defect, deployment/rollback preparation | Migration/release configuration and release evidence | Service/API continuity, migration rehearsal, rollback procedure | Can prepare alongside A–C; live cutover only after enabled-path acceptance |
| E — Integration and release | Resolve cross-lane changes, full existing suites, focused live acceptance, merge/deploy/smoke | Final release owner | Exact commit/deployment, production default/preset/ticker/export checks | Requires A–D; no parallel production mutations |

For overlap in the monolithic static file, one lane owns edits while others supply findings/tests. Data/API changes are integrated before final export reconciliation. Existing deferred migrations must not be applied wholesale merely because they exist locally; document which enabled route depends on each migration.

## Optional scope — user decides

| Capability | Recommendation for fastest MVP | Additional work if included |
| --- | --- | --- |
| Factor Explorer | Defer from launch navigation, or ship only supported axes after focused qualification | Region selection/apply/export agreement, identity/currency/coverage and plot usability checks |
| Change Monitor/manual captures | Defer | Capture completeness, compatible before/after values, no false exits, paging and exports |
| All 22 presets operational including RSI | Preserve definitions; allow honest unavailability of two initially | Reliable historical bars/indicator semantics, fresh values and preset qualification |
| Personal shortlists, saved review status and notes | Defer new workflows; retain existing saved-screen compatibility | Persistence, conflict/recovery and export checks without a team-role project |
| Automatic scheduled captures | Defer; keep activation off | Worker deployment, cadence/session rules, retry and production operational qualification |
| Peer percentiles, normalized sectors, forward growth, ROIC/debt | Defer | Additional provider coverage and verified definitions/periods/cohorts |
| Row sparklines and richer company metadata | Defer unless inexpensive and already qualified | Batched loading/source-span disclosure and missing-value behavior |
| Native XLSX | Defer; retain CSV and existing Excel format | New writer and compatibility checks |
| Exact mockup fidelity, extensive animation and polish | Defer | Additional visual iterations; not necessary for the core journey |
| Full mobile/tablet optimization | Desktop first; keep controls usable on phone | Broader device, chart-toolbar and touch workflow qualification |
| Exhaustive Moomoo universe equality | Use a bounded like-for-like sanity check first | Licensed/session-matched source access and complete membership reconciliation; public rate limits may prevent it |
| Full accessibility audit and formal multi-analyst study | Basic keyboard/readability/zoom checks now; broader audit later | Screen-reader matrix, full contrast/motion audit and recruited task study |
| Historical alias/duplicate-note migration and private cross-history review | Defer; preserve the local work disabled | Legacy migration/reconciliation, scope conflict and account qualification |

## Work that was over-scoped for this MVP

Requiring every historical review variant, team permission, automatic-monitoring failure case, advanced factor and complete device/research study to pass before users can screen stocks turns a focused release into an institutional-platform program. Those checks remain necessary when the corresponding capability ships; they are not prerequisites for a Desk-only MVP. Do not repeat successful native lease/process-death tests without a relevant change. Do not add data features solely to resemble a mockup. Core data truth, preset preservation, export correctness and deployment recovery remain mandatory.

## Release sequence

1. Launch views, RSI policy and US/HK desktop-first scope are confirmed.
2. Freeze the enabled MVP surface and migration list. Keep optional code intact but inactive.
3. Run A–D independently, closing concrete defects rather than expanding the backlog. Maintain one concise acceptance record with pass/fail and evidence.
4. Integrate and test the exact candidate. Sample Moomoo under equivalent market/filter/session conditions where accessible; explain differences and never fabricate an equality result.
5. Merge/deploy using the user's existing authorization; smoke-test production and verify rollback readiness.

No calendar promise is made from local test counts. The remaining critical-path unknowns are live classification/preset coverage, required migration compatibility and final live qualification. Report blockers or unavailable fields explicitly instead of treating advanced features as compulsory.

Latest acceptance: 868 API/worker tests, 197 UI tests and strict Ruff pass. Current production generations contain US 9,420 eligible stocks plus one ETF and HK 2,825 eligible stocks, with zero unresolved classifications. Both Moomoo aggregate counts and top-12 cap-descending samples match. Actual page, all-available and selected CSV/Excel downloads reconcile in both markets. All 22 preset definitions are preserved, with 20 supported and two visibly unavailable. [Current acceptance record](design-gap-audit/desk-mvp/review-candidate.md) supersedes dated legacy empty-HK evidence. Final merge/runtime/cron restoration is the remaining release gate.
