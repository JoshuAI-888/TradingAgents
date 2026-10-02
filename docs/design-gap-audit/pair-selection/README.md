# Changes selection and bulk handoff checkpoint

2 October 2026. Local implementation, not production or financial-data acceptance.

Changes now supports canonical row selection across review pages, page select/deselect, original Compare charts for 2–4 stocks, bulk additions to an owner-private shortlist and selected comparison CSV. The selection scope includes owner, screen definition, capture IDs, cohort/search/sort/review filters and review revision hash. Paging preserves selection; a scope change clears it with an explanation.

Bulk writes use existing per-item idempotent API additions in batches of four. Existing shortlist note/status are not submitted or overwritten. Confirmed items are excluded from retries; failures and not-started items are explicit. Closing stops subsequent batches; already-dispatched writes may finish. Account changes close the bulk dialog and reject obsolete responses. This is not an atomic bulk transaction.

Selected export fetches and validates the complete filtered pair, then emits selected identities in server order. Missing/duplicate identities, incomplete pages, changed account/comparison and changed private revisions abort the download. Scope is recorded as selected or all_filtered. Compare/full research preserve a validated owner-bound Changes origin across reload and Back; malformed or duplicate persisted selections fail closed. Remounted selection buttons retain keyboard focus.

## Evidence

- 457 API/worker tests and 132 JavaScript tests pass.
- New tests cover cross-page selection and scope invalidation; actual CSV Blob ordering/missing IDs/revision rejection; partial-addition retries and owner/loading rejection; malformed owner-bound Changes origins.
- Current actual-route offline browser at port 8903: selected US.S0001 on page 1 and US.S0103 on page 2; both additions confirmed through the shortlist API. Existing US.S0001 note "Review balance sheet quality" and unreviewed status remained visible; US.S0103 appeared once with no note.
- Actual selected browser download reconciled exactly US.S0001, US.S0103 in ascending symbol order, one capture pair and review hash, selected scope. See download-verification.json.
- Original Compare showed both tickers and existing chart controls. Reload then Back restored 101–200 of 1177 and two selected companies. Screenshot: 01-cross-page-selection.png.

## Remaining acceptance

The fixture has synthetic membership and recorded mismatched financial/chart responses. It does not qualify prices, provider coverage or financial accuracy. This checkpoint does not close R04, R05, R06, R11 or R13: real Auth/PostgREST/two-owner concurrency, team roles, complete scopes/device/accessibility/performance, live provider/Moomoo and production cutover remain open. Latest focus/account-dialog refinements pass automated tests; fresh phone/keyboard browser qualification remains to be completed. No merge/deploy occurred.
