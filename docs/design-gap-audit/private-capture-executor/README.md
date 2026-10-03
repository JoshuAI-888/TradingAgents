# Connected private executor — local checkpoint

The dedicated capture service connects the actual API builder with private dispatch, claim, scoped schedule reads, renewable leases and atomic publication. It is not deployed or enabled, and user-facing schedule enabling still returns explicit 409. R10 and broader release gates remain open.

## Built

`CaptureExecutor` claims privately, reads the current schedule using both schedule ID and owner ID, confirms revision/enabled state, renews before building, renews in a background thread at 30-second intervals, and renews again before publication. It builds once and retries an unconfirmed publication at most once using the exact same snapshot and token. Repeated unconfirmed writes stay explicitly unconfirmed; they do not trigger a new observation or falsely mark a possibly committed capture failed. Shutdown during a build requests a bounded retry without publication. Obsolete revisions/lease loss stop publication; safe failure codes keep provider/private exception details out of results.

`tradingagents_api.capture_service` supplies the actual pinned-definition/capture-builder adapter, polls at most 100 due definitions, dispatches, and executes one occurrence per cycle. Invalid definitions are permanent failures before provider access; provider/incomplete-data failures retry under the database attempt limit. It logs only safe runtime state. It exits before database work unless `PRIVATE_CAPTURE_RUNTIME_ENABLED=1`; it is not in the Render blueprint or existing analysis-worker loop. Run manually from the repository root with `PYTHONPATH=web/api:web/worker` only after isolated schema setup and explicit infrastructure opt-in. The opt-in is not proof of qualification.

## Executed evidence

2026-10-02: 10 executor tests cover private read/build/renew/publication, exact lost-response retry with one build, repeated unconfirmed writes, obsolete revision/off, permanent/transient failure, renewal loss, shutdown before claim/during build, wrong-owner storage response and real background-thread renewal loss while a builder waits. Four service tests cover disabled infrastructure gate, the actual capture adapter preserving member/nonmember evidence, tampered definitions stopping before provider and bounded dispatch continuing after an invalid row.

Full API/worker suite: **572 passed**. After updating the disabled UI/API explanation, all 28 schedule API tests pass again. `git diff --check` passes. Executor/storage orchestration uses controlled transport tests in this checkpoint, while the actual adapter calls the real builder against synthetic screener data. Prior native PostgreSQL checkpoints verify SQL operations separately. This does not prove a complete native executor transaction, real worker restart, real provider capture, PostgREST, browser or production acceptance.

## Remaining qualification and delivery

Run connected executor against isolated native storage, then actual Auth/PostgREST/provider data. Qualify concurrent claims, renew/edit/off/publication, genuine process restart/expiry and lost-response handling. Add private history/Changes/review/download readers and opt-in schedule UI with accurate last-success/failure/retry state. Resolve market-session/holiday policy, malformed-definition quarantine and fairness under more than 100 due definitions, large-cohort/time-limit/performance and safe shutdown. Complete all other R01–R15 release gates before merging/deploying and enabling user schedules.

Supabase advisor approval remains pending the existing explicit request following automatic approval rejection over possible schema/connection metadata disclosure. It was not retried or bypassed. Changes remain uncommitted; no production migration or deployment was performed.

## Connected native follow-up

2026-10-02: `native-integration.py` ran the actual `dispatch_schedule`, `CaptureExecutor`, private schedule adapter and capture builder against native PostgreSQL using a service-role SQL transport adapter. Four migrations were loaded into disposable `capture_executor_qualification`, cloned from local `postgres`. `native-integration-result.json` records two successful immutable captures, one build each, with one member and two eligible observations in the first synthetic cohort. The second actual publication committed before a deliberately lost response; the same payload retry confirmed success without a second record or build. An edit after actual building stopped publication; an incomplete source entered bounded retry without publication, preserving both prior successes. The disposable database was dropped after evidence collection.

This closes the previously missing connected native transaction evidence for those cases. It does not close actual PostgREST/Auth, real provider/full-market data, concurrent process restart/lease/publication or deployed runtime acceptance. The source is an explicit two-stock synthetic fixture. The SQL transport adapter is isolated evidence tooling, not a production PostgREST substitute.
