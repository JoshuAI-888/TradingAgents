# Populated private-history browser and export follow-up

3 October 2026. Actual browser against a synthetic local preview with private captures produced by the existing capture builder. Provider transport, accounts and financial data are synthetic; this does not qualify deployed Auth/PostgREST or market accuracy.

## Verified workflow

1. Sign in from Changes without losing that workflow; select populated private schedule history for the exact stock-only definition. The timeline offers both retained captures and one entered US.S2001 row. Shared Capture snapshot is disabled in private history; automatic scheduling remains disabled.
2. Save a private scheduled-pair note as Reviewed, revision 1. Download both [CSV](private-pair.csv) and [SpreadsheetML Excel](private-pair.xls). Parse both files: one entered canonical row, exact schedule/before/after IDs, `private_schedule_pair`, `all_filtered`, revision 1, reviewed status, retained note and 64-character review fingerprint. **All 45 fields agree exactly** ([assertion record](download-check.json)). No claim of native XLSX is made.
3. Edit the private draft; switch to shared history for the same ticker. Shared review is independently unreviewed with an empty note. Switch back: the private draft returns only to its original schedule/pair. [Retained private draft](01-retained-private-draft.png) records this pre-fix state.
4. Sign out: private notes/drafts clear, shared source becomes selected, private source and Capture schedule disable, shared Capture snapshot becomes available. Sign back in and reopen private history: the saved revision-1 note returns; the discarded unsaved draft does not.

## Defects fixed

- **False saved feedback after editing:** typing into a saved pair review now changes feedback to “Unsaved changes” and retains that message when reopening the draft. [Verified updated feedback](02-unsaved-feedback.png), visually inspected. Existing save-during-edit behavior still distinguishes submitted text from newer unsaved edits.
- **Stale source header after account changes:** authentication changes now refresh the Changes header before loading new results. [Signed-out shared header](03-signout-shared-header.png) shows the selector, schedule control and manual capture action in sync with account/source state. The regression covers signed-in private controls and signed-out manual/disabled private controls.
- Clarified the generic footer: automatic capture activation and team review remain pending. Existing retained private captures are no longer described as entirely pending.

**163 JS tests pass** and `git diff --check` passes. Backend is unchanged from the preceding 750-test checkpoint. Asset fingerprint: `20261003-private-state1`. No production flag activation, migration, merge or deployment.

## Still open

Real two-owner/role Auth and account-switch isolation; concurrent capture/variant creation; source/account changes during real downloads; large private timeline paging; full keyboard/device/accessibility/p95 measurement; real provider/Moomoo coverage, cutover and release. Automated capture execution remains default-off and unqualified on the deployed platform. This closes only the documented synthetic populated-history interaction/download follow-up, not R05/R06/R10/R11/R13/R15 overall.
