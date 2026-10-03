# Owner-private scheduled history reads — local checkpoint

R10 and broader R01–R15 remain open. History APIs are implemented, not yet connected to Changes/review/export UI. Automation is still disabled; no merge/deployment or production migration is claimed.

- `GET /api/research/capture-schedules/{schedule_id}/captures` validates a verified active owner and immutable parent definition hash before requesting owner/schedule/hash-scoped metadata. Paging is deterministic publication time/ID descending, up to 100, with explicit `has_more` and offset. It does not fetch full snapshot payloads for the timeline.
- `GET .../captures/{capture_id}` reads one matching private snapshot. It verifies IDs/revision/hash/publication timestamp, complete typed version/definition, source/capture clocks, unique canonical market membership and v3 eligible observation consistency. V3 member selection is replayed against criterion observations; conflicting membership is rejected rather than used to infer changes. Provider v2 evidence is labelled members-only, without inventing nonmember evidence.
- Disabled schedules keep accessible successful history. Missing/wrong-owner parents or captures return 404. Unconfirmed storage scope/definition fails safely; invalid evidence returns 409. Responses retain private `no-store` headers and omit publish worker/tokens. No private read falls back to deployment-shared manual history.

2026-10-02: ten HTTP tests verify metadata/detail/paging, exact retained evidence and token omission, off-state preservation, Auth/other-owner/missing identity, parent-hash rejection and malformed definition/membership/count/complete/source-time/source-clock rejection. They use controlled Auth/storage with the actual builder producing synthetic capture records. Native executor/publication/RLS are separately verified in the executor/publication checkpoints; this HTTP checkpoint is not actual Auth/PostgREST/browser qualification.

Full API/worker suite: **582 passed**. `git diff --check` passes. No frontend change is claimed.

Remaining: private pair comparison and pair-specific review/download readers; exact large history paging/read/download qualification under real platform limits; account-switch/revocation and browser continuity; opt-in schedule/history/Changes UI; full provider/Moomoo/session/concurrency/restart/accessibility/performance and production cutover/rollback.

Supabase advisor approval remains pending the earlier explicit request following automatic rejection over possible schema/connection metadata disclosure. It was not retried or bypassed. Changes remain uncommitted; production is untouched.
