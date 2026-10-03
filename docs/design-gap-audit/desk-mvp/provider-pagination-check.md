# Provider paging and count integrity

3 October 2026. Reviewed the actual preset execution and Desk load-more paths. The Desk retains loaded membership pages and independently sorts/refines them; its exports describe loaded matches rather than promising unseen provider rows. This check does not qualify live membership or source ordering.

Found and corrected a backend response-validation gap. Pagination was only checked to be a dictionary; string `has_more`, structured cursors, invalid totals and conflicting aliases could flow into count/completion controls. A short first page with a larger provider total but no flag/cursor could also be reported complete.

Execution now validates cursor, boolean flag and nonnegative integer total types before hydration, rejects contradictory aliases and totals smaller than the returned page, and refuses explicit completion when a nonterminal cursor or first-page total proves more members exist. A larger total without a cursor is honestly marked possibly truncated; no cursor or extra membership is invented. The provider's terminal `-1` token is normalized to no cursor. Invalid/inconsistent metadata returns unavailable with no rows, so the existing Desk retry path can retain previous results.

The preset criteria, sort/direction request, source quote values and immutable display-cohort hydration are unchanged. No additional network call, provider write or production mutation is introduced.

Evidence: ten additional parameterized cases cover malformed flags/cursors/totals, conflicting aliases, known missing membership, contradictory completion and valid terminal pages. **785 API/worker tests pass**, including existing preset sorts, membership identity, generation pinning and paging checks. `git diff --check` passes. The latest static checkpoint remains 186 UI tests; no static code changed in this correction.

Live release acceptance remains open: US/HK source/classification coverage, supported provider preset membership and ordering, independent Moomoo sanity checks, required migration compatibility, and exact-candidate deployment/rollback smoke checks.
