# Private history UI qualification checkpoint

The local port 8903 preview ran the current API and static files with synthetic Auth/store transport and private captures built by the actual capture builder. No production or remote platform writes occurred.

Verified in the browser:
- Default Clear shows 1,176 synthetic stocks, ETFs excluded, market-cap descending.
- Changes retains manual/shared history and permits selecting owner-private history.
- Private pair shows one entry, one exit, 1,175 unchanged and union 1,177.
- S2001 evidence opens a private pair editor; save reports success and row becomes Reviewed.
- Reload saved review retrieves revision 1 while preserving the draft.
- Selected CSV and SpreadsheetML downloads each contain exactly US.S2001, the saved note, revision 1, exact pair IDs, definition hash and selected scope.

The download event observer timed out, but both browser-created files were present in Downloads and parsed successfully. This is completed-file evidence, not a claim about event instrumentation.

Desktop screenshot: [saved private review](desktop-review.png).

Open: phone/tablet/zoom/focus checks for this new workflow, source-switch/manual regression, full filtered download, sign-out/account isolation, schedule controls and real Auth/PostgREST/provider/maximum-size/performance/restart/production qualification. Automation remains disabled. Synthetic count reconciliation does not qualify Moomoo or live coverage.
