# Original review scopes: private routes, inspector drafts and CSV

Local integration; enabled only when **all three** flags are `1`: `DUPLICATE_CAPTURE_REVIEW_SCOPES_ENABLED`, `CAPTURE_DEFINITION_ALIASES_ENABLED`, `CROSS_HISTORY_PAIR_REVIEWS_ENABLED`. No flags were activated in production.

## Behavior

Qualified discovery now supplies private comparison review rows and revision fingerprints. A unique existing note carries its original same-key or cross-key anchor even when capture discovery chooses another duplicate representative. CAS saves use those original keys; no replacement note is created under the newly preferred representative.

Multiple same-code notes remain explicit `scope_conflict` rows with all original variants. The private review filter offers “Choose review scope”; these rows are neither silently reviewed nor silently unreviewed. The inspector lists original notes/revisions/saved times and requires a choice before showing the edit form. Save without a choice, a forged/unavailable anchor, stale revision or unconfirmed discovery fails without changing notes.

Each chosen original anchor has its own private draft key, independent of mutable screen display labels. Switching variants retains separate drafts; sign-out clears choices and drafts. Reload resolves only the chosen original variant and cannot substitute another note's revision. Selection moves keyboard focus to the note; returning to scope selection focuses its first action. Choice buttons have 44 px minimum height. Full device/keyboard acceptance remains pending actual browser verification.

Comparison CSV appends `review_anchor_json` and `review_variants_json` after existing classification columns. A unique note retains its original anchor; conflict exports retain every original variant rather than export a fabricated winning note. Existing column positions are retained. Manual-private exports still validate full-pair revision fingerprints across pages. Scheduled scope handling is unchanged and appended manual-scope columns remain blank when unavailable.

Save-success response fencing now checks account generation, comparison generation, exact payload identity and active draft key before updating the current comparison. A save initiated on a different comparison cannot restore obsolete row/review state.

## Evidence

- Actual capture-builder/HTTP tests: unique note under another representative, original-key CAS/edit and stale-write denial, multiple-note conflict filtering, explicit selected-anchor-only editing, forged scope and discovery failure rejection, and unique cross-anchor saves using both original keys.
- Existing native resolver/CAS contracts remain binding for exact immutable evidence, owner isolation, namespaces and original stored revisions; this turn introduced no schema changes.
- JavaScript: separate draft scopes, display-label independence, explicit selection/no form before choice, all-variant CSV retention, sign-out clearing, chosen-anchor request and late comparison response fence.
- **750 API/worker tests passed in 7.93 seconds**, **157 JavaScript tests passed**, and `git diff --check` passes.

## Remaining qualification

### Capture-source follow-up

Browser verification exposed a transition defect: selecting private history briefly kept shared rows/review/export controls beneath the newly selected private source. Source changes now immediately clear prior rows/actions and active draft/selection pointers, cancel pending search debounce and fence pending responses. Stored owner/pair drafts remain retained. Loading text distinguishes an empty loading view from retained prior results.

Actual synthetic browser checks: select the shared `scope_conflict` filter, switch to private history and observe an explicit no-schedule state with no shared rows/review/export actions ([empty-state screenshot](browser/private-empty-scope.png)); switch back to shared history and reopen the exact unsaved original note ([retained-draft screenshot](browser/source-return-draft.png), visually inspected). The conflict filter resets to all on source change. The regression checks immediate clearing, debounce cancellation, pointer/filter/paging reset and retained separate drafts; **161 JS tests pass**. Asset fingerprint: `20261003-review-scopes4`.

This covers the absent-private-schedule path and shared return. A populated private schedule, different owners, source changes during downloads and full device/performance checks remain open. No claim of production isolation or schedule activation follows from this preview.

### Concurrent-edit follow-up

Actual browser + localhost HTTP exercise: with an unsaved cross-history draft at revision 5, a second synthetic client saved the same original anchor at revision 6 ([receipt](browser/concurrent-save.json)). Browser Save rejected its stale revision and kept the exact local note/status. Reload exposed only that original scope's revision 6, status and concurrent note; the local textarea remained unchanged. Explicit Save then advanced that scope to revision 7, while the same-history saved note remained revision 2. A subsequent new draft and Reload show both the retained draft and revision 7 together ([tablet screenshot](browser/retained-draft-latest.png)); the screenshot was visually inspected. This tests existing-variant CAS conflict recovery, not concurrent creation of a new variant or deployed multi-owner Auth.

Save and Reload failure handling now applies the same account/comparison/payload/active-draft fences as successful responses. A delayed rejection from an obsolete pair or scope cannot change its draft message or the active form. Two added regressions cover chosen-variant-only Reload with an unrelated revision 99, independent draft retention, and six delayed-failure cases across Save/Reload and payload/generation/scope switches. **160 JS tests pass**. Asset fingerprint advances to `20261003-review-scopes3`; unchanged backend retains the preceding 750-test evidence.

### Browser follow-up, 3 October 2026

The synthetic preview now seeds duplicate payloads from frozen stored captures rather than mutable construction dictionaries. Actual browser checks show both original notes/revisions, keyboard focus moving to the selected note, independent unsaved drafts surviving repeated scope switches, and a cross-history save advancing only revision 4 → 5 while the same-history saved note remains revision 2. The second draft remains unchanged after that save. At 390 × 844 the document scroll width is 390 px and all seven dialog actions measure 44 px high; the screenshot was visually inspected. This is synthetic interaction evidence, not live data or production Auth qualification.

Header sign-in exposed an unrelated navigation defect: it redirected Changes to shortlists. It now re-renders the active page while preserving explicit add-to-shortlist/pair-review intents. A new JS regression covers home, research, settings, shortlists and both explicit intents. Browser sign-out/reload/header sign-in confirms the Changes URL and heading remain intact. Asset fingerprint: `20261003-review-scopes2`.

The actual browser-downloaded [CSV](browser/conflicting-original-scopes.csv) passes [parsed assertions](browser/download-check.json): one entered US.S0001 row, captured price 12 → 8, explicit scope conflict and blank fabricated winner note, both original review contracts/anchors and revisions 5/2. Selected duplicate representative keys are equal; the original cross-history review anchor still retains its distinct keys. The preview's saved timestamp is fixed synthetic data and does not qualify production clock updates.

Evidence: [desktop scope picker](browser/original-scopes.png), [phone retained draft](browser/phone-draft.png). Current checks: **750 API/worker tests passed in 8.21 seconds, 158 JS tests passed**, and `git diff --check` passed. Concurrent-edit reload, account/source transitions, unique-note downloads and full keyboard/device/performance checks remain open.

- [ ] Actual desktop/phone browser scope selection, draft switch/reload/conflict/account/source/keyboard/focus and containment checks.
- [ ] Actual downloaded/parsed CSV with unique and conflicting original scopes and before/after provenance.
- [ ] Real Auth/PostgREST/private permissions and source/owner cutover; legacy unmapped-scope fallback and concurrent variant creation qualification.
- [ ] Full private timeline/paging/fingerprint/device/performance/accessibility acceptance.
- [ ] Advisor, migration/backfill/cutover/rollback, merge/deploy and production smoke.

This supersedes the prior discovery checkpoint's unbuilt route/inspector/export statements. It does not close duplicate-review continuity end-to-end or any overall R01–R15 gate. No note migration, production write, merge or deployment occurred.
