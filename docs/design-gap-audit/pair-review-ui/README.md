# Changes: private pair-review workflow

Build extends the private pair-review API into Changes. The table shows private review state; a separate filter supports all/unreviewed/in-review/reviewed. The evidence inspector adds status, bounded private note, save, reload saved review and Next unreviewed. Drafts stay in memory under owner + screen definition + immutable pair + canonical code. Closing/reopening the preview preserves a draft; signing out clears drafts and private payloads and cancels stale responses.

A stale save retains the draft and explains the conflict. Explicit reload shows the latest saved note/status/revision without replacing the draft; the next save uses that revision. Edits made while a save is pending remain unsaved rather than being overwritten by the completed request. Successful saves reload the filtered comparison, removing reviewed rows from an unreviewed queue.

Next unreviewed runs within the selected pair, change cohort, search and sort. It starts at the first eligible row with no inspector open, advances from the inspected row and wraps to the start. The server returns the relevant page and canonical target. An exhausted queue is explicit. Private-history page queries remain supported. Signing in through the review prompt returns to Changes rather than a detour through shortlists.

Comparison CSV now applies the private review filter and includes revision/status/note plus a hash of the complete pair-review state read in one SQL snapshot. Hash changes across export pages abort the download; account or comparison changes also abort. UI discloses that CSV includes private notes. Existing public comparison CSV remains available. Selected/bulk export remains pending.

## Evidence

457 API/worker and 128 JavaScript tests pass. New tests cover sorted/paged/wrapped/searched queue targets, starting without a fabricated ticker, exact-code reload, review hash changes, escaped note rendering, draft retention, conflict and pending-save edits, string review filters, sign-out clearing and revision-changing export rejection. Native PostgreSQL permissions/CAS evidence remains in the preceding private-pair-review checkpoint; no production migration was applied here.

Current-code offline preview at port 8903 uses actual routes with controlled in-memory capture/Auth/storage transport. Browser verification covered:

- Saved S2001 as reviewed with a synthetic note; reload retained it. Downloaded CSV parsed as exactly one canonical row with revision 1, note and review hash.
- Found and fixed a browser-observed string-to-number review-filter bug. Unreviewed New matches then showed 0 and the queue reported no unreviewed stock.
- Restarted the agent-created preview to load the final API; All matches contained 1,177 synthetic identities. Queue start inspected S0001; closing/reopening retained an unsaved draft. Saving Reviewed reduced the unreviewed count to 1,176; Next inspected S0002.
- After sign-out, private editor/state were cleared and public review status was Unavailable. Signing in through the review prompt returned directly to Changes.
- Reviewed filter on the full 1,177-row pair produced exactly US.S0001. The actual downloaded CSV contains its note, revision 1 and pair-review hash; see filtered-download-verification.json. Download-event observation timed out for the first download; the created file was inspected directly, not treated as a failed download.
- At 390 px viewport, document width was 379 px, editor width 331 px and all three editor actions were 44 px high. Escape closed the modal. Saved screenshots were opened and visually inspected; the viewport override was reset. The current preview showed no console errors in the checked captures.

Screens: 01-saved-review.png records the earlier S2001 saved/reloaded view; 02-next-unreviewed.png shows final queue advancement to S0002; 03-phone-editor.png shows the phone editor. Synthetic capture timestamps and company/financial values do not qualify investment data. Full conflict two-tab browser, screen-reader, performance, team roles, selected/bulk actions, real PostgREST/Auth and release gates remain open. Supabase advisors remain pending explicit approval following the earlier automatic rejection for possible metadata disclosure; no bypass or advisor pass is claimed.
