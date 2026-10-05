# Revision-safe private comparison downloads — local checkpoint

R11/R10 and broader release gates remain open. Private CSV and existing-compatible SpreadsheetML `.xls` exports are implemented; browser integration and real platform/large-data qualification remain unfinished. Automation remains disabled; no merge/deployment or production migration is claimed.

## Implementation

`POST /api/research/capture-schedules/{schedule_id}/pair-export` accepts explicit pair IDs, the displayed review fingerprint, query/status/sort/review filter and either all filtered rows or exact selected canonical IDs. Input rejects inconsistent scopes, duplicate/invalid selections, Boolean directions and unknown fields/formats. The private parent/captures are validated once; comparison/filter/sort runs once over at most the 40,000-row union. Internal export-only options omit eager all-row evidence; normal manual/private view limits remain 500 and normal view evidence remains unchanged.

Visible notes are fetched in batches of at most 500 against one fingerprint. Every confirmed note must match its lightweight revision/status. Evidence is calculated per written row; full before/after observations, criterion/source/generation metadata, definition/hash/query/scope and review fingerprint/revision/status/note are retained. Selected IDs must exactly belong to the filtered pair and follow comparison sort order rather than click order.

The file is assembled on a private temporary file before any attachment is returned, then the fingerprint and verified active session are checked again. A stale view, mid-batch/final review race or revoked session returns an error and deletes the file. Response cleanup runs in a `finally` block for normal completion and interrupted transfers. An abrupt process kill can still bypass Python cleanup and needs restart/temporary-retention qualification. Files over 256 MiB fail explicitly without returning a partial download; full worst-case 40,000/60-criterion/long-note support is not qualified.

CSV uses the existing formula-safe/loss-aware serializer and UTF-8 BOM. SpreadsheetML retains structured fields as safe string cells and eligible observation/review counts as numeric cells; notes beginning `=` remain literal string cells. This adds private export without removing existing manual CSV/SpreadsheetML formats or optional future XLSX.

## Executed evidence

2026-10-03 (local NZ date): eight HTTP/response tests parse actual CSV and SpreadsheetML bodies, reconcile IDs/pair/hash/scope/query/full observations/notes/numeric revisions and exact selected ordering, verify 501 rows through 500+1 note batches, reject stale/invalid scopes and revisions, discard batch/final races and revoked-session files, and verify normal/error/interrupted-transfer cleanup. They use controlled Auth/storage with the actual capture builder and shared comparison/evidence engine. No actual Auth/PostgREST/browser or native download acceptance is claimed.

Full API/worker suite: **605 passed**. `git diff --check` passes. No frontend code changed.

## Remaining

Connect private exports to timeline/Changes/review/selection UI and qualify actual downloaded files, account/selection/context continuity and feedback. Native/PostgREST/real Auth, concurrency, genuine interruption/restart, maximum scope/byte limits, database fingerprint and long-note performance, provider/Moomoo/session/currency/period and production release checks remain. No investment-grade coverage or responsiveness claim follows from these synthetic tests.

The earlier Supabase advisor approval request remains pending after automatic approval review rejected possible schema/connection metadata disclosure. It has not been retried or bypassed. Current schedule work remains uncommitted; production is untouched.
