# Private research ownership checkpoint

2 October 2026. Backend foundation and local login/shortlist UI; not a production-qualified release.

## Contract

The new `/api/research/*` endpoints require a Bearer access token. They verify it at the fixed configured Supabase Auth issuer, derive the owner from the returned user identity, reject anonymous/unverified account types, compare the verified token's subject/session IDs, and check an existing, unexpired owner session. They never accept `X-User-ID`, user-editable metadata or `DEFAULT_USER_ID` as authorization. Issuer or session-store failure fails closed. Tokens and raw database errors are not logged or returned.

The server-only session RPC wraps a narrow boolean lookup in the unexposed `research_private` schema. Its private definer function has an empty search path, an explicit identity/service-role check, no PUBLIC/anon/authenticated execution grants and no session-row output. No broad SELECT grant on `auth.sessions` is added. Supabase's current [getUser documentation](https://supabase.com/docs/reference/javascript/auth-getuser) explains issuer-backed identity validation; its [session documentation](https://supabase.com/docs/guides/auth/sessions) describes session-ID lookup for post-sign-out revocation. This path incurs issuer/session checks for private data operations; normal screener sorting/rendering is unchanged.

New list/item tables have RLS enabled and no browser grants or policies. The verified API uses explicit owner predicates on every private read/write. Composite list/owner foreign keys prevent inconsistent item ownership. The existing shared Phase 0 screens/watchlists/snapshots are unchanged and are not described as authenticated private resources.

## Data behavior

- Shortlists are separate from saved screen definitions and watchlists. Names/descriptions and canonical instrument IDs are retained; adding an instrument requires stored-universe identity evidence.
- Archive/removal is soft and reversible. Re-adding an existing member preserves notes/review status; an already-active add is idempotent.
- List and item edits compare revisions. A stale update returns conflict without overwriting another edit. Partial updates preserve omitted fields; explicit empty notes are allowed, null/no-op edits are rejected.
- Membership and review mutations lock the active owner-scoped parent inside the database transaction. Archive and item writes serialize; an archived list cannot accept a later add/edit.
- Item reads paginate with one extra row to disclose further results; list reads disclose possible truncation at 500. Notes/status are owner-private, not yet shared-team ACLs.

## Evidence and limits

**226 API/worker tests pass** (18 new research-ownership tests), including two-owner HTTP isolation, issuer identity mismatch, revoked/missing sessions, malformed tokens, anonymous accounts, payload owner injection, canonical share classes, soft restore, stale revisions, partial edit preservation and sanitized failures. Existing 22-preset golden checks continue to pass. The prior frontend checkpoint has 43 JavaScript checks; no frontend files changed in this checkpoint.

The CLI-generated additive migration was executed in an isolated PostgreSQL **16.14** cluster with minimal synthetic Auth users/sessions, no network listener, using local Unix socket port 55439. `research-db-contract.sql` verified live/foreign/missing/expired session behavior, private grants/RLS, canonical membership, soft restore, note/status preservation, stale revisions, partial edits and archive guards. All contract fixture mutations roll back. The two-connection concurrency script observed the add waiting on the archive's parent lock in `pg_stat_activity`, then returning zero members after archive committed. The first test's buffered-client readiness assumption was replaced by database-state observation. The test cluster was confirmed running and then stopped.

The migration is **not applied to production**; Supabase's actual project uses PostgreSQL 17.6, so live schema/Auth/PostgREST verification remains required. No accounts were created in Supabase, no credentials requested, no production list/notes written, and existing saved-screen count remained one during read-only inspection. No new client key was exposed.

## Remaining work

1. Browser login/refresh/sign-out with the existing identity service; no account creation or invitation is implied. Clear private cached state on owner changes, sign-out and stale responses.
2. Shortlist picker/add/remove/undo, searchable list page and review notes/status editor; hook both regular inspector and Change Monitor into them. Show conflict/retry states without discarding the user's draft. Add explicit sharing/ACLs only when the team access model is established; owner-private lists alone do not complete team workflows.
3. Apply/verify the migration alongside the feature rollout; test actual Auth, revoked sessions, API role grants, two-owner data isolation, persistence across reloads and concurrent writes against the deployed contract. Repeat advisors.
4. Move legacy private saved screens/watchlists/snapshot scopes to verified ownership with a preservation/migration plan; retain every original preset and existing stored definition. Current legacy routes still use shared Phase 0 ownership.
5. Resolve the existing database security baseline before publishing a browser client configuration: the read-only advisor report still identifies public tables without RLS, definer views and mutable function search paths. Those findings precede this migration. Review actual browser/API grants and dependencies before changing access. Relevant remedies: [RLS in exposed schemas](https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public), [definer views](https://supabase.com/docs/guides/database/database-linter?lint=0010_security_definer_view), [function search paths](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable). RLS-without-policy informational notices on service-only tables describe intentional closed browser access, not a reason to add public policies.

Developer test inputs live in `web/api/tests/research-db-bootstrap.sql`, `research-db-contract.sql` and `research-db-concurrency.py`. These scripts are explicitly for an isolated local database; the bootstrap must never be run on a Supabase project. The migration file contains schema only, not those fixture accounts.

## Local workflow follow-through

The same-origin Auth proxy and tab-scoped session UI now support existing-account sign-in, refresh and sign-out, with fixed-issuer verification and private no-store responses. Passwords are not retained. Private caches and in-memory drafts clear on account change/sign-out; generation guards reject late responses. No browser Supabase key was exposed. Login/list/review forms are wired locally with a native named dialog, pending Add handoff, chooser, phone cards, soft removal/undo, ticker/status filtering, cross-page Next unreviewed and explicit conflict comparison. Company-name search and full device/zoom checks remain open.

Every membership/review mutation advances the parent revision; already-active adds are idempotent. Full-shortlist CSV pages through 501 members in tests and checks a consistent revision through a final probe. The modified native SQL contract and observed two-connection archive/add lock test pass in isolated PostgreSQL 16.14; its server was then stopped. Synthetic two-tab browser edits demonstrate stale-save rejection, draft retention, latest comparison and explicit retry. Updated full regressions pass: 233 API/worker and 57 JavaScript tests. Production Auth/PostgREST/migration, sharing permissions and legacy ownership gates above remain open; no production account or private data was written.
