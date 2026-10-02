# Private capture status checkpoint

GET /api/research/capture-schedules/{id}/status verifies the authenticated parent and exact owner/schedule/revision of bounded latest occurrence and successful-publication reads. The response exposes safe state/error categories, attempt count, retry eligibility and last successful publication; it omits worker IDs, lease tokens and lease expiry. A running occurrence with expired lease displays awaiting recovery rather than asserting active work. Later failure never removes prior success. Earlier schedule revisions are labelled explicitly.

The cadence dialog loads status independently; failure leaves settings editable. Status and save feedback have separate targets. Response generations prevent an older status request from replacing a newer one. Automation remains unavailable and no enable request is made.

Validation:
- 613 API/worker tests pass, including status authentication/scope, retained success, expired lease, omitted worker secrets and malformed state tests.
- 147 JavaScript tests pass, including safe labels, independent failure handling, separate message regions and late response rejection.
- Actual local API/browser with synthetic Auth/store shows Failed, attempt 3 of 3, incomplete-data disclosure and retained successful publication. Saving cadence revision 2 independently shows success and labels occurrence revision 1 as earlier.
- [Desktop evidence](desktop-status.png).

Limitations: bounded reads are separate statements, not a transactional status snapshot; status may change during loading and is observational, not a completion guarantee. Real platform/Auth/native status queries, large-history query performance, ongoing refresh, provider/runtime/restart/production qualification remain open. Synthetic occurrence failure is UI evidence, not an executed live provider failure.
