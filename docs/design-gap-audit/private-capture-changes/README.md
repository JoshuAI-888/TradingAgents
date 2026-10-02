# Owner-private capture comparison — local checkpoint

R10 and all broader release gates remain open. Private comparison is implemented, while private pair review, downloads and UI integration remain unbuilt/unqualified. Automation remains disabled; no merge, deployment or production migration is claimed.

## Implementation

The existing comparison engine is extracted as `_compare_screen_captures`, which receives already scoped snapshots and history metadata without reading capture storage. The manual route retains original definition expansion, shared-history lookup, timeline and review behavior. Private `GET /api/research/capture-schedules/{schedule_id}/changes` verifies one immutable owner-scoped parent and two matching validated capture details, then calls the same engine using the original pinned criteria. It never calls deployment-owner keys or shared-history helpers.

The private route requires explicit pair IDs, accepts status/search/criterion sort/direction/pagination, and rejects reversed/identical/missing/other-owner pairs. It reports full-pair counts with paginated rows. Full new/exited member arrays are omitted to avoid duplicating large capture payloads; complete new/exited counts remain. Pair metadata is explicitly `history_scope=selected_pair`; this does not pretend to return the complete timeline. Notes/review remain explicitly unavailable until the private review path exists. Successful disabled schedules remain readable through owner-private history.

A shared sort fix treats huge/nonfinite numeric values as unavailable rather than crashing during conversion; missing values remain last in either direction. No global currency/period/data qualification is inferred from sorting.

## Evidence

2026-10-02: 14 private history/comparison HTTP tests pass. New comparison cases prove shared-history helpers are never called, only one parent read is made, explicit pair chronology and owner isolation, search/status/paging/sort validation, and actual builder-produced entry/exit membership with both before/after nonmember criterion observations. A price<=5 synthetic pair changes A 4→6 and B 7→4, yielding one exit and one entry; criterion-after sorting and paging retain those identities and observations. A shared-engine test confirms huge numeric market cap stays unavailable/last rather than throwing.

Full API/worker suite: **587 passed**. `git diff --check` passes. Actual native executor evidence exists separately; this comparison checkpoint uses controlled Auth/storage with real builder/engine logic. No real provider, actual Auth/PostgREST, browser or production comparison acceptance is claimed.

## Next

Private pair-specific CAS notes/review and revision-safe filtered/selected downloads; connect timeline/pair/review/export into existing Changes workflow; qualified worker/runtime/schedule opt-in UI; real Auth/PostgREST/device/performance/provider/Moomoo and release cutover/rollback gates. Existing 22 preset IDs/rules/sorts and manual engine behavior remain under preservation tests.

The prior Supabase advisor approval request remains pending after automatic review rejected possible schema/connection metadata disclosure. It has not been retried or bypassed. Current changes remain uncommitted.
