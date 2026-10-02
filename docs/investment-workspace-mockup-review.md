# Current build against the approved design

Reviewed 2 October 2026. This is the latest design review of the local working tree on `codex/investment-team-release-evidence`, based on HEAD `cdb6ddb` plus uncommitted login/shortlist integration. It does not describe a newly deployed release. The private-research migration is still unapplied to production.

## Verdict and scope

The Research Desk now follows the combined concept's main structure. Explorer and Changes have working foundations, but their complete analyst workflows remain unfinished. The build is **not yet investment-team presentation ready**. Preserve the three concepts as one workflow: discover → inspect → full research → compare → shortlist/export → review changes.

This review compares the current browser render with the earlier combined mockup, Factor Explorer and Change Monitor, and checks the original product proposal and implementation plan. References are illustrative: their securities, counts, prices, factors and provider names are not factual acceptance values. Do not replace the 22 original screen definitions with the shorter illustrated list.

## Fresh flow evidence

Local browser: `http://127.0.0.1:8891/#/screener`, synthetic 1,176-stock/24-ETF preview, fake local research account and in-memory lists. No real credentials, production account creation, production research writes or market-data verification occurred. Desktop CSS viewport was 1487 × 1058; mobile was 390 × 844. The signed-out capture uses the restored default viewport. Browser screenshots have a slightly different output raster; no pixel-perfect claim is made. All nine saved screenshots were opened and inspected. Desktop reference/current images were opened together for the three concept comparisons.

| Step | Task | Health and finding |
| --- | --- | --- |
| 1 | Table → select two → Inspect → Export | Main combined structure works. Export has per-item scope/counts; selection and three inspector actions are visible. Text hierarchy, compact identity/header and provenance layout still differ. |
| 2 | Explore | Scales, plotted/excluded disclosure, numeric bounds and linked table exist. Advanced factors, sector context, cap bubbles and peer ranks are absent. Constant synthetic P/E creates overlapping points; this is a collision/usability test case, not evidence of real market distribution. |
| 3 | Changes → inspect entrant evidence | New/Exited/All and date pair exist; missing numeric cause is honestly labeled. Repeated current-screen controls delay review rows. At scrollY 0, the first row starts at 735.0 CSS px, failing the ≤500 px plan target in this tested closed-inspector state. The separate evidence-inspector frame is scrolled 241 px and must not be used to claim top-page alignment. |
| 4 | Sign in → shortlist → Inspect | Synthetic login and owner-list rendering work. List context correctly differs from screen qualification. Shortlist inspector footer actions fall below the captured desktop viewport; its layout does not yet provide the desk's bounded inspector behavior. Owner-private lists are not shared-team permissions. |
| 5 | Review note dialog → Close | Note/status form and compare-latest action exist. Dialog is top-left aligned rather than centered and the accessibility tree exposes an unnamed dialog. Conflict recovery is not freshly browser-tested here. |
| 6 | Phone shortlist | Document fits: 379 px scroll width within 390 px. A 680 px internal table leaves Review/Remove off-screen; the library consumes substantial first-screen space. Fitting the document is insufficient task accessibility. |
| 7 | Ticker → full research → Back to shortlist | Seven stock tabs and KLine controls remain visible; return restores the originating list. Crowded studies/drawing controls and the ambiguous Analyze action remain. Fixture data reuses recorded company detail and does not match the synthetic row; no identity/price reconciliation claim. |
| 8 | Sign out → public screener | Private list content clears; public two-stock selection remains. No console warnings/errors were captured during these tasks. Real Auth/revocation and multi-owner production isolation are still release gates. |

### 1 — combined Research Desk

![Current desk and inspector](design-gap-audit/review-20261002/01-desk-inspector.jpg)

### 2 — Explorer

![Current Explorer](design-gap-audit/review-20261002/02-explorer.jpg)

### 3 — Change Monitor, at the top of the page

![Current Changes](design-gap-audit/review-20261002/03-changes-top.jpg)

The evidence panel state below is scrolled; compare its information and actions, not header position.

![Historical evidence inspector](design-gap-audit/review-20261002/03-changes.jpg)

### 4 — shortlist and inspector

![Shortlist inspector](design-gap-audit/review-20261002/04-shortlist.jpg)

### 5 — note review

![Review dialog](design-gap-audit/review-20261002/05-review-dialog.jpg)

### 6 — phone shortlist

![Phone shortlist](design-gap-audit/review-20261002/06-mobile-shortlist.jpg)

### 7 — full research

![Full research handoff](design-gap-audit/review-20261002/07-full-research.jpg)

### 8 — signed out

![Private research cleared](design-gap-audit/review-20261002/08-signed-out.jpg)

## Gap-to-build mapping

All rows remain open until their acceptance evidence passes. Existing implementation is a foundation, not a completed package.

| Order / gap IDs | Build missing elements | Acceptance evidence |
| --- | --- | --- |
| 1. Workflow completion — G05/G07/G12/G15 | Center and name account/review dialogs; bound height and scroll, Escape/focus restoration and draft recovery. Reuse bounded inspector layout on shortlist. Collapse phone list library into a chooser/sheet and provide stock cards with visible Review/Remove. Preserve pending Add-to-shortlist intent through sign-in. Add list search, status filter and Next unreviewed across pages; recover removed/conflicting records explicitly. | At 390/768/1280/1487 widths and 200% zoom, inspector primary actions remain reachable and dialogs fit. Keyboard-only open/save/cancel paths restore origin. Two-tab conflicting edits preserve draft and require explicit comparison before retry. No account-switch or sign-out response restores private notes. Test 501-member export and mutation between pages. |
| 2. Team ownership and persistence — G07/G10/G11 | Qualify real Auth and the additive list migration; define team/member roles and scoped permissions before sharing notes/lists. Migrate shared legacy saved-screen/watchlist/history records with an explicit ownership mapping and rollback. Keep public recommended screens, screen definitions, watchlists, shortlists and transient comparison selections separate. | Real authenticated two-owner/two-role isolation and revoked/expired sessions. Service/anonymous grants audited. Existing 22 preset keys/criteria/sorts and saved definitions preserved. Current parent-revision SQL changes need fresh native database contracts; earlier native results do not cover the modified migration. No ownership inference from a deployment default or client-supplied ID. |
| 3. Change-review workflow — G10/G11 | Contextual “What changed in [screen]?” heading, compact date/completeness summary, one review toolbar and explicit review export. Hide irrelevant current-column controls in Changes. Add criterion-specific sortable columns, selection/bulk shortlist, review status/notes and Next unreviewed scoped to capture pair. Render before/after criteria as a matrix. | First review row ≤500 CSS px at 1487 × 1058, scrollY 0, closed/open inspector. Counts state union versus current membership. Export identifies pair/definition/evidence and exact selected/filtered scope. Historical review status is not confused with a company's general shortlist status. |
| 4. Durable history and causes — G10/G11/D2 | Replace shared `app_settings` read/append/last-two writes with immutable versioned captures and observations. Retain dated history and full eligible/union observations so entrants/exits can have both sides. Add opt-in saved-screen capture schedules with running/success/failure state, idempotency and bounded provider work. | Concurrent captures lose no history. Partial, stale, unknown-classification or changed-definition runs produce no false exits. Missing or incompatible period/currency evidence produces no numeric cause. Scheduler retries preserve last success; capture time and provider source time remain distinct. Legacy captures remain marked with their actual evidence limits. |
| 5. Factor Explorer — G08/G09/C/E | Add cap-sized bubbles and normalized sector legend/peer panel. Qualify forward P/E, growth periods, sector ranks and separately derived ROIC/debt metrics. Connect brush to an explicit editable filter action and saved definition. Handle overlapping points without invented coordinate jitter or inaccessible hit targets. | Fresh eligible-universe coverage/age/source/period/currency report. ≥95% qualified coverage for broad views, or a clearly named covered subset. Inclusive region membership agrees across table/Compare/export. Pointer, numeric and keyboard paths work for constant/extreme/negative/missing values. Percentile identifies cohort and direction; high valuation does not imply quality. |
| 6. Desk and research polish — G01–G06/G13/G14 | Compact brand; brighter readable body/provenance hierarchy and consistent sourced icons. Keep original presets grouped/searchable, with accurate unavailable/modified states. Group KLine studies/drawings at narrow widths, rename job action Run agent analysis, retain every tab/subtab/tool. Replace blanket “live” copy with actual request/source/session/age status where needed. | Paired same-state mockup comparison; no copied illustrative counts or unverified fields. Full real-instrument research and Compare preservation matrix passes, including drawings, session/range/interval/fullscreen and return query/page/selection/scroll/focus. Source/period/currency formatting agrees with exports. |
| 7. Investment-team release — E/F | Fresh comparable Moomoo reconciliation, downloadable export reconciliation, device/network performance, accessibility and intended-user tasks. Then merge/deploy the passing build with migration/UI rollback and production smoke evidence. | Universe counts split provider/stock/ETF/unknown/exclusions; compare exact criteria/session/date and canonical membership, not unlike totals. Measure p50/p95, long tasks, memory and request counts; provisional feedback ≤100 ms and warm sort/query ≤300 ms p95. Keyboard/screen-reader/contrast/reduced-motion/zoom checks and 5–8 analyst task results. No remaining unexplained P1/P2. |

## Corrections to the earlier plan

- Replace “selected export later” with a current preservation requirement: selected export already exists and must survive each new view.
- Login/list/review UI is now wired locally. Earlier backend-only checkpoint statements remain historical; do not use them as current status.
- A, B, C and D1 are partially implemented. Their unchecked package gates are intentional; feature presence alone does not close them.
- Run layout/accessibility fixes and performance measurement throughout implementation. Do not postpone all F work until after data expansion.
- Owner-private persistence advances the shortlist dependency but does not provide investment-team sharing. Team role/access acceptance needs its own implementation and evidence.
- Before numeric change explanations, capture both observations. Before advanced axes, qualify coverage. UI polish can proceed while those data contracts are built.
- Use the existing KLine engine and incremental modules. No framework/chart rewrite or eager per-row history fetch is required to match the concepts.

## Current verification and limits

Freshly run on this working tree: **230 API/worker tests pass; 49 JavaScript tests pass**. They include reset/preset inventory, canonical identity, saved-state isolation, request races, region/selected/comparison exports and private-session generation safeguards. Fresh browser tasks above used synthetic fixtures only. This audit did not exercise every preset live, all seven tabs/six financial subtabs, every chart/Compare control, completed browser downloads, two-tab note conflict, the changed SQL migration, real Auth, fresh provider coverage, Moomoo counts, screen readers, contrast or production p95.

The full approved build remains active. This review updates the construction and acceptance sequence; it is not a release sign-off.
