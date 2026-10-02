# Design QA — screener workspace

Reviewed 2 October 2026. This is a local implementation review, not a production release sign-off.

## Comparison evidence

- Source visual truth: `docs/research-workspace-evidence/05-combined-research-workflow.png` (1487 × 1058 pixels).
- Normalized source: `docs/design-gap-audit/implementation/reference-normalized.png` (1476 × 1050 pixels).
- Current implementation: `docs/design-gap-audit/implementation/09-desk-compact-reviewed.jpg` (1476 × 1050 pixels), browser-rendered at `http://127.0.0.1:8891/#/screener`.
- CSS viewport: 1487 × 1058 desktop. The browser capture has a slightly smaller output raster; the source was proportionally downsampled to the same dimensions. Device pixel ratio was not independently measured; no pixel-perfect density claim is made.
- State: dark Table, All stocks excluding ETFs, market-cap descending, Overview, two stocks selected, inspector Overview/3M open, page export menu open. Source has seven illustrative US companies; implementation has synthetic fixtures, 1,176 classified stocks and 500 page rows. Dynamic values, chart/quote correspondence, company metadata and source completeness are not comparable financial evidence.
- Full-view comparison: normalized source and current implementation were opened together in one comparison input. Earlier paired comparison used `08-desk-reviewed.jpg`.
- Focused controls comparison: `reference-controls.png` and `implementation-controls.jpg`, each 900 × 310 pixels, cropped from the respective renders and opened together. Their vertical content positions differ, so compare control hierarchy, typography and affordances rather than identical pixel coordinates.
- Responsive checks: 390 × 844 CSS viewport. No authoritative mobile mockup exists; mobile results are tested against the task and checklist rather than asserted to have exact visual fidelity.

## Findings, in execution order

1. **[P1] Advanced Explorer factors and institutional comparison remain incomplete.** G08–G09, package C/E. Core scales, region selection, linked table/inspector and exports are now implemented (checkpoint below). The Factor Explorer reference also requires verified forward P/E, growth, ROIC, normalized sectors, sector-relative ranks and bubble sizing. Those remain gated on measured provider coverage and period/currency contracts. Pointer brushing, zoom/extreme cases and real-cohort performance still need complete browser qualification.
2. **[P1] Change review and persistent shortlists are incomplete.** G07/G10/G11, packages B/D. References require named research lists and New/Exited/All review queues with history and evidence. Current selection is transient. The newer D1 checkpoint below implements date-pair review and explicitly unavailable/paired captured evidence; durable history, independent named lists, ownership, review notes and comparable observations for both sides of entering/exiting members remain incomplete. Missing evidence must remain unavailable.
3. **[P1] Chart and research continuity still need complete acceptance evidence.** G05/G13. Requested ranges and actual span/count are displayed; interval/session/adjustment/completeness are not fully verified. New copy explicitly labels interval and session as requests. Verify real instruments, all ranges, history paging and timezone/period contract; then repeat seven stock tabs, six financial subtabs, studies, drawings, sessions/fullscreen, Compare and return-state checks on this build.
4. **[P2] Library status and saved-layout relationships need clearer empty/modified states.** G02/G14. Real 22 presets are preserved instead of copying illustrative strategy names/counts. No-match recovery, latest unavailable execution status, retained-column labels and Modified relationships are now implemented. A new test caught and repaired saved settings aliasing. Verify these states against real saved definitions and failure/retry flows before closing G14; preserve all original definitions.
5. **[P2] Typography, icons and menu content still drift from the mockup.** G01/G03/G04/G15. Source uses a shorter wordmark, brighter body text, a consistent icon family and per-export scope descriptions. Implementation retains a long existing brand heading, more muted company/provenance text, and bordered export buttons with one shared description. Use compact brand presentation, consistent sourced icons, stronger text hierarchy and per-item page/loaded-result counts. Keep verified units and stock identity; do not copy the mockup's unlabeled P/E or illustrative counts.
6. **[P2] Responsive/accessibility and production performance qualification remain open.** G12/G15/F. Phone first stock and Clear are visible; selection target is now 44 × 44 and inspector Escape returns focus correctly across a breakpoint. Tablet/laptop widths, 200% zoom, keyboard menu paths, screen reader, contrast and real device/network profiling remain required. No synthetic desktop timing establishes production p95.

## Required fidelity surfaces

- **Fonts/typography:** 32 px desktop desk heading, 14 px numeric cells and 13 px company text improve hierarchy. Mockup sans body appears more open/brighter; exact source font is unverified. Existing serif brand and monospace financial values are retained, not claimed as exact font matches. P2 hierarchy/contrast review remains.
- **Spacing/layout:** direct library/main/inspector structure and visible bottom research action now follow the combined workflow. Desktop table top moved from 428.6 to 356.6 CSS px, meeting the plan's ≤360 px target. Source table begins higher; compact market context and explicit count/source disclosure are intentional additions. Selection no longer overlays desktop results. Mobile touch targets were preserved.
- **Colors/tokens:** existing dark panel tokens, blue selected/action states, green/red changes are retained. Source has a deeper navy palette and stronger bright-blue accent. Do not claim contrast compliance until measured; keep source/provenance text readable.
- **Images/assets:** actual KLine rendering is preserved; it is not a screenshot substitute. Inspect uses the unmodified official Bootstrap eye SVG with license in `web/api/static/vendor/bootstrap-icons/`. Missing consistent icons remain P2; no decorative illustration is needed for this data workflow. Synthetic chart prices differ from synthetic row prices, so these captures are UI-only evidence.
- **Copy/content:** all original preset names and definitions are retained. Vendor lists/themes are labeled as such. Export scope means loaded qualified matches; intervals/session are requested, unavailable fields remain unavailable. Saved screens appear before recommendations intentionally for reachability. Exact mockup counts, Volume (avg) and inferred sector fields are not copied without provider evidence.

## Comparison history and fixes

| Earlier finding | Fix | Post-fix evidence |
| --- | --- | --- |
| Legacy layout adapter and repeated controls obscured the desk hierarchy | Direct desk markup, dedicated navigation/global search, grouped searchable library, unified controls | `05-desk-current.jpg`, then `09-desk-compact-reviewed.jpg` |
| Inspector action fell below the visible desktop panel | Scroll inner content; retain research/watchlist actions outside it | `07-desk-actions-visible.jpg`, then `09-desk-compact-reviewed.jpg`; research action bottom 982 px in 1058 px viewport |
| Table header at 428.6 px failed ≤360 px acceptance | Compact desktop context/query spacing, keep mobile sizing | `08-desk-reviewed.jpg` → `09-desk-compact-reviewed.jpg`; table top 356.6 px |
| Mobile selection target only 32 px wide | 44 × 44 label target | Browser DOM measurement on refreshed build: 44 × 44 |
| Responsive modal replaced the original row focus target | Preserve explicit row origin and restore visible counterpart | Browser: wide inspector + Export focus → phone dialog → Escape returns Inspect S0001; zero inert elements remain |
| Interval label implied verified bars | Label interval/session as requested; retain actual span/count and unknown completeness | Current inspector screenshot and DOM status |

## Verification and limits

30 JavaScript tests pass; 199 API/worker tests passed earlier in the same checkpoint, before later frontend-only refinements. Diff whitespace check passes. Browser exercised Clear, selection, tabs/ranges, library/saved search, sort, provider pagination, global search, modal Escape and focus return. Latest console error/warning check returned no entries. Selected-export bytes/order are unit-verified; a completed browser-downloaded file remains unverified.

Preliminary offline desktop timing: 12 warm in-memory sorts, nearest-rank p50 104.7 ms, p95 157.4 ms. Evidence: `docs/design-gap-audit/implementation/local-render-timings.json`. Synthetic 1,176-stock universe, 500 rendered rows, same-host browser; excludes later async panel work and was recorded before the final spacing/frozen-column refinements. This is not a release performance result.

## Implementation checklist

- [ ] Finish A/B status/empty states, export labels, typography/icons and compatible saved-layout disclosure.
- [ ] Complete inspector data contract, named lists and full research/Compare preservation verification.
- [ ] Build C linked Explorer with coverage gates.
- [ ] Build D review queue/history and paired criterion evidence.
- [ ] Re-measure E provider coverage and reconcile comparable Moomoo universes/counts, with dates and exclusions.
- [ ] Complete F breakpoint/zoom/accessibility and real performance tests; run browser-downloaded export reconciliation.
- [ ] Capture equivalent live-data states, resolve every P1/P2, then merge/deploy and verify production.

## Newer checkpoint — linked Explorer and saved-state integrity

- Source: `docs/design-gap-audit/references/03-factor-explorer.png`; normalized copy `implementation/explorer-reference-normalized.png` under the audit evidence directory. Current browser capture: `docs/design-gap-audit/implementation/12-explorer-current.jpg`, same 1487 × 1058 CSS viewport and 1476 × 1050 capture. Earlier full comparison paired the normalized reference with `11-explorer-compact.jpg`; that implementation was scrolled, so no header-alignment claim was drawn. Current capture verifies scrollY 0. Reference has four illustrative forward-P/E/growth stocks and sector comparison; implementation has a 20-stock synthetic market-cap/day-change region. Fields and data differ deliberately while advanced coverage remains unverified.
- Core Explorer now has labeled/ticked linear/log axes, central-96% view, hover values, pointer-region implementation and numeric bounds, clear/zoom, linked region rows, selection/inspection and region CSV/Excel. Units explicitly distinguish whole provider currency amounts from billions and percentage points. Missing/nonmeaningful, log-excluded and outside-view counts are separate. Main screen definitions are unchanged by exploration.
- Density iteration: initial expanded numeric form in `10-explorer-linked.jpg` pushed linked rows below the viewport. Numeric bounds now use an expandable disclosure, with Clear/Zoom/Export next to the region heading. Linked table begins at 843.2 px in the tested desktop frame (`11-explorer-compact.jpg`). This follows the reference's plot-then-table hierarchy more closely; advanced right-side sector context remains incomplete.
- Browser: applied region → 20 linked rows; zoom → 20 plotted/1,156 outside view; row selection and S0040 inspector work; Clear then Explore restores all 1,176 plottable rows with no bounds/zoom. Numeric workflow is verified; pointer drag itself remains an explicit browser test gap.
- Saved-state fix: cloned saved settings/column-filter objects before applying them, preventing edits from mutating the loaded definition. Browser showed Modified after changing sort; exports showed 108-stock page/loaded counts for that saved fixture. No-match library search exposes Clear search and recovers the inventory.
- Phone: four axis/scale controls fit the 390 px viewport, with document width 379 px. Latest console warnings/errors were empty.
- **37 JavaScript tests pass**, including exact region CSV membership/values/axis columns, sorted identity preservation, finite/inclusive bounds, log/outlier/missing partition, Clear resetting exploration and saved-definition isolation. No new production data, Moomoo reconciliation or real-device performance claim.


## Newer checkpoint — Change Monitor D1

- Paired source input: `docs/design-gap-audit/implementation/change-reference-normalized.png` and `13-change-monitor-current.jpg`, opened together after capture. Source `references/04-change-monitor.png` was resized from 1487 × 1058 to the implementation's 1476 × 1050 output raster. CSS viewport 1487 × 1058; current capture confirms scrollY 0. State: New matches with an entering member's evidence panel. Source uses illustrative Quality compounders, eight entrants and verified financial crossings; implementation uses a synthetic All-stock definition, one entrant, one exit and 1,175 retained members. These are interaction fixtures, not comparable financial observations.
- D1 now implements New/Exited/All queues, debounced symbol/company search, server pagination/sorting, explicit date-pair IDs, snapshot metadata, recoverable invalid-pair state, historical evidence inspection and complete filtered-pair CSV. All matches explicitly means union membership. Snapshot definition/version, classification, completeness and aware timestamps are validated before differences are presented. Provider criterion evidence no longer falls back to quote fields of a different period.
- Remaining visual gap: the main screen controls plus Change heading/date metadata push review rows substantially below the reference. Make the Changes heading and toolbar contextual, collapse redundant current-screen layout controls/source details, and target first review row within 500 CSS px at this viewport. Keep Clear, capture dates, review scope and export scope visible. This is an open P2, not exact mockup fidelity.
- Fonts/spacing/colors: shared desk typography and dark/blue tokens are retained; muted provenance and small explanatory text still need contrast/readability qualification. No new bitmap/icon assets are required. Criterion evidence uses readable typed values but not the reference's compact multi-criterion matrix yet. Copy honestly distinguishes membership from numeric causes and retrieval/source times; invented threshold reasons are not copied.
- Still absent from the reference workflow: criterion-specific row columns and sorts, row selection, persistent Add to shortlist, Next unreviewed/review status and notes, extended date history and scheduling. D2 must supply full compatible observations for both sides of membership changes before a crossing cause can be displayed. Current storage retains two captures using a shared pre-auth deployment owner and whole-array writes; it is not authenticated team persistence or concurrency-safe history.
- Browser evidence: New/Exited/All and pagination; search retains caret/focus; invalid identical capture IDs show a readable error and can recover through retained selectors; tab focus survives re-render. At 390 × 844 the historical inspector becomes a dialog; Escape restores `Review S2001 snapshot evidence` even after desktop remount, releases inert state, and document width is 379 px. `14-change-monitor-phone.jpg` captures the evidence sheet. Console warnings/errors were empty after the invalid-pair/recovery check.
- Tests: **208 API/worker tests and 43 JavaScript tests pass**. New checks cover missing provider criterion evidence, aware/future timestamp rejection, ETF/classification safeguards, snapshot identity/version/chronology, query pagination and missing-last sorting, late response rejection, CSV pair/definition/evidence metadata, 501-row pagination and rejection of changed pairs/counts, missing pages and duplicate identities without creating a partial file. Browser-downloaded files, real financial cohorts, production and full accessibility/performance qualification remain unverified.

This is a local, unmerged, undeployed checkpoint. QA remains blocked by concrete implementation and qualification gaps; no user approval is missing for continuing authorized work.

Final result: blocked
